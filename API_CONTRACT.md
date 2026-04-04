# RAG System — API 契约文档

## 统一返回结构
```json
{ "code": 0, "message": "ok", "data": {}, "trace_id": "uuid" }
```

## 错误码
| code | 含义 |
|------|------|
| 0 | 成功 |
| 1001 | 参数错误 |
| 1002 | 未认证 |
| 1003 | 无权限 |
| 4001 | LLM超时 |
| 4002 | LLM失败 |
| 5000 | 系统异常 |

## 认证
所有接口（除 /health /auth/login）需 Header: `Authorization: Bearer <token>`

## 接口列表

### Auth
POST /auth/login  → { token, user }
POST /auth/logout

### Chat
POST /chat/       → { answer, sources, confidence, degrade_level, reason, latency_ms, cache_hit, rewritten_query, intent, trace_id }
GET  /chat/stream?question=&session_id=   (SSE)

### Upload
POST   /upload/                → { doc_id, filename, status }
GET    /upload/docs            → [{ id, filename, status, parse_score, chunk_count, ... }]
GET    /upload/docs/{id}
DELETE /upload/docs/{id}

### Feedback
POST /feedback/        → { id }
GET  /feedback/stats   → { like, dislike, satisfaction, top_bad_queries, recent }

### Metrics
GET /metrics/overview  → { doc_count, query_count, avg_score, avg_latency_ms, cache_hit_rate, vector_count }
GET /metrics/rag?days= → { daily[], total_queries, avg_latency_ms, cache_hit_rate, avg_score }
GET /metrics/cache     → { layer_query, layer_embed, layer_rag, redis_hit_rate }
GET /metrics/docs      → { status_counts, avg_score, score_dist[], recent_docs[] }
GET /metrics/qps       → [{ minute, count }]

### Audit Log
GET /audit/?page=&limit= → { items[], total }

### Health
GET /health  (无需认证)
