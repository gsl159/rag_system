"""API layer dependencies — auth, rate limiting, singleflight, unified response.

Consolidates all cross-cutting concerns for the entry layer.
"""
import time
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config.settings import settings
from app.utils.logger import logger
from app.utils.trace import generate_trace_id, get_trace_id, set_trace_id

try:
    import jwt as pyjwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    logger.warning("PyJWT not installed, running in simplified auth mode")


# ── Unified API Response ──────────────────────────


class ErrorCode:
    """Centralized error code system."""
    OK = 0
    PARAM_ERROR = 1001
    UNAUTHENTICATED = 1002
    FORBIDDEN = 1003
    RATE_LIMITED = 1004
    NOT_FOUND = 1005
    DUPLICATE = 1006
    CACHE_MISS = 2001
    RETRIEVE_FAIL = 3001
    LLM_TIMEOUT = 4001
    LLM_FAIL = 4002
    SYSTEM_ERROR = 5000


def ok(data: Any = None, message: str = "ok", trace_id: str = "") -> dict:
    """Unified success response."""
    return {
        "code": ErrorCode.OK,
        "message": message,
        "data": data,
        "trace_id": trace_id or get_trace_id(),
    }


def err(code: int, message: str, status_code: int = 400, trace_id: str = "") -> JSONResponse:
    """Unified error response."""
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "data": None,
            "trace_id": trace_id or get_trace_id(),
        },
    )


# ── JWT Authentication ─────────────────────────


class AuthBearer(HTTPBearer):
    def __init__(self, auto_error: bool = True):
        super().__init__(auto_error=auto_error)


bearer_scheme = AuthBearer(auto_error=False)


def create_token(user_id: str, role: str = "user") -> str:
    """Create a JWT token."""
    if not JWT_AVAILABLE:
        return f"simple:{user_id}:{role}"
    from datetime import datetime, timedelta
    payload = {
        "sub": user_id,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=settings.JWT_EXPIRE_HOURS),
        "iat": datetime.utcnow(),
    }
    return pyjwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    """Verify a JWT token and return payload."""
    if token.startswith("simple:"):
        parts = token.split(":")
        return {"sub": parts[1], "role": parts[2] if len(parts) > 2 else "user"}
    if not JWT_AVAILABLE:
        return None
    try:
        return pyjwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except Exception:
        return None


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """Dependency to get the current authenticated user."""
    if settings.APP_ENV == "development":
        return {"sub": "dev_user", "role": "admin"}

    if not credentials:
        raise HTTPException(status_code=401, detail={"code": ErrorCode.UNAUTHENTICATED, "message": "未提供认证令牌"})

    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail={"code": ErrorCode.UNAUTHENTICATED, "message": "令牌无效或已过期"})

    return payload


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Dependency that requires admin role."""
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail={"code": ErrorCode.FORBIDDEN, "message": "需要管理员权限"})
    return user


# ── Rate Limiting ──────────────────────────────


async def check_rate_limit(request: Request, user: dict = Depends(get_current_user)):
    """Redis-based sliding window rate limiting."""
    from app.repository.redis_cache import cache
    if not cache.client:
        return

    user_id = user.get("sub", "anonymous")
    key = f"ratelimit:{user_id}:{int(time.time() // 60)}"
    try:
        count = await cache.client.incr(key)
        if count == 1:
            await cache.client.expire(key, 60)
        if count > settings.RATE_LIMIT_PER_MINUTE:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": ErrorCode.RATE_LIMITED,
                    "message": f"请求过于频繁，每分钟最多 {settings.RATE_LIMIT_PER_MINUTE} 次",
                },
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Rate limit check failed (skipping): {e}")
