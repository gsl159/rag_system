"""
用户反馈服务
- 记录 👍 / 👎
- 统计 like_ratio, top_bad_queries
"""
from typing import Dict, Any, Optional

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.db.postgres import Feedback


class FeedbackService:

    async def submit(
        self,
        query:      str,
        answer:     str,
        feedback:   str,
        comment:    Optional[str],
        log_id:     Optional[int],
        session_id: Optional[str],
        db:         AsyncSession,
    ) -> Feedback:
        fb = Feedback(
            log_id     = log_id,
            session_id = session_id,
            query      = (query or "")[:1000],
            answer     = (answer or "")[:2000],
            feedback   = feedback,
            comment    = (comment or "")[:500] if comment else None,
        )
        db.add(fb)
        await db.commit()
        logger.info(f"反馈记录: feedback={feedback}, log_id={log_id}")
        return fb

    async def get_stats(self, db: AsyncSession) -> Dict[str, Any]:
        like_r = (await db.execute(
            select(func.count()).select_from(Feedback).where(Feedback.feedback == "like")
        )).scalar() or 0

        dislike_r = (await db.execute(
            select(func.count()).select_from(Feedback).where(Feedback.feedback == "dislike")
        )).scalar() or 0

        total = like_r + dislike_r

        bad_r = await db.execute(
            select(Feedback.query, Feedback.comment, Feedback.created_at)
            .where(Feedback.feedback == "dislike")
            .order_by(desc(Feedback.created_at))
            .limit(10)
        )

        recent_r = await db.execute(
            select(Feedback.query, Feedback.feedback, Feedback.comment, Feedback.created_at)
            .order_by(desc(Feedback.created_at))
            .limit(20)
        )

        return {
            "like":         like_r,
            "dislike":      dislike_r,
            "total":        total,
            "like_ratio":   round(like_r / total, 3) if total else 0,
            "satisfaction": round(like_r / total * 100, 1) if total else 0,
            "top_bad_queries": [
                {"query": (r.query or "")[:80], "comment": r.comment}
                for r in bad_r
            ],
            "recent": [
                {
                    "query":    (r.query or "")[:60],
                    "feedback": r.feedback,
                    "comment":  r.comment,
                    "time":     r.created_at.isoformat() if r.created_at else None,
                }
                for r in recent_r
            ],
        }


feedback_service = FeedbackService()
