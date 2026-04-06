# RAG Knowledge System — Enterprise Architecture

A production-grade Retrieval-Augmented Generation (RAG) system with enterprise-level architecture, hybrid search, 3-layer caching, LLM timeout degradation, and full observability.

## Architecture

```
backend/app/
├── api/          # Entry layer: FastAPI routes, auth, rate limiting, singleflight
│   ├── deps.py   # Cross-cutting: JWT auth, rate limit, unified response, error codes
│   ├── auth.py   # POST /auth/login, /logout, GET /me
│   ├── chat.py   # POST /chat/, GET /chat/stream (SSE)
│   ├── upload.py  # Document management CRUD
│   ├── feedback.py # User feedback
│   ├── metrics.py # Monitoring dashboard
│   └── audit.py  # Audit logs (admin)
├── service/      # Orchestration layer: full RAG pipeline control
│   ├── rag_service.py      # RAG pipeline orchestration + permission check
│   ├── doc_service.py      # Document processing pipeline
│   ├── eval_service.py     # LLM auto-evaluation
│   └── feedback_service.py # User feedback handling
├── core/         # Core domain: embedding, retrieval, reranking, generation
│   ├── embedding.py   # Embedding with Layer-2 cache
│   ├── retriever.py   # Hybrid retrieval (Dense Milvus + BM25 + RRF)
│   ├── reranker.py    # LLM + keyword reranking
│   ├── generator.py   # LLM & Embedding API clients
│   └── pipeline.py    # Full RAG pipeline (intent → rewrite → retrieve → rerank → generate)
├── repository/   # Data access: vector store, cache, database, object storage
│   ├── postgres.py    # SQLAlchemy ORM models & DB access
│   ├── redis_cache.py # 3-layer cache + SingleFlight
│   ├── vector_store.py # Milvus vector DB
│   └── object_store.py # MinIO object storage
├── config/       # Settings management
│   └── settings.py    # Pydantic settings from environment
└── utils/        # Cross-cutting utilities
    ├── logger.py   # Structured logging with trace_id
    ├── trace.py    # trace_id generation & context propagation
    ├── context.py  # Unified RAGContext object
    └── helpers.py  # Common helpers
```

## RAG Pipeline Flow

```
Request
→ Auth + RateLimit + SingleFlight
→ Query Processing (intent classification C0/C1/C2 + rewrite)
→ Permission Check
→ Cache Check (Layer-3 RAG cache)
→ Hybrid Retrieval (vector × 0.7 + BM25 × 0.3)
→ Rerank (Top20 → Top5)
→ Context Builder (token limit)
→ LLM Call (with timeout degradation: C2 → C1 → C0)
→ Post Processing (confidence scoring, self-evaluation)
→ Response (unified format with trace_id)
```

## Core Features

| Feature | Implementation |
|---------|---------------|
| **trace_id** | Generated per request, propagated via `ContextVar`, included in all logs and responses |
| **Unified context** | `RAGContext` dataclass flows through the entire pipeline |
| **Unified response** | `{code, message, data, trace_id}` format for all endpoints |
| **Error codes** | Centralized `ErrorCode` system (1001–5000) |
| **Timeout degradation** | C2 (3s full) → C1 (1.5s summary) → C0 (raw snippet) |
| **Cache** | 3-layer Redis: Query (30min), Embedding (24h), RAG (1h) |
| **Hybrid retrieval** | `score = 0.7 × vector + 0.3 × bm25` (RRF fusion) |
| **Confidence scoring** | `0.5 × rerank + 0.3 × embedding_sim + 0.2 × llm_self_score` |
| **SingleFlight** | In-memory async lock prevents duplicate concurrent queries |
| **Rate limiting** | Redis sliding window (configurable per-minute limit) |
| **Structured logging** | Loguru with trace_id injection in every log line |

## Quick Start with Docker Compose

### Prerequisites

- Docker & Docker Compose
- 4GB+ available memory

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env and set your SILICONFLOW_API_KEY
```

### 2. Start all services

```bash
docker-compose up -d
```

This starts 8 services:
- **etcd** — Distributed config for Milvus
- **minio** — Object storage (console at :9001)
- **milvus** — Vector database
- **redis** — Caching & SingleFlight
- **postgres** — Metadata & audit
- **backend** — FastAPI application
- **frontend** — Vue 3 SPA (Nginx at :3000)

### 3. Access the system

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| API Docs | http://localhost:8000/docs |
| MinIO Console | http://localhost:9001 |

### 4. Default credentials

- **Admin login**: username=`admin`, password=`admin123`

## One-Click Deployment

```bash
chmod +x deploy.sh
./deploy.sh
```

The script handles infrastructure startup, health checks, and application deployment.

## Development Setup

### Run backend locally

```bash
cd backend
pip install -r requirements.txt
# Set environment variables
export DATABASE_URL="sqlite+aiosqlite:///dev.db"
export REDIS_URL="redis://localhost:6379/0"
export MILVUS_HOST="localhost"
export SILICONFLOW_API_KEY="your-key"
export APP_ENV="development"

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Run tests

```bash
# All tests (98 test cases)
DATABASE_URL="sqlite+aiosqlite:///test.db" PYTHONPATH=backend pytest tests/ -v

# Unit tests only
DATABASE_URL="sqlite+aiosqlite:///test.db" PYTHONPATH=backend pytest tests/test_rag_pipeline.py -v

# Integration tests only
DATABASE_URL="sqlite+aiosqlite:///test.db" PYTHONPATH=backend pytest tests/test_integration.py -v
```

### Run frontend locally

```bash
cd frontend
npm install
npm run dev
```

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `SILICONFLOW_API_KEY` | — | LLM/Embedding API key (required) |
| `LLM_MODEL` | Qwen/Qwen2.5-7B-Instruct | LLM model name |
| `EMBED_MODEL` | BAAI/bge-m3 | Embedding model name |
| `DATABASE_URL` | postgresql+asyncpg://... | PostgreSQL connection |
| `REDIS_URL` | redis://redis:6379/0 | Redis connection |
| `HYBRID_RETRIEVAL_ALPHA` | 0.7 | Vector weight in hybrid search |
| `LLM_TIMEOUT_C2` | 3.0 | Full generation timeout (seconds) |
| `LLM_TIMEOUT_C1` | 1.5 | Summary generation timeout |
| `RATE_LIMIT_PER_MINUTE` | 60 | Max requests per user per minute |
| `CACHE_TTL_QUERY` | 1800 | Query cache TTL (30 min) |
| `CACHE_TTL_EMBED` | 86400 | Embedding cache TTL (24h) |
| `CACHE_TTL_RAG` | 3600 | RAG result cache TTL (1h) |

## API Overview

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/auth/login` | Login | No |
| POST | `/auth/logout` | Logout | Yes |
| GET | `/auth/me` | Current user | Yes |
| POST | `/chat/` | RAG query | Yes + Rate limit |
| GET | `/chat/stream` | SSE streaming | Token param |
| POST | `/upload/` | Upload document | Yes |
| GET | `/upload/docs` | List documents | Yes |
| DELETE | `/upload/docs/{id}` | Delete document | Yes |
| POST | `/feedback/` | Submit feedback | Yes |
| GET | `/feedback/stats` | Feedback stats | Yes |
| GET | `/metrics/overview` | System overview | Yes |
| GET | `/metrics/rag` | RAG metrics | Yes |
| GET | `/metrics/cache` | Cache stats | Yes |
| GET | `/audit/` | Audit logs | Admin |
| GET | `/health` | Health check | No |

## Response Format

All endpoints return:

```json
{
  "code": 0,
  "message": "ok",
  "data": { ... },
  "trace_id": "abc123def456gh78"
}
```

Error codes:
- `0` — Success
- `1001` — Parameter error
- `1002` — Unauthenticated
- `1003` — Forbidden
- `1004` — Rate limited
- `3001` — Retrieval failure
- `4001` — LLM timeout
- `5000` — System error

## Technology Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy (async), Pydantic
- **Frontend**: Vue 3, Vite, ECharts
- **Vector DB**: Milvus (HNSW index, COSINE similarity)
- **Cache**: Redis (3-layer, SingleFlight)
- **Database**: PostgreSQL 16
- **Storage**: MinIO
- **LLM**: SiliconFlow API (OpenAI-compatible)
- **Search**: BM25 (rank-bm25) + Dense retrieval (Milvus)
