"""
RAG Pipeline — 完整生产版
含：意图分类、置信度计算、LLM自评分、结构化日志、硬超时降级
"""
import asyncio
import hashlib
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.logger import logger
from app.core.llm import llm_client, embed_client
from app.db.redis import cache
from app.rag.retriever import retriever
from app.rag.reranker import simple_reranker


# ── 意图分类 ─────────────────────────────────

async def classify_intent(query: str) -> str:
    """
    C0 = FAQ/简单/可缓存
    C1 = 轻量总结
    C2 = 复杂生成
    """
    q = query.strip()
    # 短问题或含关键词 → C0
    if len(q) < 15 or any(kw in q for kw in ["是什么", "定义", "什么叫", "怎么读"]):
        return "C0"
    # 中等长度 → C1
    if len(q) < 40:
        return "C1"
    return "C2"


# ── Query 改写 ────────────────────────────────

async def rewrite_query(query: str) -> str:
    prompt = (
        "你是检索优化专家。将用户问题改写为更适合信息检索的形式，只返回改写后的问题，不要解释。\n"
        f"原始问题：{query}\n改写后："
    )
    try:
        result = await asyncio.wait_for(
            llm_client.chat([{"role": "user", "content": prompt}], temperature=0, max_tokens=200),
            timeout=3.0,
        )
        return result.strip() or query
    except Exception:
        return query


# ── Embedding（带缓存）────────────────────────

async def get_embedding(text: str) -> List[float]:
    cached = await cache.get_embed(text)
    if cached:
        return cached
    vec = await embed_client.embed_one(text)
    await cache.set_embed(text, vec)
    return vec


# ── Context Builder ───────────────────────────

def build_context(docs: List[Dict], max_chars: int = 3000) -> str:
    if not docs:
        return ""
    parts, total = [], 0
    for i, doc in enumerate(docs):
        text = (doc.get("text") or "").strip()
        if not text:
            continue
        if total + len(text) > max_chars:
            remaining = max_chars - total
            if remaining > 100:
                parts.append(f"[来源{i+1}]\n{text[:remaining]}")
            break
        parts.append(f"[来源{i+1}]\n{text}")
        total += len(text)
    return "\n\n---\n\n".join(parts)


# ── LLM Generate（硬超时 + 降级）────────────

SYSTEM_PROMPT = """你是企业知识库问答助手，必须基于提供的资料回答问题。

规则：
1. 不允许编造，只能基于资料中的信息作答
2. 找不到相关信息时，明确说"根据现有文档，未找到相关信息"
3. 必须在回答末尾注明引用来源，格式：【来源：[来源N]】
4. 回答简洁、准确、有条理"""


async def generate_answer(query: str, context: str, intent: str = "C2") -> Tuple[str, str, str]:
    """返回 (answer, degrade_level, degrade_reason)"""
    if not context:
        return "根据现有文档，未找到相关信息。请上传相关文档后再试。", "C0", "NO_CONTEXT"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"【参考资料】\n{context}\n\n【问题】\n{query}"},
    ]

    # C2 完整生成（3s）
    try:
        answer = await asyncio.wait_for(
            llm_client.chat(messages, temperature=0.3, max_tokens=1024), timeout=3.0
        )
        return answer, "C2", ""
    except asyncio.TimeoutError:
        logger.warning("C2 超时，降级 C1")

    # C1 轻量（1.5s）
    try:
        c1_msg = [
            {"role": "system", "content": "你是知识助手，请基于资料简洁回答（100字以内），并注明来源。"},
            {"role": "user", "content": f"资料：{context[:800]}\n问题：{query}"},
        ]
        answer = await asyncio.wait_for(
            llm_client.chat(c1_msg, temperature=0, max_tokens=300), timeout=1.5
        )
        return answer, "C1", "C2_TIMEOUT"
    except asyncio.TimeoutError:
        logger.warning("C1 超时，降级 C0")

    # C0 返回原始片段
    snippet = context[:400]
    return f"根据文档片段（响应超时，仅返回摘要）：\n\n{snippet}…", "C0", "LLM_TIMEOUT"


# ── LLM 自评分 ────────────────────────────────

async def llm_self_score(query: str, answer: str) -> float:
    """让 LLM 对自己的回答打分（0~1）"""
    try:
        prompt = (
            f"请对以下回答的质量打分（0到1之间的小数，只输出数字，不要其他内容）：\n"
            f"问题：{query}\n回答：{answer[:300]}\n分数："
        )
        result = await asyncio.wait_for(
            llm_client.chat([{"role": "user", "content": prompt}], temperature=0, max_tokens=10),
            timeout=2.0,
        )
        return max(0.0, min(1.0, float(result.strip())))
    except Exception:
        return 0.5


# ── 置信度计算 ────────────────────────────────

def calc_confidence(top_docs: List[Dict], embedding_sim: float, llm_score: float) -> float:
    """
    confidence = 0.5×rerank_avg + 0.3×embedding_sim + 0.2×llm_self_score
    """
    if not top_docs:
        return 0.0
    rerank_scores = [d.get("rerank_score", 0) for d in top_docs]
    rerank_avg = sum(rerank_scores) / len(rerank_scores) if rerank_scores else 0
    # rerank_score 原始值范围不固定，归一化到 0~1
    rerank_norm = min(rerank_avg / 10.0, 1.0)  # LLMReranker 用 0-10 分
    conf = 0.5 * rerank_norm + 0.3 * embedding_sim + 0.2 * llm_score
    return round(min(conf, 1.0), 3)


# ── 完整 Pipeline ─────────────────────────────

async def run_rag_pipeline(
    query: str,
    doc_version: int = 0,
    session_id: str = None,
    user_id: str = None,
    trace_id: str = "",
) -> Dict[str, Any]:
    t0 = time.time()

    # Layer-3 RAG 缓存
    cached = await cache.get_rag(query, doc_version)
    if cached:
        cached["cache_hit"]  = True
        cached["latency_ms"] = int((time.time() - t0) * 1000)
        return cached

    # SingleFlight 防风暴
    sf_key = f"sf:{hashlib.md5(query.encode()).hexdigest()}"

    async def _do():
        return await _run_internal(query, doc_version, t0, trace_id)

    try:
        result = await cache.single_flight(sf_key, _do)
        if result is None:
            result = await _do()
        return result
    except Exception as e:
        logger.error(f"[{trace_id}] RAG pipeline 异常: {e}")
        return {
            "answer": "系统暂时繁忙，请稍后重试。",
            "sources": [], "context": "", "confidence": 0.0,
            "rewritten_query": query, "intent": "C0",
            "cache_hit": False, "latency_ms": int((time.time() - t0) * 1000),
            "degrade_level": "C0", "degrade_reason": "SYSTEM_ERROR",
        }


async def _run_internal(query: str, doc_version: int, t0: float, trace_id: str) -> Dict[str, Any]:
    # 意图分类
    intent = await classify_intent(query)

    # Query 缓存
    q_cached = await cache.get_query(query, doc_version)
    rewritten = q_cached.get("rewritten", query) if q_cached else await rewrite_query(query)
    if not q_cached:
        await cache.set_query(query, {"rewritten": rewritten}, doc_version)

    # Embedding
    t_ret_start = time.time()
    try:
        query_vec = await get_embedding(rewritten)
    except Exception as e:
        logger.error(f"[{trace_id}] Embedding 失败: {e}")
        return {
            "answer": "向量化服务暂时不可用。", "sources": [], "context": "",
            "confidence": 0.0, "rewritten_query": rewritten, "intent": intent,
            "cache_hit": False, "latency_ms": int((time.time() - t0) * 1000),
            "degrade_level": "C0", "degrade_reason": "EMBED_FAIL",
        }

    # 检索
    try:
        docs = await retriever.retrieve(rewritten, query_vec, top_k=settings.TOP_K)
    except Exception as e:
        logger.error(f"[{trace_id}] 检索失败: {e}")
        docs = []
    retrieval_ms = int((time.time() - t_ret_start) * 1000)

    # Rerank
    top_docs = simple_reranker.rerank(rewritten, docs, top_n=settings.RERANK_TOP_N)
    context  = build_context(top_docs)

    # Embedding 相似度均值（用于置信度）
    emb_sim = float(top_docs[0].get("score", 0)) if top_docs else 0.0

    # LLM 生成
    t_llm_start = time.time()
    answer, degrade_level, degrade_reason = await generate_answer(rewritten, context, intent)
    llm_ms = int((time.time() - t_llm_start) * 1000)

    # LLM 自评分（异步，不阻塞）
    self_score = 0.5
    try:
        self_score = await asyncio.wait_for(llm_self_score(query, answer), timeout=2.5)
    except Exception:
        pass

    # 置信度
    confidence = calc_confidence(top_docs, emb_sim, self_score)

    latency = int((time.time() - t0) * 1000)

    result = {
        "answer":          answer,
        "context":         context,
        "sources": [
            {
                "text":         d.get("text", "")[:200],
                "score":        round(d.get("rerank_score", 0), 4),
                "doc_id":       d.get("doc_id", ""),
                "chunk_idx":    d.get("chunk_idx", 0),
            }
            for d in top_docs
        ],
        "rewritten_query": rewritten,
        "intent":          intent,
        "confidence":      confidence,
        "cache_hit":       False,
        "latency_ms":      latency,
        "retrieval_ms":    retrieval_ms,
        "llm_ms":          llm_ms,
        "degrade_level":   degrade_level,
        "degrade_reason":  degrade_reason,
    }

    await cache.set_rag(query, result, doc_version)
    logger.info(
        f"[{trace_id}] RAG完成 intent={intent} latency={latency}ms "
        f"ret={retrieval_ms}ms llm={llm_ms}ms conf={confidence} degrade={degrade_level}"
    )
    return result


async def run_rag_stream(query: str, trace_id: str = "") -> AsyncGenerator[str, None]:
    try:
        intent   = await classify_intent(query)
        rewritten = await rewrite_query(query)
        query_vec = await get_embedding(rewritten)
        docs      = await retriever.retrieve(rewritten, query_vec)
        top_docs  = simple_reranker.rerank(rewritten, docs, top_n=settings.RERANK_TOP_N)
        context   = build_context(top_docs)

        if not context:
            yield "根据现有文档，未找到相关信息。请上传相关文档后再试。"
            return

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"【参考资料】\n{context}\n\n【问题】\n{query}"},
        ]
        async for token in llm_client.stream(messages):
            yield token
    except Exception as e:
        logger.error(f"[{trace_id}] 流式RAG失败: {e}")
        yield f"抱歉，处理时发生错误。"
