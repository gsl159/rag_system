"""
RAG Pipeline — 完整流程（生产加固版）
Step 1: Query Rewrite
Step 2: Embedding（带缓存）
Step 3: Hybrid Retrieve
Step 4: Rerank
Step 5: Context Build
Step 6: LLM Generate（带超时降级）
"""
import asyncio
import hashlib
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.core.config import settings
from app.core.llm import llm_client, embed_client
from app.core.logger import logger
from app.db.redis import cache
from app.rag.retriever import retriever
from app.rag.reranker import simple_reranker


# ── Step 1: Query Rewrite ─────────────────────

async def rewrite_query(query: str) -> str:
    """改写 query：纠错、扩展同义词、更明确"""
    prompt = f"""你是一个查询优化专家。请将用户问题改写成更清晰、更适合信息检索的形式。
只返回改写后的问题，不要解释。

原始问题：{query}
改写后："""
    try:
        rewritten = await asyncio.wait_for(
            llm_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=256,
            ),
            timeout=3.0,  # C1 级超时
        )
        result = rewritten.strip()
        if not result:
            return query
        logger.debug(f"Query Rewrite: '{query[:50]}' → '{result[:50]}'")
        return result
    except asyncio.TimeoutError:
        logger.warning("Query Rewrite 超时，使用原始 query")
        return query
    except Exception as e:
        logger.warning(f"Query Rewrite 失败: {e}")
        return query


# ── Step 2: Embedding（带缓存）────────────────

async def get_embedding(text: str) -> List[float]:
    """Embedding with Layer-2 cache"""
    cached = await cache.get_embed(text)
    if cached:
        return cached
    vec = await embed_client.embed_one(text)
    await cache.set_embed(text, vec)
    return vec


# ── Step 5: Context Builder ───────────────────

def build_context(docs: List[Dict], max_chars: int = 3000) -> str:
    """将检索结果拼成 context，控制总长度"""
    if not docs:
        return ""
    parts = []
    total = 0
    for i, doc in enumerate(docs):
        text = (doc.get("text") or "").strip()
        if not text:
            continue
        if total + len(text) > max_chars:
            remaining = max_chars - total
            if remaining > 100:
                parts.append(f"[片段{i+1}]\n{text[:remaining]}")
            break
        parts.append(f"[片段{i+1}]\n{text}")
        total += len(text)
    return "\n\n---\n\n".join(parts)


# ── Step 6: LLM Generate（带硬超时）──────────

SYSTEM_PROMPT = """你是一个专业的企业知识库问答助手。
请根据提供的上下文回答用户问题。
要求：
1. 只基于上下文中的信息作答
2. 如果上下文中没有足够信息，请明确说明"根据现有文档，未找到相关信息"
3. 回答要简洁、准确、有条理
4. 可以适当总结和归纳"""


async def generate_answer(
    query: str,
    context: str,
    timeout: float = 3.0,
) -> tuple[str, str]:
    """
    生成回答，带硬超时降级
    返回 (answer, degrade_level)
    degrade_level: C2/C1/C0
    """
    if not context:
        return "根据现有文档，未找到相关信息。请上传相关文档后再试。", "C0"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": f"【参考上下文】\n{context}\n\n【问题】\n{query}"},
    ]

    # C2: 完整回答（3s超时）
    try:
        answer = await asyncio.wait_for(
            llm_client.chat(messages, temperature=0.3, max_tokens=1024),
            timeout=timeout,
        )
        return answer, "C2"
    except asyncio.TimeoutError:
        logger.warning(f"C2 LLM 超时（{timeout}s），降级到 C1")

    # C1: 轻量总结（1.5s超时）
    try:
        c1_messages = [
            {"role": "system", "content": "你是知识助手，请简洁回答问题（50字以内）"},
            {"role": "user",   "content": f"问题：{query}\n资料：{context[:500]}"},
        ]
        answer = await asyncio.wait_for(
            llm_client.chat(c1_messages, temperature=0, max_tokens=200),
            timeout=1.5,
        )
        return answer, "C1"
    except asyncio.TimeoutError:
        logger.warning("C1 LLM 超时，降级到 C0（直接返回 chunk）")

    # C0: 返回原始 chunk
    return f"根据文档片段：\n{context[:300]}…\n（因响应超时，仅返回原文摘要）", "C0"


async def stream_answer(query: str, context: str) -> AsyncGenerator[str, None]:
    """流式 Pipeline"""
    if not context:
        yield "根据现有文档，未找到相关信息。请上传相关文档后再试。"
        return

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": f"【参考上下文】\n{context}\n\n【问题】\n{query}"},
    ]
    async for token in llm_client.stream(messages):
        yield token


# ── 完整 Pipeline ─────────────────────────────

async def run_rag_pipeline(query: str, doc_version: int = 0) -> Dict[str, Any]:
    """
    非流式完整 Pipeline（SingleFlight + 三层缓存）
    返回：answer, context, sources, latency_ms, cache_hit, rewritten_query, degrade_level
    """
    t0 = time.time()

    # SingleFlight key
    sf_key = f"sf:{hashlib.md5(query.encode()).hexdigest()}"

    async def _do_rag():
        return await _run_rag_internal(query, doc_version, t0)

    # Layer-3: RAG 结果缓存（含版本）
    cached = await cache.get_rag(query, doc_version)
    if cached:
        cached["cache_hit"]  = True
        cached["latency_ms"] = int((time.time() - t0) * 1000)
        logger.info(f"RAG cache HIT: '{query[:40]}'")
        return cached

    # SingleFlight 防风暴
    try:
        result = await cache.single_flight(sf_key, _do_rag)
        if result is None:
            result = await _do_rag()
        return result
    except Exception as e:
        logger.error(f"RAG pipeline 异常: {e}")
        return {
            "answer":          "系统暂时繁忙，请稍后重试。",
            "context":         "",
            "sources":         [],
            "rewritten_query": query,
            "cache_hit":       False,
            "latency_ms":      int((time.time() - t0) * 1000),
            "degrade_level":   "C0",
        }


async def _run_rag_internal(query: str, doc_version: int, t0: float) -> Dict[str, Any]:
    """RAG Pipeline 内部实现"""

    # Layer-1: Query 缓存
    query_cached = await cache.get_query(query, doc_version)
    if query_cached:
        rewritten = query_cached.get("rewritten", query)
    else:
        rewritten = await rewrite_query(query)
        await cache.set_query(query, {"rewritten": rewritten}, doc_version)

    # Embedding（Layer-2 缓存在内部）
    try:
        query_vec = await get_embedding(rewritten)
    except Exception as e:
        logger.error(f"Embedding 失败: {e}")
        return {
            "answer":          "向量化服务暂时不可用，请稍后重试。",
            "context":         "",
            "sources":         [],
            "rewritten_query": rewritten,
            "cache_hit":       False,
            "latency_ms":      int((time.time() - t0) * 1000),
            "degrade_level":   "C0",
        }

    # Hybrid Retrieve
    try:
        docs = await retriever.retrieve(rewritten, query_vec, top_k=settings.TOP_K)
    except Exception as e:
        logger.error(f"检索失败: {e}")
        docs = []

    # Rerank
    top_docs = simple_reranker.rerank(rewritten, docs, top_n=settings.RERANK_TOP_N)

    # Context
    context = build_context(top_docs)

    # Generate（硬超时 + 降级）
    answer, degrade_level = await generate_answer(rewritten, context, timeout=3.0)

    latency = int((time.time() - t0) * 1000)
    result = {
        "answer":          answer,
        "context":         context,
        "sources":         [
            {"text": d.get("text", "")[:200], "score": round(d.get("rerank_score", 0), 4)}
            for d in top_docs
        ],
        "rewritten_query": rewritten,
        "cache_hit":       False,
        "latency_ms":      latency,
        "degrade_level":   degrade_level,
    }

    # 写 Layer-3 缓存
    await cache.set_rag(query, result, doc_version)
    logger.info(f"RAG pipeline 完成, latency={latency}ms, degrade={degrade_level}")
    return result


async def run_rag_stream(query: str) -> AsyncGenerator[str, None]:
    """流式 Pipeline"""
    try:
        rewritten = await rewrite_query(query)
        query_vec = await get_embedding(rewritten)
        docs      = await retriever.retrieve(rewritten, query_vec)
        top_docs  = simple_reranker.rerank(rewritten, docs, top_n=settings.RERANK_TOP_N)
        context   = build_context(top_docs)

        async for token in stream_answer(rewritten, context):
            yield token
    except Exception as e:
        logger.error(f"流式 RAG 失败: {e}")
        yield f"抱歉，处理您的问题时发生错误：{str(e)[:100]}"
