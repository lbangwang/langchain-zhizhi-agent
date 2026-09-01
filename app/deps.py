"""FastAPI 依赖：当前登录用户。

受保护接口通过 `Depends(get_current_user)` 注入；无/无效 token → HTTP 401。
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AppUser
from app.security import decode_access_token

# auto_error=False：自行抛 401（默认 Bearer 缺失时是 403）
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AppUser:
    """功能：从 Authorization Bearer 解析当前用户（受保护接口通用依赖）。

    技术点：HTTPBearer；JWT sub → 查库；软删/禁用视为未登录；缺票 401 而非 403。
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或缺少 token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = payload.get("sub")
        if not user_id or not isinstance(user_id, str):
            raise ValueError("missing sub")
    except Exception as exc:  # noqa: BLE001 — jwt 各类错误统一 401
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token 无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.scalar(
        select(AppUser).where(
            AppUser.id == user_id,
            AppUser.is_del == 0,
            AppUser.status == 1,
        )
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已禁用",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
