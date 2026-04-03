"""
RAG Pipeline — 完整流程
Step 1: Query Rewrite
Step 2: Embedding（带缓存）
Step 3: Hybrid Retrieve
Step 4: Rerank
Step 5: Context Build
Step 6: LLM Generate
"""
import time
from typing import Any, AsyncGenerator, Dict, List

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
        rewritten = await llm_client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=256,
        )
        logger.debug(f"Query Rewrite: '{query}' → '{rewritten}'")
        return rewritten.strip()
    except Exception as e:
        logger.warning(f"Query Rewrite 失败，使用原始 query: {e}")
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
    parts  = []
    total  = 0
    for i, doc in enumerate(docs):
        text = doc["text"].strip()
        if total + len(text) > max_chars:
            break
        parts.append(f"[片段{i+1}]\n{text}")
        total += len(text)
    return "\n\n---\n\n".join(parts)


# ── Step 6: LLM Generate ──────────────────────

SYSTEM_PROMPT = """你是一个专业的企业知识库问答助手。
请根据提供的上下文回答用户问题。
要求：
1. 只基于上下文中的信息作答
2. 如果上下文中没有足够信息，请明确说明
3. 回答要简洁、准确、有条理
4. 可以适当总结和归纳"""


async def generate_answer(query: str, context: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": f"【参考上下文】\n{context}\n\n【问题】\n{query}"},
    ]
    return await llm_client.chat(messages, temperature=0.3, max_tokens=1024)


async def stream_answer(query: str, context: str) -> AsyncGenerator[str, None]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": f"【参考上下文】\n{context}\n\n【问题】\n{query}"},
    ]
    async for token in llm_client.stream(messages):
        yield token


# ── 完整 Pipeline ─────────────────────────────

async def run_rag_pipeline(query: str) -> Dict[str, Any]:
    """
    非流式完整 Pipeline（带三层缓存）
    返回：answer, context, sources, latency_ms, cache_hit, rewritten_query
    """
    t0 = time.time()

    # Layer-3: RAG 结果缓存
    cached = await cache.get_rag(query)
    if cached:
        cached["cache_hit"]  = True
        cached["latency_ms"] = int((time.time() - t0) * 1000)
        logger.info(f"RAG cache HIT: '{query[:40]}'")
        return cached

    # Layer-1: Query 缓存
    query_cached = await cache.get_query(query)
    rewritten = query_cached["rewritten"] if query_cached else await rewrite_query(query)
    if not query_cached:
        await cache.set_query(query, {"rewritten": rewritten})

    # Embedding
    query_vec = await get_embedding(rewritten)

    # Hybrid Retrieve
    docs = await retriever.retrieve(rewritten, query_vec, top_k=settings.TOP_K)

    # Rerank（轻量版，避免多余 API 调用）
    top_docs = simple_reranker.rerank(rewritten, docs, top_n=settings.RERANK_TOP_N)

    # Context
    context = build_context(top_docs)

    # Generate
    answer  = await generate_answer(rewritten, context)

    latency = int((time.time() - t0) * 1000)
    result  = {
        "answer":          answer,
        "context":         context,
        "sources":         [{"text": d["text"][:200], "score": d.get("rerank_score", 0)} for d in top_docs],
        "rewritten_query": rewritten,
        "cache_hit":       False,
        "latency_ms":      latency,
    }

    # 写 Layer-3 缓存
    await cache.set_rag(query, result)
    logger.info(f"RAG pipeline 完成, latency={latency}ms")
    return result


async def run_rag_stream(query: str) -> AsyncGenerator[str, None]:
    """流式 Pipeline"""
    rewritten = await rewrite_query(query)
    query_vec = await get_embedding(rewritten)
    docs      = await retriever.retrieve(rewritten, query_vec)
    top_docs  = simple_reranker.rerank(rewritten, docs, top_n=settings.RERANK_TOP_N)
    context   = build_context(top_docs)

    async for token in stream_answer(rewritten, context):
        yield token
