"""
Reranker — LLM 交叉编码重排 + 简单关键词重排
"""
import asyncio
from typing import List, Dict, Any

from app.core.llm import llm_client
from app.core.logger import logger


class LLMReranker:
    """用 LLM 对每个 passage 打相关性分，取 top_n"""

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

        passages = "\n".join(
            f"[{i}] {(d.get('text') or '')[:300]}" for i, d in enumerate(docs)
        )
        prompt = f"""你是一个检索相关性评分专家。
请对以下每个段落与用户问题的相关性进行打分（0-10分），并以 JSON 返回。

用户问题：{query}

候选段落：
{passages}

请严格按如下 JSON 格式返回（不要有任何额外文字）：
{{"scores": [8, 3, 9, 2, ...]}}
其中数组长度与候选段落数量相同。"""

        try:
            result = await asyncio.wait_for(
                llm_client.chat_json([{"role": "user", "content": prompt}]),
                timeout=2.0,
            )
            scores = result.get("scores", [])
            if len(scores) == len(docs):
                ranked = sorted(
                    zip(scores, docs),
                    key=lambda x: x[0],
                    reverse=True,
                )
                reranked = [doc for _, doc in ranked[:top_n]]
                for i, (score, _) in enumerate(zip([s for s, _ in ranked[:top_n]], reranked)):
                    reranked[i]["rerank_score"] = float(score)
                logger.debug(f"Rerank 完成，top_n={top_n}")
                return reranked
        except asyncio.TimeoutError:
            logger.warning("LLM Reranker 超时，回退到简单重排")
        except Exception as e:
            logger.warning(f"Rerank 失败，回退原序: {e}")

        return docs[:top_n]


class SimpleReranker:
    """轻量 Reranker：关键词覆盖率打分（无 API 调用）"""

    def rerank(self, query: str, docs: List[Dict], top_n: int = 5) -> List[Dict]:
        if not docs:
            return []
        keywords = set(query) if query else set()
        for doc in docs:
            text     = doc.get("text") or ""
            coverage = sum(1 for kw in keywords if kw in text) / max(len(keywords), 1) if keywords else 0
            rrf      = doc.get("rrf_score", 0)
            doc["rerank_score"] = round(rrf * 0.7 + coverage * 0.3, 6)
        return sorted(docs, key=lambda d: d.get("rerank_score", 0), reverse=True)[:top_n]


reranker        = LLMReranker()
simple_reranker = SimpleReranker()
