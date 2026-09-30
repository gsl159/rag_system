"""
认证与租户上下文 — 通用 OIDC / JWT

- AUTH_ENABLED=false：视为默认租户，便于本地联调
- AUTH_ENABLED=true ：校验 Bearer Token（RS256 走 OIDC JWKS；HS256 走本地密钥）
  校验通过后从 claim 提取 tenant_id（默认取 `tenant_id`，其次 `org`/`sub`），
  写入请求上下文与 ContextVar，供 PG RLS 与 Milvus 过滤使用。
"""
from typing import Optional

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from jwt import PyJWKClient

from app.core.config import settings
from app.core.logger import logger
from app.db.postgres import set_current_tenant


# 缓存 JWKS 客户端（按 URL）
_jwks_client: Optional[PyJWKClient] = None


def _get_jwks_client() -> Optional[PyJWKClient]:
    global _jwks_client
    if not settings.OIDC_JWKS_URL:
        return None
    if _jwks_client is None:
        _jwks_client = PyJWKClient(settings.OIDC_JWKS_URL)
    return _jwks_client


def _decode_token(token: str) -> dict:
    """校验并解码 JWT"""
    options = {"verify_aud": bool(settings.OIDC_AUDIENCE)}
    if settings.OIDC_JWKS_URL:
        # OIDC：从 JWKS 取公钥校验 RS256
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            signing_key,
            algorithms=settings.jwt_algorithms_list,
            audience=settings.OIDC_AUDIENCE or None,
            issuer=settings.OIDC_ISSUER or None,
            options=options,
        )
    # 本地 HS256 兜底（仅开发/内网）
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=settings.jwt_algorithms_list,
        audience=settings.OIDC_AUDIENCE or None,
        options={"verify_aud": bool(settings.OIDC_AUDIENCE)},
    )


def _extract_tenant(payload: dict) -> str:
    for claim in ("tenant_id", "org_id", "org", "workspace_id"):
        val = payload.get(claim)
        if val:
            return str(val)
    sub = payload.get("sub")
    return str(sub) if sub else settings.DEFAULT_TENANT_ID


async def auth_middleware(request: Request, call_next):
    """
    认证中间件：
    1. 解析 Bearer Token（若启用认证）
    2. 提取租户并写入上下文
    3. 后续路由可直接读取 request.state.tenant_id / payload
    """
    tenant_id = settings.DEFAULT_TENANT_ID
    payload   = {}

    if settings.AUTH_ENABLED:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "缺少 Bearer Token"})
        token = auth_header[7:].strip()
        try:
            payload = _decode_token(token)
        except jwt.ExpiredSignatureError:
            return JSONResponse(status_code=401, content={"detail": "Token 已过期"})
        except Exception as e:
            logger.warning(f"Token 校验失败: {e}")
            return JSONResponse(status_code=401, content={"detail": "Token 无效"})
        tenant_id = _extract_tenant(payload)

    request.state.tenant_id = tenant_id
    request.state.auth_payload = payload
    set_current_tenant(tenant_id)

    return await call_next(request)
