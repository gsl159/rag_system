"""
评估服务
- LLM 自动评分（relevance / faithfulness / completeness / overall）
- 指标聚合（avg_score, latency, QPS）
"""
from datetime import datetime, timedelta
from typing import Dict, Any, List

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import llm_client
from app.core.logger import logger
from app.db.postgres import Evaluation, QueryLog


class EvalService:

    # ── 自动评分 ──────────────────────────────────

    async def evaluate(
        self,
        query:   str,
        answer:  str,
        context: str = "",
        log_id:  int = None,
        db:      AsyncSession = None,
    ) -> Dict[str, Any]:
        scores = await self._llm_score(query, answer, context)

        if db:
            ev = Evaluation(
                log_id       = log_id,
                query        = query,
                answer       = answer,
                relevance    = scores.get("relevance",    0),
                faithfulness = scores.get("faithfulness", 0),
                completeness = scores.get("completeness", 0),
                overall      = scores.get("overall",      0),
                reason       = scores.get("reason",       ""),
            )
            db.add(ev)
            await db.commit()

        return scores

    async def _llm_score(self, query: str, answer: str, context: str) -> Dict[str, Any]:
        prompt = f"""请对 RAG 系统的回答进行评分（每项 1-5 分）：

维度：
1. relevance（相关性）：回答是否切题
2. faithfulness（忠实性）：是否忠于上下文，无捏造
3. completeness（完整性）：是否全面回答了问题

用户问题：{query}
参考上下文（前500字）：{context[:500]}
系统回答：{answer}

请严格返回 JSON（不含其他文字）：
{{"relevance": 4, "faithfulness": 5, "completeness": 3, "overall": 4, "reason": "简短理由"}}"""

        try:
            result = await llm_client.chat_json([{"role": "user", "content": prompt}])
            # 计算 overall（如果模型没返回）
            if "overall" not in result:
                result["overall"] = round(
                    (result.get("relevance", 0) + result.get("faithfulness", 0) + result.get("completeness", 0)) / 3, 2
                )
            return result
        except Exception as e:
            logger.warning(f"LLM 评分失败: {e}")
            return {"relevance": 0, "faithfulness": 0, "completeness": 0, "overall": 0, "reason": str(e)}

    # ── 指标聚合 ──────────────────────────────────

    async def get_metrics(self, days: int = 7, db: AsyncSession = None) -> Dict[str, Any]:
        since = datetime.utcnow() - timedelta(days=days)

        total_q  = (await db.execute(
            select(func.count()).select_from(QueryLog).where(QueryLog.created_at >= since)
        )).scalar() or 0

        avg_lat  = (await db.execute(
            select(func.avg(QueryLog.latency_ms)).where(QueryLog.created_at >= since)
        )).scalar() or 0

        cache_hit = (await db.execute(
            select(func.count()).select_from(QueryLog).where(
                and_(QueryLog.cache_hit == True, QueryLog.created_at >= since)
            )
        )).scalar() or 0

        avg_score = (await db.execute(
            select(func.avg(Evaluation.overall)).where(Evaluation.created_at >= since)
        )).scalar() or 0

        # 每日统计
        daily = await db.execute(
            select(
                func.date(QueryLog.created_at).label("day"),
                func.count().label("queries"),
                func.avg(QueryLog.latency_ms).label("avg_latency"),
                func.sum(QueryLog.cache_hit.cast(func.Integer() if False else "INTEGER")).label("cache_hits"),
            )
            .where(QueryLog.created_at >= since)
            .group_by("day")
            .order_by("day")
        )

        return {
            "total_queries":  total_q,
            "avg_latency_ms": round(avg_lat, 1),
            "cache_hit_count": cache_hit,
            "cache_hit_rate": round(cache_hit / total_q, 3) if total_q else 0,
            "avg_score":      round(avg_score, 2),
            "days":           days,
            "daily": [
                {
                    "day":         str(r.day),
                    "queries":     r.queries,
                    "avg_latency": round(r.avg_latency or 0, 1),
                    "cache_hits":  r.cache_hits or 0,
                }
                for r in daily
            ],
        }


eval_service = EvalService()
