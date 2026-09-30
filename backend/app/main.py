"""
RAG System — FastAPI 主入口
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.logger import logger
from app.core.limiter import limiter
from app.core.tracing import init_tracing
from app.core.security import auth_middleware
from app.db.postgres import init_db
from app.db.redis import cache
from app.db.milvus import milvus_db
from app.api import chat, upload, feedback, metrics


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 启动 ─────────────────────────────────────
    logger.info("=" * 50)
    logger.info("RAG System 启动中...")

    # 链路追踪（须尽早初始化）
    init_tracing()

    try:
        await init_db()
        logger.info("✅ PostgreSQL 初始化完成")
    except Exception as e:
        logger.error(f"❌ PostgreSQL 初始化失败: {e}")

    try:
        await cache.connect()
        logger.info("✅ Redis 连接成功")
    except Exception as e:
        logger.error(f"❌ Redis 连接失败: {e}")

    try:
        # Milvus 2.5 原生 Sparse/BM25，无需再重建进程内 BM25 索引
        await milvus_db.connect()
        logger.info("✅ Milvus 连接成功")
    except Exception as e:
        logger.error(f"❌ Milvus 连接失败: {e}")

    logger.info("🚀 所有服务启动完成")
    logger.info("=" * 50)
    yield

    # ── 关闭 ─────────────────────────────────────
    from app.db.postgres import engine
    await engine.dispose()
    logger.info("RAG System 已关闭")


app = FastAPI(
    title="RAG Knowledge System",
    description="企业级 RAG 知识库系统 API",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# 限流
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 认证中间件（OIDC/JWT → 租户上下文）
app.middleware("http")(auth_middleware)

# CORS（生产环境通过 CORS_ORIGINS 收窄白名单）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 全局异常处理 ──────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"未处理的异常 [{request.method} {request.url}]: {exc}")
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后重试"})


# ── 路由注册 ──────────────────────────────────

app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(feedback.router)
app.include_router(metrics.router)


@app.get("/health", tags=["系统"])
async def health():
    return {"status": "ok", "version": "2.0.0", "env": settings.APP_ENV}


@app.get("/", tags=["系统"])
async def root():
    return {"message": "RAG Knowledge System is running", "docs": "/docs"}
