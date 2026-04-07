"""RAG Service — orchestration layer for the full RAG pipeline.

Pipeline flow:
  Request → Auth + RateLimit + SingleFlight → Query Processing
  → Permission Check → Cache Check → Hybrid Retrieval → Rerank
  → Context Builder → LLM Call → Post Processing → Response
"""
from typing import Any, AsyncGenerator, Dict, Optional

from app.utils.logger import logger
from app.utils.trace import get_trace_id
from app.utils.context import RAGContext
from app.core.pipeline import (
    run_rag_pipeline,
    run_rag_stream,
    classify_intent,
)
from app.repository.redis_cache import cache


class RAGService:
    """Orchestration layer for the RAG pipeline."""

    async def query(
        self,
        question: str,
        user_id: str = "",
        session_id: Optional[str] = None,
        tenant_id: str = "default",
        user_role: str = "user",
    ) -> Dict[str, Any]:
        """Execute full RAG pipeline with permission and cache checks."""
        trace_id = get_trace_id()

        # Build unified context
        ctx = RAGContext(
            trace_id=trace_id,
            user_id=user_id,
            session_id=session_id or "",
            tenant_id=tenant_id,
            original_query=question,
            user_role=user_role,
        )

        # Permission check (extensible: check tenant/dept access)
        if not self._check_permission(ctx):
            logger.warning(f"[{trace_id}] Permission denied for user={user_id}")
            return {
                "answer": "您没有权限执行此查询。",
                "sources": [],
                "context": "",
                "confidence": 0.0,
                "rewritten_query": question,
                "intent": "C0",
                "cache_hit": False,
                "latency_ms": 0,
                "retrieval_ms": 0,
                "llm_ms": 0,
                "degrade_level": "C0",
                "degrade_reason": "PERMISSION_DENIED",
            }

        # Get doc version for cache key
        doc_version = await cache.get_global_doc_version()

        # Delegate to core pipeline
        result = await run_rag_pipeline(
            query=question,
            doc_version=doc_version,
            session_id=session_id,
            user_id=user_id,
            trace_id=trace_id,
        )

        return result

    async def stream(
        self,
        question: str,
        user_id: str = "",
    ) -> AsyncGenerator[str, None]:
        """Execute streaming RAG pipeline."""
        trace_id = get_trace_id()
        async for token in run_rag_stream(question, trace_id=trace_id):
            yield token

    async def classify(self, question: str) -> str:
        """Classify query intent."""
        return await classify_intent(question)

    def _check_permission(self, ctx: RAGContext) -> bool:
        """Check user permission for the query.

        Extensible: can check tenant-level, department-level,
        or document-level access control.
        Currently allows all authenticated users.
        """
        if not ctx.user_id:
            return False
        return True


rag_service = RAGService()
