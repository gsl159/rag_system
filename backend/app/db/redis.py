"""
Redis 三层缓存模块
Layer 1 — Query 结果缓存     (TTL: 30min)
Layer 2 — Embedding 缓存     (TTL: 24h)
Layer 3 — RAG Pipeline 缓存  (TTL: 1h)
"""
import hashlib
import json
import random
from typing import Optional, Any

import redis.asyncio as aioredis
from app.core.config import settings
from app.core.logger import logger


class CacheStats:
    """内存中统计命中率（重启归零，轻量级）"""
    hits:   int = 0
    misses: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return round(self.hits / total, 4) if total else 0.0

    def record_hit(self):   self.hits   += 1
    def record_miss(self):  self.misses += 1


# 全局统计
_stats = {
    "query": CacheStats(),
    "embed": CacheStats(),
    "rag":   CacheStats(),
}


class RedisCache:
    def __init__(self):
        self.client: aioredis.Redis | None = None

    async def connect(self):
        self.client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await self.client.ping()
        logger.info("Redis 连接成功")

    # ── 通用 get/set ─────────────────────────────

    async def get(self, key: str) -> Optional[str]:
        try:
            return await self.client.get(key)
        except Exception as e:
            logger.warning(f"Redis GET 失败: {e}")
            return None

    async def set(self, key: str, value: str, ttl: int):
        """写入缓存，TTL 加随机抖动防止雪崩"""
        jitter = random.randint(0, ttl // 10)
        try:
            await self.client.set(key, value, ex=ttl + jitter)
        except Exception as e:
            logger.warning(f"Redis SET 失败: {e}")

    async def delete(self, key: str):
        try:
            await self.client.delete(key)
        except Exception as e:
            logger.warning(f"Redis DELETE 失败: {e}")

    # ── Layer 1: Query Cache ──────────────────────

    def _query_key(self, query: str) -> str:
        return "cache:query:" + hashlib.md5(query.encode()).hexdigest()

    async def get_query(self, query: str) -> Optional[dict]:
        raw = await self.get(self._query_key(query))
        if raw:
            _stats["query"].record_hit()
            return json.loads(raw)
        _stats["query"].record_miss()
        return None

    async def set_query(self, query: str, value: dict):
        await self.set(self._query_key(query), json.dumps(value, ensure_ascii=False), settings.CACHE_TTL_QUERY)

    # ── Layer 2: Embedding Cache ──────────────────

    def _embed_key(self, text: str) -> str:
        return "cache:embed:" + hashlib.md5(text.encode()).hexdigest()

    async def get_embed(self, text: str) -> Optional[list]:
        raw = await self.get(self._embed_key(text))
        if raw:
            _stats["embed"].record_hit()
            return json.loads(raw)
        _stats["embed"].record_miss()
        return None

    async def set_embed(self, text: str, vec: list):
        await self.set(self._embed_key(text), json.dumps(vec), settings.CACHE_TTL_EMBED)

    # ── Layer 3: RAG Pipeline Cache ───────────────

    def _rag_key(self, query: str) -> str:
        return "cache:rag:" + hashlib.md5(query.encode()).hexdigest()

    async def get_rag(self, query: str) -> Optional[dict]:
        raw = await self.get(self._rag_key(query))
        if raw:
            _stats["rag"].record_hit()
            return json.loads(raw)
        _stats["rag"].record_miss()
        return None

    async def set_rag(self, query: str, value: dict):
        await self.set(self._rag_key(query), json.dumps(value, ensure_ascii=False), settings.CACHE_TTL_RAG)

    # ── Stats ─────────────────────────────────────

    async def get_stats(self) -> dict:
        try:
            info  = await self.client.info("stats")
            hits  = int(info.get("keyspace_hits",   0))
            misses= int(info.get("keyspace_misses", 0))
            total = hits + misses
            # 获取 key 总数
            dbinfo = await self.client.info("keyspace")
            key_count = 0
            for v in dbinfo.values():
                if isinstance(v, str) and "keys=" in v:
                    key_count += int(v.split(",")[0].split("=")[1])
            return {
                "redis_hit_rate":  round(hits / total, 4) if total else 0,
                "redis_hits":      hits,
                "redis_misses":    misses,
                "total_keys":      key_count,
                "layer_query":  {"hits": _stats["query"].hits, "misses": _stats["query"].misses, "hit_rate": _stats["query"].hit_rate},
                "layer_embed":  {"hits": _stats["embed"].hits, "misses": _stats["embed"].misses, "hit_rate": _stats["embed"].hit_rate},
                "layer_rag":    {"hits": _stats["rag"].hits,   "misses": _stats["rag"].misses,   "hit_rate": _stats["rag"].hit_rate},
            }
        except Exception as e:
            logger.warning(f"Redis stats 失败: {e}")
            return {}


cache = RedisCache()
