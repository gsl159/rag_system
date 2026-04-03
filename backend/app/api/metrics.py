"""
/metrics 路由 — 可视化所需全量指标
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db, Document, QueryLog, Evaluation
from app.db.redis import cache
from app.db.milvus import milvus_db
from app.services.eval_service import eval_service

router = APIRouter(prefix="/metrics", tags=["监控指标"])


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db)):
    """首页总览卡片"""
    doc_total   = (await db.execute(select(func.count()).select_from(Document))).scalar() or 0
    query_total = (await db.execute(select(func.count()).select_from(QueryLog))).scalar() or 0
    avg_score   = (await db.execute(select(func.avg(Evaluation.overall)))).scalar() or 0
    avg_lat     = (await db.execute(select(func.avg(QueryLog.latency_ms)))).scalar() or 0
    cache_stats = await cache.get_stats()
    milvus_stats= milvus_db.get_stats()

    return {
        "doc_count":       doc_total,
        "query_count":     query_total,
        "avg_score":       round(avg_score, 2),
        "avg_latency_ms":  round(avg_lat, 1),
        "cache_hit_rate":  cache_stats.get("redis_hit_rate", 0),
        "vector_count":    milvus_stats.get("total_entities", 0),
    }


@router.get("/rag")
async def rag_metrics(days: int = Query(7, ge=1, le=90), db: AsyncSession = Depends(get_db)):
    """RAG 查询质量指标"""
    return await eval_service.get_metrics(days=days, db=db)


@router.get("/cache")
async def cache_metrics():
    """Redis 三层缓存命中率"""
    return await cache.get_stats()


@router.get("/docs")
async def doc_metrics(db: AsyncSession = Depends(get_db)):
    """文档质量统计"""
    totals = await db.execute(
        select(Document.status, func.count().label("cnt"))
        .group_by(Document.status)
    )
    status_map = {r.status: r.cnt for r in totals}

    avg_score = (await db.execute(
        select(func.avg(Document.parse_score)).where(Document.status == "done")
    )).scalar() or 0

    avg_chunks = (await db.execute(
        select(func.avg(Document.chunk_count)).where(Document.status == "done")
    )).scalar() or 0

    # 质量分布（按0.1分桶）
    dist_r = await db.execute(
        select(
            func.round(Document.parse_score, 1).label("bucket"),
            func.count().label("cnt"),
        )
        .where(Document.status == "done")
        .group_by("bucket")
        .order_by("bucket")
    )

    # 最近上传
    recent_r = await db.execute(
        select(Document.filename, Document.parse_score, Document.chunk_count, Document.status, Document.created_at)
        .order_by(Document.created_at.desc())
        .limit(10)
    )

    return {
        "status_counts": status_map,
        "avg_score":     round(avg_score, 3),
        "avg_chunks":    round(avg_chunks, 1),
        "score_dist": [
            {"score": str(r.bucket), "count": r.cnt} for r in dist_r
        ],
        "recent_docs": [
            {
                "filename":  r.filename,
                "score":     round(r.parse_score or 0, 2),
                "chunks":    r.chunk_count,
                "status":    r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recent_r
        ],
    }


@router.get("/qps")
async def qps(db: AsyncSession = Depends(get_db)):
    """近1小时 QPS（按分钟聚合）"""
    from datetime import datetime, timedelta
    since = datetime.utcnow() - timedelta(hours=1)
    result = await db.execute(
        select(
            func.date_trunc("minute", QueryLog.created_at).label("minute"),
            func.count().label("count"),
        )
        .where(QueryLog.created_at >= since)
        .group_by("minute")
        .order_by("minute")
    )
    return [{"minute": str(r.minute), "count": r.count} for r in result]
