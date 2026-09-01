"""注册 / 登录 / 当前用户（W1 D4）。

公开接口（无需 token）：
- POST /api/auth/login
- GET /api/auth/features（是否开放注册）
- POST /api/auth/register（仅 REGISTER_ENABLED=true）

受保护：
- GET /api/auth/me
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import AppUser
from app.schemas import (
    ApiResult,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.config import get_settings
from app.errors import REGISTER_DISABLED
from app.security import create_access_token, hash_password, verify_password
from app.utils import new_id, utcnow

router = APIRouter(prefix="/auth", tags=["鉴权"])


def _register_closed() -> ApiResult | None:
    """功能：生产关闭注册时返回统一失败体；开启则返回 None。"""
    if get_settings().register_enabled:
        return None
    return ApiResult.fail(REGISTER_DISABLED.message, code=403)


@router.get("/features")
def auth_features() -> dict[str, bool]:
    """功能：给前端判断是否展示注册入口（无需登录）。"""
    return {"register_enabled": bool(get_settings().register_enabled)}


@router.post("/register", response_model=ApiResult[TokenResponse])
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> ApiResult[TokenResponse]:
    """功能：注册用户并立刻返回 access_token（免再登录）。

    技术点：REGISTER_ENABLED=false 时拒绝；用户名唯一；PBKDF2；签发 JWT。
    """
    closed = _register_closed()
    if closed is not None:
        return closed
    username = body.username.strip()
    if db.scalar(
        select(AppUser).where(AppUser.username == username, AppUser.is_del == 0)
    ):
        return ApiResult.fail("用户名已存在")

    now = utcnow()
    user = AppUser(
        id=new_id(),
        username=username,
        password_hash=hash_password(body.password),
        nickname=(body.nickname or username).strip(),
        status=1,
        create_date=now,
        create_by=username,
        update_date=now,
        update_by=username,
        is_del=0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user_id=user.id, username=user.username)
    return ApiResult.ok(
        TokenResponse(
            access_token=token,
            token_type="bearer",
            user=UserResponse.model_validate(user),
        )
    )


@router.post("/login", response_model=ApiResult[TokenResponse])
def login(body: LoginRequest, db: Session = Depends(get_db)) -> ApiResult[TokenResponse]:
    """功能：用户名密码登录，返回 Bearer token。

    技术点：verify_password；用户名/密码错误用同一文案；status 禁用拦截。
    """
    user = db.scalar(
        select(AppUser).where(
            AppUser.username == body.username.strip(),
            AppUser.is_del == 0,
        )
    )
    if not user or not verify_password(body.password, user.password_hash):
        return ApiResult.fail("用户名或密码错误")
    if user.status != 1:
        return ApiResult.fail("用户已禁用")

    token = create_access_token(user_id=user.id, username=user.username)
    return ApiResult.ok(
        TokenResponse(
            access_token=token,
            token_type="bearer",
            user=UserResponse.model_validate(user),
        )
    )


@router.get("/me", response_model=ApiResult[UserResponse])
def me(current_user: AppUser = Depends(get_current_user)) -> ApiResult[UserResponse]:
    """功能：返回当前登录用户资料（刷新页面校验 token）。

    技术点：Depends(get_current_user)；UserResponse 不含 password_hash。
    """
    return ApiResult.ok(UserResponse.model_validate(current_user))
