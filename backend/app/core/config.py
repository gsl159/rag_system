"""
全局配置 — 所有配置从环境变量读取，禁止硬编码
"""
from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── LLM ──────────────────────────────────────
    SILICONFLOW_API_KEY: str = "sk-placeholder"
    SILICONFLOW_BASE_URL: str = "https://api.siliconflow.cn/v1"
    LLM_MODEL: str = "deepseek-ai/DeepSeek-V2.5"
    EMBED_MODEL: str = "BAAI/bge-m3"
    EMBED_DIM: int = 1024
    # 重排模型（Cross-Encoder，走 API）
    RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"

    # ── PostgreSQL ───────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://raguser:ragpass123@postgres:5432/ragdb"

    # ── Redis ────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"

    # ── Milvus（2.5+ Sparse/BM25 原生混合检索）────
    MILVUS_HOST: str = "milvus"
    MILVUS_PORT: int = 19530
    MILVUS_COLLECTION: str = "rag_docs"

    # ── MinIO ────────────────────────────────────
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin123"
    MINIO_BUCKET: str = "documents"
    MINIO_SECURE: bool = False

    # ── RAG ──────────────────────────────────────
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    TOP_K: int = 10
    RERANK_TOP_N: int = 5
    QUALITY_THRESHOLD: float = 0.6
    # 混合检索 Dense 权重（0~1），其余权重给 Sparse
    HYBRID_ALPHA: float = 0.7

    # ── 语义缓存 ─────────────────────────────────
    # 余弦相似度阈值，超过则命中语义缓存（复用历史 RAG 结果）
    SEMANTIC_CACHE_THRESHOLD: float = 0.95
    SEMANTIC_CACHE_MAX_SIZE: int = 5000

    # ── Cache TTL ────────────────────────────────
    CACHE_TTL_QUERY: int = 1800
    CACHE_TTL_EMBED: int = 86400
    CACHE_TTL_RAG: int = 3600

    # ── 安全：认证 ───────────────────────────────
    # 认证开关：关闭时所有请求视为默认租户（便于本地联调）
    AUTH_ENABLED: bool = False
    # 通用 OIDC：从 IdP 的 JWKS 校验 JWT 签名
    OIDC_ISSUER: str = ""
    OIDC_JWKS_URL: str = ""
    OIDC_AUDIENCE: str = ""
    JWT_ALGORITHMS: str = "RS256"
    # 关闭 OIDC 时的兜底：HS256 本地密钥（仅开发）
    JWT_SECRET: str = "change-me-in-production"
    # 未携带 token 时使用的默认租户
    DEFAULT_TENANT_ID: str = "default"

    # ── 安全：限流 ───────────────────────────────
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: str = "60/minute"
    RATE_LIMIT_CHAT: str = "30/minute"
    RATE_LIMIT_UPLOAD: str = "10/minute"

    # ── 安全：CORS ───────────────────────────────
    CORS_ORIGINS: str = "*"

    # ── 异步任务（Celery）────────────────────────
    CELERY_BROKER_URL: str = "redis://redis:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/2"
    # 大于该大小的文档走 Celery 队列，小文件走进程内后台任务
    CELERY_SIZE_THRESHOLD_MB: int = 5
    # 是否强制全部走 Celery（生产推荐 true）
    CELERY_ALWAYS: bool = False

    # ── 可观测性 ─────────────────────────────────
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "rag-backend"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://jaeger:4317"

    # ── App ──────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    APP_ENV: str = "production"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def jwt_algorithms_list(self) -> List[str]:
        return [a.strip() for a in self.JWT_ALGORITHMS.split(",") if a.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
