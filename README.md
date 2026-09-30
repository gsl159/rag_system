# 🧠 RAG System — 企业级知识库问答平台

> 一套完整的企业级 RAG（Retrieval-Augmented Generation，检索增强生成）系统。
> 覆盖 文档解析 → 混合检索 → 重排 → 生成 → 缓存 → 评估 → 反馈 的全链路，支持一键 Docker 部署。
>
> **v2.0 高可用与分布式架构**：Milvus 原生 Sparse/BM25 分布式混合检索、全链路异步化、
> 向量语义缓存、Cross-Encoder 重排、多租户 RLS 隔离、限流与 OIDC 认证、
> OpenTelemetry 链路追踪、Celery 分布式任务队列。

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi&logoColor=white)
![Vue](https://img.shields.io/badge/Vue-3.4-42b883?logo=vue.js&logoColor=white)
![Milvus](https://img.shields.io/badge/Milvus-2.5-00A1EA)
![Celery](https://img.shields.io/badge/Celery-5.4-37814A?logo=celery&logoColor=white)
![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-Jaeger-F5A800?logo=opentelemetry&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)

---

## 📖 目录

- [功能特性](#-功能特性)
- [系统架构](#-系统架构)
- [RAG Pipeline 详解](#-rag-pipeline-详解)
- [项目结构](#-项目结构)
- [快速部署](#-快速部署)
- [环境变量说明](#️-环境变量说明)
- [API 接口文档](#-api-接口文档)
- [数据存储设计](#️-数据存储设计)
- [本地开发](#-本地开发)
- [运行测试](#-运行测试)
- [更换 LLM / Embedding](#-更换-llm--embedding)
- [性能调优](#-性能调优)
- [常见问题 FAQ](#-常见问题-faq)
- [生产化待办](#-生产化待办)
- [验收清单](#-验收清单)

---

## ✨ 功能特性

| 模块 | 能力说明 |
|------|----------|
| **文档处理** | PDF / Word / HTML / TXT / Markdown 解析，自动清洗、滑动窗口分块、质量评分，不合格文档拦截入库 |
| **分布式混合检索** | **Milvus 2.5 原生** Dense（HNSW 余弦）+ Sparse（内置 BM25 全文检索）双路召回，`WeightedRanker` 加权融合；索引由 Milvus 统一维护，**多实例天然共享、无需重建** |
| **RAG Pipeline** | Query Rewrite → Embed（缓存）→ Hybrid Retrieve → Cross-Encoder Rerank → Context Build → LLM Generate 全链路，每步 OpenTelemetry 埋点 |
| **四层缓存** | Query 改写 / Embedding / RAG 结果（精确 MD5）/ **语义缓存（余弦 > 0.95 复用历史结果）**，TTL 随机抖动防雪崩 |
| **全链路异步** | Milvus / MinIO / 同步 IO 全部经 `asyncio.to_thread` 执行，**不阻塞事件循环**；MinIO 客户端惰性初始化 |
| **多租户隔离** | `tenant_id` 贯穿 PostgreSQL（**Row-Level Security 强隔离**）与 Milvus（标量过滤），检索强制拼接租户条件 |
| **安全与流控** | `slowapi` 按 IP 限流、通用 **OIDC/JWT** 认证中间件（JWKS 校验）、参数长度校验、CORS 白名单 |
| **异步任务队列** | **Celery + Redis** 剥离文档解析与向量化，支持指数退避重试与失败标记 |
| **可观测性** | **OpenTelemetry → Jaeger** 分布式链路追踪，定位 Rewrite/Embed/Retrieve/Rerank/LLM 各步耗时 |
| **自动评估** | LLM 自动打分：相关性 / 忠实性 / 完整性 / 综合分，落库 PostgreSQL |
| **用户反馈** | 👍/👎 反馈闭环，满意度统计、差评 Top 分析、最近反馈列表 |
| **可视化** | Vue3 + ECharts：查询趋势、缓存命中率、文档质量分布、QPS、评分趋势 |
| **流式输出** | SSE（Server-Sent Events）流式问答，Nginx 关闭缓冲透传，流结束写入查询日志 |

---

## 🏗️ 系统架构

```
┌───────────────────────────────────────────────────────────┐
│  前端  Vue3 + ECharts + vue-router           (port 3000)   │
│  Chat / Docs / Metrics / Feedback 四个页面                  │
└────────────────────────┬──────────────────────────────────┘
                         │  /api/  (Nginx 反向代理 + SSE 透传)
┌────────────────────────▼──────────────────────────────────┐
│  FastAPI 后端                                 (port 8000)  │
│  中间件：认证(OIDC/JWT) → 租户上下文 → 限流(slowapi) → CORS   │
│  ├── POST /chat/            RAG 问答（同步，租户隔离）        │
│  ├── GET  /chat/stream      RAG 问答（SSE 流式，写日志）      │
│  ├── POST /upload/          文档上传（大文件投递 Celery）      │
│  ├── GET  /upload/docs      文档列表（RLS 自动限定租户）       │
│  ├── DEL  /upload/docs/{id} 删除文档（联动清理向量/文件）      │
│  ├── POST /feedback/        提交反馈                         │
│  ├── GET  /feedback/stats   反馈统计                         │
│  └── GET  /metrics/*        监控指标（6 个端点）              │
└──────┬──────────┬──────────┬───────────┬──────────────────┘
       │          │          │           │
  ┌────▼───┐ ┌────▼───┐ ┌────▼────┐ ┌────▼────┐   ┌──────────┐
  │ Milvus │ │ Redis  │ │   PG    │ │  MinIO  │   │  Celery  │
  │2.5 向量 │ │ 四层缓存│ │ 元数据  │ │ 文件存储 │   │  Worker  │
  │+Sparse │ │+任务队列│ │ +RLS   │ │         │   │(文档处理) │
  └────────┘ └────────┘ └─────────┘ └─────────┘   └────┬─────┘
                                                        │
                                          ┌─────────────▼──────────┐
                                          │  Jaeger (OpenTelemetry) │
                                          └────────────────────────┘
```

**组件职责：**

| 组件 | 版本 | 作用 |
|------|------|------|
| **Milvus** | v2.5.4 | 向量 + Sparse(BM25) 存储与混合检索；**内置全文检索替代进程内 BM25**，分布式共享 |
| **Redis** | 7.2 | 四层缓存 + Celery 消息代理/结果后端，`maxmemory 512mb` LRU |
| **PostgreSQL** | 16 | 文档 / chunk / 查询日志 / 评估 / 反馈 五张业务表，启用 RLS 租户隔离 |
| **MinIO** | 2024-01 | 原始上传文件的对象存储（客户端惰性初始化 + 异步 IO） |
| **Celery** | 5.4 | 分布式任务队列，剥离文档解析/向量化，支持重试 |
| **Jaeger** | 1.57 | OpenTelemetry 链路追踪后端与 UI |
| **etcd** | v3.5.11 | Milvus 的元数据依赖（Milvus standalone 必需） |

---

## 🔍 RAG Pipeline 详解

一次问答的完整链路（见 [pipeline.py](backend/app/rag/pipeline.py)）：

```
用户问题
   │
   ├─▶ Layer-3 精确缓存命中？ ──是──▶ 直接返回（cache_hit=true）
   │       (RAG 结果缓存，MD5)
   ▼ 否
[Step 1] Query Rewrite      LLM 改写问题，使其更适合检索（Layer-1 缓存改写结果）
   │
   ▼
[Step 2] Embedding          向量化（Layer-2 缓存向量）
   │
   ├─▶ Layer-3+ 语义缓存命中？(余弦 > 0.95) ──是──▶ 复用历史结果
   ▼ 否
[Step 3] Hybrid Retrieve    Milvus 内 Dense + Sparse(BM25) 双路召回 → WeightedRanker 融合
   │                        （强制拼接 tenant_id 过滤，实现租户隔离）
   ▼
[Step 4] Rerank             Cross-Encoder（bge-reranker-v2-m3 API）精排，取 Top-N
   │
   ▼
[Step 5] Context Build      拼接检索片段，控制总长度（默认 3000 字符）
   │
   ▼
[Step 6] LLM Generate       基于上下文生成答案 → 写入 Layer-3 与语义缓存
   │
   ▼
返回 answer / sources / latency_ms / cache_hit
```

**关键设计点：**

- **融合策略**：Dense 与 Sparse 两路在 Milvus 内用 `WeightedRanker(α, 1-α)` 融合，`α` 由 `HYBRID_ALPHA` 控制（默认 0.7，Dense 权重更高）。
- **分布式索引**：Sparse 由 Milvus 的 BM25 Function 从 `text` 字段**自动生成**，TF/IDF 实时更新；索引由 Milvus 统一维护，多实例天然共享，**重启无需重建**。
- **租户隔离**：检索与删除均强制拼接 `tenant_id` 标量过滤条件，避免跨租户数据泄漏。
- **降级容错**：Query Rewrite 失败回退原始 query；Rerank API 失败回退融合分数原序，均不阻断主流程。
- **链路追踪**：Rewrite / Embed / Retrieve / Rerank / Generate 各步以 `trace_step` 埋点，启用后上报 Jaeger。

---

## 📁 项目结构

```
rag-system/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口 + lifespan（初始化 PG/Redis/Milvus/Tracing）
│   │   ├── core/
│   │   │   ├── config.py        # 全局配置（pydantic-settings，全环境变量）
│   │   │   ├── logger.py        # loguru 日志（控制台 + 按天轮转文件）
│   │   │   ├── llm.py           # LLM + Embedding 客户端（OpenAI 兼容）
│   │   │   ├── security.py      # OIDC/JWT 认证中间件 + 租户提取
│   │   │   ├── limiter.py       # slowapi 限流器（独立模块，避免循环导入）
│   │   │   └── tracing.py       # OpenTelemetry 初始化 + trace_step 埋点
│   │   ├── db/
│   │   │   ├── postgres.py      # SQLAlchemy 异步 ORM + 租户上下文 + RLS GUC 注入
│   │   │   ├── redis.py         # 四层缓存（含语义缓存）+ 命中率统计
│   │   │   ├── milvus.py        # Milvus 2.5（Dense HNSW + Sparse BM25 混合检索，异步 IO）
│   │   │   └── minio.py         # 对象存储（惰性初始化 + 异步 IO）
│   │   ├── rag/
│   │   │   ├── pipeline.py      # 完整 RAG Pipeline（精确缓存→语义缓存→检索→重排）
│   │   │   ├── retriever.py     # 混合检索薄封装（委托 Milvus 原生 hybrid_search）
│   │   │   └── reranker.py      # CrossEncoderReranker（bge-reranker-v2-m3 API）
│   │   ├── tasks/
│   │   │   ├── celery_app.py    # Celery 应用（Redis broker/backend）
│   │   │   └── doc_tasks.py     # process_document 任务（重试 + 失败标记）
│   │   ├── services/
│   │   │   ├── doc_service.py   # 解析 / 清洗 / 分块 / 质量控制 / 入库
│   │   │   ├── eval_service.py  # LLM 自动评分 + 指标聚合
│   │   │   └── feedback_service.py  # 反馈存储 + 统计
│   │   └── api/
│   │       ├── chat.py          # /chat（同步 + SSE，限流 + 租户隔离）
│   │       ├── upload.py        # /upload（文档管理，大文件投递 Celery）
│   │       ├── feedback.py      # /feedback
│   │       └── metrics.py       # /metrics（6 个端点）
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Chat.vue         # 流式问答 + 反馈按钮
│   │   │   ├── Docs.vue         # 拖拽上传 + 质量分展示
│   │   │   ├── Metrics.vue      # ECharts 图表大盘
│   │   │   └── Feedback.vue     # 满意度 + 差评分析
│   │   ├── api/index.js         # Axios API 封装
│   │   ├── router.js            # 路由定义
│   │   ├── App.vue              # 侧边栏布局 + 健康探针
│   │   └── styles/global.css    # 设计系统变量
│   ├── nginx.conf               # 静态托管 + /api 反代 + SSE 配置
│   ├── vite.config.js
│   ├── package.json
│   └── Dockerfile
├── tests/
│   ├── conftest.py              # 路径注入
│   └── test_rag_pipeline.py     # 单元测试
├── infra/
│   └── init.sql                 # PG 索引初始化（RLS 由应用层 init_db 应用）
├── docker-compose.yml           # 编排 etcd/minio/redis/postgres/milvus/jaeger/backend/worker/frontend
├── .env                         # 环境配置（已被 .gitignore 忽略）
├── deploy.sh                    # 一键部署脚本
└── README.md
```

---

## 🚀 快速部署

### 前置要求

- Docker >= 24.0
- Docker Compose >= 2.20
- 可用内存 >= 4GB（Milvus 需较多内存，建议 8GB+）
- 一个可用的 LLM/Embedding API Key（默认使用[硅基流动](https://siliconflow.cn)，兼容 OpenAI 协议）

### Step 1 — 初始化环境变量

```bash
cd rag-system
chmod +x deploy.sh
./deploy.sh
# 首次运行会自动生成 .env 并提示填写 API Key
```

### Step 2 — 填写 API Key

```bash
nano .env
# 将 SILICONFLOW_API_KEY=sk-your-key-here 替换为你的真实 Key
```

> ⚠️ `.env` 已被 `.gitignore` 忽略，请勿提交真实密钥到版本库。

### Step 3 — 正式部署

```bash
./deploy.sh
```

脚本会依次：检查依赖 → 拉取基础镜像 → 启动 etcd/minio/redis/postgres → 等待健康 → 启动 Milvus → 构建并启动后端与前端 → 健康检查。

### 部署完成后访问

| 服务 | 地址 | 说明 |
|------|------|------|
| **前端** | http://localhost:3000 | 应用主入口 |
| **API 文档** | http://localhost:8000/docs | Swagger UI |
| **ReDoc** | http://localhost:8000/redoc | 备用 API 文档 |
| **健康检查** | http://localhost:8000/health | 返回服务状态 |
| **MinIO 控制台** | http://localhost:9001 | 账号 `minioadmin` / `minioadmin123` |
| **Milvus 指标** | http://localhost:9091/healthz | Milvus 健康端点 |
| **Jaeger UI** | http://localhost:16686 | 链路追踪（需 `OTEL_ENABLED=true`） |

---

## ⚙️ 环境变量说明

所有配置经 [config.py](backend/app/core/config.py) 的 pydantic-settings 从环境变量读取，**禁止硬编码**。

### LLM / Embedding

| 变量 | 必填 | 说明 | 默认值 |
|------|:----:|------|--------|
| `SILICONFLOW_API_KEY` | ✅ | API Key | `sk-your-key-here` |
| `SILICONFLOW_BASE_URL` | | OpenAI 兼容 API 基址 | `https://api.siliconflow.cn/v1` |
| `LLM_MODEL` | | LLM 模型名 | `deepseek-ai/DeepSeek-V2.5` |
| `EMBED_MODEL` | | Embedding 模型名 | `BAAI/bge-m3` |
| `EMBED_DIM` | | 向量维度（需与模型一致） | `1024` |

### 数据库与存储

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 异步连接串 | `postgresql+asyncpg://raguser:ragpass123@postgres:5432/ragdb` |
| `REDIS_URL` | Redis 连接串 | `redis://redis:6379/0` |
| `MILVUS_HOST` / `MILVUS_PORT` | Milvus 地址 | `milvus` / `19530` |
| `MILVUS_COLLECTION` | 向量集合名 | `rag_docs` |
| `MINIO_ENDPOINT` | MinIO 地址 | `minio:9000` |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | MinIO 凭据 | `minioadmin` / `minioadmin123` |
| `MINIO_BUCKET` | 桶名 | `documents` |
| `MINIO_SECURE` | 是否启用 TLS | `false` |

### RAG 与缓存

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CHUNK_SIZE` | 分块字符数 | `500` |
| `CHUNK_OVERLAP` | 分块重叠字符数 | `50` |
| `TOP_K` | 检索召回数 | `10` |
| `RERANK_TOP_N` | 最终入 LLM 的段落数 | `5` |
| `RERANK_MODEL` | Cross-Encoder 重排模型 | `BAAI/bge-reranker-v2-m3` |
| `HYBRID_ALPHA` | 混合检索 Dense 权重（Sparse 为 1-α） | `0.7` |
| `QUALITY_THRESHOLD` | 文档质量门槛（低于则拒绝入库） | `0.6` |
| `CACHE_TTL_QUERY` | Query 改写缓存 TTL（秒） | `1800` |
| `CACHE_TTL_EMBED` | Embedding 缓存 TTL（秒） | `86400` |
| `CACHE_TTL_RAG` | RAG 结果缓存 TTL（秒） | `3600` |
| `SEMANTIC_CACHE_THRESHOLD` | 语义缓存余弦相似度阈值 | `0.95` |
| `SEMANTIC_CACHE_MAX_SIZE` | 单租户语义缓存条目上限 | `5000` |

### 安全、限流与认证

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `AUTH_ENABLED` | 是否启用认证中间件（关闭则使用默认租户） | `false` |
| `OIDC_ISSUER` | OIDC Issuer（用于发现/校验） | 空 |
| `OIDC_JWKS_URL` | JWKS 端点（RS256 公钥校验） | 空 |
| `OIDC_AUDIENCE` | 期望的 audience（可选） | 空 |
| `JWT_ALGORITHMS` | 允许的签名算法（逗号分隔） | `RS256` |
| `JWT_SECRET` | HS256 兜底密钥（仅内网/测试用） | 空 |
| `DEFAULT_TENANT_ID` | 未启用认证时使用的默认租户 | `default` |
| `RATE_LIMIT_CHAT` | 问答接口限流（IP 维度） | `30/minute` |
| `RATE_LIMIT_UPLOAD` | 上传接口限流 | `10/minute` |
| `RATE_LIMIT_DEFAULT` | 全局默认限流 | `100/minute` |
| `CORS_ORIGINS` | 允许的跨域来源（逗号分隔） | `http://localhost:3000` |

### 异步任务与可观测性

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Celery broker / 结果后端 | `redis://redis:6379/1` |
| `CELERY_ALWAYS` | 是否所有文档都走 Celery（否则超大文件才走） | `false` |
| `CELERY_SIZE_THRESHOLD_MB` | 走 Celery 的文件大小阈值（MB） | `5` |
| `OTEL_ENABLED` | 是否启用 OpenTelemetry 上报 | `false` |
| `OTEL_SERVICE_NAME` | Jaeger 中显示的服务名 | `rag-backend` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP gRPC 端点 | `http://jaeger:4317` |

### 应用

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `APP_ENV` | 运行环境 | `production` |
| `APP_HOST` / `APP_PORT` | 监听地址 / 端口 | `0.0.0.0` / `8000` |

---

## 🔌 API 接口文档

> 所有业务接口均受 **slowapi 限流**（按客户端 IP，默认值见「环境变量说明」）。
> 启用 `AUTH_ENABLED=true` 后，需在请求头携带 `Authorization: Bearer <JWT>`，
> 中间件会从 token 中解析 `tenant_id`（取自 `tenant_id`/`org_id`/`org`/`workspace_id`/`sub` claim），
> 并保证**仅能访问本租户数据**；未启用时统一使用 `DEFAULT_TENANT_ID`。

### 系统

```http
GET /health          # {"status":"ok","version":"2.0.0","env":"production"}
GET /                # 服务信息
```

### 查询

```http
POST /chat/
Authorization: Bearer <JWT>   # AUTH_ENABLED=true 时必需
Content-Type: application/json
{"question": "什么是 RAG？", "session_id": "user-123"}
```

响应：

```json
{
  "answer": "...",
  "rewritten_query": "...",
  "sources": [{"text": "...", "score": 0.82}],
  "latency_ms": 1234,
  "cache_hit": false,
  "log_id": 42
}
```

```http
GET /chat/stream?question=什么是RAG&session_id=user-123
# SSE 流式输出，逐 token 推送 data: 帧，以 data: [DONE] 结束；流结束后写入 QueryLog（可按 log_id 反馈）
```

### 文档

```http
POST   /upload/                 # 上传（multipart/form-data，字段名 file）
GET    /upload/docs?skip=0&limit=30   # 文档列表（RLS 自动限定当前租户）
DELETE /upload/docs/{doc_id}    # 删除（联动清理 MinIO + Milvus 向量/Sparse + PG）
```

上传限制：支持 `.pdf .docx .doc .html .htm .txt .md`，单文件 <= 50MB。上传后进入**异步处理**—
文件超过 `CELERY_SIZE_THRESHOLD_MB`（或 `CELERY_ALWAYS=true`）时投递到 **Celery** 队列，否则用进程内后台任务；接口立即返回 `status: "processing"`。

### 反馈

```http
POST /feedback/
{"query":"...", "answer":"...", "feedback":"like", "log_id":1}

GET /feedback/stats
# {like, dislike, total, like_ratio, satisfaction, top_bad_queries, recent}
```

### 指标

```http
GET /metrics/overview        # 总览卡片：文档数/查询数/平均分/平均延迟/缓存命中率/向量数
GET /metrics/rag?days=7      # RAG 查询质量指标（含每日趋势）
GET /metrics/cache           # Redis 四层缓存命中率（query/embed/rag/semantic）+ 键总数
GET /metrics/docs            # 文档质量统计（状态分布/评分分布/最近上传）
GET /metrics/qps             # 近 1 小时 QPS（按分钟聚合）
```

---

## 🗄️ 数据存储设计

### PostgreSQL 五张表（[postgres.py](backend/app/db/postgres.py)）

| 表 | 说明 |
|----|------|
| `documents` | 文档元数据：文件名、大小、状态、质量分、chunk 数、`tenant_id` |
| `chunks` | chunk 全文：`id / doc_id / content / chunk_idx / tenant_id`；BM25 语料由 Milvus 从向量集合的 `text` 字段原生维护 |
| `query_logs` | 每次问答日志：原始/改写 query、答案、上下文、延迟、缓存命中、`tenant_id` |
| `evaluations` | LLM 自动评分：relevance / faithfulness / completeness / overall |
| `feedback` | 用户反馈：like / dislike、评论、关联 log_id、`tenant_id` |

### 多租户隔离（Row-Level Security）

所有表均含 `tenant_id` 列，并启用 **PostgreSQL 行级安全（RLS）**：

1. **策略定义** — `init_db()` 建表后，对业务表执行 `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY`，策略表达式为 `tenant_id = current_setting('app.tenant_id', true)`。
2. **上下文传递** — 请求进入时认证中间件解析 JWT 得到 `tenant_id`，通过 `ContextVar` 存入 `set_current_tenant()`。
3. **每事务自动注入** — 监听 SQLAlchemy `engine.sync_engine` 的 `begin` 事件，在每个事务开始时执行 `SELECT set_config('app.tenant_id', :tid, true)`（事务级 GUC），**避免路由内多次 commit 后上下文失效**。
4. **向量侧过滤** — Milvus 检索 / 删除均强制拼接 `tenant_id == "<tid>"` 标量过滤表达式，双向保证数据不越界。

> 应用层过滤（Milvus）+ 数据库层强隔离（PG RLS）双保险，任何跨租户访问都会被拦截。

### 混合检索索引（Milvus 2.5）

放弃进程内纯内存 BM25，改用 **Milvus 原生 Sparse(BM25) 全文检索**：

1. **Schema** — 集合含 `dense`（`FLOAT_VECTOR`，HNSW/余弦）与 `sparse`（`SPARSE_FLOAT_VECTOR`）双向量字段，以及 `text`（`enable_analyzer=True`、`enable_match=True`）标量字段。
2. **自动生成** — 定义 `Function(type=BM25)`，由 Milvus 从 `text` 字段**自动派生** `sparse` 向量，TF/IDF 实时维护。
3. **索引** — `sparse` 建 `SPARSE_INVERTED_INDEX`（`metric_type=BM25`），`dense` 建 HNSW。
4. **融合检索** — `hybrid_search` 用 `AnnSearchRequest` 分别发起两路检索，`WeightedRanker(HYBRID_ALPHA, 1-HYBRID_ALPHA)` 融合。
5. **分布式共享** — 索引与向量数据由 Milvus 集群统一存储，**多实例天然共享，重启无需重建**，彻底解决内存索引不跨进程的问题。
6. **异步 IO** — 所有 Milvus / MinIO 调用经 `asyncio.to_thread` 卸载到线程池，不阻塞事件循环。

### Redis 缓存键

| 层级 | 键前缀 | TTL | 内容 |
|------|--------|-----|------|
| Layer-1 | `cache:query:` | 30min | Query 改写结果（MD5 精确匹配） |
| Layer-2 | `cache:embed:` | 24h | 文本向量（MD5 精确匹配） |
| Layer-3 | `cache:rag:` | 1h | 完整 RAG 结果（MD5 精确匹配） |
| Layer-3+ | `cache:sem:{tenant}:*` | 1h | **语义缓存**：保留历史 Query 向量，余弦相似度 > `SEMANTIC_CACHE_THRESHOLD`（默认 0.95）即复用对应 RAG 结果 |

所有精确键以内容 MD5 生成，写入时 TTL 附加 0~10% 随机抖动防雪崩。语义缓存按租户隔离，单租户条目上限由 `SEMANTIC_CACHE_MAX_SIZE` 控制（LRU 淘汰）。

---

## 🛠 本地开发

### 后端

```bash
cd backend
pip install -r requirements.txt
# 需先启动依赖服务（可直接用 docker compose 只起基础设施）
docker compose up -d etcd minio redis postgres milvus
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 前端

```bash
cd frontend
npm install
npm run dev     # Vite 开发服务器，默认代理 /api 到 localhost:8000
npm run build   # 生产构建，产物在 dist/
```

Vite 开发代理配置见 [vite.config.js](frontend/vite.config.js)：`/api` → `http://localhost:8000` 并去除 `/api` 前缀。

---

## 🧪 运行测试

```bash
cd rag-system
pip install pytest pytest-asyncio
cd backend && pip install -r requirements.txt && cd ..
pytest tests/ -v
```

测试覆盖：文档解析回退、文本清洗、滑动分块、质量评分、**租户过滤表达式**、**语义缓存余弦相似度**、**配置解析**、**租户上下文传递**、**JWT 租户提取**、缓存键生成、上下文构建、缓存统计。

---

## 🔄 更换 LLM / Embedding

本系统使用标准 OpenAI 兼容 API，修改 `.env` 即可切换，**无需改代码**。

### 使用 OpenAI

```bash
SILICONFLOW_BASE_URL=https://api.openai.com/v1
SILICONFLOW_API_KEY=sk-...
LLM_MODEL=gpt-4o
EMBED_MODEL=text-embedding-3-large
EMBED_DIM=3072
```

### 使用本地 Ollama

```bash
SILICONFLOW_BASE_URL=http://host.docker.internal:11434/v1
SILICONFLOW_API_KEY=ollama
LLM_MODEL=llama3.1
EMBED_MODEL=nomic-embed-text
EMBED_DIM=768
```

> ⚠️ 切换 Embedding 模型后 `EMBED_DIM` 必须同步修改，且**需清空并重建 Milvus 集合**（旧向量维度不匹配）。

---

## 📈 性能调优

| 问题 | 解决方案 |
|------|----------|
| 检索结果不相关 | 减小 `CHUNK_SIZE`、增大 `CHUNK_OVERLAP`；检查文档质量分；调整混合检索 `HYBRID_ALPHA`（增大更偏语义，减小更偏关键词） |
| 响应延迟高 | 提高 `CACHE_TTL_RAG`；减小 `TOP_K` / `RERANK_TOP_N` |
| 内存不足 | Milvus 最低需 4GB，建议 8GB+；Redis 已设 512MB LRU |
| 文档入库失败 | 检查 `errors_msg`；适当降低 `QUALITY_THRESHOLD`（如 0.4） |
| 缓存命中率低 | 对 Query 做归一化（去停用词、统一标点、统一大小写） |
| Milvus 启动慢 | 首次启动需初始化，健康检查已设 `start_period: 120s` |

---

## ❓ 常见问题 FAQ

**Q1：部署后前端 502 / 接口不可用？**
先看后端健康状态：`docker compose ps`，再查日志 `docker compose logs -f backend`。常见原因是 Milvus 尚未就绪（首次启动较慢）。

**Q2：上传文档后一直是 `processing`？**
文档在后台异步处理，处理较慢（大 PDF 解析 + 批量 Embedding）。查看日志是否有解析或质量分异常；质量分低于阈值会置为 `failed`。

**Q3：第二次相同问题为什么没命中缓存？**
精确缓存键基于**原始问题文本**的 MD5，文本有细微差异即为不同键；此时会走**语义缓存**——若与历史 Query 余弦相似度 > 0.95 仍可复用结果。两者都未命中则正常走 Pipeline。

**Q4：如何查看各步骤耗时瓶颈？**
设置 `OTEL_ENABLED=true` 并访问 Jaeger UI（http://localhost:16686），选择 `rag-backend` 服务，即可看到 Rewrite / Embed / Retrieve / Rerank / Generate 各 Span 的耗时。

**Q5：如何启用多租户与认证？**
设置 `AUTH_ENABLED=true` 并配置 `OIDC_JWKS_URL`（或 `JWT_SECRET` 用于 HS256），客户端请求携带 `Authorization: Bearer <JWT>`；中间件会解析租户并强制隔离数据。

**Q6：如何完全清理数据重来？**
```bash
docker compose down -v   # 删除所有数据卷（PG/Redis/Milvus/MinIO 全部清空！）
```

**Q7：`.env` 会被提交吗？**
不会。`.env` 已在 `.gitignore` 中忽略。请勿使用 `git add -f` 强制添加。

---

## 🚧 生产化说明

v2.0 已完成以下企业级加固（原「待办」多数已落地）：

- [x] **鉴权与限流** — slowapi 按 IP 限流；OIDC/JWT 认证中间件；`ChatRequest.question` 长度校验（1~2000）。
- [x] **CORS 收窄** — 由 `CORS_ORIGINS` 白名单控制。
- [x] **启动期外部依赖阻塞** — MinIO / Milvus 客户端改为惰性/异步初始化。
- [x] **Milvus 同步调用** — 所有 IO 经 `asyncio.to_thread` 卸载，不阻塞事件循环。
- [x] **分布式词法检索** — 内存 BM25 已被 Milvus 原生 Sparse(BM25) 替换，多实例共享。
- [x] **多 worker 一致性** — 检索索引由 Milvus 统一维护，`Dockerfile` 生产以 `--workers 2` 运行。
- [x] **语义缓存与重排** — 语义缓存（余弦 > 0.95）+ Cross-Encoder 重排。
- [x] **可观测性** — OpenTelemetry → Jaeger 链路追踪。
- [x] **异步任务队列** — Celery + Redis 处理文档解析/向量化，含指数退避重试与失败标记。
- [ ] **依赖锁定** — 目前仅 `requirements.txt`，建议补充 `requirements-dev.txt` 与锁文件（Poetry/pip-tools）。
- [ ] **Milvus `text` 字段长度** — `max_length` 按字节计，中文长 chunk 可能超限，建议入库前截断校验。
- [ ] **失败告警通道** — Celery 任务失败目前仅落日志与状态标记，建议接入告警（如 webhook / Sentry）。

---

## ✅ 验收清单

- [ ] `./deploy.sh` 或 `docker compose up -d` 一键启动全部服务
- [ ] 前端 http://localhost:3000 可访问，侧边栏显示「服务正常」
- [ ] `POST /chat/` 返回 RAG 结果，含 `sources` 与 `latency_ms`
- [ ] `GET /chat/stream` 可流式输出
- [ ] 文档上传 → 解析 → 入库，状态变为 `done` 且有质量分（大文件经 Celery 处理）
- [ ] 重复相同问题，第二次 `cache_hit: true`；近似问题命中语义缓存
- [ ] 监控大盘显示查询趋势、缓存命中、文档质量、QPS 数据
- [ ] 用户反馈可提交，`/feedback/stats` 统计正确
- [ ] 删除文档后，Milvus 向量与 Sparse 索引同步清理
- [ ]（可选）`OTEL_ENABLED=true` 后 Jaeger UI 可见各 Step 链路
- [ ]（可选）`AUTH_ENABLED=true` 后不同租户数据严格隔离
- [ ]（可选）超过限流阈值时返回 HTTP 429

---

## 📄 License

内部项目，未经授权请勿外传。
