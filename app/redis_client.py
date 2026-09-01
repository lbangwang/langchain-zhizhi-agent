"""Redis 连接（W1 D5 停止信号）。

仅在 `REDIS_ENABLED=true` 时建立连接；否则停止信号相关接口返回明确错误。
"""

from __future__ import annotations

from redis import Redis

from app.config import get_settings

_client: Redis | None = None


def get_redis() -> Redis:
    """功能：返回进程内单例 Redis 客户端；未启用则抛错。

    技术点：from_url；decode_responses 后取值是 str；短超时避免健康检查卡死。
    """
    global _client
    settings = get_settings()
    if not settings.redis_enabled:
        raise RuntimeError("Redis is disabled. Set REDIS_ENABLED=true in .env")
    if _client is None:
        _client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _client


def redis_ping() -> bool:
    """功能：PING 探测 Redis，供 /health 使用。

    技术点：关闭开关或网络失败都返回 False，不把异常抛给健康检查。
    """
    settings = get_settings()
    if not settings.redis_enabled:
        return False
    try:
        return bool(get_redis().ping())
    except Exception:  # noqa: BLE001
        return False
