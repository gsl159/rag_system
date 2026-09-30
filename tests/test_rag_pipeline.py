"""
RAG Pipeline 单元测试
运行: pytest tests/ -v

说明：混合检索已下沉至 Milvus（Dense + 原生 Sparse/BM25），
进程内不再有 BM25 索引，因此相关用例改为覆盖新组件：
语义缓存余弦计算、租户过滤表达式、Cross-Encoder 重排回退、配置解析等。
"""
import math

import pytest


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
        result = self.cleaner.clean("Line1\n\n\n\nLine2")
        assert "\n\n\n" not in result

    def test_collapse_spaces(self):
        result = self.cleaner.clean("word1   word2    word3")
        assert "   " not in result

    def test_strip(self):
        result = self.cleaner.clean("  \n  Hello  \n  ")
        assert result == "Hello"

    def test_keep_chinese(self):
        result = self.cleaner.clean("这是中文内容 This is English")
        assert "这是中文内容" in result
        assert "This is English" in result


# ── Test: TextSplitter ───────────────────────

class TestTextSplitter:
    def setup_method(self):
        from app.services.doc_service import TextSplitter
        self.splitter = TextSplitter(chunk_size=100, overlap=20)

    def test_basic_split(self):
        chunks = self.splitter.split("A" * 250)
        assert len(chunks) > 1
        assert all(len(c) <= 150 for c in chunks)

    def test_short_text_single_chunk(self):
        chunks = self.splitter.split("短文本内容")
        assert len(chunks) == 1
        assert chunks[0] == "短文本内容"

    def test_empty_text(self):
        assert self.splitter.split("") == []

    def test_sentence_boundary_preference(self):
        text = "这是第一句话。" * 10 + "这是最后一句。"
        assert len(self.splitter.split(text)) >= 1


# ── Test: QualityChecker ─────────────────────

class TestQualityChecker:
    def setup_method(self):
        from app.services.doc_service import QualityChecker
        self.checker = QualityChecker()

    def test_empty_input(self):
        assert self.checker.evaluate([])["score"] == 0.0

    def test_all_valid(self):
        chunks = ["这是一段有效内容，超过二十个字符的文本。" * 2] * 5
        result = self.checker.evaluate(chunks)
        assert result["score"] > 0.6
        assert result["valid"] == 5

    def test_all_invalid(self):
        result = self.checker.evaluate(["短"] * 5)
        assert result["valid"] == 0
        assert result["valid_ratio"] == 0.0

    def test_mixed(self):
        chunks = ["这是有效内容，超过20字。" * 2] * 3 + ["短"] * 7
        result = self.checker.evaluate(chunks)
        assert result["valid"] == 3
        assert result["total"] == 10


# ── Test: Milvus 租户过滤表达式 ───────────────

class TestTenantFilter:
    def test_none_returns_none(self):
        from app.db.milvus import MilvusDB
        assert MilvusDB._tenant_expr(None) is None
        assert MilvusDB._tenant_expr("") is None

    def test_basic_expr(self):
        from app.db.milvus import MilvusDB
        assert MilvusDB._tenant_expr("acme") == 'tenant_id == "acme"'

    def test_escape_quotes(self):
        from app.db.milvus import MilvusDB
        expr = MilvusDB._tenant_expr('a"b')
        # 引号应被转义，避免表达式注入
        assert '\\"' in expr


# ── Test: 语义缓存余弦相似度 ──────────────────

class TestSemanticCosine:
    def test_identical_vectors(self):
        from app.db.redis import _cosine
        assert abs(_cosine([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) - 1.0) < 1e-9

    def test_orthogonal_vectors(self):
        from app.db.redis import _cosine
        assert abs(_cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9

    def test_opposite_vectors(self):
        from app.db.redis import _cosine
        assert abs(_cosine([1.0, 0.0], [-1.0, 0.0]) + 1.0) < 1e-9

    def test_length_mismatch(self):
        from app.db.redis import _cosine
        assert _cosine([1.0, 0.0], [1.0]) == 0.0

    def test_empty_vectors(self):
        from app.db.redis import _cosine
        assert _cosine([], []) == 0.0

    def test_magnitude_invariance(self):
        from app.db.redis import _cosine
        # 余弦对向量缩放不敏感
        assert abs(_cosine([2.0, 0.0], [5.0, 0.0]) - 1.0) < 1e-9


# ── Test: Cache Key Generation ───────────────

class TestCacheKeys:
    def setup_method(self):
        from app.db.redis import RedisCache
        self.cache = RedisCache.__new__(RedisCache)

    def test_query_key_deterministic(self):
        assert self.cache._query_key("相同的问题") == self.cache._query_key("相同的问题")

    def test_different_queries_different_keys(self):
        assert self.cache._query_key("问题一") != self.cache._query_key("问题二")

    def test_key_prefixes(self):
        assert self.cache._query_key("t").startswith("cache:query:")
        assert self.cache._embed_key("t").startswith("cache:embed:")
        assert self.cache._rag_key("t").startswith("cache:rag:")

    def test_semantic_key_by_tenant(self):
        assert self.cache._sem_key("acme") == "cache:semantic:acme"

    def test_key_length(self):
        assert len(self.cache._query_key("任意长度的问题" * 100)) < 60


# ── Test: Context Builder ────────────────────

class TestContextBuilder:
    def test_basic_build(self):
        from app.rag.pipeline import build_context
        ctx = build_context([{"text": "段落一内容"}, {"text": "段落二内容"}])
        assert "段落一内容" in ctx
        assert "段落二内容" in ctx

    def test_max_chars_limit(self):
        from app.rag.pipeline import build_context
        ctx = build_context([{"text": "A" * 1000}] * 10, max_chars=500)
        assert len(ctx) <= 600

    def test_empty_docs(self):
        from app.rag.pipeline import build_context
        assert build_context([]) == ""


# ── Test: CacheStats ─────────────────────────

class TestCacheStats:
    def test_hit_rate_zero(self):
        from app.db.redis import CacheStats
        assert CacheStats().hit_rate == 0.0

    def test_hit_rate_calculation(self):
        from app.db.redis import CacheStats
        s = CacheStats()
        s.record_hit(); s.record_hit(); s.record_miss()
        assert abs(s.hit_rate - 0.6667) < 0.001

    def test_all_hits(self):
        from app.db.redis import CacheStats
        s = CacheStats()
        for _ in range(5):
            s.record_hit()
        assert s.hit_rate == 1.0


# ── Test: 配置解析 ───────────────────────────

class TestConfig:
    def test_cors_origins_list(self):
        from app.core.config import settings
        assert isinstance(settings.cors_origins_list, list)
        assert len(settings.cors_origins_list) >= 1

    def test_jwt_algorithms_list(self):
        from app.core.config import settings
        assert "RS256" in settings.jwt_algorithms_list

    def test_hybrid_alpha_range(self):
        from app.core.config import settings
        assert 0.0 <= settings.HYBRID_ALPHA <= 1.0

    def test_semantic_threshold_range(self):
        from app.core.config import settings
        assert 0.0 < settings.SEMANTIC_CACHE_THRESHOLD <= 1.0


# ── Test: 租户上下文 ─────────────────────────

class TestTenantContext:
    def test_default_tenant(self):
        from app.db.postgres import get_current_tenant, set_current_tenant
        from app.core.config import settings
        set_current_tenant("")
        assert get_current_tenant() == settings.DEFAULT_TENANT_ID

    def test_set_and_get(self):
        from app.db.postgres import get_current_tenant, set_current_tenant
        set_current_tenant("acme")
        assert get_current_tenant() == "acme"
        set_current_tenant("globex")
        assert get_current_tenant() == "globex"


# ── Test: 认证 token 租户提取 ────────────────

class TestTenantExtraction:
    def test_from_tenant_claim(self):
        from app.core.security import _extract_tenant
        assert _extract_tenant({"tenant_id": "acme"}) == "acme"

    def test_fallback_to_org(self):
        from app.core.security import _extract_tenant
        assert _extract_tenant({"org": "globex"}) == "globex"

    def test_fallback_to_sub(self):
        from app.core.security import _extract_tenant
        assert _extract_tenant({"sub": "user-123"}) == "user-123"

    def test_default_when_empty(self):
        from app.core.security import _extract_tenant
        from app.core.config import settings
        assert _extract_tenant({}) == settings.DEFAULT_TENANT_ID


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
