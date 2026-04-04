"""
PostgreSQL — 异步 SQLAlchemy ORM 定义
新增：doc_version 用于缓存强一致性版本控制
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


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ── ORM Models ────────────────────────────────

class Document(Base):
    __tablename__ = "documents"
    id          = Column(String(64),  primary_key=True)
    filename    = Column(String(512), nullable=False)
    file_path   = Column(String(512))
    file_type   = Column(String(16))
    file_size   = Column(BigInteger, default=0)
    status      = Column(String(20),  default="pending")   # pending/processing/done/failed
    parse_score = Column(Float,       default=0.0)
    chunk_count = Column(Integer,     default=0)
    doc_version = Column(Integer,     default=1)           # 版本控制：更新时自增
    error_msg   = Column(Text)
    created_at  = Column(DateTime,    default=datetime.utcnow)
    updated_at  = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_docs_status", "status"),
        Index("idx_docs_created", "created_at"),
    )


class Chunk(Base):
    __tablename__ = "chunks"
    id         = Column(String(64),  primary_key=True)
    doc_id     = Column(String(64),  ForeignKey("documents.id", ondelete="CASCADE"))
    content    = Column(Text,        nullable=False)
    chunk_idx  = Column(Integer,     nullable=False)
    char_count = Column(Integer,     default=0)
    meta_info  = Column(JSON,        default=dict)
    created_at = Column(DateTime,    default=datetime.utcnow)

    __table_args__ = (
        Index("idx_chunks_doc_id", "doc_id"),
    )


class QueryLog(Base):
    __tablename__ = "query_logs"
    id              = Column(Integer,  primary_key=True, autoincrement=True)
    session_id      = Column(String(64))
    original_query  = Column(Text,    nullable=False)
    rewritten_query = Column(Text)
    answer          = Column(Text)
    context         = Column(Text)
    latency_ms      = Column(Integer)
    cache_hit       = Column(Boolean,  default=False)
    token_count     = Column(Integer,  default=0)
    degrade_level   = Column(String(4))                    # C0/C1/C2
    created_at      = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_qlog_created", "created_at"),
        Index("idx_qlog_cache", "cache_hit"),
    )


class Evaluation(Base):
    __tablename__ = "evaluations"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    log_id       = Column(Integer, ForeignKey("query_logs.id", ondelete="SET NULL"), nullable=True)
    query        = Column(Text,    nullable=False)
    answer       = Column(Text)
    relevance    = Column(Float,   default=0.0)
    faithfulness = Column(Float,   default=0.0)
    completeness = Column(Float,   default=0.0)
    overall      = Column(Float,   default=0.0)
    reason       = Column(Text)
    created_at   = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_eval_created", "created_at"),
    )


class Feedback(Base):
    __tablename__ = "feedback"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    log_id     = Column(Integer, ForeignKey("query_logs.id", ondelete="SET NULL"), nullable=True)
    session_id = Column(String(64))
    query      = Column(Text,   nullable=False)
    answer     = Column(Text)
    feedback   = Column(String(10), nullable=False)   # like / dislike
    comment    = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_fb_type", "feedback"),
    )


# ── Session dependency ────────────────────────

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
