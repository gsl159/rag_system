"""
Milvus 向量库 — Milvus 2.5 原生 Hybrid Search

- Dense  : FLOAT_VECTOR + HNSW(COSINE)
- Sparse : SPARSE_FLOAT_VECTOR + BM25 Function（原生全文检索，分布式共享）
- 融合   : WeightedRanker（Dense/Sparse 加权）
- 隔离   : tenant_id 标量字段，检索强制拼接租户过滤条件

所有对 Milvus 的 IO 均通过 asyncio.to_thread 执行，避免阻塞事件循环。
"""
import asyncio
from typing import List, Dict, Any, Optional

from pymilvus import (
    MilvusClient, DataType, Function, FunctionType,
    AnnSearchRequest, WeightedRanker,
)
from app.core.config import settings
from app.core.logger import logger


class MilvusDB:
    def __init__(self):
        self.client: Optional[MilvusClient] = None
        self.collection: str = settings.MILVUS_COLLECTION

    # ── 连接与集合管理 ────────────────────────────

    def _connect_sync(self):
        uri = f"http://{settings.MILVUS_HOST}:{settings.MILVUS_PORT}"
        self.client = MilvusClient(uri=uri)
        self._ensure_collection()
        logger.info(f"Milvus 连接成功 [{uri}]")

    async def connect(self):
        await asyncio.to_thread(self._connect_sync)

    def _ensure_collection(self):
        name = self.collection
        if self.client.has_collection(name):
            self.client.load_collection(name)
            logger.info(f"Milvus 集合 '{name}' 已加载")
            return

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id",        DataType.VARCHAR,             is_primary=True, max_length=64)
        schema.add_field("doc_id",    DataType.VARCHAR,             max_length=64)
        schema.add_field("tenant_id", DataType.VARCHAR,             max_length=64)
        schema.add_field("chunk_idx", DataType.INT64)
        # 开启 analyzer 与 match，供 BM25 Function 自动分词并生成稀疏向量
        schema.add_field("text",      DataType.VARCHAR,             max_length=8192,
                         enable_analyzer=True, enable_match=True)
        schema.add_field("embedding", DataType.FLOAT_VECTOR,        dim=settings.EMBED_DIM)
        schema.add_field("sparse",    DataType.SPARSE_FLOAT_VECTOR)

        # BM25 Function：text -> sparse，由 Milvus 内部维护 TF/IDF
        schema.add_function(Function(
            name="bm25",
            function_type=FunctionType.BM25,
            input_field_names=["text"],
            output_field_names="sparse",
        ))

        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="embedding", index_name="dense_idx",
            index_type="HNSW", metric_type="COSINE",
            params={"M": 16, "efConstruction": 256},
        )
        index_params.add_index(
            field_name="sparse", index_name="sparse_idx",
            index_type="SPARSE_INVERTED_INDEX", metric_type="BM25",
        )

        self.client.create_collection(name, schema=schema, index_params=index_params)
        self.client.load_collection(name)
        logger.info(f"Milvus 集合 '{name}' 创建完成（Dense + Sparse/BM25）")

    # ── 写入 ──────────────────────────────────────

    def _insert_sync(self, rows: List[dict]):
        self.client.insert(collection_name=self.collection, data=rows)
        # 使数据对检索可见
        self.client.flush(self.collection)

    async def insert(self, ids: List[str], doc_ids: List[str], tenant_ids: List[str],
                     chunk_idxs: List[int], texts: List[str],
                     embeddings: List[List[float]]):
        rows = [
            {
                "id":        ids[i],
                "doc_id":    doc_ids[i],
                "tenant_id": tenant_ids[i],
                "chunk_idx": chunk_idxs[i],
                "text":      texts[i],
                "embedding": embeddings[i],
            }
            for i in range(len(ids))
        ]
        await asyncio.to_thread(self._insert_sync, rows)
        logger.info(f"Milvus 插入 {len(ids)} 条向量")

    # ── 检索 ──────────────────────────────────────

    @staticmethod
    def _tenant_expr(tenant_id: Optional[str]) -> Optional[str]:
        if not tenant_id:
            return None
        escaped = tenant_id.replace('"', '\\"')
        return f'tenant_id == "{escaped}"'

    def _hybrid_search_sync(self, query_vec: List[float], query_text: str,
                            top_k: int, tenant_id: Optional[str]) -> List[Dict[str, Any]]:
        alpha = settings.HYBRID_ALPHA
        reqs = [
            AnnSearchRequest(
                data=[query_vec], anns_field="embedding",
                param={"metric_type": "COSINE"},
                limit=top_k,
            ),
            # Sparse 直接传原始文本，由 Milvus 内置 BM25 处理
            AnnSearchRequest(
                data=[query_text], anns_field="sparse",
                param={"metric_type": "BM25"},
                limit=top_k,
            ),
        ]
        results = self.client.hybrid_search(
            collection_name=self.collection,
            reqs=reqs,
            ranker=WeightedRanker(alpha, round(1 - alpha, 4)),
            limit=top_k,
            filter=self._tenant_expr(tenant_id),
            output_fields=["id", "doc_id", "tenant_id", "chunk_idx", "text"],
        )
        hits = []
        for hit in results[0]:
            ent = hit.get("entity", {})
            hits.append({
                "id":        ent.get("id"),
                "doc_id":    ent.get("doc_id"),
                "tenant_id": ent.get("tenant_id"),
                "chunk_idx": ent.get("chunk_idx"),
                "text":      ent.get("text"),
                "score":     float(hit.get("distance", 0.0)),
                "source":    "hybrid",
            })
        return hits

    async def hybrid_search(self, query_vec: List[float], query_text: str,
                            top_k: int = 10, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(
            self._hybrid_search_sync, query_vec, query_text, top_k, tenant_id
        )

    # ── 删除 ──────────────────────────────────────

    def _delete_sync(self, expr: str):
        self.client.delete(collection_name=self.collection, filter=expr)
        self.client.flush(self.collection)

    async def delete_by_doc(self, doc_id: str, tenant_id: Optional[str] = None):
        expr = f'doc_id == "{doc_id}"'
        t_expr = self._tenant_expr(tenant_id)
        if t_expr:
            expr = f"({expr}) and ({t_expr})"
        await asyncio.to_thread(self._delete_sync, expr)
        logger.info(f"Milvus 删除 doc_id={doc_id} 的向量")

    # ── 统计 ──────────────────────────────────────

    def _stats_sync(self) -> dict:
        try:
            stats = self.client.get_collection_stats(self.collection)
            return {"total_entities": int(stats.get("row_count", 0)), "collection": self.collection}
        except Exception as e:
            logger.warning(f"Milvus stats 失败: {e}")
            return {}

    async def get_stats(self) -> dict:
        return await asyncio.to_thread(self._stats_sync)


milvus_db = MilvusDB()
