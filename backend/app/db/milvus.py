"""
Milvus 向量库 — 支持 Dense HNSW 检索
修复：连接状态检查、安全删除、graceful degradation
"""
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.core.logger import logger


class MilvusDB:
    def __init__(self):
        self._connected = False
        self._collection = None

    def connect(self):
        try:
            from pymilvus import connections, Collection, CollectionSchema, FieldSchema, DataType, utility
            connections.connect(
                alias="default",
                host=settings.MILVUS_HOST,
                port=settings.MILVUS_PORT,
                timeout=10,
            )
            self._ensure_collection()
            self._connected = True
            logger.info(f"Milvus 连接成功 [{settings.MILVUS_HOST}:{settings.MILVUS_PORT}]")
        except Exception as e:
            logger.error(f"Milvus 连接失败: {e}")
            self._connected = False

    def _ensure_collection(self):
        from pymilvus import Collection, CollectionSchema, FieldSchema, DataType, utility
        name = settings.MILVUS_COLLECTION
        if utility.has_collection(name):
            self._collection = Collection(name)
            self._collection.load()
            logger.info(f"Milvus 集合 '{name}' 已加载，共 {self._collection.num_entities} 条")
            return

        fields = [
            FieldSchema("id",        DataType.VARCHAR,      is_primary=True, max_length=64),
            FieldSchema("doc_id",    DataType.VARCHAR,      max_length=64),
            FieldSchema("chunk_idx", DataType.INT64),
            FieldSchema("text",      DataType.VARCHAR,      max_length=8192),
            FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=settings.EMBED_DIM),
        ]
        schema = CollectionSchema(fields, description="RAG Document Chunks")
        self._collection = Collection(name=name, schema=schema)
        self._collection.create_index(
            "embedding",
            {
                "metric_type": "COSINE",
                "index_type":  "HNSW",
                "params":      {"M": 16, "efConstruction": 256},
            },
        )
        self._collection.load()
        logger.info(f"Milvus 集合 '{name}' 创建完成")

    def insert(self, ids: List[str], doc_ids: List[str],
               chunk_idxs: List[int], texts: List[str],
               embeddings: List[List[float]]):
        if not self._connected or self._collection is None:
            raise RuntimeError("Milvus 未连接")
        # 截断超长 text
        safe_texts = [t[:8000] if len(t) > 8000 else t for t in texts]
        data = [ids, doc_ids, chunk_idxs, safe_texts, embeddings]
        self._collection.insert(data)
        self._collection.flush()
        logger.info(f"Milvus 插入 {len(ids)} 条向量")

    def search(self, query_vec: List[float], top_k: int = 10) -> List[Dict[str, Any]]:
        if not self._connected or self._collection is None:
            logger.warning("Milvus 未连接，返回空检索结果")
            return []
        try:
            results = self._collection.search(
                data       = [query_vec],
                anns_field = "embedding",
                param      = {"metric_type": "COSINE", "params": {"ef": 128}},
                limit      = top_k,
                output_fields = ["id", "doc_id", "chunk_idx", "text"],
            )
            hits = []
            for hit in results[0]:
                hits.append({
                    "id":        hit.entity.get("id"),
                    "doc_id":    hit.entity.get("doc_id"),
                    "chunk_idx": hit.entity.get("chunk_idx"),
                    "text":      hit.entity.get("text") or "",
                    "score":     float(hit.score),
                    "source":    "dense",
                })
            return hits
        except Exception as e:
            logger.error(f"Milvus search 失败: {e}")
            return []

    def delete_by_doc(self, doc_id: str):
        if not self._connected or self._collection is None:
            logger.warning("Milvus 未连接，跳过删除")
            return
        try:
            expr = f'doc_id == "{doc_id}"'
            self._collection.delete(expr)
            self._collection.flush()
            logger.info(f"Milvus 删除 doc_id={doc_id}")
        except Exception as e:
            logger.error(f"Milvus 删除失败: {e}")

    def get_stats(self) -> dict:
        try:
            if self._connected and self._collection:
                return {
                    "total_entities": self._collection.num_entities,
                    "collection":     settings.MILVUS_COLLECTION,
                    "connected":      True,
                }
        except Exception:
            pass
        return {"total_entities": 0, "collection": settings.MILVUS_COLLECTION, "connected": False}

    @property
    def is_connected(self) -> bool:
        return self._connected


milvus_db = MilvusDB()
