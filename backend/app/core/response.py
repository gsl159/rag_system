"""
统一返回结构：{code, message, data, trace_id}
"""
from typing import Any, Optional
from fastapi.responses import JSONResponse


def ok(data: Any = None, message: str = "ok", trace_id: str = "") -> dict:
    return {"code": 0, "message": message, "data": data, "trace_id": trace_id}


def err(code: int, message: str, trace_id: str = "") -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"code": code, "message": message, "data": None, "trace_id": trace_id},
    )


# 错误码常量
class Code:
    OK            = 0
    PARAM_ERROR   = 1001
    UNAUTHENTICATED = 1002
    FORBIDDEN     = 1003
    CACHE_MISS    = 2001
    RETRIEVE_FAIL = 3001
    LLM_TIMEOUT   = 4001
    LLM_FAIL      = 4002
    SYSTEM_ERROR  = 5000
