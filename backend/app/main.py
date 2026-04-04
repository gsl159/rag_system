"""
RAG System — FastAPI 主入口（生产级）
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logger import logger
from app.core.response import ok
from app.core.security import generate_trace_id
from app.db.postgres import init_db
from app.db.redis import cache
from app.db.milvus import milvus_db
from app.api import chat, upload, feedback, metrics, auth, audit


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info(f"RAG System 启动中... ENV={settings.APP_ENV}")
    try:
        await init_db(); logger.info("✅ PostgreSQL 初始化完成")
    except Exception as e:
        logger.error(f"❌ PostgreSQL: {e}")
    try:
        await cache.connect(); logger.info("✅ Redis 连接成功")
    except Exception as e:
        logger.error(f"❌ Redis: {e}")
    try:
        milvus_db.connect(); logger.info("✅ Milvus 连接成功")
    except Exception as e:
        logger.error(f"❌ Milvus: {e}")
    logger.info("🚀 系统启动完成")
    yield
    from app.db.postgres import engine
    await engine.dispose()
    logger.info("RAG System 已关闭")


app = FastAPI(title="RAG Knowledge System", version="1.0.0",
              docs_url="/docs", redoc_url="/redoc", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    """为每个请求注入 trace_id"""
    trace_id = request.headers.get("X-Trace-Id") or generate_trace_id()
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    trace_id = getattr(request.state, "trace_id", "")
    logger.error(f"[{trace_id}] 未处理异常 [{request.method} {request.url}]: {exc}")
    return JSONResponse(status_code=500, content={
        "code": 5000, "message": "服务器内部错误，请稍后重试",
        "data": None, "trace_id": trace_id,
    })


app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(feedback.router)
app.include_router(metrics.router)
app.include_router(audit.router)


@app.get("/health", tags=["系统"])
async def health():
    return ok({
        "status": "ok" if milvus_db.is_connected else "degraded",
        "version": "1.0.0", "env": settings.APP_ENV,
        "checks": {"milvus": milvus_db.is_connected, "redis": cache.client is not None},
    })


@app.get("/", tags=["系统"])
async def root():
    return ok({"message": "RAG Knowledge System is running", "docs": "/docs"})
