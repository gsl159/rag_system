"""
/feedback 路由
"""
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.services.feedback_service import feedback_service

router = APIRouter(prefix="/feedback", tags=["用户反馈"])


class FeedbackRequest(BaseModel):
    query:      str
    answer:     str
    feedback:   str          # "like" | "dislike"
    comment:    Optional[str] = None
    log_id:     Optional[int] = None
    session_id: Optional[str] = None


@router.post("/")
async def submit(req: FeedbackRequest, db: AsyncSession = Depends(get_db)):
    if req.feedback not in ("like", "dislike"):
        from fastapi import HTTPException
        raise HTTPException(400, "feedback 必须是 'like' 或 'dislike'")
    fb = await feedback_service.submit(
        query=req.query, answer=req.answer, feedback=req.feedback,
        comment=req.comment, log_id=req.log_id,
        session_id=req.session_id, db=db,
    )
    return {"message": "反馈已记录", "id": fb.id}


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    return await feedback_service.get_stats(db)
