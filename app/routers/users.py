"""用户查询路由（W1 D2 + D4 鉴权）。

注册请走 `/api/auth/register`。本模块接口均需 Bearer token。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.errors import REGISTER_DISABLED
from app.models import AppUser
from app.schemas import ApiResult, CreateUserRequest, UserResponse
from app.security import hash_password
from app.utils import new_id, utcnow

router = APIRouter(prefix="/users", tags=["用户"])


@router.post("", response_model=ApiResult[UserResponse])
def create_user(
    body: CreateUserRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[UserResponse]:
    """功能：登录后创建用户（演示后台用；日常走 /auth/register）。

    技术点：生产 REGISTER_ENABLED=false 时同样关闭，避免登录后批量开号。
    """
    _ = current_user
    if not get_settings().register_enabled:
        return ApiResult.fail(REGISTER_DISABLED.message, code=403)
    exists = db.scalar(
        select(AppUser).where(AppUser.username == body.username, AppUser.is_del == 0)
    )
    if exists:
        return ApiResult.fail("用户名已存在")
    if not body.password:
        return ApiResult.fail("密码不能为空")

    now = utcnow()
    user = AppUser(
        id=new_id(),
        username=body.username,
        password_hash=hash_password(body.password),
        nickname=body.nickname or body.username,
        status=1,
        create_date=now,
        create_by=body.create_by or current_user.id,
        update_date=now,
        update_by=body.create_by or current_user.id,
        is_del=0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return ApiResult.ok(UserResponse.model_validate(user))


@router.get("/{user_id}", response_model=ApiResult[UserResponse])
def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[UserResponse]:
    """功能：按 id 查用户，且只能看自己。

    技术点：403 防越权；软删用户当不存在。
    """
    if user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权查看其他用户",
        )
    user = db.scalar(select(AppUser).where(AppUser.id == user_id, AppUser.is_del == 0))
    if not user:
        return ApiResult.fail("用户不存在")
    return ApiResult.ok(UserResponse.model_validate(user))
