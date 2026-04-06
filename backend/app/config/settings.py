"""
Global configuration — all settings are read from environment variables.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # LLM
    SILICONFLOW_API_KEY: str = "sk-placeholder"
    SILICONFLOW_BASE_URL: str = "https://api.siliconflow.cn/v1"
    LLM_MODEL: str = "Qwen/Qwen2.5-7B-Instruct"
    EMBED_MODEL: str = "BAAI/bge-m3"
    EMBED_DIM: int = 1024

    # PostgreSQL
    DATABASE_URL: str = "postgresql+asyncpg://raguser:ragpass123@postgres:5432/ragdb"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # Milvus
    MILVUS_HOST: str = "milvus"
    MILVUS_PORT: int = 19530
    MILVUS_COLLECTION: str = "rag_docs"

    # MinIO
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin123"
    MINIO_BUCKET: str = "documents"
    MINIO_SECURE: bool = False

    # RAG
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    TOP_K: int = 10
    RERANK_TOP_N: int = 5
    QUALITY_THRESHOLD: float = 0.6

    # Hybrid retrieval: score = alpha * vector + (1-alpha) * bm25
    HYBRID_RETRIEVAL_ALPHA: float = 0.7

    # Timeouts (seconds)
    LLM_TIMEOUT_C2: float = 3.0
    LLM_TIMEOUT_C1: float = 1.5
    LLM_SELF_SCORE_TIMEOUT: float = 2.0
    QUERY_REWRITE_TIMEOUT: float = 3.0
    SINGLEFLIGHT_WAIT_TIMEOUT: float = 2.0

    # Content limits
    CONTEXT_MAX_CHARS: int = 3000
    MAX_QUERY_LENGTH: int = 2000

    # Cache TTL
    CACHE_TTL_QUERY: int = 1800
    CACHE_TTL_EMBED: int = 86400
    CACHE_TTL_RAG: int = 3600

    # Auth & Security
    JWT_SECRET: str = "rag-system-jwt-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24
    RATE_LIMIT_PER_MINUTE: int = 60

    # App
    LOG_LEVEL: str = "INFO"
    APP_ENV: str = "production"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
