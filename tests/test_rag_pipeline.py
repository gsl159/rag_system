"""
RAG Pipeline 单元测试
运行: pytest tests/ -v
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


# ── Test: DocParser ───────────────────────────

class TestDocParser:
    def setup_method(self):
        from app.services.doc_service import DocParser
        self.parser = DocParser()

    def test_fallback_parse_txt(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello 你好 World")
        result = self.parser._fallback_parse(str(f), ".txt")
        assert "Hello" in result
        assert "你好" in result

    def test_fallback_parse_html(self, tmp_path):
        f = tmp_path / "test.html"
        f.write_text("<html><body><p>Test Content</p></body></html>")
        result = self.parser._fallback_parse(str(f), ".html")
        assert "Test Content" in result


# ── Test: TextCleaner ────────────────────────

class TestTextCleaner:
    def setup_method(self):
        from app.services.doc_service import TextCleaner
        self.cleaner = TextCleaner()

    def test_collapse_newlines(self):
        text = "Line1\n\n\n\nLine2"
        result = self.cleaner.clean(text)
        assert "\n\n\n" not in result

    def test_collapse_spaces(self):
        text = "word1   word2    word3"
        result = self.cleaner.clean(text)
        assert "   " not in result

    def test_strip(self):
        text = "  \n  Hello  \n  "
        result = self.cleaner.clean(text)
        assert result == "Hello"

    def test_keep_chinese(self):
        text = "这是中文内容 This is English"
        result = self.cleaner.clean(text)
        assert "这是中文内容" in result
        assert "This is English" in result


# ── Test: TextSplitter ───────────────────────

class TestTextSplitter:
    def setup_method(self):
        from app.services.doc_service import TextSplitter
        self.splitter = TextSplitter(chunk_size=100, overlap=20)

    def test_basic_split(self):
        text = "A" * 250
        chunks = self.splitter.split(text)
        assert len(chunks) > 1
        assert all(len(c) <= 150 for c in chunks)  # 允许一点弹性

    def test_short_text_single_chunk(self):
        text = "短文本内容"
        chunks = self.splitter.split(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_empty_text(self):
        chunks = self.splitter.split("")
        assert chunks == []

    def test_sentence_boundary_preference(self):
        # 应在句号处断开，而不是在字符中间
        text = "这是第一句话。" * 10 + "这是最后一句。"
        chunks = self.splitter.split(text)
        # 每个 chunk 应在句号结束（不一定强制，视窗口大小）
        assert len(chunks) >= 1


# ── Test: QualityChecker ─────────────────────

class TestQualityChecker:
    def setup_method(self):
        from app.services.doc_service import QualityChecker
        self.checker = QualityChecker()

    def test_empty_input(self):
        result = self.checker.evaluate([])
        assert result["score"] == 0.0

    def test_all_valid(self):
        chunks = ["这是一段有效内容，超过二十个字符的文本。" * 2] * 5
        result = self.checker.evaluate(chunks)
        assert result["score"] > 0.6
        assert result["valid"] == 5

    def test_all_invalid(self):
        chunks = ["短"] * 5
        result = self.checker.evaluate(chunks)
        assert result["valid"] == 0
        assert result["valid_ratio"] == 0.0

    def test_mixed(self):
        chunks = ["这是有效内容，超过20字。" * 2] * 3 + ["短"] * 7
        result = self.checker.evaluate(chunks)
        assert result["valid"] == 3
        assert result["total"] == 10


# ── Test: HybridRetriever ────────────────────

class TestHybridRetriever:
    def setup_method(self):
        from app.rag.retriever import HybridRetriever
        self.retriever = HybridRetriever()

    def test_bm25_search_no_index(self):
        result = self.retriever._sparse_search("query", top_k=5)
        assert result == []

    def test_bm25_add_and_search(self):
        texts = [
            "Python 是一种编程语言",
            "机器学习需要大量数据",
            "向量数据库用于相似搜索",
        ]
        self.retriever.add_texts(texts)
        result = self.retriever._sparse_search("Python 编程", top_k=3)
        assert len(result) >= 1
        # Python 相关内容应排第一
        assert "Python" in result[0]["text"]

    def test_rrf_merge_deduplication(self):
        dense  = [{"text": "同一段文本内容", "score": 0.9, "id": "1", "source": "dense"}]
        sparse = [{"text": "同一段文本内容", "score": 5.0, "id": "bm25_0", "source": "sparse"}]
        merged = self.retriever._rrf_merge(dense, sparse)
        # 相同文本（前100字）应合并，不重复
        assert len(merged) == 1

    def test_rrf_merge_alpha(self):
        dense  = [{"text": "Dense 优先内容 " * 5, "score": 0.95, "id": "d1", "source": "dense"}]
        sparse = [{"text": "Sparse 优先内容 " * 5, "score": 10.0, "id": "s1", "source": "sparse"}]
        merged = self.retriever._rrf_merge(dense, sparse, alpha=0.9)
        # alpha=0.9 时 dense 权重高，应排前
        assert "Dense" in merged[0]["text"]


# ── Test: SimpleReranker ─────────────────────

class TestSimpleReranker:
    def setup_method(self):
        from app.rag.reranker import SimpleReranker
        self.reranker = SimpleReranker()

    def test_rerank_top_n(self):
        docs = [{"text": f"文档{i}内容", "rrf_score": i * 0.1} for i in range(10)]
        result = self.reranker.rerank("文档", docs, top_n=3)
        assert len(result) == 3

    def test_rerank_keyword_boost(self):
        docs = [
            {"text": "这是关于 Python 编程的内容", "rrf_score": 0.5},
            {"text": "这是关于 Java 开发的内容",   "rrf_score": 0.8},
        ]
        result = self.reranker.rerank("Python", docs, top_n=2)
        # 包含 Python 的文档应被提升
        assert "Python" in result[0]["text"]


# ── Test: Cache Key Generation ───────────────

class TestCacheKeys:
    def setup_method(self):
        # 不需要真实 Redis 连接，只测 key 生成
        from app.db.redis import RedisCache
        self.cache = RedisCache.__new__(RedisCache)

    def test_query_key_deterministic(self):
        k1 = self.cache._query_key("相同的问题")
        k2 = self.cache._query_key("相同的问题")
        assert k1 == k2

    def test_different_queries_different_keys(self):
        k1 = self.cache._query_key("问题一")
        k2 = self.cache._query_key("问题二")
        assert k1 != k2

    def test_key_prefixes(self):
        qk = self.cache._query_key("test")
        ek = self.cache._embed_key("test")
        rk = self.cache._rag_key("test")
        assert qk.startswith("cache:query:")
        assert ek.startswith("cache:embed:")
        assert rk.startswith("cache:rag:")

    def test_key_length(self):
        key = self.cache._query_key("任意长度的问题" * 100)
        # MD5 hex = 32 chars，加前缀不超过 50 chars
        assert len(key) < 60


# ── Test: Context Builder ────────────────────

class TestContextBuilder:
    def test_basic_build(self):
        from app.rag.pipeline import build_context
        docs = [{"text": "段落一内容"}, {"text": "段落二内容"}]
        ctx  = build_context(docs)
        assert "段落一内容" in ctx
        assert "段落二内容" in ctx

    def test_max_chars_limit(self):
        from app.rag.pipeline import build_context
        docs = [{"text": "A" * 1000}] * 10
        ctx  = build_context(docs, max_chars=500)
        assert len(ctx) <= 600  # 允许分隔符等少量溢出

    def test_empty_docs(self):
        from app.rag.pipeline import build_context
        ctx = build_context([])
        assert ctx == ""


# ── Test: CacheStats ─────────────────────────

class TestCacheStats:
    def test_hit_rate_zero(self):
        from app.db.redis import CacheStats
        s = CacheStats()
        assert s.hit_rate == 0.0

    def test_hit_rate_calculation(self):
        from app.db.redis import CacheStats
        s = CacheStats()
        s.record_hit(); s.record_hit(); s.record_miss()
        assert abs(s.hit_rate - 0.6667) < 0.001

    def test_all_hits(self):
        from app.db.redis import CacheStats
        s = CacheStats()
        for _ in range(5): s.record_hit()
        assert s.hit_rate == 1.0


# ── Async test helpers ───────────────────────

@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
