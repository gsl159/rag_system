"""
Reranker — Cross-Encoder 重排（API 形态）

调用兼容 OpenAI 协议的 /rerank 接口（如硅基流动 BAAI/bge-reranker-v2-m3），
以 Cross-Encoder 方式对 query-passage 对精排，效果显著优于关键词覆盖。
失败时回退为 RRF 分数原序，保证主流程不中断。
"""
from typing import List, Dict, Any

import httpx

from app.core.config import settings
from app.core.logger import logger


class CrossEncoderReranker:
    """基于 /rerank API 的 Cross-Encoder 精排"""

    def __init__(self):
        self.base_url = settings.SILICONFLOW_BASE_URL
        self.api_key  = settings.SILICONFLOW_API_KEY
        self.model    = settings.RERANK_MODEL

    async def rerank(
        self,
        query: str,
        docs:  List[Dict[str, Any]],
        top_n: int = 5,
    ) -> List[Dict[str, Any]]:
        if not docs:
            return []
        if len(docs) <= top_n:
            return docs

        payload = {
            "model": self.model,
            "query": query,
            "documents": [d.get("text", "") for d in docs],
            "top_n": top_n,
            "return_documents": False,
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.base_url}/rerank",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])

            reranked = []
            for item in results:
                idx = item.get("index")
                if idx is None or idx >= len(docs):
                    continue
                doc = dict(docs[idx])
                doc["rerank_score"] = float(item.get("relevance_score", 0.0))
                reranked.append(doc)
            if reranked:
                logger.debug(f"Rerank 完成，top_n={top_n}")
                return reranked[:top_n]
        except Exception as e:
            logger.warning(f"Rerank API 失败，回退原序: {e}")

        # 回退：按已有 RRF/混合分数排序
        return sorted(docs, key=lambda d: d.get("score", 0), reverse=True)[:top_n]


reranker = CrossEncoderReranker()
