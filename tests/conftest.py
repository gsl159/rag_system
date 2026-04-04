"""
pytest 配置 — 路径设置，让 app.* 导入可用
提供公共 fixtures
"""
import sys
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 将 backend/ 目录加入 Python path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))


# ── 公共 Fixtures ──────────────────────────────

@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def mock_llm_client():
    """Mock LLM 客户端，避免真实 API 调用"""
    with patch("app.core.llm.llm_client") as mock:
        mock.chat = AsyncMock(return_value="这是一个模拟回答，基于提供的上下文。")
        mock.chat_json = AsyncMock(return_value={
            "relevance": 4, "faithfulness": 5, "completeness": 3, "overall": 4, "reason": "测试"
        })
        mock.stream = AsyncMock(return_value=iter(["这是", "流式", "回答"]))
        yield mock


@pytest.fixture
def mock_embed_client():
    """Mock Embedding 客户端"""
    with patch("app.core.llm.embed_client") as mock:
        mock.embed_one = AsyncMock(return_value=[0.1] * 1024)
        mock.embed_batch = AsyncMock(return_value=[[0.1] * 1024])
        yield mock


@pytest.fixture
def mock_redis_cache():
    """Mock Redis Cache"""
    with patch("app.db.redis.cache") as mock:
        mock.get_rag = AsyncMock(return_value=None)
        mock.set_rag = AsyncMock()
        mock.get_query = AsyncMock(return_value=None)
        mock.set_query = AsyncMock()
        mock.get_embed = AsyncMock(return_value=None)
        mock.set_embed = AsyncMock()
        mock.get_global_doc_version = AsyncMock(return_value=0)
        mock.increment_doc_version = AsyncMock(return_value=1)
        mock.single_flight = AsyncMock(side_effect=lambda key, coro: coro())
        mock.client = MagicMock()
        yield mock


@pytest.fixture
def mock_milvus():
    """Mock Milvus"""
    with patch("app.db.milvus.milvus_db") as mock:
        mock.search = MagicMock(return_value=[
            {"id": "chunk-1", "doc_id": "doc-1", "chunk_idx": 0,
             "text": "这是测试文档内容，用于检索测试", "score": 0.9, "source": "dense"}
        ])
        mock.insert = MagicMock()
        mock.delete_by_doc = MagicMock()
        mock.get_stats = MagicMock(return_value={"total_entities": 100, "connected": True})
        mock.is_connected = True
        yield mock
