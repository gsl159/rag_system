"""
安全模块：JWT 认证 + Redis 限流 + trace_id
"""
import uuid
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import settings
from app.core.logger import logger

try:
    import jwt as pyjwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    logger.warning("PyJWT 未安装，JWT 认证将以简化模式运行")


# ── Trace ID ──────────────────────────────────

def generate_trace_id() -> str:
    return str(uuid.uuid4()).replace("-", "")[:16]


# ── JWT ───────────────────────────────────────

class AuthBearer(HTTPBearer):
    def __init__(self, auto_error: bool = True):
        super().__init__(auto_error=auto_error)


bearer_scheme = AuthBearer(auto_error=False)


def create_token(user_id: str, role: str = "user") -> str:
    if not JWT_AVAILABLE:
        return f"simple:{user_id}:{role}"
    payload = {
        "sub": user_id,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=settings.JWT_EXPIRE_HOURS),
        "iat": datetime.utcnow(),
    }
    return pyjwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
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
    # 开发环境跳过认证
    if settings.APP_ENV == "development":
        return {"sub": "dev_user", "role": "admin"}

    if not credentials:
        raise HTTPException(status_code=401, detail={"code": 1002, "message": "未提供认证令牌"})

    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail={"code": 1002, "message": "令牌无效或已过期"})

    return payload


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail={"code": 1003, "message": "需要管理员权限"})
    return user


# ── Rate Limiting ────────────────────────────

async def check_rate_limit(request: Request, user: dict = Depends(get_current_user)):
    """基于 Redis 的滑动窗口限流"""
    from app.db.redis import cache
    if not cache.client:
        return  # Redis 不可用时跳过限流

    user_id = user.get("sub", "anonymous")
    key = f"ratelimit:{user_id}:{int(time.time() // 60)}"
    try:
        count = await cache.client.incr(key)
        if count == 1:
            await cache.client.expire(key, 60)
        if count > settings.RATE_LIMIT_PER_MINUTE:
            raise HTTPException(
                status_code=429,
                detail={"code": 1001, "message": f"请求过于频繁，每分钟最多 {settings.RATE_LIMIT_PER_MINUTE} 次"}
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"限流检查失败（跳过）: {e}")
