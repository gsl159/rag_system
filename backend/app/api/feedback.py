"""
/feedback 路由
"""
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ok, err, ErrorCode, get_current_user
from app.repository.postgres import get_db
from app.service.feedback_service import feedback_service

router = APIRouter(prefix="/feedback", tags=["用户反馈"])


class FeedbackRequest(BaseModel):
    query:      str
    answer:     str
    feedback:   str   # like | dislike
    comment:    Optional[str] = None
    log_id:     Optional[int] = None
    session_id: Optional[str] = None


@router.post("/")
async def submit(req: FeedbackRequest, db: AsyncSession = Depends(get_db),
                 user: dict = Depends(get_current_user)):
    if req.feedback not in ("like", "dislike"):
        from fastapi import HTTPException
        raise HTTPException(400, detail={"code": 1001, "message": "feedback 必须是 like 或 dislike"})
    fb = await feedback_service.submit(
        query=req.query, answer=req.answer, feedback=req.feedback,
        comment=req.comment, log_id=req.log_id, session_id=req.session_id,
        db=db, user_id=user.get("sub"),
    )
    return ok({"id": fb.id, "message": "反馈已记录"})


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    return ok(await feedback_service.get_stats(db))
