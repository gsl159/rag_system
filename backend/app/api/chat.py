"""
/chat 路由 — 同步查询 + SSE 流式
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.db.postgres import get_db, QueryLog
from app.rag.pipeline import run_rag_pipeline, run_rag_stream
from app.services.eval_service import eval_service

router = APIRouter(prefix="/chat", tags=["RAG 查询"])


class ChatRequest(BaseModel):
    question:   str
    session_id: str | None = None


@router.post("/")
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    """同步 RAG 查询，返回完整结果"""
    if not req.question.strip():
        raise HTTPException(400, "问题不能为空")

    try:
        result = await run_rag_pipeline(req.question)
    except Exception as e:
        logger.error(f"RAG 执行失败: {e}")
        raise HTTPException(500, f"查询失败: {str(e)}")

    # 写查询日志
    log = QueryLog(
        session_id      = req.session_id,
        original_query  = req.question,
        rewritten_query = result.get("rewritten_query"),
        answer          = result["answer"],
        context         = (result.get("context") or "")[:2000],
        latency_ms      = result["latency_ms"],
        cache_hit       = result["cache_hit"],
    )
    db.add(log)
    await db.flush()

    # 异步评估（不阻塞响应）
    if not result["cache_hit"]:
        try:
            await eval_service.evaluate(
                query   = req.question,
                answer  = result["answer"],
                context = result.get("context", ""),
                log_id  = log.id,
                db      = db,
            )
        except Exception as e:
            logger.warning(f"评估写入失败: {e}")

    await db.commit()

    return {
        "answer":          result["answer"],
        "rewritten_query": result.get("rewritten_query"),
        "sources":         result.get("sources", []),
        "latency_ms":      result["latency_ms"],
        "cache_hit":       result["cache_hit"],
        "log_id":          log.id,
    }


@router.get("/stream")
async def chat_stream(question: str):
    """SSE 流式输出"""
    if not question.strip():
        raise HTTPException(400, "问题不能为空")

    async def gen():
        try:
            async for token in run_rag_stream(question):
                yield f"data: {token}\n\n"
        except Exception as e:
            yield f"data: [ERROR] {e}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
