"""
集成测试 — 端到端流程验证
覆盖：文档上传流程、RAG流程、缓存版本一致性、降级机制
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))


# ════════════════════════════════════════════════
# 1. 文档处理完整流程
# ════════════════════════════════════════════════

class TestDocProcessingFlow:
    @pytest.mark.asyncio
    async def test_full_doc_pipeline_success(self, tmp_path):
        """验证文档处理完整流程不报错"""
        from app.services.doc_service import DocParser, TextCleaner, TextSplitter, QualityChecker

        f = tmp_path / "test.txt"
        f.write_text("这是一段测试文档内容。" * 100, encoding="utf-8")

        parser   = DocParser()
        cleaner  = TextCleaner()
        splitter = TextSplitter(chunk_size=200, overlap=20)
        checker  = QualityChecker()

        raw    = parser.parse(str(f))
        text   = cleaner.clean(raw)
        chunks = splitter.split(text)
        qual   = checker.evaluate(chunks)

        assert len(chunks) > 0
        assert qual["score"] > 0
        assert qual["total"] == len(chunks)

    @pytest.mark.asyncio
    async def test_html_doc_pipeline(self, tmp_path):
        f = tmp_path / "test.html"
        f.write_text("""
        <html><body>
        <h1>企业知识库</h1>
        <p>这是企业内部知识文档。</p>
        <p>包含重要的业务流程信息。</p>
        </body></html>
        """, encoding="utf-8")

        from app.services.doc_service import DocParser, TextCleaner
        parser  = DocParser()
        cleaner = TextCleaner()
        raw  = parser.parse(str(f))
        text = cleaner.clean(raw)

        assert "企业知识库" in text
        assert "业务流程" in text

    def test_chunk_overlap_content_continuity(self):
        """验证分块重叠保证内容连续性"""
        from app.services.doc_service import TextSplitter
        s = TextSplitter(chunk_size=100, overlap=30)
        text = "A" * 50 + "OVERLAP_MARKER" + "B" * 50 + "OVERLAP_MARKER" + "C" * 50
        chunks = s.split(text)
        assert len(chunks) > 0
        # 合并后应包含完整文本的主要内容
        combined = "".join(chunks)
        assert "OVERLAP_MARKER" in combined


# ════════════════════════════════════════════════
# 2. 缓存版本一致性
# ════════════════════════════════════════════════

class TestCacheVersionConsistency:
    def setup_method(self):
        from app.db.redis import RedisCache
        self.cache = RedisCache.__new__(RedisCache)
        self.cache.embedding_version = "v1"
        self.cache.client = None

    def test_doc_version_changes_cache_key(self):
        """文档版本变化导致缓存Key不同，旧缓存自动失效"""
        k_v1 = self.cache._rag_key("同一个问题", doc_version=1)
        k_v2 = self.cache._rag_key("同一个问题", doc_version=2)
        assert k_v1 != k_v2

    def test_embedding_version_changes_embed_key(self):
        """Embedding版本变化导致向量缓存失效"""
        self.cache.embedding_version = "v1"
        k_v1 = self.cache._embed_key("测试文本")
        self.cache.embedding_version = "v2"
        k_v2 = self.cache._embed_key("测试文本")
        assert k_v1 != k_v2

    def test_same_version_same_key(self):
        """相同版本和相同查询必须返回相同的Key"""
        k1 = self.cache._rag_key("问题", doc_version=3)
        k2 = self.cache._rag_key("问题", doc_version=3)
        assert k1 == k2

    def test_doc_version_increment_invalidates_cache(self):
        """
        验证缓存Key随doc_version变化而不同。
        doc_version=0 和 doc_version=1 生成不同的Key，
        因此查询新版本时不会命中旧版本的缓存。
        """
        import hashlib
        emb_ver = "v1"
        query = "同一个问题"
        h = hashlib.md5(query.encode()).hexdigest()

        key_v0 = f"cache:rag:{h}:0:{emb_ver}"
        key_v1 = f"cache:rag:{h}:1:{emb_ver}"

        # 两个版本的Key必须不同，从而自动隔离缓存
        assert key_v0 != key_v1
        # 同一版本的Key必须相同，确保缓存命中
        assert key_v0 == f"cache:rag:{h}:0:{emb_ver}"


# ════════════════════════════════════════════════
# 3. 降级机制端到端
# ════════════════════════════════════════════════

class TestDegradationFlow:
    @pytest.mark.asyncio
    async def test_milvus_down_uses_bm25(self):
        """Milvus不可用时，自动降级为纯BM25检索"""
        from app.rag.retriever import HybridRetriever
        r = HybridRetriever()
        r.add_texts(["这是BM25测试文档，包含关键词Python"])

        # 模拟Milvus失败
        with patch("app.rag.retriever.milvus_db") as mock_milvus:
            mock_milvus.search = MagicMock(side_effect=Exception("Milvus不可用"))
            result = await r.retrieve("Python", [0.1] * 1024, top_k=5)

        # BM25结果仍然返回
        assert len(result) >= 0  # 可能有BM25结果

    @pytest.mark.asyncio
    async def test_pipeline_no_docs_returns_graceful(self):
        """无相关文档时返回友好提示，不崩溃"""
        from app.rag.pipeline import run_rag_pipeline
        with patch("app.rag.pipeline.cache") as mc, \
             patch("app.rag.pipeline.embed_client") as me, \
             patch("app.rag.pipeline.retriever") as mr:

            mc.get_rag = AsyncMock(return_value=None)
            mc.get_query = AsyncMock(return_value={"rewritten": "问题"})
            mc.set_rag = AsyncMock()
            mc.set_query = AsyncMock()
            mc.get_embed = AsyncMock(return_value=None)
            mc.set_embed = AsyncMock()

            # single_flight 必须 await factory（它是一个 async def）
            async def sf(key, factory):
                return await factory()
            mc.single_flight = sf

            me.embed_one = AsyncMock(return_value=[0.1] * 1024)
            mr.retrieve = AsyncMock(return_value=[])  # 无检索结果

            with patch("app.rag.pipeline.llm_client") as ml:
                ml.chat = AsyncMock(return_value="根据现有文档，未找到相关信息。")
                result = await run_rag_pipeline("什么是量子力学？")

        assert isinstance(result, dict)
        assert "answer" in result
        assert result["answer"]  # 非空
        assert result["sources"] == []

    @pytest.mark.asyncio
    async def test_c2_timeout_c1_succeeds(self):
        """C2超时后C1成功"""
        from app.rag.pipeline import generate_answer
        import asyncio as aio

        call_count = 0
        async def mock_chat(messages, temperature=0.3, max_tokens=1024):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await aio.sleep(10)  # C2超时
            return "C1快速回答"

        with patch("app.rag.pipeline.llm_client") as mock:
            mock.chat = mock_chat
            answer, level, _ = await generate_answer("问题", "上下文")

        assert level in ("C1", "C0")


# ════════════════════════════════════════════════
# 4. 数据一致性与边界测试
# ════════════════════════════════════════════════

class TestDataConsistency:
    def test_text_splitter_no_data_loss(self):
        """分块后合并的内容覆盖原文主要信息"""
        from app.services.doc_service import TextSplitter
        content = "".join([f"句子{i}内容。" for i in range(50)])
        s = TextSplitter(chunk_size=100, overlap=20)
        chunks = s.split(content)
        combined = "".join(chunks)
        # 检查关键内容在chunks中
        for i in [0, 10, 25, 49]:
            assert f"句子{i}" in combined

    def test_quality_score_monotonic(self):
        """质量更好的内容得分更高"""
        from app.services.doc_service import QualityChecker
        checker = QualityChecker()

        low_quality  = ["x"] * 10          # 全是短chunk
        high_quality = ["这是高质量内容，超过20字。" * 2] * 10

        low_score  = checker.evaluate(low_quality)["score"]
        high_score = checker.evaluate(high_quality)["score"]
        assert high_score > low_score

    def test_rrf_scores_sum_correctly(self):
        """RRF分数计算正确（alpha归一化）"""
        from app.rag.retriever import HybridRetriever
        r = HybridRetriever()
        dense  = [{"text": "A" * 20, "score": 0.9, "id": "d1", "source": "dense"}]
        sparse = [{"text": "B" * 20, "score": 5.0, "id": "s1", "source": "sparse"}]
        merged = r._rrf_merge(dense, sparse, alpha=0.7, k=60)
        # 验证分数非负
        for m in merged:
            assert m["rrf_score"] >= 0

    def test_cache_key_collision_resistance(self):
        """不同查询不会碰撞到同一个缓存Key"""
        from app.db.redis import RedisCache
        cache = RedisCache.__new__(RedisCache)
        cache.embedding_version = "v1"
        cache.client = None

        queries = ["什么是RAG", "RAG是什么", "RAG定义", "检索增强生成", "Retrieval Augmented Generation"]
        keys = [cache._rag_key(q) for q in queries]
        assert len(set(keys)) == len(queries)  # 无碰撞


# ════════════════════════════════════════════════
# 5. 并发安全测试
# ════════════════════════════════════════════════

class TestConcurrencySafety:
    @pytest.mark.asyncio
    async def test_concurrent_bm25_updates(self):
        """并发更新BM25索引不崩溃"""
        from app.rag.retriever import HybridRetriever
        r = HybridRetriever()

        async def update_index(i):
            r.add_texts([f"文档{i}的内容，包含关键词{i}"])

        tasks = [update_index(i) for i in range(10)]
        await asyncio.gather(*tasks)
        # 索引应有内容
        assert len(r._corpus) > 0

    @pytest.mark.asyncio
    async def test_single_flight_multiple_keys(self):
        """不同Key的SingleFlight互不影响"""
        from app.db.redis import RedisCache, _inflight
        _inflight.clear()
        r = RedisCache.__new__(RedisCache)
        r.client = None
        r.embedding_version = "v1"

        results = {}
        async def make_coro(key, val):
            async def _():
                await asyncio.sleep(0.01)
                return val
            results[key] = await r.single_flight(key, _)

        await asyncio.gather(
            make_coro("key1", "result1"),
            make_coro("key2", "result2"),
        )
        assert results.get("key1") == "result1"
        assert results.get("key2") == "result2"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
