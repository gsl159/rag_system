"""Backward compatibility — imports from app.api.deps"""
from app.api.deps import (
    create_token, verify_token,
    get_current_user, require_admin, check_rate_limit,
    bearer_scheme, AuthBearer,
)
from app.utils.trace import generate_trace_id

__all__ = [
    "generate_trace_id", "create_token", "verify_token",
    "get_current_user", "require_admin", "check_rate_limit",
    "bearer_scheme", "AuthBearer",
]
