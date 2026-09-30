"""
检索模块 — Hybrid Search

Dense + Sparse(BM25) 的召回与 RRF/加权融合均在 Milvus 2.5 内部完成
（见 app/db/milvus.py），因此本模块不再维护进程内 BM25 索引：
- 多实例天然共享同一份索引（分布式）
- 服务重启无需重建
- 检索强制拼接 tenant_id 过滤条件，实现租户隔离
"""
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.core.logger import logger
from app.db.milvus import milvus_db


class HybridRetriever:
    """混合检索：Dense + Sparse(BM25)，融合下沉至 Milvus"""

    async def retrieve(
        self,
        query: str,
        query_vec: List[float],
        top_k: int = None,
        tenant_id: Optional[str] = None,
    ) -> List[Dict]:
        top_k = top_k or settings.TOP_K
        hits = await milvus_db.hybrid_search(
            query_vec=query_vec,
            query_text=query,
            top_k=top_k,
            tenant_id=tenant_id,
        )
        logger.debug(f"混合检索完成: query='{query[:30]}' tenant={tenant_id} hits={len(hits)}")
        return hits


retriever = HybridRetriever()
