"""
检索模块 — Hybrid Search（Dense Milvus + Sparse BM25）+ RRF 融合
线程安全版：BM25 索引操作加锁
"""
import threading
from typing import List, Dict, Any, Optional

from rank_bm25 import BM25Okapi
from app.config.settings import settings
from app.utils.logger import logger
from app.repository.vector_store import milvus_db


class HybridRetriever:
    """混合检索：向量召回 + BM25 → RRF 融合"""

    def __init__(self):
        self._corpus: List[str] = []
        self._bm25:   Optional[BM25Okapi] = None
        self._lock = threading.Lock()

    def add_texts(self, texts: List[str]):
        """新增文本到 BM25 索引（线程安全）"""
        with self._lock:
            self._corpus.extend(texts)
            tokenized  = [list(t) for t in self._corpus]
            self._bm25 = BM25Okapi(tokenized)
        logger.debug(f"BM25 索引更新，共 {len(self._corpus)} 条")

    def reset(self):
        with self._lock:
            self._corpus = []
            self._bm25   = None

    # ── BM25 稀疏检索 ─────────────────────────────

    def _sparse_search(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        with self._lock:
            if not self._bm25 or not self._corpus:
                return []
            scores  = self._bm25.get_scores(list(query))
            corpus  = list(self._corpus)  # 快照避免竞争

        if len(scores) == 0:
            return []

        top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [
            {
                "id":     f"bm25_{i}",
                "text":   corpus[i],
                "score":  float(scores[i]),
                "source": "sparse",
            }
            for i in top_idx if i < len(corpus) and scores[i] > 0
        ]

    # ── RRF 融合 ──────────────────────────────────

    @staticmethod
    def _rrf_merge(
        dense:  List[Dict],
        sparse: List[Dict],
        alpha:  float = None,
        k:      int   = 60,
    ) -> List[Dict]:
        alpha = alpha if alpha is not None else settings.HYBRID_RETRIEVAL_ALPHA

        scores: Dict[str, float] = {}
        texts:  Dict[str, str]   = {}
        meta:   Dict[str, dict]  = {}

        def _key(item): return (item.get("text") or "")[:100]

        for rank, item in enumerate(dense):
            key = _key(item)
            if not key:
                continue
            scores[key] = scores.get(key, 0) + alpha * (1 / (k + rank + 1))
            texts[key]  = item.get("text", "")
            meta[key]   = item

        for rank, item in enumerate(sparse):
            key = _key(item)
            if not key:
                continue
            scores[key] = scores.get(key, 0) + (1 - alpha) * (1 / (k + rank + 1))
            texts[key]  = item.get("text", "")
            if key not in meta:
                meta[key] = item

        ranked = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        result = []
        for key in ranked:
            item = dict(meta[key])
            item["rrf_score"] = round(scores[key], 6)
            item["text"]      = texts[key]
            result.append(item)
        return result

    # ── 主检索入口 ────────────────────────────────

    async def retrieve(self, query: str, query_vec: List[float], top_k: int = None) -> List[Dict]:
        top_k  = top_k or settings.TOP_K

        dense: List[Dict] = []
        try:
            dense = milvus_db.search(query_vec, top_k=top_k)
        except Exception as e:
            logger.warning(f"Milvus 检索失败（降级到纯BM25）: {e}")

        sparse = self._sparse_search(query, top_k=top_k)
        merged = self._rrf_merge(dense, sparse)
        logger.debug(f"检索结果: dense={len(dense)}, sparse={len(sparse)}, merged={len(merged)}")
        return merged[:top_k * 2]


retriever = HybridRetriever()
