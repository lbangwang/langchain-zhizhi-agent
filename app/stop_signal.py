"""Agent 停止信号（基于 Redis）。

约定：
- Key：`zhizhi:agent:stop:{chat_id}`
- 值为 `"1"` 表示该会话的 Agent 循环应在下一步前退出
- 启动任务前 `clear_stop`；用户点停止时 `request_stop`
"""

from __future__ import annotations

from app.redis_client import get_redis

# 停止标记默认 10 分钟过期，避免残留 key 永久阻塞新任务
_STOP_TTL_SECONDS = 600


def _stop_key(chat_id: str) -> str:
    """功能：停止信号的 Redis key，按会话隔离。

    技术点：不同 chat_id 互不影响，点停止只停当前对话。
    """
    return f"zhizhi:agent:stop:{chat_id}"


def clear_stop(chat_id: str) -> None:
    """功能：新任务开始时清掉停止标记。

    技术点：DELETE key；不清理的话上次点停止会立刻结束新任务。
    """
    get_redis().delete(_stop_key(chat_id))


def request_stop(chat_id: str) -> None:
    """功能：前端点停止时写入标记。

    技术点：SET + TTL，避免 key 永久残留导致永远跑不起来。
    """
    get_redis().set(_stop_key(chat_id), "1", ex=_STOP_TTL_SECONDS)


def is_stopped(chat_id: str) -> bool:
    """功能：Agent 每步前轮询，值为 1 则不再进入后续 step。

    技术点：decode_responses=True 时与字符串 \"1\" 比较。
    """
    return get_redis().get(_stop_key(chat_id)) == "1"
