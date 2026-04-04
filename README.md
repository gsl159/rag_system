# 🧠 RAG System — 企业级知识库问答平台

> 完整的企业级 RAG（检索增强生成）系统，支持一键 Docker 部署。

## ✨ 功能特性

| 模块 | 功能 |
|------|------|
| **文档处理** | PDF / Word / HTML / TXT / Markdown 解析，质量自动评分，MD5去重 |
| **混合检索** | Dense（Milvus HNSW）+ Sparse（BM25）→ RRF 融合，线程安全 |
| **RAG Pipeline** | Query Rewrite → Retrieve → Rerank → Generate，C2→C1→C0 硬超时降级 |
| **三层缓存** | Redis：含 doc_version + embedding_version 的版本化Key，文档更新自动失效 |
| **SingleFlight** | 热点查询防风暴，同一 Query 只允许 1 个请求进入 RAG 主流程 |
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
│  ├── /upload   文档上传与管理（MD5去重）              │
│  ├── /feedback 用户反馈                              │
│  └── /metrics  监控指标                              │
└──────┬─────────┬────────┬────────────┬──────────────┘
       │         │        │            │
  ┌────▼──┐ ┌───▼───┐ ┌──▼────┐ ┌────▼───┐
  │Milvus │ │ Redis │ │  PG   │ │ MinIO  │
  │向量库 │ │版本缓存│ │元数据 │ │文件存储│
  └───────┘ └───────┘ └───────┘ └────────┘

RAG Pipeline（生产加固版）:
  Query → SingleFlight → RAG缓存? → Rewrite(缓存)
        → Embed(缓存) → Hybrid Search(Dense+BM25+RRF)
        → SimpleRerank → ContextBuild → LLM(硬超时C2→C1→C0)
        → 写缓存(版本Key) → 返回
```

---

## 🚀 快速部署（3步）

### 前置要求
- Docker >= 24.0
- Docker Compose >= 2.20
- 可用内存 ≥ 4GB（Milvus 需要）
- 硅基流动 API Key：[免费注册](https://siliconflow.cn)

### Step 1 — 配置环境变量
```bash
cp .env.example .env
# 编辑 .env，填写 SILICONFLOW_API_KEY
nano .env
```

### Step 2 — 一键部署
```bash
chmod +x deploy.sh
./deploy.sh
```

### Step 3 — 访问服务

| 服务 | 地址 |
|------|------|
| **前端** | http://localhost:3000 |
| **API 文档** | http://localhost:8000/docs |
| **MinIO 控制台** | http://localhost:9001 |

---

## 🧪 运行测试

```bash
# 安装测试依赖
pip install pytest pytest-asyncio pytest-mock httpx aiosqlite rank-bm25

# 运行全部测试（98个用例）
cd rag_system
DATABASE_URL="sqlite+aiosqlite:///test.db" \
PYTHONPATH=backend \
pytest tests/ -v

# 只运行单元测试
pytest tests/test_rag_pipeline.py -v

# 只运行集成测试
pytest tests/test_integration.py -v
```

**测试覆盖（98个用例，全部通过）：**

| 测试模块 | 覆盖内容 |
|----------|----------|
| DocParser | 文件解析、HTML标签剥离、空文件处理 |
| TextCleaner | 换行折叠、空格清理、中文保留、控制字符过滤 |
| TextSplitter | 基础分块、空文本、句子边界、大文本、无限循环保护 |
| QualityChecker | 空输入、有效/无效比例、分数范围 |
| HybridRetriever | BM25检索、RRF融合、去重、线程安全 |
| SimpleReranker | Top-N截取、关键词提升、空输入 |
| CacheStats | 命中率计算 |
| CacheKeys | 确定性、版本感知、无碰撞 |
| ContextBuilder | 基础构建、长度限制、空文本跳过 |
| RAGPipeline | 完整流程、缓存命中、超时降级、空上下文 |
| SingleFlight | 并发去重、多Key独立 |
| FeedbackService | 提交like/dislike、长文本截断 |
| MilvusDB | 未连接降级、insert保护 |
| 版本一致性 | 版本变化Key不同、无碰撞 |
| 集成测试 | 文档处理流程、降级流程、并发安全 |

---

## ⚙️ 关键设计决策

### 缓存版本控制（防旧缓存污染）
```
cache_key = f"{prefix}:{md5(query)}:{doc_version}:{embedding_version}"
```
- 文档上传/删除 → `doc_version++` → 旧缓存自动失效
- Embedding模型升级 → `embedding_version++` → 向量缓存自动失效

### SingleFlight 防查询风暴
- 同一 Query 在同一时间窗口只允许 1 个请求进入 RAG 主流程
- 后续请求等待共享结果（最多 2s 超时）

### LLM 硬超时降级
| 级别 | 超时 | 行为 |
|------|------|------|
| C2 | 3s | 完整生成回答 |
| C1 | 1.5s | 轻量50字总结 |
| C0 | - | 直接返回原始chunk |

---

## ⚙️ 环境变量说明

| 变量 | 必填 | 说明 | 默认值 |
|------|------|------|--------|
| `SILICONFLOW_API_KEY` | ✅ | API Key | - |
| `LLM_MODEL` | | LLM 模型名 | `Qwen/Qwen2.5-7B-Instruct` |
| `EMBED_MODEL` | | Embedding 模型 | `BAAI/bge-m3` |
| `CHUNK_SIZE` | | 分块字符数 | `500` |
| `QUALITY_THRESHOLD` | | 质量门槛 | `0.6` |
| `CACHE_TTL_RAG` | | RAG 结果缓存 TTL（秒）| `3600` |

---

## 🔧 常用运维命令

```bash
docker compose ps                    # 查看服务状态
docker compose logs -f backend       # 实时后端日志
docker compose restart backend       # 重启后端
docker compose down                  # 停止服务
docker compose down -v               # 完全清理（含数据卷）
```

---

## 🔄 切换 LLM / Embedding

```bash
# 使用 OpenAI
SILICONFLOW_BASE_URL=https://api.openai.com/v1
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
