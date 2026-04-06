"""RAG System — FastAPI entry point (enterprise architecture)."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config.settings import settings
from app.utils.logger import logger
from app.utils.trace import generate_trace_id, set_trace_id
from app.api.deps import ok, ErrorCode
from app.repository.postgres import init_db, engine
from app.repository.redis_cache import cache
from app.repository.vector_store import milvus_db
from app.api import chat, upload, feedback, metrics, auth, audit


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info(f"RAG System starting... ENV={settings.APP_ENV}")
    try:
        await init_db()
        logger.info("PostgreSQL initialized")
    except Exception as e:
        logger.error(f"PostgreSQL init failed: {e}")
    try:
        await cache.connect()
        logger.info("Redis connected")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
    try:
        milvus_db.connect()
        logger.info("Milvus connected")
    except Exception as e:
        logger.error(f"Milvus connection failed: {e}")
    logger.info("System startup complete")
    yield
    await engine.dispose()
    logger.info("RAG System shut down")


app = FastAPI(
    title="RAG Knowledge System",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    """Inject trace_id into every request and propagate via context."""
    trace_id = request.headers.get("X-Trace-Id") or generate_trace_id()
    set_trace_id(trace_id)
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    trace_id = getattr(request.state, "trace_id", "")
    logger.error(f"[{trace_id}] Unhandled exception [{request.method} {request.url}]: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "code": ErrorCode.SYSTEM_ERROR,
            "message": "Internal server error, please try again later",
            "data": None,
            "trace_id": trace_id,
        },
    )


app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(feedback.router)
app.include_router(metrics.router)
app.include_router(audit.router)


@app.get("/health", tags=["System"])
async def health():
    return ok({
        "status": "ok" if milvus_db.is_connected else "degraded",
        "version": "2.0.0",
        "env": settings.APP_ENV,
        "checks": {
            "milvus": milvus_db.is_connected,
            "redis": cache.client is not None,
        },
    })


@app.get("/", tags=["System"])
async def root():
    return ok({"message": "RAG Knowledge System is running", "docs": "/docs"})
