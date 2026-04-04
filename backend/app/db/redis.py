"""
Redis 三层缓存模块（强一致性版本控制版）
Layer 1 — Query 结果缓存     (TTL: 30min)
Layer 2 — Embedding 缓存     (TTL: 24h)
Layer 3 — RAG Pipeline 缓存  (TTL: 1h)

Key 包含 doc_version + embedding_version 确保版本失效
SingleFlight 防并发风暴
"""
import asyncio
import hashlib
import json
import random
from typing import Optional, Any, Dict

import redis.asyncio as aioredis
from app.core.config import settings
from app.core.logger import logger


class CacheStats:
    """内存中统计命中率（重启归零，轻量级）"""
    def __init__(self):
        self.hits:   int = 0
        self.misses: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return round(self.hits / total, 4) if total else 0.0

    def record_hit(self):   self.hits   += 1
    def record_miss(self):  self.misses += 1


# 全局统计
_stats: Dict[str, CacheStats] = {
    "query": CacheStats(),
    "embed": CacheStats(),
    "rag":   CacheStats(),
}

# SingleFlight: 正在执行的请求锁 {key: asyncio.Future}
_inflight: Dict[str, asyncio.Future] = {}


class RedisCache:
    def __init__(self):
        self.client: Optional[aioredis.Redis] = None
        # 当前 embedding 版本（与 doc_version 共同控制缓存失效）
        self.embedding_version: str = "v1"

    async def connect(self):
        self.client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        await self.client.ping()
        logger.info("Redis 连接成功")

    async def _safe_get(self, key: str) -> Optional[str]:
        if not self.client:
            return None
        try:
            return await self.client.get(key)
        except Exception as e:
            logger.warning(f"Redis GET 失败: {e}")
            return None

    async def _safe_set(self, key: str, value: str, ttl: int):
        if not self.client:
            return
        jitter = random.randint(0, max(ttl // 10, 1))
        try:
            await self.client.set(key, value, ex=ttl + jitter)
        except Exception as e:
            logger.warning(f"Redis SET 失败: {e}")

    async def _safe_delete(self, key: str):
        if not self.client:
            return
        try:
            await self.client.delete(key)
        except Exception as e:
            logger.warning(f"Redis DELETE 失败: {e}")

    # ── Layer 1: Query Cache ──────────────────────

    def _query_key(self, query: str, doc_version: int = 0) -> str:
        h = hashlib.md5(query.encode()).hexdigest()
        return f"cache:query:{h}:{doc_version}:{self.embedding_version}"

    async def get_query(self, query: str, doc_version: int = 0) -> Optional[dict]:
        raw = await self._safe_get(self._query_key(query, doc_version))
        if raw:
            _stats["query"].record_hit()
            try:
                return json.loads(raw)
            except Exception:
                return None
        _stats["query"].record_miss()
        return None

    async def set_query(self, query: str, value: dict, doc_version: int = 0):
        await self._safe_set(
            self._query_key(query, doc_version),
            json.dumps(value, ensure_ascii=False),
            settings.CACHE_TTL_QUERY,
        )

    # ── Layer 2: Embedding Cache ──────────────────

    def _embed_key(self, text: str) -> str:
        h = hashlib.md5(text.encode()).hexdigest()
        return f"cache:embed:{h}:{self.embedding_version}"

    async def get_embed(self, text: str) -> Optional[list]:
        raw = await self._safe_get(self._embed_key(text))
        if raw:
            _stats["embed"].record_hit()
            try:
                return json.loads(raw)
            except Exception:
                return None
        _stats["embed"].record_miss()
        return None

    async def set_embed(self, text: str, vec: list):
        await self._safe_set(
            self._embed_key(text),
            json.dumps(vec),
            settings.CACHE_TTL_EMBED,
        )

    # ── Layer 3: RAG Pipeline Cache ───────────────

    def _rag_key(self, query: str, doc_version: int = 0) -> str:
        h = hashlib.md5(query.encode()).hexdigest()
        return f"cache:rag:{h}:{doc_version}:{self.embedding_version}"

    async def get_rag(self, query: str, doc_version: int = 0) -> Optional[dict]:
        raw = await self._safe_get(self._rag_key(query, doc_version))
        if raw:
            _stats["rag"].record_hit()
            try:
                return json.loads(raw)
            except Exception:
                return None
        _stats["rag"].record_miss()
        return None

    async def set_rag(self, query: str, value: dict, doc_version: int = 0):
        # 排除不可序列化字段
        safe_value = {k: v for k, v in value.items() if k != "context" or len(str(v)) < 5000}
        await self._safe_set(
            self._rag_key(query, doc_version),
            json.dumps(safe_value, ensure_ascii=False),
            settings.CACHE_TTL_RAG,
        )

    # ── SingleFlight 防风暴 ───────────────────────

    async def single_flight(self, key: str, coro_factory) -> Any:
        """
        同一 key 在同一时间窗口内只允许 1 个协程执行，
        其余协程等待共享结果（最多 2s 超时）
        """
        if key in _inflight:
            try:
                return await asyncio.wait_for(
                    asyncio.shield(_inflight[key]), timeout=2.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"SingleFlight 等待超时 key={key[:40]}")
                return None
            except Exception:
                return None

        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        _inflight[key] = fut
        try:
            result = await coro_factory()
            if not fut.done():
                fut.set_result(result)
            return result
        except Exception as e:
            if not fut.done():
                fut.set_exception(e)
            raise
        finally:
            _inflight.pop(key, None)

    # ── 版本管理 ──────────────────────────────────

    async def get_global_doc_version(self) -> int:
        """获取全局文档版本号（用于缓存 Key）"""
        try:
            val = await self._safe_get("global:doc_version")
            return int(val) if val else 0
        except Exception:
            return 0

    async def increment_doc_version(self) -> int:
        """文档更新时递增版本号，使所有相关缓存自动失效"""
        if not self.client:
            return 0
        try:
            return await self.client.incr("global:doc_version")
        except Exception as e:
            logger.warning(f"doc_version incr 失败: {e}")
            return 0

    # ── Stats ─────────────────────────────────────

    async def get_stats(self) -> dict:
        try:
            if not self.client:
                raise RuntimeError("Redis not connected")
            info  = await self.client.info("stats")
            hits  = int(info.get("keyspace_hits",   0))
            misses= int(info.get("keyspace_misses", 0))
            total = hits + misses

            dbinfo = await self.client.info("keyspace")
            key_count = 0
            for v in dbinfo.values():
                if isinstance(v, dict):
                    key_count += v.get("keys", 0)
                elif isinstance(v, str) and "keys=" in v:
                    try:
                        key_count += int(v.split(",")[0].split("=")[1])
                    except Exception:
                        pass

            return {
                "redis_hit_rate":  round(hits / total, 4) if total else 0,
                "redis_hits":      hits,
                "redis_misses":    misses,
                "total_keys":      key_count,
                "layer_query": {"hits": _stats["query"].hits, "misses": _stats["query"].misses, "hit_rate": _stats["query"].hit_rate},
                "layer_embed": {"hits": _stats["embed"].hits, "misses": _stats["embed"].misses, "hit_rate": _stats["embed"].hit_rate},
                "layer_rag":   {"hits": _stats["rag"].hits,   "misses": _stats["rag"].misses,   "hit_rate": _stats["rag"].hit_rate},
            }
        except Exception as e:
            logger.warning(f"Redis stats 失败: {e}")
            return {
                "redis_hit_rate": 0, "redis_hits": 0, "redis_misses": 0, "total_keys": 0,
                "layer_query": {"hits": _stats["query"].hits, "misses": _stats["query"].misses, "hit_rate": _stats["query"].hit_rate},
                "layer_embed": {"hits": _stats["embed"].hits, "misses": _stats["embed"].misses, "hit_rate": _stats["embed"].hit_rate},
                "layer_rag":   {"hits": _stats["rag"].hits,   "misses": _stats["rag"].misses,   "hit_rate": _stats["rag"].hit_rate},
            }


cache = RedisCache()
