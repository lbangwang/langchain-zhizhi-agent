"""密码哈希与 JWT 签发/校验（W1 D4）。

约定：
- Access Token 使用 HS256，`sub` 存放用户 ID（32 位）
- 密码使用 PBKDF2-SHA256（标准库，无需额外依赖），不明文入库
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.config import get_settings

# 密码哈希格式：pbkdf2_sha256$iterations$salt_b64$hash_b64
_PWD_SCHEME = "pbkdf2_sha256"
_PWD_ITERATIONS = 120_000


def hash_password(plain: str) -> str:
    """功能：明文密码 → 可入库的哈希串（不明文存储）。

    技术点：PBKDF2-HMAC-SHA256 + 随机 salt；格式 scheme$iter$salt$hash。
    """
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        plain.encode("utf-8"),
        salt,
        _PWD_ITERATIONS,
    )
    return (
        f"{_PWD_SCHEME}${_PWD_ITERATIONS}$"
        f"{base64.b64encode(salt).decode()}$"
        f"{base64.b64encode(digest).decode()}"
    )


def verify_password(plain: str, password_hash: str | None) -> bool:
    """功能：校验登录密码是否匹配库里的哈希。

    技术点：按存库时的 iterations 重算；hmac.compare_digest 防计时攻击。
    """
    if not password_hash:
        return False
    try:
        scheme, iter_s, salt_b64, hash_b64 = password_hash.split("$", 3)
        if scheme != _PWD_SCHEME:
            return False
        iterations = int(iter_s)
        salt = base64.b64decode(salt_b64.encode())
        expected = base64.b64decode(hash_b64.encode())
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            plain.encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_access_token(*, user_id: str, username: str) -> str:
    """功能：签发登录 JWT（无状态会话）。

    技术点：HS256；payload.sub=用户 ID；exp 由 JWT_EXPIRE_MINUTES 控制。
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": user_id,
        "username": username,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """功能：校验签名与过期时间，解码 JWT payload。

    技术点：PyJWT decode；失败抛异常，由 deps 统一转 HTTP 401。
    """
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
