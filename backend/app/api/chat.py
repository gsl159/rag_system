"""
/chat 路由 — 同步 + SSE 流式，含 trace_id、限流、审计
"""
import time
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.core.response import ok
from app.core.security import get_current_user, check_rate_limit, generate_trace_id
from app.db.postgres import get_db, QueryLog, AuditLog
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
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
    _rl = Depends(check_rate_limit),
):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(400, detail={"code": 1001, "message": "问题不能为空"})
    if len(question) > 2000:
        raise HTTPException(400, detail={"code": 1001, "message": "问题过长，请控制在2000字以内"})

    trace_id = generate_trace_id()
    user_id  = user.get("sub", "anonymous")

    try:
        doc_version = await cache.get_global_doc_version()
        result = await run_rag_pipeline(
            question, doc_version=doc_version,
            session_id=req.session_id, user_id=user_id, trace_id=trace_id,
        )
    except Exception as e:
        logger.error(f"[{trace_id}] RAG 执行失败: {e}")
        raise HTTPException(500, detail={"code": 5000, "message": "查询失败，请稍后重试"})

    # 写查询日志
    log = QueryLog(
        trace_id        = trace_id,
        session_id      = req.session_id,
        user_id         = user_id,
        original_query  = question,
        rewritten_query = result.get("rewritten_query"),
        intent          = result.get("intent"),
        answer          = (result.get("answer") or "")[:2000],
        context         = (result.get("context") or "")[:2000],
        sources         = result.get("sources", []),
        confidence      = result.get("confidence", 0.0),
        latency_ms      = result.get("latency_ms"),
        retrieval_ms    = result.get("retrieval_ms"),
        llm_ms          = result.get("llm_ms"),
        cache_hit       = result.get("cache_hit", False),
        degrade_level   = result.get("degrade_level", "C2"),
        degrade_reason  = result.get("degrade_reason", ""),
    )
    db.add(log)
    db.add(AuditLog(trace_id=trace_id, user_id=user_id, action="query",
                    resource=question[:100], ip=request.client.host if request.client else None))
    try:
        await db.flush()
        log_id = log.id
        await db.commit()
    except Exception as e:
        logger.warning(f"[{trace_id}] DB写入失败: {e}")
        log_id = None

    # 后台评估（非缓存结果）
    if not result.get("cache_hit") and result.get("answer") and log_id:
        background_tasks.add_task(
            _async_evaluate, question, result.get("answer", ""),
            result.get("context", ""), log_id,
        )

    return ok({
        "answer":          result.get("answer", ""),
        "rewritten_query": result.get("rewritten_query"),
        "intent":          result.get("intent", "C2"),
        "sources":         result.get("sources", []),
        "confidence":      result.get("confidence", 0.0),
        "latency_ms":      result.get("latency_ms"),
        "cache_hit":       result.get("cache_hit", False),
        "degrade_level":   result.get("degrade_level", "C2"),
        "degrade_reason":  result.get("degrade_reason", ""),
        "log_id":          log_id,
    }, trace_id=trace_id)


async def _async_evaluate(query: str, answer: str, context: str, log_id: int):
    try:
        from app.db.postgres import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await eval_service.evaluate(query=query, answer=answer, context=context,
                                        log_id=log_id, db=db)
    except Exception as e:
        logger.warning(f"后台评估失败: {e}")


@router.get("/stream")
async def chat_stream(
    question: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    q = (question or "").strip()
    if not q:
        raise HTTPException(400, detail={"code": 1001, "message": "问题不能为空"})
    trace_id = generate_trace_id()

    async def gen():
        try:
            async for token in run_rag_stream(q, trace_id=trace_id):
                safe = token.replace("\n", "\\n")
                yield f"data: {safe}\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)[:200]}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no",
                                      "X-Trace-Id": trace_id})
