"""
Redis 三层缓存模块
Layer 1 — Query 结果缓存     (TTL: 30min)
Layer 2 — Embedding 缓存     (TTL: 24h)
Layer 3 — RAG Pipeline 缓存  (TTL: 1h)
       └─ 语义缓存：以 query 向量做余弦相似度匹配（>阈值即复用历史结果）

说明：语义缓存在 Layer-3 之上增加一层「近似命中」，显著提升缓存命中率。
索引以 Redis List 保存 (向量 + 结果) 条目，查询时在进程内做余弦比较；
受 SEMANTIC_CACHE_MAX_SIZE 限制，规模可控（超大场景可换 RediSearch 向量索引）。
"""
import hashlib
import json
import math
import random
from typing import Optional, Any, List, Tuple

import redis.asyncio as aioredis
from app.core.config import settings
from app.core.logger import logger


def _cosine(a: List[float], b: List[float]) -> float:
    """余弦相似度（向量已归一化时可退化为点积，这里做通用计算）"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


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
    "semantic": CacheStats(),
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

    # ── Layer 3+: 语义缓存 ────────────────────────

    def _sem_key(self, tenant_id: str) -> str:
        return f"cache:semantic:{tenant_id}"

    async def get_semantic(
        self, query_vec: List[float], tenant_id: str = "default"
    ) -> Optional[dict]:
        """按向量余弦相似度匹配历史结果，超过阈值即命中"""
        threshold = settings.SEMANTIC_CACHE_THRESHOLD
        try:
            raw_items = await self.client.lrange(self._sem_key(tenant_id), 0, -1)
        except Exception as e:
            logger.warning(f"语义缓存读取失败: {e}")
            return None

        best_score, best_payload = 0.0, None
        for raw in raw_items:
            try:
                entry = json.loads(raw)
                score = _cosine(query_vec, entry.get("vec", []))
                if score > best_score:
                    best_score, best_payload = score, entry
            except Exception:
                continue

        if best_payload and best_score >= threshold:
            _stats["semantic"].record_hit()
            logger.info(f"语义缓存 HIT (sim={best_score:.4f}): '{best_payload.get('query', '')[:40]}'")
            return best_payload.get("result")
        _stats["semantic"].record_miss()
        return None

    async def set_semantic(self, query: str, query_vec: List[float], result: dict,
                           tenant_id: str = "default"):
        """写入语义缓存（有界队列 + 过期由 TTL 控制）"""
        key = self._sem_key(tenant_id)
        entry = json.dumps(
            {"query": query, "vec": query_vec, "result": result},
            ensure_ascii=False,
        )
        try:
            await self.client.lpush(key, entry)
            await self.client.ltrim(key, 0, settings.SEMANTIC_CACHE_MAX_SIZE - 1)
            await self.client.expire(key, settings.CACHE_TTL_RAG)
        except Exception as e:
            logger.warning(f"语义缓存写入失败: {e}")

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
                "layer_semantic": {"hits": _stats["semantic"].hits, "misses": _stats["semantic"].misses, "hit_rate": _stats["semantic"].hit_rate},
            }
        except Exception as e:
            logger.warning(f"Redis stats 失败: {e}")
            return {}


cache = RedisCache()
