"""Backward compatibility — imports from app.core.generator"""
from app.core.generator import llm_client, embed_client, LLMClient, EmbedClient

__all__ = ["llm_client", "embed_client", "LLMClient", "EmbedClient"]
