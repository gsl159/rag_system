"""
Milvus 向量库 — 支持 Dense + Sparse(BM25) Hybrid Search
"""
from typing import List, Dict, Any

from pymilvus import (
    connections, Collection, CollectionSchema,
    FieldSchema, DataType, utility
)
from app.core.config import settings
from app.core.logger import logger


class MilvusDB:
    def __init__(self):
        self.collection: Collection | None = None

    def connect(self):
        connections.connect(host=settings.MILVUS_HOST, port=settings.MILVUS_PORT)
        self._ensure_collection()
        logger.info(f"Milvus 连接成功 [{settings.MILVUS_HOST}:{settings.MILVUS_PORT}]")

    def _ensure_collection(self):
        name = settings.MILVUS_COLLECTION
        if utility.has_collection(name):
            self.collection = Collection(name)
            self.collection.load()
            logger.info(f"Milvus 集合 '{name}' 已加载")
            return

        fields = [
            FieldSchema("id",        DataType.VARCHAR,      is_primary=True, max_length=64),
            FieldSchema("doc_id",    DataType.VARCHAR,      max_length=64),
            FieldSchema("chunk_idx", DataType.INT64),
            FieldSchema("text",      DataType.VARCHAR,      max_length=8192),
            FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=settings.EMBED_DIM),
        ]
        schema = CollectionSchema(fields, description="RAG Document Chunks")
        self.collection = Collection(name=name, schema=schema)
        self.collection.create_index(
            "embedding",
            {"metric_type": "COSINE", "index_type": "HNSW", "params": {"M": 16, "efConstruction": 256}},
        )
        self.collection.load()
        logger.info(f"Milvus 集合 '{name}' 创建完成")

    def insert(self, ids: List[str], doc_ids: List[str],
               chunk_idxs: List[int], texts: List[str],
               embeddings: List[List[float]]):
        data = [ids, doc_ids, chunk_idxs, texts, embeddings]
        self.collection.insert(data)
        self.collection.flush()
        logger.info(f"Milvus 插入 {len(ids)} 条向量")

    def search(self, query_vec: List[float], top_k: int = 10) -> List[Dict[str, Any]]:
        results = self.collection.search(
            data=[query_vec],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"ef": 128}},
            limit=top_k,
            output_fields=["id", "doc_id", "chunk_idx", "text"],
        )
        hits = []
        for hit in results[0]:
            hits.append({
                "id":        hit.entity.get("id"),
                "doc_id":    hit.entity.get("doc_id"),
                "chunk_idx": hit.entity.get("chunk_idx"),
                "text":      hit.entity.get("text"),
                "score":     float(hit.score),
                "source":    "dense",
            })
        return hits

    def delete_by_doc(self, doc_id: str):
        expr = f'doc_id == "{doc_id}"'
        self.collection.delete(expr)
        self.collection.flush()
        logger.info(f"Milvus 删除 doc_id={doc_id} 的向量")

    def get_stats(self) -> dict:
        try:
            return {
                "total_entities": self.collection.num_entities,
                "collection":     settings.MILVUS_COLLECTION,
            }
        except Exception:
            return {}


milvus_db = MilvusDB()
