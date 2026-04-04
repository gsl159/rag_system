"""
RAG System — FastAPI 主入口（生产级）
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logger import logger
from app.db.postgres import init_db
from app.db.redis import cache
from app.db.milvus import milvus_db
from app.api import chat, upload, feedback, metrics


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 启动 ─────────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"RAG System 启动中... ENV={settings.APP_ENV}")

    try:
        await init_db()
        logger.info("✅ PostgreSQL 初始化完成")
    except Exception as e:
        logger.error(f"❌ PostgreSQL 初始化失败: {e}")

    try:
        await cache.connect()
        logger.info("✅ Redis 连接成功")
    except Exception as e:
        logger.error(f"❌ Redis 连接失败（系统将在无缓存模式下运行）: {e}")

    try:
        milvus_db.connect()
        logger.info("✅ Milvus 连接成功")
    except Exception as e:
        logger.error(f"❌ Milvus 连接失败（向量检索不可用）: {e}")

    logger.info("🚀 所有服务启动完成")
    logger.info("=" * 60)
    yield

    # ── 关闭 ─────────────────────────────────────
    from app.db.postgres import engine
    await engine.dispose()
    logger.info("RAG System 已关闭")


app = FastAPI(
    title="RAG Knowledge System",
    description="企业级 RAG 知识库系统 API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 全局异常处理 ──────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"未处理的异常 [{request.method} {request.url}]: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请稍后重试", "error": str(exc)[:200]},
    )


# ── 路由注册 ──────────────────────────────────

app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(feedback.router)
app.include_router(metrics.router)


@app.get("/health", tags=["系统"])
async def health():
    """健康检查端点"""
    checks = {
        "milvus": milvus_db.is_connected,
        "redis":  cache.client is not None,
    }
    all_ok = all(checks.values())
    return {
        "status":  "ok" if all_ok else "degraded",
        "version": "1.0.0",
        "env":     settings.APP_ENV,
        "checks":  checks,
    }


@app.get("/", tags=["系统"])
async def root():
    return {"message": "RAG Knowledge System is running", "docs": "/docs"}
