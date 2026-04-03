# 🧠 RAG System — 企业级知识库问答平台

> 完整的企业级 RAG（检索增强生成）系统，支持一键 Docker 部署。

## ✨ 功能特性

| 模块 | 功能 |
|------|------|
| **文档处理** | PDF / Word / HTML / TXT / Markdown 解析，质量自动评分，不合格文档拦截 |
| **混合检索** | Dense（Milvus HNSW）+ Sparse（BM25）→ RRF 融合，召回率更高 |
| **RAG Pipeline** | Query Rewrite → Retrieve → Rerank → Generate 全链路 |
| **三层缓存** | Redis：Query缓存 / Embedding缓存 / RAG结果缓存，防雪崩抖动TTL |
| **自动评估** | LLM 自动打分：相关性 / 忠实性 / 完整性，写入 PostgreSQL |
| **用户反馈** | 👍/👎 反馈闭环，差评 Top 分析，满意度统计 |
| **可视化** | Vue3 + ECharts：查询趋势、缓存命中、文档质量、QPS、评分趋势 |
| **流式输出** | SSE Server-Sent Events 流式问答 |

---

## 🏗️ 架构总览

```
┌─────────────────────────────────────────────────────┐
│  前端 Vue3 + ECharts  (port 3000)                   │
└───────────────────┬─────────────────────────────────┘
                    │ /api/  (Nginx 反代)
┌───────────────────▼─────────────────────────────────┐
│  FastAPI 后端  (port 8000)                          │
│  ├── /chat     RAG 问答（同步 + SSE 流式）           │
│  ├── /upload   文档上传与管理                        │
│  ├── /feedback 用户反馈                              │
│  └── /metrics  监控指标                              │
└──────┬─────────┬────────┬────────────┬──────────────┘
       │         │        │            │
  ┌────▼──┐ ┌───▼───┐ ┌──▼────┐ ┌────▼───┐
  │Milvus │ │ Redis │ │  PG   │ │ MinIO  │
  │向量库 │ │三层缓存│ │元数据 │ │文件存储│
  └───────┘ └───────┘ └───────┘ └────────┘

RAG Pipeline:
  Query → Rewrite → Embed(缓存) → Hybrid Search
        → Rerank → Context Build → LLM Generate → Cache
```

---

## 📁 项目结构

```
rag-system/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口 + lifespan
│   │   ├── core/
│   │   │   ├── config.py        # 全局配置（pydantic-settings）
│   │   │   ├── logger.py        # loguru 日志
│   │   │   └── llm.py           # LLM + Embed 客户端
│   │   ├── db/
│   │   │   ├── postgres.py      # SQLAlchemy ORM + 连接
│   │   │   ├── redis.py         # 三层缓存 + 命中率统计
│   │   │   ├── milvus.py        # 向量库（HNSW索引）
│   │   │   └── minio.py         # 对象存储
│   │   ├── rag/
│   │   │   ├── pipeline.py      # 完整 RAG Pipeline
│   │   │   ├── retriever.py     # Hybrid Search（Dense+BM25+RRF）
│   │   │   └── reranker.py      # LLM Reranker + Simple Reranker
│   │   ├── services/
│   │   │   ├── doc_service.py   # 解析/清洗/分块/质量控制
│   │   │   ├── eval_service.py  # LLM 自动评分 + 指标聚合
│   │   │   └── feedback_service.py  # 反馈存储 + 统计
│   │   └── api/
│   │       ├── chat.py          # /chat（同步 + SSE）
│   │       ├── upload.py        # /upload（文档管理）
│   │       ├── feedback.py      # /feedback
│   │       └── metrics.py       # /metrics（6个指标端点）
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Chat.vue         # 流式问答 + 反馈按钮
│   │   │   ├── Docs.vue         # 拖拽上传 + 质量分
│   │   │   ├── Metrics.vue      # 6个ECharts图表
│   │   │   └── Feedback.vue     # 满意度 + 差评分析
│   │   ├── api/index.js         # Axios API 封装
│   │   ├── router.js
│   │   ├── App.vue              # 侧边栏布局
│   │   └── styles/global.css    # 设计系统变量
│   ├── nginx.conf
│   └── Dockerfile
├── tests/
│   ├── conftest.py
│   └── test_rag_pipeline.py     # 单元测试（30+ cases）
├── infra/
│   └── init.sql                 # PG 索引初始化
├── docker-compose.yml
├── .env                         # 环境配置
├── deploy.sh                    # 一键部署脚本
└── README.md
```

---

## 🚀 快速部署（3步）

### 前置要求
- Docker >= 24.0
- Docker Compose >= 2.20
- 可用内存 ≥ 4GB（Milvus 需要）
- 硅基流动 API Key：[免费注册](https://siliconflow.cn)

### Step 1 — 克隆并初始化
```bash
cd rag-system
chmod +x deploy.sh
./deploy.sh
# 首次运行会生成 .env 并提示填写 API Key
```

### Step 2 — 填写 API Key
```bash
nano .env
# 修改 SILICONFLOW_API_KEY=sk-your-actual-key
```

### Step 3 — 正式部署
```bash
./deploy.sh
```

**部署完成后访问：**

| 服务 | 地址 |
|------|------|
| **前端** | http://localhost:3000 |
| **API 文档** | http://localhost:8000/docs |
| **MinIO 控制台** | http://localhost:9001 |

---

## ⚙️ 环境变量说明

| 变量 | 必填 | 说明 | 默认值 |
|------|------|------|--------|
| `SILICONFLOW_API_KEY` | ✅ | API Key | - |
| `LLM_MODEL` | | LLM 模型名 | `Qwen/Qwen2.5-7B-Instruct` |
| `EMBED_MODEL` | | Embedding 模型 | `BAAI/bge-m3` |
| `CHUNK_SIZE` | | 分块字符数 | `500` |
| `CHUNK_OVERLAP` | | 分块重叠 | `50` |
| `TOP_K` | | 检索返回数 | `10` |
| `RERANK_TOP_N` | | 最终入 LLM 段落数 | `5` |
| `QUALITY_THRESHOLD` | | 质量门槛（低于则拒绝）| `0.6` |
| `CACHE_TTL_QUERY` | | Query 缓存 TTL（秒）| `1800` |
| `CACHE_TTL_EMBED` | | Embedding 缓存 TTL | `86400` |
| `CACHE_TTL_RAG` | | RAG 结果缓存 TTL | `3600` |

---

## 🔌 API 接口

### 查询
```http
POST /chat/
Content-Type: application/json
{"question": "什么是 RAG？", "session_id": "user-123"}

GET /chat/stream?question=什么是RAG
# SSE 流式输出
```

### 文档
```http
POST   /upload/               上传文档（multipart/form-data）
GET    /upload/docs            文档列表
DELETE /upload/docs/{doc_id}  删除文档
```

### 反馈
```http
POST /feedback/
{"query":"...", "answer":"...", "feedback":"like", "log_id":1}

GET /feedback/stats
```

### 指标
```http
GET /metrics/overview    总览卡片
GET /metrics/rag?days=7  RAG查询指标
GET /metrics/cache       三层缓存命中率
GET /metrics/docs        文档质量统计
GET /metrics/qps         近1小时QPS
```

---

## 🧪 运行测试

```bash
cd rag-system
pip install pytest pytest-asyncio
cd backend
pip install -r requirements.txt
cd ..
pytest tests/ -v
```

---

## 🔧 常用运维命令

```bash
# 查看所有服务状态
docker compose ps

# 实时日志
docker compose logs -f backend
docker compose logs -f frontend

# 重启后端（修改代码后）
docker compose restart backend

# 进入后端容器调试
docker compose exec backend bash

# 停止所有服务
docker compose down

# 完全清理（含所有数据卷！）
docker compose down -v
```

---

## 🔄 更换 LLM / Embedding

本系统使用标准 OpenAI 兼容 API，修改 `.env` 即可切换：

```bash
# 使用 OpenAI
SILICONFLOW_BASE_URL=https://api.openai.com/v1
SILICONFLOW_API_KEY=sk-...
LLM_MODEL=gpt-4o
EMBED_MODEL=text-embedding-3-large
EMBED_DIM=3072

# 使用本地 Ollama
SILICONFLOW_BASE_URL=http://host.docker.internal:11434/v1
SILICONFLOW_API_KEY=ollama
LLM_MODEL=llama3.1
EMBED_MODEL=nomic-embed-text
EMBED_DIM=768
```

---

## 📈 性能调优

| 问题 | 解决方案 |
|------|----------|
| 检索结果不相关 | 减小 `CHUNK_SIZE`，增大 `CHUNK_OVERLAP`，检查文档质量 |
| 响应延迟高 | 提高 `CACHE_TTL_RAG`，减小 `TOP_K` |
| 内存不足 | Milvus 最低需 4GB，建议 8GB+ |
| 文档入库失败 | 检查 `QUALITY_THRESHOLD`，降低至 `0.4` |
| 缓存命中率低 | 对 Query 做 normalization（去停用词、统一标点）|

---

## 验收清单

- [ ] `docker compose up` 一键启动
- [ ] 前端 http://localhost:3000 可访问
- [ ] `/chat/` 返回 RAG 结果
- [ ] 文档上传并解析入库
- [ ] Redis 缓存生效（第二次查询 `cache_hit: true`）
- [ ] 监控大盘显示数据
- [ ] 用户反馈可记录
