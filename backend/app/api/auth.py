"""
/auth 路由 — 登录/登出/当前用户
"""
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ok
from app.core.security import create_token, generate_trace_id, get_current_user
from app.db.postgres import get_db, User, AuditLog

router = APIRouter(prefix="/auth", tags=["认证"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    trace_id = generate_trace_id()
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()

    # 验证密码
    valid = False
    if user:
        try:
            import bcrypt
            valid = bcrypt.checkpw(req.password.encode(), user.password.encode())
        except Exception:
            # bcrypt未安装时，明文比较（仅开发）
            valid = user.password == req.password

    if not user or not valid or not user.is_active:
        # 记录失败审计
        db.add(AuditLog(trace_id=trace_id, action="login_fail",
                        resource=req.username,
                        ip=request.client.host if request.client else None))
        await db.commit()
        raise HTTPException(status_code=401, detail={"code": 1002, "message": "用户名或密码错误"})

    token = create_token(user.id, user.role)

    # 记录成功审计
    db.add(AuditLog(trace_id=trace_id, user_id=user.id, username=user.username,
                    action="login", ip=request.client.host if request.client else None))
    await db.commit()

    return ok({
        "token": token,
        "user": {"id": user.id, "username": user.username, "role": user.role,
                 "tenant_id": user.tenant_id},
    }, trace_id=trace_id)


@router.post("/logout")
async def logout(user: dict = Depends(get_current_user)):
    return ok({"message": "已退出登录"})


@router.get("/me")
async def me(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user["sub"]))
    u = result.scalar_one_or_none()
    if not u:
        return ok({"id": user["sub"], "role": user.get("role", "user")})
    return ok({"id": u.id, "username": u.username, "role": u.role,
               "tenant_id": u.tenant_id, "dept_id": u.dept_id})
