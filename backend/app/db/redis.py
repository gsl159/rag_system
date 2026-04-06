"""Backward compatibility — imports from app.repository.redis_cache"""
from app.repository.redis_cache import cache, CacheStats, _stats, _inflight, RedisCache

__all__ = ["cache", "CacheStats", "_stats", "_inflight", "RedisCache"]
