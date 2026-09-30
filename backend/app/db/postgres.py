"""
PostgreSQL — 异步 SQLAlchemy ORM 定义

多租户：业务表携带 tenant_id，并启用 Row-Level Security（见 infra/init.sql）。
每个请求通过 set_tenant_context() 设置会话级 GUC `app.tenant_id`，
RLS 策略据此自动过滤，实现数据库层强隔离（防止漏加 where 导致越权）。
"""
from contextvars import ContextVar
from datetime import datetime
from typing import AsyncGenerator, Optional

from sqlalchemy import (
    Column, String, Float, Integer, Boolean,
    Text, BigInteger, ForeignKey, DateTime, JSON, select, text, event
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# 当前请求的租户上下文（由认证中间件 / Celery 任务写入）
_tenant_ctx: ContextVar[str] = ContextVar("tenant_id", default=settings.DEFAULT_TENANT_ID)


def set_current_tenant(tenant_id: str):
    _tenant_ctx.set(tenant_id or settings.DEFAULT_TENANT_ID)


def get_current_tenant() -> str:
    return _tenant_ctx.get()


@event.listens_for(engine.sync_engine, "begin")
def _inject_tenant_guc(conn):
    """
    每个事务开始时自动注入会话 GUC `app.tenant_id`，供 RLS 策略使用。
    - 用事务级 set_config(..., true)：事务结束自动失效，绝不跨请求/跨租户泄漏
    - 在此处统一注入，避免业务层 commit 后 GUC 丢失导致 RLS 拒绝
    """
    tid = get_current_tenant()
    conn.exec_driver_sql("SELECT set_config('app.tenant_id', %s, true)", (tid,))


class Base(DeclarativeBase):
    pass


# ── ORM Models ────────────────────────────────

class Document(Base):
    __tablename__ = "documents"
    id          = Column(String(64),  primary_key=True)
    tenant_id   = Column(String(64),  nullable=False, default="default", index=True)
    filename    = Column(String(512), nullable=False)
    file_path   = Column(String(512))
    file_type   = Column(String(16))
    file_size   = Column(BigInteger, default=0)
    status      = Column(String(20),  default="pending")   # pending/processing/done/failed
    parse_score = Column(Float,       default=0.0)
    chunk_count = Column(Integer,     default=0)
    error_msg   = Column(Text)
    created_at  = Column(DateTime,    default=datetime.utcnow)
    updated_at  = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)


class Chunk(Base):
    __tablename__ = "chunks"
    id         = Column(String(64),  primary_key=True)
    doc_id     = Column(String(64),  ForeignKey("documents.id", ondelete="CASCADE"))
    tenant_id  = Column(String(64),  nullable=False, default="default", index=True)
    content    = Column(Text,        nullable=False)
    chunk_idx  = Column(Integer,     nullable=False)
    char_count = Column(Integer,     default=0)
    meta_info   = Column(JSON,        default=dict)
    created_at = Column(DateTime,    default=datetime.utcnow)


class QueryLog(Base):
    __tablename__ = "query_logs"
    id              = Column(Integer,  primary_key=True, autoincrement=True)
    tenant_id       = Column(String(64),  nullable=False, default="default", index=True)
    session_id      = Column(String(64))
    original_query  = Column(Text,    nullable=False)
    rewritten_query = Column(Text)
    answer          = Column(Text)
    context         = Column(Text)
    latency_ms      = Column(Integer)
    cache_hit       = Column(Boolean,  default=False)
    token_count     = Column(Integer,  default=0)
    created_at      = Column(DateTime, default=datetime.utcnow)


class Evaluation(Base):
    __tablename__ = "evaluations"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    log_id       = Column(Integer, ForeignKey("query_logs.id", ondelete="SET NULL"), nullable=True)
    tenant_id    = Column(String(64),  nullable=False, default="default", index=True)
    query        = Column(Text,    nullable=False)
    answer       = Column(Text)
    relevance    = Column(Float,   default=0.0)
    faithfulness = Column(Float,   default=0.0)
    completeness = Column(Float,   default=0.0)
    overall      = Column(Float,   default=0.0)
    reason       = Column(Text)
    created_at   = Column(DateTime, default=datetime.utcnow)


class Feedback(Base):
    __tablename__ = "feedback"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    log_id     = Column(Integer, ForeignKey("query_logs.id", ondelete="SET NULL"), nullable=True)
    tenant_id  = Column(String(64),  nullable=False, default="default", index=True)
    session_id = Column(String(64))
    query      = Column(Text,   nullable=False)
    answer     = Column(Text)
    feedback   = Column(String(10), nullable=False)   # like / dislike
    comment    = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Session dependency ────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    # 租户 GUC 由 engine 的 begin 事件在每个事务自动注入，此处无需重复设置
    async with AsyncSessionLocal() as session:
        yield session


async def set_tenant_context(session: AsyncSession, tenant_id: Optional[str] = None):
    """把当前租户写入会话 GUC，触发 RLS 策略自动过滤"""
    tid = tenant_id or get_current_tenant()
    # 参数化传入，避免 SQL 注入
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tid}
    )


async def set_tenant_context(session: AsyncSession, tenant_id: Optional[str] = None):
    """兼容用法：显式在会话上设置租户 GUC（一般无需调用，engine begin 事件已自动注入）"""
    tid = tenant_id or get_current_tenant()
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tid}
    )


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_rls(conn)


# 需要启用行级安全（RLS）的业务表
_RLS_TABLES = ["documents", "chunks", "query_logs", "evaluations", "feedback"]

_RLS_DDL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON {table};
CREATE POLICY tenant_isolation ON {table}
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
"""


async def _apply_rls(conn):
    """
    为业务表启用 RLS 并创建租户隔离策略。
    current_setting('app.tenant_id', true) 由 engine 的 begin 事件每事务注入；
    第二参数 true 表示缺失时返回 NULL（策略不匹配任何行，安全默认拒绝）。
    ORM 建表者为表所有者，默认会被 RLS 绕过，故需 FORCE ROW LEVEL SECURITY。
    """
    from sqlalchemy import text as _text
    from app.core.logger import logger
    for table in _RLS_TABLES:
        try:
            for stmt in _RLS_DDL.format(table=table).strip().split(";"):
                if stmt.strip():
                    await conn.execute(_text(stmt))
        except Exception as e:
            # 策略创建失败不应阻断启动（如权限不足）
            logger.warning(f"RLS 策略应用失败 [{table}]: {e}")
