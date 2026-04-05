"""
PostgreSQL ORM — 包含用户、审计日志等完整模型
支持：PostgreSQL（生产）和 SQLite（测试）
"""
from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import (
    Column, String, Float, Integer, Boolean,
    Text, BigInteger, ForeignKey, DateTime, JSON, Index
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# PostgreSQL 支持连接池；SQLite 不支持 pool_size/max_overflow
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

_engine_kwargs = {"echo": False, "pool_pre_ping": True}
if not _is_sqlite:
    _engine_kwargs["pool_size"]   = 10
    _engine_kwargs["max_overflow"] = 20

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id         = Column(String(64), primary_key=True)
    username   = Column(String(128), unique=True, nullable=False)
    password   = Column(String(256), nullable=False)
    role       = Column(String(32), default="user")        # user/admin/super_admin
    tenant_id  = Column(String(64), default="default")
    dept_id    = Column(String(64))
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("idx_user_username", "username"),)


class Document(Base):
    __tablename__ = "documents"
    id          = Column(String(64), primary_key=True)
    filename    = Column(String(512), nullable=False)
    file_path   = Column(String(512))
    file_type   = Column(String(16))
    file_size   = Column(BigInteger, default=0)
    status      = Column(String(20), default="pending")    # pending/processing/done/failed
    parse_score = Column(Float, default=0.0)
    chunk_count = Column(Integer, default=0)
    doc_version = Column(Integer, default=1)
    tenant_id   = Column(String(64), default="default")
    dept_id     = Column(String(64))
    error_msg   = Column(Text)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        Index("idx_docs_status",  "status"),
        Index("idx_docs_created", "created_at"),
        Index("idx_docs_tenant",  "tenant_id"),
    )


class Chunk(Base):
    __tablename__ = "chunks"
    id         = Column(String(64), primary_key=True)
    doc_id     = Column(String(64), ForeignKey("documents.id", ondelete="CASCADE"))
    content    = Column(Text, nullable=False)
    chunk_idx  = Column(Integer, nullable=False)
    char_count = Column(Integer, default=0)
    meta_info  = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("idx_chunks_doc_id", "doc_id"),)


class QueryLog(Base):
    __tablename__ = "query_logs"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    trace_id        = Column(String(32), index=True)
    session_id      = Column(String(64))
    user_id         = Column(String(64))
    tenant_id       = Column(String(64), default="default")
    original_query  = Column(Text, nullable=False)
    rewritten_query = Column(Text)
    intent          = Column(String(4))                    # C0/C1/C2
    answer          = Column(Text)
    context         = Column(Text)
    sources         = Column(JSON)
    confidence      = Column(Float, default=0.0)
    latency_ms      = Column(Integer)
    retrieval_ms    = Column(Integer)
    llm_ms          = Column(Integer)
    cache_hit       = Column(Boolean, default=False)
    token_count     = Column(Integer, default=0)
    degrade_level   = Column(String(4))
    degrade_reason  = Column(String(64))
    created_at      = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        Index("idx_qlog_created", "created_at"),
        Index("idx_qlog_trace",   "trace_id"),
        Index("idx_qlog_tenant",  "tenant_id"),
    )


class Evaluation(Base):
    __tablename__ = "evaluations"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    log_id       = Column(Integer, ForeignKey("query_logs.id", ondelete="SET NULL"), nullable=True)
    query        = Column(Text, nullable=False)
    answer       = Column(Text)
    relevance    = Column(Float, default=0.0)
    faithfulness = Column(Float, default=0.0)
    completeness = Column(Float, default=0.0)
    overall      = Column(Float, default=0.0)
    reason       = Column(Text)
    created_at   = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("idx_eval_created", "created_at"),)


class Feedback(Base):
    __tablename__ = "feedback"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    log_id     = Column(Integer, ForeignKey("query_logs.id", ondelete="SET NULL"), nullable=True)
    trace_id   = Column(String(32))
    session_id = Column(String(64))
    user_id    = Column(String(64))
    query      = Column(Text, nullable=False)
    answer     = Column(Text)
    feedback   = Column(String(10), nullable=False)        # like / dislike
    comment    = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("idx_fb_type", "feedback"),)


class AuditLog(Base):
    """操作审计日志"""
    __tablename__ = "audit_logs"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    trace_id   = Column(String(32))
    user_id    = Column(String(64))
    username   = Column(String(128))
    action     = Column(String(64), nullable=False)        # login/upload/delete/query
    resource   = Column(String(256))
    detail     = Column(JSON)
    ip         = Column(String(64))
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        Index("idx_audit_created", "created_at"),
        Index("idx_audit_user",    "user_id"),
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_default_admin()


async def _ensure_default_admin():
    """启动时确保默认 admin 账号存在"""
    import uuid
    try:
        import bcrypt
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(User).where(User.username == "admin"))
            if not r.scalar_one_or_none():
                pw = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
                db.add(User(
                    id=str(uuid.uuid4()), username="admin",
                    password=pw, role="super_admin",
                ))
                await db.commit()
    except Exception as e:
        from app.core.logger import logger
        logger.warning(f"默认管理员创建失败（可忽略）: {e}")
