"""用户级 Agent 日配额（Redis；无 Redis 时跳过限制）。"""

from __future__ import annotations

from datetime import date

from app.config import get_settings


def _redis():
    """功能：拿到 Redis 客户端；未启用或连不上则返回 None（不抛给调用方）。

    技术点：延迟 import，避免循环依赖；失败降级为「不限流」。
    """
    try:
        from app.redis_client import get_redis

        return get_redis()
    except Exception:  # noqa: BLE001
        return None


def _key(user_id: str) -> str:
    """功能：拼日配额 Redis key（按用户 + 自然日）。

    技术点：key 带日期，第二天自动是新计数；过期靠 expire 兜底。
    """
    return f"zhizhi:quota:agent:{user_id}:{date.today().isoformat()}"


def get_quota_status(user_id: str) -> dict:
    """功能：查询今日已用次数、上限、剩余。

    技术点：只读 Redis GET；无 Redis 时 used=0，不拦截。
    """
    settings = get_settings()
    limit = int(getattr(settings, "agent_daily_quota", 50) or 50)
    r = _redis()
    used = 0
    if r is not None:
        raw = r.get(_key(user_id))
        used = int(raw) if raw else 0
    remaining = max(0, limit - used)
    return {"used": used, "limit": limit, "remaining": remaining}


def check_and_consume_quota(user_id: str) -> tuple[bool, dict]:
    """功能：尝试扣 1 次日配额；超限返回 False。

    技术点：INCR 原子加一；第一次设置 TTL；超限再 DECR 回滚。
    无 Redis 时放行并标记 enforced=False。
    """
    settings = get_settings()
    limit = int(getattr(settings, "agent_daily_quota", 50) or 50)
    r = _redis()
    if r is None:
        # 无 Redis：不拦，但仍返回名义配额
        return True, {"used": 0, "limit": limit, "remaining": limit, "enforced": False}

    key = _key(user_id)
    used = r.incr(key)
    if used == 1:
        r.expire(key, 86400 * 2)
    if used > limit:
        # 回滚本次 incr
        r.decr(key)
        return False, {
            "used": limit,
            "limit": limit,
            "remaining": 0,
            "enforced": True,
        }
    return True, {
        "used": int(used),
        "limit": limit,
        "remaining": max(0, limit - int(used)),
        "enforced": True,
    }
