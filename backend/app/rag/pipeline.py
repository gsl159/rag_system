"""Backward compatibility — imports from app.core.pipeline"""
from app.core.pipeline import (
    classify_intent, rewrite_query, get_embedding, build_context,
    generate_answer, llm_self_score, calc_confidence,
    run_rag_pipeline, run_rag_stream, SYSTEM_PROMPT,
)

__all__ = [
    "classify_intent", "rewrite_query", "get_embedding", "build_context",
    "generate_answer", "llm_self_score", "calc_confidence",
    "run_rag_pipeline", "run_rag_stream", "SYSTEM_PROMPT",
]
