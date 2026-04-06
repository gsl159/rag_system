"""Embedding module with caching support."""
from typing import List

from app.core.generator import embed_client
from app.repository.redis_cache import cache
from app.utils.logger import logger


async def get_embedding(text: str) -> List[float]:
    """Get embedding for text with Layer-2 cache."""
    cached = await cache.get_embed(text)
    if cached:
        return cached
    vec = await embed_client.embed_one(text)
    await cache.set_embed(text, vec)
    return vec


async def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Get embeddings for multiple texts."""
    return await embed_client.embed_batch(texts)
