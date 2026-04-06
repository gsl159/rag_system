"""
评估服务
- LLM 自动评分（relevance / faithfulness / completeness / overall）
- 指标聚合（avg_score, latency, QPS）
修复：cache_hit cast 语法错误
"""
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from sqlalchemy import select, func, and_, cast, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.generator import llm_client
from app.utils.logger import logger
from app.repository.postgres import Evaluation, QueryLog


class EvalService:

    # ── 自动评分 ──────────────────────────────────

    async def evaluate(
        self,
        query:   str,
        answer:  str,
        context: str = "",
        log_id:  Optional[int] = None,
        db:      Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        scores = await self._llm_score(query, answer, context)

        if db:
            try:
                ev = Evaluation(
                    log_id       = log_id,
                    query        = query[:1000],
                    answer       = (answer or "")[:2000],
                    relevance    = scores.get("relevance",    0),
                    faithfulness = scores.get("faithfulness", 0),
                    completeness = scores.get("completeness", 0),
                    overall      = scores.get("overall",      0),
                    reason       = (scores.get("reason", "") or "")[:500],
                )
                db.add(ev)
                await db.commit()
            except Exception as e:
                logger.warning(f"评估写入DB失败: {e}")
                await db.rollback()

        return scores

    async def _llm_score(self, query: str, answer: str, context: str) -> Dict[str, Any]:
        prompt = f"""请对 RAG 系统的回答进行评分（每项 1-5 分）：

维度：
1. relevance（相关性）：回答是否切题
2. faithfulness（忠实性）：是否忠于上下文，无捏造
3. completeness（完整性）：是否全面回答了问题

用户问题：{query}
参考上下文（前500字）：{context[:500]}
系统回答：{answer[:500]}

请严格返回 JSON（不含其他文字）：
{{"relevance": 4, "faithfulness": 5, "completeness": 3, "overall": 4, "reason": "简短理由"}}"""

        try:
            result = await llm_client.chat_json([{"role": "user", "content": prompt}])
            # 校验分数范围
            for k in ("relevance", "faithfulness", "completeness", "overall"):
                v = result.get(k, 0)
                result[k] = max(0, min(5, float(v)))
            if "overall" not in result or result["overall"] == 0:
                result["overall"] = round(
                    (result.get("relevance", 0) + result.get("faithfulness", 0) + result.get("completeness", 0)) / 3, 2
                )
            return result
        except Exception as e:
            logger.warning(f"LLM 评分失败: {e}")
            return {"relevance": 0, "faithfulness": 0, "completeness": 0, "overall": 0, "reason": str(e)[:200]}

    # ── 指标聚合 ──────────────────────────────────

    async def get_metrics(self, days: int = 7, db: Optional[AsyncSession] = None) -> Dict[str, Any]:
        if db is None:
            return {"total_queries": 0, "avg_latency_ms": 0, "cache_hit_count": 0,
                    "cache_hit_rate": 0, "avg_score": 0, "days": days, "daily": []}

        since = datetime.utcnow() - timedelta(days=days)

        total_q = (await db.execute(
            select(func.count()).select_from(QueryLog).where(QueryLog.created_at >= since)
        )).scalar() or 0

        avg_lat = (await db.execute(
            select(func.avg(QueryLog.latency_ms)).where(QueryLog.created_at >= since)
        )).scalar() or 0

        cache_hit = (await db.execute(
            select(func.count()).select_from(QueryLog).where(
                and_(QueryLog.cache_hit == True, QueryLog.created_at >= since)  # noqa: E712
            )
        )).scalar() or 0

        avg_score = (await db.execute(
            select(func.avg(Evaluation.overall)).where(Evaluation.created_at >= since)
        )).scalar() or 0

        # 每日统计 — 修复 cast 语法
        daily_rows = await db.execute(
            select(
                func.date(QueryLog.created_at).label("day"),
                func.count().label("queries"),
                func.avg(QueryLog.latency_ms).label("avg_latency"),
                func.sum(cast(QueryLog.cache_hit, Integer)).label("cache_hits"),
            )
            .where(QueryLog.created_at >= since)
            .group_by(func.date(QueryLog.created_at))
            .order_by(func.date(QueryLog.created_at))
        )

        return {
            "total_queries":   total_q,
            "avg_latency_ms":  round(float(avg_lat), 1),
            "cache_hit_count": cache_hit,
            "cache_hit_rate":  round(cache_hit / total_q, 3) if total_q else 0,
            "avg_score":       round(float(avg_score), 2),
            "days":            days,
            "daily": [
                {
                    "day":         str(r.day),
                    "queries":     r.queries,
                    "avg_latency": round(float(r.avg_latency or 0), 1),
                    "cache_hits":  int(r.cache_hits or 0),
                }
                for r in daily_rows
            ],
        }


eval_service = EvalService()
