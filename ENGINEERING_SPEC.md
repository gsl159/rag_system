# RAG Knowledge System — Implementable Engineering Specification

> **Version**: 2.0.0  
> **Status**: Production-ready implementation spec  
> **Stack**: Python 3.11 · FastAPI · SQLAlchemy (async) · Redis · Milvus · PostgreSQL 16 · MinIO

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Module Interfaces (Python)](#2-module-interfaces-python)
3. [RAG Pipeline Orchestration](#3-rag-pipeline-orchestration)
4. [Cache + SingleFlight Logic](#4-cache--singleflight-logic)
5. [Degrade Strategy](#5-degrade-strategy)
6. [Retrieval + Rerank Flow](#6-retrieval--rerank-flow)
7. [Redis Key Design](#7-redis-key-design)
8. [PostgreSQL DB Schema](#8-postgresql-db-schema)
9. [Tracing Propagation Design](#9-tracing-propagation-design)
10. [Async Concurrency Model](#10-async-concurrency-model)
11. [Document Processing Pipeline](#11-document-processing-pipeline)
12. [API Layer Contract](#12-api-layer-contract)
13. [Configuration Reference](#13-configuration-reference)
14. [Error Code Registry](#14-error-code-registry)

---

## 1. System Architecture

### 1.1 Layered Module Map

```
backend/app/
├── api/            # L1: Entry layer — routes, auth, rate limiting
│   ├── deps.py     #     Cross-cutting: JWT, rate limit, unified response, ErrorCode
│   ├── auth.py     #     POST /auth/login, /logout, GET /me
│   ├── chat.py     #     POST /chat/, GET /chat/stream (SSE)
│   ├── upload.py   #     Document CRUD + background processing
│   ├── feedback.py #     POST /feedback/, GET /feedback/stats
│   ├── metrics.py  #     GET /metrics/{overview,rag,cache,docs,qps}
│   └── audit.py    #     GET /audit/ (admin-only)
├── service/        # L2: Orchestration — business logic, permission, evaluation
│   ├── rag_service.py      #     RAG pipeline orchestration + permission
│   ├── doc_service.py      #     Document parse → chunk → embed → store
│   ├── eval_service.py     #     LLM auto-evaluation (background)
│   └── feedback_service.py #     Feedback CRUD + aggregation
├── core/           # L3: Domain — embedding, retrieval, reranking, generation
│   ├── pipeline.py    #     Full pipeline: intent → rewrite → retrieve → rerank → generate
│   ├── retriever.py   #     HybridRetriever: Dense(Milvus) + Sparse(BM25) + RRF
│   ├── reranker.py    #     LLMReranker + SimpleReranker
│   ├── generator.py   #     LLMClient + EmbedClient (OpenAI-compatible)
│   └── embedding.py   #     get_embedding() with Layer-2 cache
├── repository/     # L4: Data access — vector store, cache, database, object store
│   ├── postgres.py    #     SQLAlchemy ORM models + async engine
│   ├── redis_cache.py #     3-layer cache + SingleFlight + version control
│   ├── vector_store.py#     Milvus HNSW wrapper
│   └── object_store.py#     MinIO S3-compatible wrapper
├── config/
│   └── settings.py    #     Pydantic BaseSettings from environment
└── utils/
    ├── logger.py      #     Loguru structured logging with trace_id
    ├── trace.py       #     ContextVar-based trace_id propagation
    ├── context.py     #     RAGContext dataclass
    └── helpers.py     #     md5_hash(), truncate()
```

### 1.2 Request Lifecycle

```
HTTP Request
  │
  ▼
┌─────────────────────────────────────────────────────┐
│ FastAPI Middleware                                   │
│   1. trace_middleware: generate/propagate trace_id   │
│   2. CORSMiddleware                                 │
│   3. global_exception_handler                       │
└─────────────┬───────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│ API Layer (api/chat.py)                             │
│   4. Depends(get_current_user) → JWT validation     │
│   5. Depends(check_rate_limit) → Redis sliding win  │
│   6. Input validation: 0 < len(question) ≤ 2000    │
└─────────────┬───────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│ Service Layer (service/rag_service.py)              │
│   7. Build RAGContext                               │
│   8. _check_permission(ctx)                         │
│   9. cache.get_global_doc_version()                 │
│  10. Delegate to run_rag_pipeline()                 │
└─────────────┬───────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│ Core Pipeline (core/pipeline.py)                    │
│  11. Layer-3 RAG cache check                        │
│  12. SingleFlight deduplication                     │
│  13. classify_intent(query)                         │
│  14. Layer-1 Query cache → rewrite_query(query)     │
│  15. get_embedding(rewritten) [Layer-2 cache]       │
│  16. retriever.retrieve(rewritten, vec, top_k)      │
│  17. simple_reranker.rerank(rewritten, docs, top_n) │
│  18. build_context(top_docs)                        │
│  19. generate_answer(rewritten, context, intent)    │
│  20. llm_self_score(query, answer) [bounded 2.5s]   │
│  21. calc_confidence(top_docs, emb_sim, self_score) │
│  22. cache.set_rag(query, result, doc_version)      │
└─────────────┬───────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│ Post-Processing (api/chat.py)                       │
│  23. Write QueryLog to PostgreSQL                   │
│  24. Write AuditLog to PostgreSQL                   │
│  25. BackgroundTask: _async_evaluate() [if !cached] │
│  26. Return ok({answer, sources, confidence, ...})   │
└─────────────────────────────────────────────────────┘
```

### 1.3 External Service Dependencies

| Service    | Role                     | Connection            | Pool Config             |
|------------|--------------------------|----------------------|-------------------------|
| PostgreSQL | Metadata, logs, users    | asyncpg              | pool_size=10, max_overflow=20 |
| Redis      | 3-layer cache, rate limit| redis.asyncio        | socket_timeout=5s       |
| Milvus     | Dense vector search      | pymilvus (sync)      | Single connection       |
| MinIO      | Document object storage  | minio (sync)         | Single connection       |
| SiliconFlow| LLM + Embedding API      | httpx.AsyncClient    | Per-request client, timeout=120s |

---

## 2. Module Interfaces (Python)

### 2.1 Data Models

#### 2.1.1 RAGContext — Pipeline State Object

```python
# app/utils/context.py
from dataclasses import dataclass, field
from typing import Any, Dict, List

@dataclass
class RAGContext:
    # Request metadata
    trace_id: str = ""
    user_id: str = ""
    session_id: str = ""
    tenant_id: str = "default"

    # Query
    original_query: str = ""
    rewritten_query: str = ""
    intent: str = ""                          # "C0" | "C1" | "C2"

    # Permission
    user_role: str = "user"                   # "user" | "admin" | "super_admin"

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
    degrade_level: str = "C2"                 # "C0" | "C1" | "C2"
    degrade_reason: str = ""

    # Timing (milliseconds)
    latency_ms: int = 0
    retrieval_ms: int = 0
    llm_ms: int = 0

    # Cache
    cache_hit: bool = False

    # Sources for response
    sources: List[Dict[str, Any]] = field(default_factory=list)

    def to_result(self) -> Dict[str, Any]:
        """Convert context to API response dict."""
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
```

#### 2.1.2 Pipeline Result Dict Shape

```python
# Returned by run_rag_pipeline()
PipelineResult = TypedDict("PipelineResult", {
    "answer":          str,       # Generated answer text
    "context":         str,       # Assembled context from top docs
    "sources":         list,      # [{text, score, doc_id, chunk_idx}, ...]
    "rewritten_query": str,       # LLM-rewritten query
    "intent":          str,       # "C0" | "C1" | "C2"
    "confidence":      float,     # 0.0–1.0
    "cache_hit":       bool,
    "latency_ms":      int,       # Total pipeline latency
    "retrieval_ms":    int,       # Hybrid retrieval latency
    "llm_ms":          int,       # LLM generation latency
    "degrade_level":   str,       # "C0" | "C1" | "C2"
    "degrade_reason":  str,       # "" | "C2_TIMEOUT" | "LLM_TIMEOUT" | ...
})
```

#### 2.1.3 Unified API Response Envelope

```python
# All API endpoints return:
{
    "code":     int,       # 0 = success, see ErrorCode
    "message":  str,       # Human-readable message
    "data":     Any,       # Payload (dict, list, or None)
    "trace_id": str,       # 16-char hex, e.g. "a1b2c3d4e5f6a7b8"
}
```

### 2.2 Core Module Interfaces

#### 2.2.1 pipeline.py — RAG Pipeline

```python
# app/core/pipeline.py

async def classify_intent(query: str) -> str:
    """Classify query into C0/C1/C2 based on length + keyword heuristics.

    Rules:
        len < 15 OR contains FAQ keywords → "C0"
        15 ≤ len < 40                     → "C1"
        len ≥ 40                          → "C2"

    FAQ keywords: ["是什么", "定义", "什么叫", "怎么读", "含义"]
    """

async def rewrite_query(query: str) -> str:
    """LLM-based query rewriting for better retrieval.

    Timeout: settings.QUERY_REWRITE_TIMEOUT (default 3.0s)
    Fallback: returns original query on timeout/error.
    """

def build_context(docs: List[Dict], max_chars: int = None) -> str:
    """Assemble retrieved docs into a formatted context string.

    Format per doc: "[来源{i+1}]\n{text}"
    Separator: "\n\n---\n\n"
    Truncation: stops at max_chars (default settings.CONTEXT_MAX_CHARS=3000),
                includes partial doc if remaining > 100 chars.
    """

async def generate_answer(
    query: str, context: str, intent: str = "C2"
) -> Tuple[str, str, str]:
    """LLM generation with cascading timeout degradation.

    Returns: (answer, degrade_level, degrade_reason)

    If context is empty → returns canned "no info" response, level="C0", reason="NO_CONTEXT"

    Degradation cascade:
        C2: full generation, timeout=LLM_TIMEOUT_C2 (3.0s), max_tokens=1024
          ↓ TimeoutError
        C1: summary mode, timeout=LLM_TIMEOUT_C1 (1.5s), max_tokens=300, context[:800]
          ↓ TimeoutError
        C0: raw snippet, context[:400], no LLM call
    """

async def llm_self_score(query: str, answer: str) -> float:
    """LLM self-evaluation score (0.0–1.0).

    Timeout: settings.LLM_SELF_SCORE_TIMEOUT (2.0s)
    Fallback: 0.5 on any error.
    Non-blocking: outer caller wraps with asyncio.wait_for(timeout=2.5).
    """

def calc_confidence(
    top_docs: List[Dict], embedding_sim: float, llm_score: float
) -> float:
    """Weighted confidence score with dynamic normalization.

    Formula: 0.5 × rerank_norm + 0.3 × emb_norm + 0.2 × llm_score

    Normalization logic:
        if max(rerank_scores) > 1.0:
            # LLMReranker range (0–10): rerank_norm = avg / 10.0
        else:
            # SimpleReranker range (≈0.01): rerank_norm = avg × 20.0
        Both clamped to [0, 1]
    """

async def run_rag_pipeline(
    query: str,
    doc_version: int = 0,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    trace_id: str = "",
) -> Dict[str, Any]:
    """Full RAG pipeline entry point. Returns PipelineResult dict.

    Flow: cache_check → singleflight → _run_internal → cache_store
    Error fallback: returns canned error response with degrade_reason="SYSTEM_ERROR"
    """

async def run_rag_stream(
    query: str, trace_id: str = ""
) -> AsyncGenerator[str, None]:
    """Streaming RAG pipeline (SSE). Yields LLM tokens.

    Flow: rewrite → embed → retrieve → rerank → build_context → llm.stream()
    Error fallback: yields single error message string.
    """
```

#### 2.2.2 retriever.py — Hybrid Retrieval

```python
# app/core/retriever.py

class HybridRetriever:
    """Thread-safe hybrid retriever: Dense(Milvus) + Sparse(BM25) + RRF fusion."""

    def __init__(self) -> None:
        self._corpus: List[str]              # In-memory BM25 corpus
        self._bm25: Optional[BM25Okapi]      # BM25 index (rebuilt on add)
        self._lock: threading.Lock            # Thread safety for BM25 ops

    def add_texts(self, texts: List[str]) -> None:
        """Append texts to BM25 corpus and rebuild index. Thread-safe."""

    def reset(self) -> None:
        """Clear BM25 corpus and index."""

    def _sparse_search(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """BM25 sparse retrieval.

        Tokenization: character-level (list(query), list(text))
        Returns: [{"id": "bm25_{i}", "text": str, "score": float, "source": "sparse"}]
        Filters: score > 0 only
        """

    @staticmethod
    def _rrf_merge(
        dense: List[Dict],
        sparse: List[Dict],
        alpha: float = None,      # Default: settings.HYBRID_RETRIEVAL_ALPHA (0.7)
        k: int = 60,              # RRF constant
    ) -> List[Dict]:
        """Reciprocal Rank Fusion merge.

        For each document d appearing in either list:
            score(d) = alpha × 1/(k + rank_dense(d) + 1)
                     + (1 - alpha) × 1/(k + rank_sparse(d) + 1)

        Dedup key: text[:100]
        Adds "rrf_score" field to each output dict.
        Returns: sorted by rrf_score descending.
        """

    async def retrieve(
        self, query: str, query_vec: List[float], top_k: int = None
    ) -> List[Dict]:
        """Main retrieval entry point.

        1. milvus_db.search(query_vec, top_k) → dense results
           (fallback to empty on Milvus failure → pure BM25)
        2. _sparse_search(query, top_k) → sparse results
        3. _rrf_merge(dense, sparse) → merged
        4. Return merged[:top_k * 2]
        """

# Module singleton
retriever = HybridRetriever()
```

#### 2.2.3 reranker.py — Reranking

```python
# app/core/reranker.py

class LLMReranker:
    """LLM-based cross-encoder reranking. Scores 0–10 per document."""

    async def rerank(
        self, query: str, docs: List[Dict[str, Any]], top_n: int = 5
    ) -> List[Dict[str, Any]]:
        """Rerank with LLM scoring.

        1. Build prompt with passages (text[:300] each)
        2. LLM returns JSON: {"scores": [8, 3, 9, ...]}
        3. Sort by score descending, take top_n
        4. Add "rerank_score" field (float, 0–10)

        Timeout: 2.0s
        Fallback: return docs[:top_n] (original order)
        """


class SimpleReranker:
    """Keyword-coverage reranker. No API calls."""

    def rerank(
        self, query: str, docs: List[Dict], top_n: int = 5
    ) -> List[Dict]:
        """Lightweight rerank using keyword coverage + RRF score.

        For each doc:
            coverage = |{char ∈ query : char ∈ doc.text}| / |set(query)|
            rerank_score = rrf_score × 0.7 + coverage × 0.3

        Returns: sorted by rerank_score descending, top_n.
        """

# Module singletons
reranker = LLMReranker()
simple_reranker = SimpleReranker()
```

#### 2.2.4 generator.py — LLM & Embedding Clients

```python
# app/core/generator.py

class LLMClient:
    """OpenAI-compatible LLM text generation client."""

    def __init__(self) -> None:
        self.base_url: str   # settings.SILICONFLOW_BASE_URL
        self.api_key: str    # settings.SILICONFLOW_API_KEY
        self.model: str      # settings.LLM_MODEL

    async def chat(
        self, messages: list, temperature: float = 0.3, max_tokens: int = 1024
    ) -> str:
        """Synchronous chat completion. Returns content string.
        HTTP: POST {base_url}/chat/completions
        Client timeout: 120s
        """

    async def chat_json(self, messages: list) -> dict:
        """Chat completion with JSON response format constraint.
        Adds response_format={"type": "json_object"}
        Client timeout: 60s
        """

    async def stream(self, messages: list) -> AsyncGenerator[str, None]:
        """SSE streaming chat completion. Yields content delta strings.
        Processes "data: " lines, stops on "[DONE]".
        """


class EmbedClient:
    """OpenAI-compatible embedding client."""

    def __init__(self) -> None:
        self.base_url: str   # settings.SILICONFLOW_BASE_URL
        self.api_key: str    # settings.SILICONFLOW_API_KEY
        self.model: str      # settings.EMBED_MODEL

    async def embed_one(self, text: str) -> List[float]:
        """Single text embedding. Delegates to embed_batch([text])[0]."""

    async def embed_batch(
        self, texts: List[str], batch_size: int = 32
    ) -> List[List[float]]:
        """Batch embedding. Splits into 32-item batches.
        HTTP: POST {base_url}/embeddings
        Client timeout: 60s per batch.
        """

# Module singletons
llm_client = LLMClient()
embed_client = EmbedClient()
```

#### 2.2.5 embedding.py — Cached Embedding

```python
# app/core/embedding.py

async def get_embedding(text: str) -> List[float]:
    """Get embedding with Layer-2 Redis cache.

    1. cache.get_embed(text) → hit? return cached vector
    2. embed_client.embed_one(text) → compute
    3. cache.set_embed(text, vec) → store
    4. Return vec
    """

async def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Batch embedding (no per-text caching). Delegates to embed_client.embed_batch()."""
```

### 2.3 Service Layer Interfaces

#### 2.3.1 rag_service.py — Pipeline Orchestration

```python
# app/service/rag_service.py

class RAGService:
    """Orchestration layer adding permission + version control to core pipeline."""

    async def query(
        self,
        question: str,
        user_id: str = "",
        session_id: Optional[str] = None,
        tenant_id: str = "default",
        user_role: str = "user",
    ) -> Dict[str, Any]:
        """Execute full RAG pipeline.

        1. Build RAGContext
        2. _check_permission(ctx) → deny if user_id is empty
        3. cache.get_global_doc_version() → for cache key
        4. run_rag_pipeline(question, doc_version, session_id, user_id, trace_id)
        5. Return PipelineResult dict
        """

    async def stream(
        self, question: str, user_id: str = ""
    ) -> AsyncGenerator[str, None]:
        """Streaming RAG. Delegates to run_rag_stream()."""

    async def classify(self, question: str) -> str:
        """Classify intent. Delegates to classify_intent()."""

    def _check_permission(self, ctx: RAGContext) -> bool:
        """Permission gate. Currently: requires non-empty user_id.
        Extension point for tenant/dept/document ACL.
        """

# Module singleton
rag_service = RAGService()
```

#### 2.3.2 doc_service.py — Document Processing

```python
# app/service/doc_service.py

class DocParser:
    def parse(self, file_path: str) -> str:
        """Route by extension: .pdf→pymupdf, .docx→python-docx, .html→html.parser, else→read_text"""

class TextCleaner:
    def clean(self, text: str) -> str:
        """Remove control chars, normalize whitespace, keep CJK+ASCII printable."""

class TextSplitter:
    def __init__(self, chunk_size: int = 500, overlap: int = 50): ...
    def split(self, text: str) -> List[str]:
        """Sliding window chunking with sentence-boundary awareness.
        Break points: 。！？.!?\n\n\n；;
        Search range: [chunk_size//2, chunk_size] (prefer later sentence end)
        """

class QualityChecker:
    def evaluate(self, chunks: List[str]) -> Dict[str, Any]:
        """Score = 0.7 × valid_ratio + 0.3 × length_norm
        valid: chunk ≥ 10 chars; length_norm: min(avg_len/100, 1.0)
        Returns: {score, valid_ratio, avg_length, total, valid}
        """

class DocumentService:
    async def process(self, doc_id: str, file_path: str, db: AsyncSession) -> None:
        """Full document processing pipeline:
        1. Set status = "processing"
        2. Parse → clean → split → quality check (≥ QUALITY_THRESHOLD)
        3. embed_client.embed_batch(chunks)
        4. milvus_db.insert(ids, doc_ids, chunk_idxs, texts, embeddings)
        5. retriever.add_texts(chunks)  # BM25 index
        6. Persist Chunk records to PostgreSQL
        7. Set status = "done", parse_score, chunk_count
        8. On error: rollback, set status = "failed", error_msg
        """

# Module singleton
doc_service = DocumentService()
```

### 2.4 Repository Layer Interfaces

#### 2.4.1 redis_cache.py — 3-Layer Cache + SingleFlight

```python
# app/repository/redis_cache.py

class CacheStats:
    hits: int
    misses: int

    @property
    def hit_rate(self) -> float: ...
    def record_hit(self) -> None: ...
    def record_miss(self) -> None: ...


class RedisCache:
    client: Optional[aioredis.Redis]
    embedding_version: str                   # "v1" — bumped on model change

    async def connect(self) -> None: ...

    # Layer 1: Query Cache (TTL: 1800s)
    async def get_query(self, query: str, doc_version: int = 0) -> Optional[dict]: ...
    async def set_query(self, query: str, value: dict, doc_version: int = 0) -> None: ...

    # Layer 2: Embedding Cache (TTL: 86400s)
    async def get_embed(self, text: str) -> Optional[list]: ...
    async def set_embed(self, text: str, vec: list) -> None: ...

    # Layer 3: RAG Pipeline Cache (TTL: 3600s)
    async def get_rag(self, query: str, doc_version: int = 0) -> Optional[dict]: ...
    async def set_rag(self, query: str, value: dict, doc_version: int = 0) -> None: ...

    # SingleFlight
    async def single_flight(self, key: str, coro_factory: Callable) -> Any: ...

    # Version management
    async def get_global_doc_version(self) -> int: ...
    async def increment_doc_version(self) -> int: ...

    # Stats
    async def get_stats(self) -> dict: ...

# Module singleton
cache = RedisCache()
```

#### 2.4.2 vector_store.py — Milvus Wrapper

```python
# app/repository/vector_store.py

class MilvusDB:
    _connected: bool
    _collection: Optional[Collection]

    def connect(self) -> None: ...
    def insert(
        self, ids: List[str], doc_ids: List[str],
        chunk_idxs: List[int], texts: List[str],
        embeddings: List[List[float]]
    ) -> None: ...
    def search(self, query_vec: List[float], top_k: int = 10) -> List[Dict[str, Any]]: ...
    def delete_by_doc(self, doc_id: str) -> None: ...
    def get_stats(self) -> dict: ...

    @property
    def is_connected(self) -> bool: ...

# Module singleton
milvus_db = MilvusDB()
```

---

## 3. RAG Pipeline Orchestration

### 3.1 Complete Pipeline Pseudocode

```
FUNCTION run_rag_pipeline(query, doc_version, session_id, user_id, trace_id):
    t0 = NOW()

    ┌─ STEP 1: Layer-3 RAG Cache ────────────────────────┐
    │ key = "cache:rag:{md5(query)}:{doc_version}:{embed_version}"
    │ cached = redis.GET(key)
    │ IF cached:
    │   cached.cache_hit = true
    │   cached.latency_ms = elapsed(t0)
    │   RETURN cached
    └────────────────────────────────────────────────────┘

    ┌─ STEP 2: SingleFlight Deduplication ───────────────┐
    │ sf_key = "sf:{md5(query)}"
    │ IF sf_key IN _inflight:
    │   WAIT for _inflight[sf_key] (max 2.0s)
    │   RETURN shared result OR fallback to own execution
    │ ELSE:
    │   _inflight[sf_key] = new Future
    │   result = _run_internal(query, doc_version, t0, trace_id)
    │   future.set_result(result)
    │   DELETE _inflight[sf_key]
    │   RETURN result
    └────────────────────────────────────────────────────┘

    ┌─ STEP 2a: _run_internal ───────────────────────────┐
    │                                                     │
    │ ── 3: Intent Classification ──────────────          │
    │ intent = classify_intent(query)  # C0/C1/C2         │
    │                                                     │
    │ ── 4: Layer-1 Query Cache ─────────────────         │
    │ key = "cache:query:{md5(query)}:{doc_version}:{ev}" │
    │ q_cached = redis.GET(key)                           │
    │ IF q_cached:                                        │
    │   rewritten = q_cached["rewritten"]                 │
    │ ELSE:                                               │
    │   rewritten = await rewrite_query(query) [3.0s TO]  │
    │   redis.SET(key, {"rewritten": rewritten}, TTL=1800)│
    │                                                     │
    │ ── 5: Embedding (Layer-2 Cache) ──────────          │
    │ t_ret = NOW()                                       │
    │ key = "cache:embed:{md5(rewritten)}:{ev}"           │
    │ vec_cached = redis.GET(key)                         │
    │ IF vec_cached:                                      │
    │   query_vec = vec_cached                            │
    │ ELSE:                                               │
    │   query_vec = embed_client.embed_one(rewritten)     │
    │   redis.SET(key, query_vec, TTL=86400)              │
    │ ON ERROR: RETURN error result, reason=EMBED_FAIL    │
    │                                                     │
    │ ── 6: Hybrid Retrieval ───────────────────          │
    │ dense  = milvus_db.search(query_vec, top_k=10)     │
    │   ON ERROR: dense = []  (degrade to BM25-only)      │
    │ sparse = bm25.get_scores(list(rewritten))           │
    │ merged = RRF_merge(dense, sparse, alpha=0.7, k=60) │
    │ docs   = merged[:top_k * 2]                         │
    │ retrieval_ms = elapsed(t_ret)                       │
    │                                                     │
    │ ── 7: Rerank ─────────────────────────────          │
    │ top_docs = SimpleReranker.rerank(rewritten, docs, 5)│
    │   rerank_score = rrf_score × 0.7 + coverage × 0.3  │
    │                                                     │
    │ ── 8: Context Assembly ───────────────────          │
    │ context = build_context(top_docs, max_chars=3000)   │
    │ emb_sim = top_docs[0].score IF top_docs ELSE 0.0    │
    │                                                     │
    │ ── 9: LLM Generation (Cascading Degrade) ─         │
    │ t_llm = NOW()                                       │
    │ (answer, deg_level, deg_reason) =                   │
    │     generate_answer(rewritten, context, intent)     │
    │ llm_ms = elapsed(t_llm)                             │
    │                                                     │
    │ ── 10: Self-Score (Non-blocking) ─────────          │
    │ self_score = 0.5                                    │
    │ TRY:                                                │
    │   self_score = await wait_for(                      │
    │     llm_self_score(query, answer), timeout=2.5      │
    │   )                                                 │
    │ EXCEPT: pass                                        │
    │                                                     │
    │ ── 11: Confidence Calculation ────────────          │
    │ confidence = calc_confidence(top_docs, emb_sim,     │
    │                              self_score)            │
    │                                                     │
    │ ── 12: Build Result + Cache Store ────────          │
    │ result = {answer, context, sources, rewritten_query,│
    │          intent, confidence, cache_hit=false,        │
    │          latency_ms, retrieval_ms, llm_ms,          │
    │          degrade_level, degrade_reason}              │
    │ redis.SET(rag_key, result, TTL=3600)                │
    │ LOG: "[{trace_id}] RAG complete ..."                │
    │ RETURN result                                       │
    └─────────────────────────────────────────────────────┘
```

### 3.2 Streaming Pipeline Pseudocode

```
ASYNC GENERATOR run_rag_stream(query, trace_id):
    rewritten = await rewrite_query(query)
    query_vec = await get_embedding(rewritten)
    docs      = await retriever.retrieve(rewritten, query_vec)
    top_docs  = simple_reranker.rerank(rewritten, docs, top_n=5)
    context   = build_context(top_docs)

    IF NOT context:
        YIELD "根据现有文档，未找到相关信息。请上传相关文档后再试。"
        RETURN

    messages = [
        {role: "system", content: SYSTEM_PROMPT},
        {role: "user",   content: "【参考资料】\n{context}\n\n【问题】\n{query}"},
    ]
    ASYNC FOR token IN llm_client.stream(messages):
        YIELD token

    ON ERROR:
        YIELD "抱歉，处理时发生错误，请稍后重试。"
```

---

## 4. Cache + SingleFlight Logic

### 4.1 Three-Layer Cache Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Three-Layer Redis Cache                         │
├───────────┬──────────┬──────────┬───────────────────────────────────┤
│  Layer    │  TTL     │  Content │  Invalidation                    │
├───────────┼──────────┼──────────┼───────────────────────────────────┤
│  L1 Query │  30 min  │  {rewritten_query}           │ doc_version │
│  L2 Embed │  24 h    │  float[1024] vector          │ embed_ver   │
│  L3 RAG   │  1 h     │  full PipelineResult dict    │ doc_version │
└───────────┴──────────┴──────────┴───────────────────────────────────┘
```

### 4.2 Cache Key Construction

```python
def _query_key(query: str, doc_version: int) -> str:
    h = hashlib.md5(query.encode()).hexdigest()
    return f"cache:query:{h}:{doc_version}:{self.embedding_version}"

def _embed_key(text: str) -> str:
    h = hashlib.md5(text.encode()).hexdigest()
    return f"cache:embed:{h}:{self.embedding_version}"

def _rag_key(query: str, doc_version: int) -> str:
    h = hashlib.md5(query.encode()).hexdigest()
    return f"cache:rag:{h}:{doc_version}:{self.embedding_version}"
```

### 4.3 TTL Jitter to Prevent Stampede

```python
async def _safe_set(self, key: str, value: str, ttl: int):
    jitter = random.randint(0, max(ttl // 10, 1))
    await self.client.set(key, value, ex=ttl + jitter)
```

**Example**: L3 RAG cache with TTL=3600 → actual expiry is 3600 + random(0..360).

### 4.4 Version-Based Invalidation

```
Document uploaded/deleted → cache.increment_doc_version()
                          → Redis INCR "global:doc_version" → new version N+1

Next query → cache.get_global_doc_version() → N+1
           → key includes :{N+1}: → cache miss on all old entries
           → old keys expire naturally via TTL
```

No explicit cache purge needed — version mismatch causes automatic misses.

### 4.5 SingleFlight Implementation

```python
# In-memory deduplication (process-level, not distributed)
_inflight: Dict[str, asyncio.Future] = {}

async def single_flight(key: str, coro_factory: Callable) -> Any:
    """
    Scenario: 100 concurrent identical queries arrive in 50ms.

    Request 1 (leader):
        1. key NOT in _inflight
        2. Create Future, store _inflight[key] = future
        3. result = await coro_factory()
        4. future.set_result(result)
        5. Delete _inflight[key]
        6. Return result

    Requests 2–100 (followers):
        1. key IS in _inflight
        2. await asyncio.wait_for(asyncio.shield(future), timeout=2.0s)
        3. Return shared result
        4. On timeout: return None (caller retries independently)
    """
```

**Key design decisions**:
- `asyncio.shield()` prevents follower cancellation from cancelling the leader
- `SINGLEFLIGHT_WAIT_TIMEOUT = 2.0s` prevents indefinite blocking
- Cleanup in `finally` block ensures _inflight dict never leaks

### 4.6 Cache Layer Hit/Miss Flow

```
Request arrives with query Q, doc_version V

1. CHECK L3 (RAG cache):
   key = "cache:rag:{md5(Q)}:{V}:{ev}"
   HIT  → return cached result (latency ≈ 1ms)
   MISS → continue

2. CHECK L1 (Query cache):
   key = "cache:query:{md5(Q)}:{V}:{ev}"
   HIT  → use cached rewritten_query (skip LLM rewrite)
   MISS → call rewrite_query(Q), store to L1

3. CHECK L2 (Embedding cache):
   key = "cache:embed:{md5(rewritten)}:{ev}"
   HIT  → use cached vector (skip embedding API)
   MISS → call embed_client.embed_one(rewritten), store to L2

4. Execute retrieval + rerank + generation

5. STORE L3:
   key = "cache:rag:{md5(Q)}:{V}:{ev}"
   value = PipelineResult (excluding context if > 5000 chars)
   TTL = 3600 + jitter
```

---

## 5. Degrade Strategy

### 5.1 LLM Timeout Degradation (Cascading)

```
┌──────────────────────────────────────────────────────────────────┐
│                  LLM Timeout Degradation                         │
│                                                                  │
│  Level  │ Timeout │ max_tokens │ Context   │ Behavior            │
│ ────────┼─────────┼────────────┼───────────┼─────────────────── │
│  C2     │ 3.0s    │ 1024       │ Full      │ Complete generation │
│  C1     │ 1.5s    │ 300        │ First 800 │ Summary (≤100 chars)│
│  C0     │ —       │ —          │ First 400 │ Raw snippet, no LLM │
└──────────────────────────────────────────────────────────────────┘
```

### 5.2 Executable Degrade Flow

```python
async def generate_answer(query, context, intent="C2"):
    if not context:
        return ("根据现有文档，未找到相关信息。...", "C0", "NO_CONTEXT")

    # ── Attempt C2: Full generation ──
    messages_c2 = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": f"【参考资料】\n{context}\n\n【问题】\n{query}"},
    ]
    try:
        answer = await asyncio.wait_for(
            llm_client.chat(messages_c2, temperature=0.3, max_tokens=1024),
            timeout=settings.LLM_TIMEOUT_C2,   # 3.0s
        )
        return (answer, "C2", "")
    except asyncio.TimeoutError:
        logger.warning("C2 timeout, degrading to C1")

    # ── Attempt C1: Summary mode ──
    messages_c1 = [
        {"role": "system", "content": "请基于资料简洁回答（100字以内），并注明来源。"},
        {"role": "user",   "content": f"资料：{context[:800]}\n问题：{query}"},
    ]
    try:
        answer = await asyncio.wait_for(
            llm_client.chat(messages_c1, temperature=0, max_tokens=300),
            timeout=settings.LLM_TIMEOUT_C1,   # 1.5s
        )
        return (answer, "C1", "C2_TIMEOUT")
    except asyncio.TimeoutError:
        logger.warning("C1 timeout, degrading to C0")

    # ── Fallback C0: Raw snippet ──
    snippet = context[:400]
    return (f"根据文档片段（响应超时，仅返回摘要）：\n\n{snippet}…", "C0", "LLM_TIMEOUT")
```

### 5.3 Component-Level Degradation

| Component       | Failure Mode              | Degradation Behavior                          |
|-----------------|---------------------------|----------------------------------------------|
| Milvus          | Connection failure        | Fall back to BM25-only retrieval             |
| Redis           | Connection failure        | Skip all cache ops, every request is fresh   |
| Embedding API   | Timeout / error           | Return error result, reason="EMBED_FAIL"     |
| LLM (generate)  | Timeout                   | C2 → C1 → C0 cascade (see §5.2)             |
| LLM (rewrite)   | Timeout / error           | Use original query (no rewrite)              |
| LLM (self-score) | Timeout / error          | Default score = 0.5                          |
| LLM (reranker)  | Timeout / error           | Fall back to SimpleReranker                  |
| PostgreSQL      | Write failure             | Log warning, continue (query still returned) |
| SingleFlight    | Wait timeout (2.0s)       | Execute independently (no dedup)             |

### 5.4 degrade_reason Enum

| Value              | Meaning                                    |
|--------------------|--------------------------------------------|
| `""`               | No degradation, C2 full generation          |
| `"NO_CONTEXT"`     | No retrieved documents, returned canned msg |
| `"C2_TIMEOUT"`     | C2 timed out, fell back to C1 summary      |
| `"LLM_TIMEOUT"`    | Both C2 and C1 timed out, returned snippet  |
| `"EMBED_FAIL"`     | Embedding service unavailable               |
| `"SYSTEM_ERROR"`   | Unhandled pipeline exception                |
| `"PERMISSION_DENIED"` | User failed permission check             |

---

## 6. Retrieval + Rerank Flow

### 6.1 Hybrid Retrieval Architecture

```
Query: "什么是微服务架构"
                │
    ┌───────────┴───────────┐
    ▼                       ▼
┌─────────────┐     ┌─────────────┐
│ Dense Path  │     │ Sparse Path │
│ (Milvus)    │     │ (BM25)      │
│             │     │             │
│ embed(query)│     │ char-level  │
│ → HNSW      │     │ tokenize    │
│ COSINE sim  │     │ BM25Okapi   │
│ top_k=10    │     │ top_k=10    │
└──────┬──────┘     └──────┬──────┘
       │                   │
       │ [{id, text,       │ [{id, text,
       │   score, "dense"}]│   score, "sparse"}]
       │                   │
       └────────┬──────────┘
                ▼
        ┌───────────────┐
        │  RRF Merge    │
        │ alpha=0.7     │
        │ k=60          │
        └───────┬───────┘
                │
                ▼ [{...rrf_score}]  (top_k × 2 = 20)
        ┌───────────────┐
        │ SimpleReranker │
        │ top_n=5        │
        └───────┬───────┘
                │
                ▼ [{...rerank_score}]  (5 docs)
        ┌───────────────┐
        │ build_context  │
        │ max_chars=3000 │
        └───────┬───────┘
                │
                ▼ context string → LLM
```

### 6.2 RRF Merge Algorithm

```python
def _rrf_merge(dense, sparse, alpha=0.7, k=60):
    """
    Reciprocal Rank Fusion with weighted alpha.

    Input:
        dense  = [d1, d2, d3, ...] sorted by Milvus COSINE score desc
        sparse = [s1, s2, s3, ...] sorted by BM25 score desc
        alpha  = 0.7 (dense weight)
        k      = 60  (RRF smoothing constant)

    For each document d:
        dedup_key = text[:100]

        if d in dense at rank r_d:
            score += alpha × 1/(k + r_d + 1)

        if d in sparse at rank r_s:
            score += (1 - alpha) × 1/(k + r_s + 1)

    Output: sorted by combined RRF score descending
    """

    scores = {}  # dedup_key → float
    texts  = {}  # dedup_key → full text
    meta   = {}  # dedup_key → original dict (prefers dense metadata)

    for rank, item in enumerate(dense):
        key = item["text"][:100]
        scores[key] = scores.get(key, 0) + alpha * (1 / (k + rank + 1))
        texts[key] = item["text"]
        meta[key] = item

    for rank, item in enumerate(sparse):
        key = item["text"][:100]
        scores[key] = scores.get(key, 0) + (1 - alpha) * (1 / (k + rank + 1))
        texts[key] = item["text"]
        if key not in meta:
            meta[key] = item

    # Sort and return
    ranked = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    return [
        {**meta[key], "rrf_score": round(scores[key], 6), "text": texts[key]}
        for key in ranked
    ]
```

### 6.3 Rerank Score Calculation

```python
# SimpleReranker (default, no API call)
def rerank(query, docs, top_n=5):
    keywords = set(query)  # Character-level keywords
    for doc in docs:
        text = doc.get("text", "")
        coverage = sum(1 for kw in keywords if kw in text) / max(len(keywords), 1)
        rrf = doc.get("rrf_score", 0)
        doc["rerank_score"] = round(rrf * 0.7 + coverage * 0.3, 6)
    return sorted(docs, key=lambda d: d["rerank_score"], reverse=True)[:top_n]
```

### 6.4 Confidence Score Calculation

```python
def calc_confidence(top_docs, embedding_sim, llm_score):
    """
    confidence = 0.5 × rerank_norm + 0.3 × emb_norm + 0.2 × llm_score

    Normalization:
        rerank_scores = [d["rerank_score"] for d in top_docs]
        max_score = max(rerank_scores)
        rerank_avg = mean(rerank_scores)

        if max_score > 1.0:  # LLMReranker (0–10)
            rerank_norm = clamp(rerank_avg / 10.0, 0, 1)
        else:               # SimpleReranker (≈0.01)
            rerank_norm = clamp(rerank_avg × 20.0, 0, 1)

        emb_norm = clamp(embedding_sim, 0, 1)

    Returns: round(confidence, 3), clamped to [0, 1]
    """
```

---

## 7. Redis Key Design

### 7.1 Complete Key Catalog

| Key Pattern | Layer | TTL | Value Type | Purpose |
|---|---|---|---|---|
| `cache:query:{md5}:{docVer}:{embedVer}` | L1 | 1800s + jitter | JSON `{"rewritten": str}` | Rewritten query cache |
| `cache:embed:{md5}:{embedVer}` | L2 | 86400s + jitter | JSON `float[]` (1024 dims) | Embedding vector cache |
| `cache:rag:{md5}:{docVer}:{embedVer}` | L3 | 3600s + jitter | JSON PipelineResult | Full pipeline result cache |
| `global:doc_version` | — | None | Integer (string) | Global document version counter |
| `ratelimit:{userId}:{minuteTs}` | — | 60s | Integer (string) | Per-user request count |

### 7.2 Key Component Details

| Component | Format | Example |
|---|---|---|
| `{md5}` | `hashlib.md5(text.encode()).hexdigest()` | `a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6` |
| `{docVer}` | Integer from `global:doc_version` | `42` |
| `{embedVer}` | Hardcoded string, bumped on model change | `v1` |
| `{userId}` | User ID from JWT `sub` claim | `usr_abc123` |
| `{minuteTs}` | `int(time.time() // 60)` | `28757012` |

### 7.3 Key Examples

```
# Layer-1 Query cache
cache:query:e99a18c428cb38d5f260853678922e03:42:v1

# Layer-2 Embedding cache
cache:embed:7d793037a0760186574b0282f2f435e7:v1

# Layer-3 RAG pipeline cache
cache:rag:e99a18c428cb38d5f260853678922e03:42:v1

# Global doc version
global:doc_version  →  "42"

# Rate limit counter
ratelimit:usr_abc123:28757012  →  "15"
```

### 7.4 Jitter Formula

```python
jitter = random.randint(0, max(ttl // 10, 1))
effective_ttl = ttl + jitter
```

| Layer | Base TTL | Max Jitter | Effective Range |
|---|---|---|---|
| L1 Query | 1800s | 180s | 1800–1980s |
| L2 Embed | 86400s | 8640s | 86400–95040s |
| L3 RAG   | 3600s  | 360s  | 3600–3960s  |

---

## 8. PostgreSQL DB Schema

### 8.1 Entity-Relationship Diagram

```
users
  │
  │ 1:N
  ▼
query_logs ─── 1:1 ──→ evaluations
  │
  │ 1:N
  ▼
feedback

documents
  │
  │ 1:N (CASCADE DELETE)
  ▼
chunks

audit_logs (standalone, references user_id)
```

### 8.2 Table Definitions

#### users

```sql
CREATE TABLE users (
    id         VARCHAR(64)  PRIMARY KEY,          -- UUID string
    username   VARCHAR(128) NOT NULL UNIQUE,
    password   VARCHAR(256) NOT NULL,             -- bcrypt hash
    role       VARCHAR(32)  DEFAULT 'user',       -- 'user' | 'admin' | 'super_admin'
    tenant_id  VARCHAR(64)  DEFAULT 'default',
    dept_id    VARCHAR(64),
    is_active  BOOLEAN      DEFAULT TRUE,
    created_at TIMESTAMP    DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_user_username ON users(username);
```

#### documents

```sql
CREATE TABLE documents (
    id          VARCHAR(64)  PRIMARY KEY,          -- UUID string
    filename    VARCHAR(512) NOT NULL,
    file_path   VARCHAR(512),                      -- MinIO object key
    file_type   VARCHAR(16),                       -- 'pdf' | 'docx' | 'html' | 'txt' | 'md'
    file_size   BIGINT       DEFAULT 0,
    status      VARCHAR(20)  DEFAULT 'pending',    -- 'pending' | 'processing' | 'done' | 'failed'
    parse_score FLOAT        DEFAULT 0.0,          -- Quality score 0.0–1.0
    chunk_count INTEGER      DEFAULT 0,
    doc_version INTEGER      DEFAULT 1,
    tenant_id   VARCHAR(64)  DEFAULT 'default',
    dept_id     VARCHAR(64),
    error_msg   TEXT,
    created_at  TIMESTAMP    DEFAULT NOW(),
    updated_at  TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX idx_docs_status  ON documents(status);
CREATE INDEX idx_docs_created ON documents(created_at DESC);
CREATE INDEX idx_docs_tenant  ON documents(tenant_id);
```

#### chunks

```sql
CREATE TABLE chunks (
    id         VARCHAR(64)  PRIMARY KEY,           -- UUID string
    doc_id     VARCHAR(64)  REFERENCES documents(id) ON DELETE CASCADE,
    content    TEXT         NOT NULL,
    chunk_idx  INTEGER      NOT NULL,
    char_count INTEGER      DEFAULT 0,
    meta_info  JSONB        DEFAULT '{}',
    created_at TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX idx_chunks_doc_id ON chunks(doc_id);
```

#### query_logs

```sql
CREATE TABLE query_logs (
    id              SERIAL       PRIMARY KEY,
    trace_id        VARCHAR(32),
    session_id      VARCHAR(64),
    user_id         VARCHAR(64),
    tenant_id       VARCHAR(64)  DEFAULT 'default',
    original_query  TEXT         NOT NULL,
    rewritten_query TEXT,
    intent          VARCHAR(4),                     -- 'C0' | 'C1' | 'C2'
    answer          TEXT,
    context         TEXT,
    sources         JSONB,
    confidence      FLOAT        DEFAULT 0.0,
    latency_ms      INTEGER,
    retrieval_ms    INTEGER,
    llm_ms          INTEGER,
    cache_hit       BOOLEAN      DEFAULT FALSE,
    token_count     INTEGER      DEFAULT 0,
    degrade_level   VARCHAR(4),                     -- 'C0' | 'C1' | 'C2'
    degrade_reason  VARCHAR(64),
    created_at      TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX idx_qlog_created ON query_logs(created_at DESC);
CREATE INDEX idx_qlog_trace   ON query_logs(trace_id);
CREATE INDEX idx_qlog_tenant  ON query_logs(tenant_id);
CREATE INDEX idx_qlog_cache   ON query_logs(cache_hit);
```

#### evaluations

```sql
CREATE TABLE evaluations (
    id           SERIAL   PRIMARY KEY,
    log_id       INTEGER  REFERENCES query_logs(id) ON DELETE SET NULL,
    query        TEXT     NOT NULL,
    answer       TEXT,
    relevance    FLOAT    DEFAULT 0.0,              -- 0.0–5.0
    faithfulness FLOAT    DEFAULT 0.0,              -- 0.0–5.0
    completeness FLOAT    DEFAULT 0.0,              -- 0.0–5.0
    overall      FLOAT    DEFAULT 0.0,              -- avg or explicit
    reason       TEXT,
    created_at   TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_eval_created ON evaluations(created_at DESC);
```

#### feedback

```sql
CREATE TABLE feedback (
    id         SERIAL      PRIMARY KEY,
    log_id     INTEGER     REFERENCES query_logs(id) ON DELETE SET NULL,
    trace_id   VARCHAR(32),
    session_id VARCHAR(64),
    user_id    VARCHAR(64),
    query      TEXT        NOT NULL,
    answer     TEXT,
    feedback   VARCHAR(10) NOT NULL,                -- 'like' | 'dislike'
    comment    TEXT,
    created_at TIMESTAMP   DEFAULT NOW()
);
CREATE INDEX idx_fb_type ON feedback(feedback);
```

#### audit_logs

```sql
CREATE TABLE audit_logs (
    id         SERIAL       PRIMARY KEY,
    trace_id   VARCHAR(32),
    user_id    VARCHAR(64),
    username   VARCHAR(128),
    action     VARCHAR(64)  NOT NULL,               -- 'login' | 'upload' | 'delete' | 'query'
    resource   VARCHAR(256),
    detail     JSONB,
    ip         VARCHAR(64),
    created_at TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX idx_audit_created ON audit_logs(created_at DESC);
CREATE INDEX idx_audit_user    ON audit_logs(user_id);
```

### 8.3 Connection Pool Configuration

```python
# PostgreSQL (asyncpg)
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,        # Steady-state connections
    max_overflow=20,     # Burst connections (total max = 30)
)
```

### 8.4 Milvus Collection Schema

```python
# Collection: "rag_docs"
fields = [
    FieldSchema("id",        DataType.VARCHAR,      is_primary=True, max_length=64),
    FieldSchema("doc_id",    DataType.VARCHAR,      max_length=64),
    FieldSchema("chunk_idx", DataType.INT64),
    FieldSchema("text",      DataType.VARCHAR,      max_length=8192),
    FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=1024),
]

# Index
index_params = {
    "metric_type": "COSINE",
    "index_type":  "HNSW",
    "params":      {"M": 16, "efConstruction": 256},
}

# Search params
search_params = {
    "metric_type": "COSINE",
    "params":      {"ef": 128},
}
```

---

## 9. Tracing Propagation Design

### 9.1 Trace ID Format

```python
trace_id = uuid.uuid4().hex[:16]  # 16-char hex string
# Example: "a1b2c3d4e5f6a7b8"
```

### 9.2 ContextVar Propagation

```python
# app/utils/trace.py
from contextvars import ContextVar

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")

def generate_trace_id() -> str:
    return uuid.uuid4().hex[:16]

def get_trace_id() -> str:
    return _trace_id_var.get()

def set_trace_id(trace_id: str) -> None:
    _trace_id_var.set(trace_id)
```

### 9.3 Propagation Path

```
┌─ HTTP Request ────────────────────────────────────────────────────────┐
│ Client sends:  X-Trace-Id: <external_id>  (optional)                 │
│                                                                       │
│ trace_middleware (FastAPI):                                           │
│   trace_id = request.headers["X-Trace-Id"] OR generate_trace_id()    │
│   set_trace_id(trace_id)       ← ContextVar, async-safe              │
│   request.state.trace_id = trace_id                                  │
│                                                                       │
│ ┌─ Route Handler ───────────────────────────────────────────┐        │
│ │ trace_id = get_trace_id()   ← reads from ContextVar       │        │
│ │                                                            │        │
│ │ ┌─ Service Layer ────────────────────────────────┐        │        │
│ │ │ trace_id = get_trace_id()                       │        │        │
│ │ │                                                  │        │        │
│ │ │ ┌─ Core Pipeline ───────────────────────┐       │        │        │
│ │ │ │ trace_id = get_trace_id()              │       │        │        │
│ │ │ │ logger.info(f"[{trace_id}] ...")       │       │        │        │
│ │ │ └───────────────────────────────────────┘       │        │        │
│ │ └──────────────────────────────────────────────────┘        │        │
│ └─────────────────────────────────────────────────────────────┘        │
│                                                                       │
│ Response header: X-Trace-Id: <same_trace_id>                         │
│ Response body:   {"trace_id": "<same_trace_id>", ...}                │
└───────────────────────────────────────────────────────────────────────┘
```

### 9.4 Trace ID Injection Points

| Layer | Injection | Example |
|---|---|---|
| HTTP Response Header | `X-Trace-Id` | `a1b2c3d4e5f6a7b8` |
| API Response Body | `trace_id` field | `{"code": 0, ..., "trace_id": "a1b2c3d4e5f6a7b8"}` |
| All log lines | `[{trace_id}]` prefix | `[a1b2c3d4e5f6a7b8] RAG complete intent=C1 latency=420ms` |
| QueryLog record | `trace_id` column | Indexed for fast lookup |
| AuditLog record | `trace_id` column | Links audit to request |
| Feedback record  | `trace_id` column | Links feedback to query |
| SSE Stream Header | `X-Trace-Id` | For streaming responses |

### 9.5 Log Format

```python
# Loguru configuration
logger.add(
    f"logs/app_{{time:YYYY-MM-DD}}.log",
    rotation="00:00",
    retention="30 days",
    compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
)

# Usage pattern — trace_id always included:
logger.info(f"[{trace_id}] RAG完成 intent={intent} latency={latency}ms "
            f"ret={retrieval_ms}ms llm={llm_ms}ms conf={confidence} degrade={degrade_level}")
```

---

## 10. Async Concurrency Model

### 10.1 Runtime Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  uvicorn (ASGI server)                   │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │            asyncio Event Loop (single thread)     │   │
│  │                                                    │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  │   │
│  │  │  Request 1  │  │  Request 2  │  │  Request N  │  │   │
│  │  │  coroutine  │  │  coroutine  │  │  coroutine  │  │   │
│  │  └──────┬─────┘  └──────┬─────┘  └──────┬─────┘  │   │
│  │         │               │               │          │   │
│  │    await I/O        await I/O       await I/O      │   │
│  │   (httpx, pg,     (httpx, pg,     (httpx, pg,      │   │
│  │    redis)          redis)          redis)           │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │          Background Task Queue (FastAPI)           │   │
│  │  _async_evaluate() runs after response is sent     │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 10.2 Async vs Sync Boundaries

| Component | Async/Sync | Reason |
|---|---|---|
| FastAPI routes | `async def` | All handlers are coroutines |
| SQLAlchemy (asyncpg) | `async` | `AsyncSession`, `create_async_engine` |
| Redis (redis.asyncio) | `async` | `aioredis.from_url()` |
| httpx (LLM/Embed) | `async` | `httpx.AsyncClient` per-request |
| Milvus (pymilvus) | **sync** | No async driver; runs in event loop thread |
| BM25 (rank_bm25) | **sync** | CPU-bound, runs under `threading.Lock` |
| MinIO (minio) | **sync** | No async driver; used in background tasks |
| File I/O (parsing) | **sync** | pymupdf, python-docx are sync |

### 10.3 Concurrency Patterns

#### Pattern 1: SingleFlight Request Deduplication

```python
# Prevents N identical queries from each running the full pipeline.
# Only 1 coroutine executes; others await the shared Future.

_inflight: Dict[str, asyncio.Future] = {}

async def single_flight(key, coro_factory):
    if key in _inflight:
        return await asyncio.wait_for(
            asyncio.shield(_inflight[key]), timeout=2.0
        )
    fut = asyncio.get_running_loop().create_future()
    _inflight[key] = fut
    try:
        result = await coro_factory()
        fut.set_result(result)
        return result
    finally:
        _inflight.pop(key, None)
```

#### Pattern 2: Background Task Evaluation

```python
# After returning response to client, run LLM evaluation in background.
# Uses FastAPI's BackgroundTasks (runs in same event loop after response).

@router.post("/")
async def chat(req, background_tasks: BackgroundTasks, ...):
    result = await rag_service.query(...)
    # ... write to DB ...

    if not result["cache_hit"] and result["answer"] and log_id:
        background_tasks.add_task(
            _async_evaluate, question, answer, context, log_id
        )
    return ok(result)

async def _async_evaluate(query, answer, context, log_id):
    async with AsyncSessionLocal() as db:
        await eval_service.evaluate(query=query, answer=answer,
                                     context=context, log_id=log_id, db=db)
```

#### Pattern 3: Timeout-Bounded LLM Calls

```python
# Every LLM call is wrapped in asyncio.wait_for with hard timeout.
# Prevents single slow request from blocking the event loop.

answer = await asyncio.wait_for(
    llm_client.chat(messages, temperature=0.3, max_tokens=1024),
    timeout=settings.LLM_TIMEOUT_C2,  # 3.0 seconds
)
```

#### Pattern 4: Thread-Safe BM25 with Lock

```python
# BM25 corpus updates use threading.Lock since BM25Okapi is not thread-safe.
# Search also acquires lock but takes a snapshot for processing outside lock.

class HybridRetriever:
    _lock = threading.Lock()

    def add_texts(self, texts):
        with self._lock:
            self._corpus.extend(texts)
            self._bm25 = BM25Okapi([list(t) for t in self._corpus])

    def _sparse_search(self, query, top_k):
        with self._lock:
            if not self._bm25:
                return []
            scores = self._bm25.get_scores(list(query))
            corpus = list(self._corpus)  # Snapshot
        # Process outside lock
        return sorted_results(scores, corpus, top_k)
```

### 10.4 Timeout Budget Per Request

```
Total request budget: ~10s (before HTTP gateway timeout)

Component          │ Timeout    │ Fallback
───────────────────┼────────────┼──────────────────
Query Rewrite      │ 3.0s       │ Use original query
Embedding          │ 60s*       │ Error response
Milvus Search      │ ~2s**      │ BM25-only
BM25 Search        │ ~50ms      │ Empty results
LLM Generate (C2)  │ 3.0s       │ Degrade to C1
LLM Generate (C1)  │ 1.5s       │ Degrade to C0
LLM Self-Score     │ 2.5s       │ Default 0.5
SingleFlight Wait  │ 2.0s       │ Execute independently

*  Embedding uses httpx 60s default; typically <1s
** Milvus has no explicit timeout; connection timeout is 10s
```

---

## 11. Document Processing Pipeline

### 11.1 Processing Flow

```
Upload Request (multipart/form-data)
  │
  ▼
┌─────────────────────────────────────────┐
│ API Layer (api/upload.py)               │
│ 1. Validate extension (pdf/docx/html/  │
│    txt/md), size ≤ 50MB                 │
│ 2. Compute MD5 hash (dedup check)       │
│ 3. Upload to MinIO (object_store)       │
│ 4. Create Document record (status=      │
│    "pending")                           │
│ 5. AuditLog record                      │
│ 6. BackgroundTask: _process_document()  │
│ 7. Return {doc_id, filename, status:    │
│    "processing"}                        │
└─────────────────┬───────────────────────┘
                  │ (background)
                  ▼
┌─────────────────────────────────────────┐
│ Document Service (service/doc_service)  │
│                                         │
│ Step 1: Set status = "processing"       │
│                                         │
│ Step 2: Parse (DocParser)               │
│   .pdf  → pymupdf (fitz)               │
│   .docx → python-docx                  │
│   .html → html.parser (std lib)        │
│   .txt/.md → open().read()             │
│                                         │
│ Step 3: Clean (TextCleaner)             │
│   Remove control chars, normalize       │
│   whitespace, keep CJK + ASCII          │
│                                         │
│ Step 4: Split (TextSplitter)            │
│   chunk_size=500, overlap=50            │
│   Sentence-boundary-aware splitting     │
│                                         │
│ Step 5: Quality Check (QualityChecker)  │
│   score = 0.7 × valid_ratio            │
│         + 0.3 × min(avg_len/100, 1.0)  │
│   REJECT if score < QUALITY_THRESHOLD   │
│   (default 0.6)                         │
│                                         │
│ Step 6: Batch Embed                     │
│   embed_client.embed_batch(chunks,      │
│   batch_size=32)                        │
│                                         │
│ Step 7: Milvus Insert                   │
│   milvus_db.insert(ids, doc_ids,        │
│   chunk_idxs, texts, embeddings)        │
│                                         │
│ Step 8: BM25 Index Update               │
│   retriever.add_texts(chunks)           │
│                                         │
│ Step 9: PostgreSQL Chunk Records        │
│   Bulk insert Chunk rows                │
│                                         │
│ Step 10: Update Document                │
│   status="done", parse_score,           │
│   chunk_count                           │
│                                         │
│ ON ERROR:                               │
│   rollback, status="failed",            │
│   error_msg=str(e)[:500]               │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│ Cache Invalidation                      │
│ cache.increment_doc_version()           │
│ → all L1/L3 caches auto-invalidate     │
└─────────────────────────────────────────┘
```

---

## 12. API Layer Contract

### 12.1 Authentication Flow

```python
# JWT Token Creation
def create_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=24),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

# JWT Token Verification
def verify_token(token: str) -> Optional[dict]:
    # Fallback mode: "simple:{user_id}:{role}" for dev
    if token.startswith("simple:"):
        parts = token.split(":")
        return {"sub": parts[1], "role": parts[2]}
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])

# FastAPI Dependency Chain
@router.post("/chat/")
async def chat(
    user = Depends(get_current_user),   # JWT validation
    _rl  = Depends(check_rate_limit),   # Redis rate limit
): ...
```

### 12.2 Rate Limiting

```python
async def check_rate_limit(request, user):
    user_id = user["sub"]
    minute_key = f"ratelimit:{user_id}:{int(time.time() // 60)}"

    count = await cache.client.incr(minute_key)
    if count == 1:
        await cache.client.expire(minute_key, 60)

    if count > settings.RATE_LIMIT_PER_MINUTE:  # default: 60
        raise HTTPException(429, detail={
            "code": ErrorCode.RATE_LIMITED,
            "message": f"Rate limited: max {RATE_LIMIT_PER_MINUTE}/min"
        })
```

### 12.3 Endpoint Specifications

#### POST /chat/

```
Request:
    Header: Authorization: Bearer <jwt>
    Body:   {"question": str (1–2000 chars), "session_id": str? }

Response (200):
    {
        "code": 0,
        "message": "ok",
        "data": {
            "answer":          str,
            "rewritten_query": str,
            "intent":          "C0" | "C1" | "C2",
            "sources":         [{"text": str, "score": float, "doc_id": str, "chunk_idx": int}],
            "confidence":      float (0–1),
            "latency_ms":      int,
            "cache_hit":       bool,
            "degrade_level":   "C0" | "C1" | "C2",
            "degrade_reason":  str,
            "log_id":          int
        },
        "trace_id": str
    }

Side Effects:
    - QueryLog record inserted
    - AuditLog record inserted
    - Background: eval_service.evaluate() (if not cached)
```

#### GET /chat/stream

```
Request:
    Query: question=str, token=<jwt> (SSE requires query param auth)

Response: text/event-stream
    data: <token>\n\n
    data: <token>\n\n
    ...
    data: [DONE]\n\n

Headers:
    Cache-Control: no-cache
    X-Accel-Buffering: no
    X-Trace-Id: <trace_id>
```

---

## 13. Configuration Reference

### 13.1 Complete Settings

```python
class Settings(BaseSettings):
    # ── LLM / Embedding ──
    SILICONFLOW_API_KEY: str          # Required
    SILICONFLOW_BASE_URL: str = "https://api.siliconflow.cn/v1"
    LLM_MODEL: str = "Qwen/Qwen2.5-7B-Instruct"
    EMBED_MODEL: str = "BAAI/bge-m3"
    EMBED_DIM: int = 1024

    # ── PostgreSQL ──
    DATABASE_URL: str = "postgresql+asyncpg://raguser:ragpass123@postgres:5432/ragdb"

    # ── Redis ──
    REDIS_URL: str = "redis://redis:6379/0"

    # ── Milvus ──
    MILVUS_HOST: str = "milvus"
    MILVUS_PORT: int = 19530
    MILVUS_COLLECTION: str = "rag_docs"

    # ── MinIO ──
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin123"
    MINIO_BUCKET: str = "documents"
    MINIO_SECURE: bool = False

    # ── RAG Parameters ──
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    TOP_K: int = 10
    RERANK_TOP_N: int = 5
    QUALITY_THRESHOLD: float = 0.6
    HYBRID_RETRIEVAL_ALPHA: float = 0.7   # Dense weight in RRF

    # ── Timeouts (seconds) ──
    LLM_TIMEOUT_C2: float = 3.0
    LLM_TIMEOUT_C1: float = 1.5
    LLM_SELF_SCORE_TIMEOUT: float = 2.0
    QUERY_REWRITE_TIMEOUT: float = 3.0
    SINGLEFLIGHT_WAIT_TIMEOUT: float = 2.0

    # ── Content Limits ──
    CONTEXT_MAX_CHARS: int = 3000
    MAX_QUERY_LENGTH: int = 2000

    # ── Cache TTL (seconds) ──
    CACHE_TTL_QUERY: int = 1800       # 30 minutes
    CACHE_TTL_EMBED: int = 86400      # 24 hours
    CACHE_TTL_RAG: int = 3600         # 1 hour

    # ── Auth & Security ──
    JWT_SECRET: str = "rag-system-jwt-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24
    RATE_LIMIT_PER_MINUTE: int = 60

    # ── Application ──
    LOG_LEVEL: str = "INFO"
    APP_ENV: str = "production"       # "production" | "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
```

---

## 14. Error Code Registry

| Code | Constant | HTTP Status | Description |
|---|---|---|---|
| 0 | `OK` | 200 | Success |
| 1001 | `PARAM_ERROR` | 400 | Invalid parameter (empty query, too long, bad format) |
| 1002 | `UNAUTHENTICATED` | 401 | Missing or invalid JWT token |
| 1003 | `FORBIDDEN` | 403 | Insufficient role (admin required) |
| 1004 | `RATE_LIMITED` | 429 | Exceeded per-minute request limit |
| 1005 | `NOT_FOUND` | 404 | Resource not found |
| 1006 | `DUPLICATE` | 409 | Duplicate resource (e.g., same file hash) |
| 2001 | `CACHE_MISS` | — | Internal: cache miss (not returned to client) |
| 3001 | `RETRIEVE_FAIL` | 500 | Retrieval subsystem failure |
| 4001 | `LLM_TIMEOUT` | 200* | LLM timed out (degraded response still returned) |
| 4002 | `LLM_FAIL` | 500 | LLM API failure |
| 5000 | `SYSTEM_ERROR` | 500 | Unhandled server error |

\* LLM timeout returns `code: 0` with degraded answer; `degrade_reason` field indicates the timeout.

---

## Appendix A: Known Limitations and Recommendations

### A.1 BM25 Corpus Persistence

The in-memory BM25 corpus in `HybridRetriever` is **not persisted**. On service restart, the BM25 index is empty until new documents are uploaded. To mitigate:

- **Current behavior**: Dense (Milvus) retrieval still works; BM25 gracefully returns empty results.
- **Recommended improvement**: On startup, query all `chunks` from PostgreSQL and call `retriever.add_texts(all_chunk_texts)` to rebuild the BM25 index.

### A.2 Sync Operations in Async Context

Two components run synchronous I/O in the asyncio event loop thread:

| Component | Issue | Recommended Fix |
|---|---|---|
| Milvus (`pymilvus`) | `search()` and `insert()` are blocking | Wrap with `asyncio.to_thread(milvus_db.search, query_vec, top_k)` |
| BM25 (`rank_bm25`) | CPU-bound scoring under `threading.Lock` | Wrap with `await asyncio.get_event_loop().run_in_executor(None, self._sparse_search, query, top_k)` |

These are acceptable at moderate concurrency but should be offloaded for high-throughput deployments.

---

## Appendix C: Startup Sequence

```python
# app/main.py lifespan
async def lifespan(app):
    # 1. PostgreSQL: create tables + ensure admin user
    await init_db()

    # 2. Redis: connect with retry
    await cache.connect()

    # 3. Milvus: connect + ensure collection + load index
    milvus_db.connect()

    yield

    # Shutdown: dispose engine
    await engine.dispose()
```

## Appendix D: Infrastructure Services

| Service | Image | Ports | Purpose |
|---|---|---|---|
| etcd | quay.io/coreos/etcd | 2379 | Milvus metadata store |
| minio | minio/minio | 9000, 9001 | Object storage |
| milvus | milvusdb/milvus | 19530 | Vector database |
| redis | redis:7-alpine | 6379 | Cache + rate limiting |
| postgres | postgres:16-alpine | 5432 | Relational database |
| backend | custom Dockerfile | 8000 | FastAPI application |
| frontend | custom Dockerfile | 3000 | Vue 3 SPA (Nginx) |
