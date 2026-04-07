"""Unified context object for request propagation across all layers."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RAGContext:
    """Unified context object that propagates through the entire RAG pipeline."""
    # Request metadata
    trace_id: str = ""
    user_id: str = ""
    session_id: str = ""
    tenant_id: str = "default"

    # Query
    original_query: str = ""
    rewritten_query: str = ""
    intent: str = ""  # C0, C1, C2

    # Permission
    user_role: str = "user"

    # Retrieval
    query_embedding: List[float] = field(default_factory=list)
    doc_version: int = 0

    # Results
    retrieved_docs: List[Dict[str, Any]] = field(default_factory=list)
    reranked_docs: List[Dict[str, Any]] = field(default_factory=list)
    context_text: str = ""

    # Generation
    answer: str = ""
    confidence: float = 0.0
    degrade_level: str = "C2"
    degrade_reason: str = ""

    # Timing
    latency_ms: int = 0
    retrieval_ms: int = 0
    llm_ms: int = 0

    # Cache
    cache_hit: bool = False

    # Sources for response
    sources: List[Dict[str, Any]] = field(default_factory=list)

    def to_result(self) -> Dict[str, Any]:
        """Convert context to pipeline result dict."""
        return {
            "answer": self.answer,
            "context": self.context_text,
            "sources": self.sources,
            "rewritten_query": self.rewritten_query,
            "intent": self.intent,
            "confidence": self.confidence,
            "cache_hit": self.cache_hit,
            "latency_ms": self.latency_ms,
            "retrieval_ms": self.retrieval_ms,
            "llm_ms": self.llm_ms,
            "degrade_level": self.degrade_level,
            "degrade_reason": self.degrade_reason,
        }
