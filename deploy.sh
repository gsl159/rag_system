#!/usr/bin/env bash
# ==============================================================
# RAG System — 一键部署脚本
# 用法: chmod +x deploy.sh && ./deploy.sh
# ==============================================================
set -euo pipefail

# ── 颜色 ──────────────────────────────────────
RED="\033[31m"; GREEN="\033[32m"; YELLOW="\033[33m"
BLUE="\033[34m"; BOLD="\033[1m"; RESET="\033[0m"

info()  { echo -e "${GREEN}[INFO]${RESET}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error() { echo -e "${RED}[ERROR]${RESET} $*"; exit 1; }
step()  { echo -e "\n${BOLD}${BLUE}▶ $*${RESET}"; }

# ── Banner ────────────────────────────────────
echo -e "${BOLD}${BLUE}"
cat << 'EOF'
  ____      _    ____   ____            _
 |  _ \    / \  / ___| / ___| _   _ ___| |_ ___ _ __ ___
 | |_) |  / _ \| |  _ \___ \| | | / __| __/ _ \ '_ ` _ \
 |  _ <  / ___ \ |_| | ___) | |_| \__ \ ||  __/ | | | | |
 |_| \_\/_/   \_\____||____/ \__, |___/\__\___|_| |_| |_|
                              |___/  Enterprise RAG Platform
EOF
echo -e "${RESET}"

# ── 检查依赖 ──────────────────────────────────
step "检查系统依赖"
command -v docker         >/dev/null 2>&1 || error "请先安装 Docker (https://docs.docker.com/get-docker/)"
command -v docker compose >/dev/null 2>&1 || error "请先安装 Docker Compose v2"

DOCKER_VER=$(docker --version | grep -oE '[0-9]+\.[0-9]+' | head -1)
info "Docker 版本: $DOCKER_VER"
info "Docker Compose 版本: $(docker compose version --short)"

# ── 检查可用内存 ──────────────────────────────
AVAIL_MEM=$(free -m 2>/dev/null | awk '/^Mem:/{print $7}' || echo "unknown")
if [[ "$AVAIL_MEM" != "unknown" && "$AVAIL_MEM" -lt 4096 ]]; then
  warn "可用内存 ${AVAIL_MEM}MB，建议 ≥ 4GB（Milvus 需要较多内存）"
fi

# ── 生成 .env ────────────────────────────────
step "配置环境变量"
if [ ! -f .env ]; then
  info "未检测到 .env，正在生成默认配置…"
  cat > .env << 'ENV'
# =============================================
# RAG System — 环境配置
# =============================================

# ⚠️  必须修改：替换为你的真实 API Key
SILICONFLOW_API_KEY=sk-your-key-here
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=deepseek-ai/DeepSeek-V2.5
EMBED_MODEL=BAAI/bge-m3
EMBED_DIM=1024

# 数据库（默认即可）
POSTGRES_DB=ragdb
POSTGRES_USER=raguser
POSTGRES_PASSWORD=ragpass123
DATABASE_URL=postgresql+asyncpg://raguser:ragpass123@postgres:5432/ragdb

# Redis
REDIS_URL=redis://redis:6379/0

# Milvus
MILVUS_HOST=milvus
MILVUS_PORT=19530
MILVUS_COLLECTION=rag_docs

# MinIO
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
MINIO_BUCKET=documents
MINIO_SECURE=false

# RAG 参数
CHUNK_SIZE=500
CHUNK_OVERLAP=50
TOP_K=10
RERANK_TOP_N=5
QUALITY_THRESHOLD=0.6

# Cache TTL（秒）
CACHE_TTL_QUERY=1800
CACHE_TTL_EMBED=86400
CACHE_TTL_RAG=3600

# 日志
LOG_LEVEL=INFO
APP_ENV=production
ENV
  echo ""
  warn "┌──────────────────────────────────────────┐"
  warn "│  .env 已生成，请编辑填入真实 API Key 后    │"
  warn "│  再次运行此脚本以完成部署                  │"
  warn "└──────────────────────────────────────────┘"
  echo ""
  info "编辑命令: nano .env  或  vim .env"
  exit 0
fi

# 检查 API Key 是否填写
if grep -q "sk-your-key-here" .env; then
  error ".env 中 SILICONFLOW_API_KEY 尚未填写！请先编辑 .env 文件"
fi
info ".env 配置检查通过 ✓"

# ── 创建目录 ──────────────────────────────────
step "准备目录结构"
mkdir -p infra
info "目录就绪 ✓"

# ── 拉取基础镜像 ──────────────────────────────
step "拉取基础镜像（首次较慢，请耐心等待）"
docker compose pull --quiet etcd minio redis postgres || warn "部分镜像拉取失败，尝试继续…"

# ── 启动基础设施 ──────────────────────────────
step "启动基础设施服务"
docker compose up -d etcd minio redis postgres
info "等待服务健康检查（30s）…"
sleep 30

# 等待 postgres 就绪
MAX=30; i=0
while ! docker compose exec -T postgres pg_isready -U raguser -d ragdb >/dev/null 2>&1; do
  i=$((i+1))
  [ $i -ge $MAX ] && error "PostgreSQL 启动超时"
  echo -n "."
  sleep 2
done
info "PostgreSQL 就绪 ✓"

# 等待 redis 就绪
docker compose exec -T redis redis-cli ping >/dev/null 2>&1 && info "Redis 就绪 ✓" || warn "Redis 可能未就绪"

# ── 启动 Milvus ───────────────────────────────
step "启动 Milvus 向量数据库"
docker compose up -d milvus
info "等待 Milvus 就绪（60s，首次启动较慢）…"
MAX=30; i=0
while ! curl -sf http://localhost:9091/healthz >/dev/null 2>&1; do
  i=$((i+1))
  [ $i -ge $MAX ] && { warn "Milvus 可能还在启动，继续部署…"; break; }
  echo -n "."
  sleep 2
done
echo ""
info "Milvus 就绪 ✓"

# ── 构建并启动应用 ────────────────────────────
step "构建并启动后端 & 前端（首次需要较长时间）"
docker compose up -d --build backend frontend
info "等待后端启动（30s）…"
sleep 30

# 健康检查
MAX=20; i=0
while ! curl -sf http://localhost:8000/health >/dev/null 2>&1; do
  i=$((i+1))
  [ $i -ge $MAX ] && { warn "后端可能还在启动，请稍后手动访问"; break; }
  echo -n "."
  sleep 3
done
echo ""

# ── 完成 ──────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║        🚀  部署完成！                    ║${RESET}"
echo -e "${BOLD}${GREEN}╠══════════════════════════════════════════╣${RESET}"
echo -e "${BOLD}${GREEN}║${RESET}  前端入口:   ${BOLD}http://localhost:3000${RESET}       ${BOLD}${GREEN}║${RESET}"
echo -e "${BOLD}${GREEN}║${RESET}  API 文档:   ${BOLD}http://localhost:8000/docs${RESET}  ${BOLD}${GREEN}║${RESET}"
echo -e "${BOLD}${GREEN}║${RESET}  MinIO 控台: ${BOLD}http://localhost:9001${RESET}       ${BOLD}${GREEN}║${RESET}"
echo -e "${BOLD}${GREEN}║${RESET}  (MinIO: minioadmin / minioadmin123)    ${BOLD}${GREEN}║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${YELLOW}常用命令：${RESET}"
echo -e "  查看日志:    ${BOLD}docker compose logs -f backend${RESET}"
echo -e "  查看状态:    ${BOLD}docker compose ps${RESET}"
echo -e "  停止服务:    ${BOLD}docker compose down${RESET}"
echo -e "  完全清理:    ${BOLD}docker compose down -v${RESET}"
echo ""
