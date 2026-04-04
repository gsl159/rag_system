"""
/chat 路由 — 同步查询 + SSE 流式
支持 SingleFlight、超时降级、doc_version 版本缓存
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.db.postgres import get_db, QueryLog
from app.db.redis import cache
from app.rag.pipeline import run_rag_pipeline, run_rag_stream
from app.services.eval_service import eval_service

router = APIRouter(prefix="/chat", tags=["RAG 查询"])


class ChatRequest(BaseModel):
    question:   str
    session_id: str | None = None


@router.post("/")
async def chat(
    req: ChatRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """同步 RAG 查询，返回完整结果"""
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(400, "问题不能为空")
    if len(question) > 2000:
        raise HTTPException(400, "问题过长，请控制在2000字以内")

    try:
        doc_version = await cache.get_global_doc_version()
        result = await run_rag_pipeline(question, doc_version=doc_version)
    except Exception as e:
        logger.error(f"RAG 执行失败: {e}")
        raise HTTPException(500, f"查询失败: {str(e)[:200]}")

    # 写查询日志
    log = QueryLog(
        session_id      = req.session_id,
        original_query  = question,
        rewritten_query = result.get("rewritten_query"),
        answer          = (result.get("answer") or "")[:2000],
        context         = (result.get("context") or "")[:2000],
        latency_ms      = result.get("latency_ms"),
        cache_hit       = result.get("cache_hit", False),
        degrade_level   = result.get("degrade_level", "C2"),
    )
    db.add(log)
    try:
        await db.flush()
        log_id = log.id
    except Exception as e:
        logger.warning(f"QueryLog 写入失败: {e}")
        log_id = None

    # 异步评估（不阻塞响应，仅非缓存结果）
    if not result.get("cache_hit") and result.get("answer") and log_id:
        background_tasks.add_task(
            _async_evaluate,
            query=question,
            answer=result.get("answer", ""),
            context=result.get("context", ""),
            log_id=log_id,
        )

    try:
        await db.commit()
    except Exception as e:
        logger.warning(f"DB commit 失败: {e}")

    return {
        "answer":          result.get("answer", ""),
        "rewritten_query": result.get("rewritten_query"),
        "sources":         result.get("sources", []),
        "latency_ms":      result.get("latency_ms"),
        "cache_hit":       result.get("cache_hit", False),
        "degrade_level":   result.get("degrade_level", "C2"),
        "log_id":          log_id,
    }


async def _async_evaluate(query: str, answer: str, context: str, log_id: int):
    """后台异步评估，不影响响应速度"""
    try:
        from app.db.postgres import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await eval_service.evaluate(
                query=query, answer=answer, context=context, log_id=log_id, db=db,
            )
    except Exception as e:
        logger.warning(f"后台评估失败: {e}")


@router.get("/stream")
async def chat_stream(question: str):
    """SSE 流式输出"""
    q = (question or "").strip()
    if not q:
        raise HTTPException(400, "问题不能为空")

    async def gen():
        try:
            async for token in run_rag_stream(q):
                # SSE 格式：每个 token 单独一行
                safe_token = token.replace("\n", " ")
                yield f"data: {safe_token}\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)[:200]}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
