"""
/chat 路由 — 同步查询 + SSE 流式
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import logger
from app.core.limiter import limiter
from app.db.postgres import get_db, QueryLog, get_current_tenant
from app.rag.pipeline import run_rag_pipeline, run_rag_stream
from app.services.eval_service import eval_service

router = APIRouter(prefix="/chat", tags=["RAG 查询"])


class ChatRequest(BaseModel):
    question:   str = Field(..., min_length=1, max_length=2000, description="用户问题，最长 2000 字符")
    session_id: str | None = Field(None, max_length=64)


@router.post("/")
@limiter.limit(settings.RATE_LIMIT_CHAT)
async def chat(request: Request, req: ChatRequest, db: AsyncSession = Depends(get_db)):
    """同步 RAG 查询，返回完整结果"""
    if not req.question.strip():
        raise HTTPException(400, "问题不能为空")

    tenant_id = get_current_tenant()

    try:
        result = await run_rag_pipeline(req.question, tenant_id=tenant_id)
    except Exception as e:
        logger.error(f"RAG 执行失败: {e}")
        raise HTTPException(500, f"查询失败: {str(e)}")

    # 写查询日志
    log = QueryLog(
        tenant_id       = tenant_id,
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
                tenant_id = tenant_id,
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
@limiter.limit(settings.RATE_LIMIT_CHAT)
async def chat_stream(request: Request, question: str, session_id: str | None = None,
                      db: AsyncSession = Depends(get_db)):
    """SSE 流式输出（记录查询日志，便于前端反馈绑定 log_id）"""
    if not question.strip():
        raise HTTPException(400, "问题不能为空")
    if len(question) > 2000:
        raise HTTPException(400, "问题过长（最长 2000 字符）")

    tenant_id = get_current_tenant()

    async def gen():
        collected = []
        try:
            async for token in run_rag_stream(question, tenant_id=tenant_id):
                collected.append(token)
                yield f"data: {token}\n\n"
        except Exception as e:
            logger.error(f"流式查询失败: {e}")
            yield f"data: [ERROR] {e}\n\n"
        finally:
            # 流结束写日志（含 tenant），前端可用 log_id 提交反馈
            try:
                answer = "".join(collected)
                log = QueryLog(
                    tenant_id      = tenant_id,
                    session_id     = session_id,
                    original_query = question,
                    answer         = answer,
                    cache_hit      = False,
                )
                db.add(log)
                await db.commit()
                logger.info(f"流式查询日志已写入 log_id={log.id} tenant={tenant_id}")
            except Exception as e:
                logger.warning(f"流式查询日志写入失败: {e}")
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
