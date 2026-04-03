"""
检索模块 — Hybrid Search（Dense Milvus + Sparse BM25）+ RRF 融合
"""
from typing import List, Dict, Any

from rank_bm25 import BM25Okapi
from app.core.config import settings
from app.core.logger import logger
from app.db.milvus import milvus_db


class HybridRetriever:
    """混合检索：向量召回 + BM25 → RRF 融合"""

    def __init__(self):
        self._corpus: List[str] = []
        self._bm25:   BM25Okapi | None = None

    def add_texts(self, texts: List[str]):
        """新增文本到 BM25 索引"""
        self._corpus.extend(texts)
        tokenized  = [list(t) for t in self._corpus]
        self._bm25 = BM25Okapi(tokenized)
        logger.debug(f"BM25 索引更新，共 {len(self._corpus)} 条")

    def reset(self):
        self._corpus = []
        self._bm25   = None

    # ── BM25 稀疏检索 ─────────────────────────────

    def _sparse_search(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        if not self._bm25 or not self._corpus:
            return []
        scores  = self._bm25.get_scores(list(query))
        top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [
            {
                "id":    f"bm25_{i}",
                "text":  self._corpus[i],
                "score": float(scores[i]),
                "source": "sparse",
            }
            for i in top_idx if scores[i] > 0
        ]

    # ── RRF 融合 ──────────────────────────────────

    @staticmethod
    def _rrf_merge(
        dense:  List[Dict],
        sparse: List[Dict],
        alpha:  float = 0.7,
        k:      int   = 60,
    ) -> List[Dict]:
        scores: Dict[str, float] = {}
        texts:  Dict[str, str]   = {}
        meta:   Dict[str, dict]  = {}

        def _key(item): return item["text"][:100]

        for rank, item in enumerate(dense):
            key = _key(item)
            scores[key] = scores.get(key, 0) + alpha * (1 / (k + rank + 1))
            texts[key]  = item["text"]
            meta[key]   = item

        for rank, item in enumerate(sparse):
            key = _key(item)
            scores[key] = scores.get(key, 0) + (1 - alpha) * (1 / (k + rank + 1))
            texts[key]  = item["text"]
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
        dense  = milvus_db.search(query_vec, top_k=top_k)
        sparse = self._sparse_search(query, top_k=top_k)
        merged = self._rrf_merge(dense, sparse)
        logger.debug(f"检索结果: dense={len(dense)}, sparse={len(sparse)}, merged={len(merged)}")
        return merged[:top_k * 2]


retriever = HybridRetriever()
