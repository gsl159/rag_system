"""
/audit 路由 — 审计日志查询
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ok, err, ErrorCode, require_admin
from app.repository.postgres import get_db, AuditLog

router = APIRouter(prefix="/audit", tags=["审计日志"])


@router.get("/")
async def list_audit(
    page:   int = Query(1, ge=1),
    limit:  int = Query(20, ge=1, le=100),
    action: str = Query(None),
    db: AsyncSession = Depends(get_db),
    _admin = Depends(require_admin),
):
    q = select(AuditLog).order_by(desc(AuditLog.created_at))
    if action:
        q = q.where(AuditLog.action == action)
    total_r = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_r.scalar() or 0
    items_r = await db.execute(q.offset((page - 1) * limit).limit(limit))
    items = items_r.scalars().all()
    return ok({
        "total": total, "page": page, "limit": limit,
        "items": [
            {"id": i.id, "trace_id": i.trace_id, "user_id": i.user_id,
             "username": i.username, "action": i.action,
             "resource": i.resource, "ip": i.ip,
             "created_at": i.created_at.isoformat() if i.created_at else None}
            for i in items
        ]
    })
