"""职责：HITL——危险工具执行前等待人工批准/拒绝。

技术点：Redis pending/decision 键；轮询等待；超时默认 reject。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
import time
from typing import Any

from app.config import get_settings
from app.utils import new_id


# 由 runner 在单次运行前设置；None 表示跟随全局 settings.hitl_enabled
_runtime_hitl_override: bool | None = None


DANGEROUS_TOOLS = frozenset(
    {
        # 仅落盘 / 改系统侧产物需要人工确认；检索类工具直接放行
        "write_text_file",
        "create_pdf_report",
        "create_doc_report",
    }
)


def _redis():
    """功能：惰性获取 Redis 客户端；不可用则返回 None。

    技术点：延迟导入避免循环依赖；异常吞掉以降级为自动放行。
    """
    try:
        from app.redis_client import get_redis

        return get_redis()
    except Exception:  # noqa: BLE001
        return None


def _pending_key(chat_id: str) -> str:
    """功能：拼出当前会话的 HITL 待审批 Redis 键。

    技术点：按 chat_id 隔离 pending。
    """
    return f"zhizhi:hitl:pending:{chat_id}"


def _decision_key(chat_id: str, request_id: str) -> str:
    """功能：拼出某次审批请求的决策 Redis 键。

    技术点：chat_id + request_id 双维度，避免串单。
    """
    return f"zhizhi:hitl:decision:{chat_id}:{request_id}"


def is_dangerous(tool_name: str) -> bool:
    """功能：判断工具是否属于写盘类危险操作。

    技术点：白名单 frozenset；检索类工具不走 HITL。
    """
    return tool_name in DANGEROUS_TOOLS


def publish_hitl_request(
    *,
    chat_id: str,
    tool_name: str,
    args_preview: str,
) -> str:
    """功能：写入待审批请求到 Redis，返回 request_id。

    技术点：HITL 关闭或无 Redis 时返回 auto: 前缀，调用方视为自动批准。
    """
    request_id = new_id()
    settings = get_settings()
    enabled = (
        _runtime_hitl_override
        if _runtime_hitl_override is not None
        else settings.hitl_enabled
    )
    if not enabled:
        return f"auto:{request_id}"
    payload = {
        "request_id": request_id,
        "tool_name": tool_name,
        "args_preview": (args_preview or "")[:400],
        "created_at": time.time(),
    }
    r = _redis()
    if r is None:
        return f"auto:{request_id}"
    r.setex(_pending_key(chat_id), 300, json.dumps(payload, ensure_ascii=False))
    return request_id


def clear_hitl_pending(chat_id: str) -> None:
    """功能：清除会话上的待审批 pending 键。

    技术点：Redis DELETE；无客户端则空操作。
    """
    r = _redis()
    if r is None:
        return
    r.delete(_pending_key(chat_id))


def get_hitl_pending(chat_id: str) -> dict[str, Any] | None:
    """功能：读取当前会话是否有待审批请求。

    技术点：Redis GET + JSON；坏 JSON 视为无 pending。
    """
    r = _redis()
    if r is None:
        return None
    raw = r.get(_pending_key(chat_id))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def submit_hitl_decision(
    *,
    chat_id: str,
    request_id: str,
    decision: str,
) -> bool:
    """功能：前端提交 approve / reject 决策。

    技术点：写入 decision 键 TTL 120s；同时清 pending；auto: 请求直接成功。
    """
    if decision not in {"approve", "reject"}:
        return False
    if request_id.startswith("auto:"):
        return True
    r = _redis()
    if r is None:
        return False
    r.setex(
        _decision_key(chat_id, request_id),
        120,
        json.dumps({"decision": decision}, ensure_ascii=False),
    )
    clear_hitl_pending(chat_id)
    return True


def wait_hitl_decision(
    *,
    chat_id: str,
    request_id: str,
    timeout_seconds: float | None = None,
) -> str:
    """功能：阻塞轮询等待人工决策；超时默认 reject。

    技术点：Redis GET 轮询；is_stopped 立刻当 reject，避免卡死 HITL。
    """
    if request_id.startswith("auto:"):
        return "approve"
    settings = get_settings()
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else float(settings.hitl_timeout_seconds)
    )
    r = _redis()
    if r is None:
        return "approve"
    deadline = time.time() + max(5.0, timeout)
    key = _decision_key(chat_id, request_id)
    while time.time() < deadline:
        # 用户点停止：立刻当作拒绝，别卡死在 HITL 等待
        try:
            from app.stop_signal import is_stopped

            if is_stopped(chat_id):
                clear_hitl_pending(chat_id)
                return "reject"
        except Exception:  # noqa: BLE001
            pass
        raw = r.get(key)
        if raw:
            try:
                data = json.loads(raw)
                decision = data.get("decision") or "reject"
            except json.JSONDecodeError:
                decision = "reject"
            r.delete(key)
            clear_hitl_pending(chat_id)
            return decision if decision in {"approve", "reject"} else "reject"
        time.sleep(0.25)
    clear_hitl_pending(chat_id)
    return "reject"


async def iter_hitl_while_waiting(
    chat_id: str,
    work: asyncio.Future,
    *,
    poll_interval: float = 0.2,
) -> AsyncIterator[dict[str, Any]]:
    """功能：后台任务卡在 HITL 时，把 Redis pending 推成 hitl_required 给前端。

    技术点：asyncio.wait_for + shield；写文件在线程里时必须走这里否则前端看不到批准按钮。
    """
    seen: set[str] = set()
    while not work.done():
        pending = get_hitl_pending(chat_id)
        if pending:
            rid = str(pending.get("request_id") or "")
            if rid and not rid.startswith("auto:") and rid not in seen:
                seen.add(rid)
                yield {
                    "type": "hitl_required",
                    "request_id": rid,
                    "tool_name": pending.get("tool_name"),
                    "args_preview": pending.get("args_preview"),
                    "message": (
                        f"危险工具待确认：{pending.get('tool_name')}，"
                        "请批准或拒绝后继续"
                    ),
                }
        try:
            from app.stop_signal import is_stopped

            if is_stopped(chat_id):
                return
        except Exception:  # noqa: BLE001
            pass
        try:
            await asyncio.wait_for(asyncio.shield(work), timeout=poll_interval)
        except TimeoutError:
            continue
        except asyncio.CancelledError:
            return


def require_hitl_or_skip(tool_name: str, args_preview: str) -> str | None:
    """功能：危险工具执行前发布 HITL 并等待；放行返回 None，拒绝返回原因字符串。

    技术点：ContextVar current_chat_id；无 chat_id 或未启用则直接放行。
    """
    settings = get_settings()
    enabled = (
        _runtime_hitl_override
        if _runtime_hitl_override is not None
        else settings.hitl_enabled
    )
    if not enabled or not is_dangerous(tool_name):
        return None
    chat_id = ""
    try:
        from agent.tools import current_chat_id

        chat_id = current_chat_id.get() or ""
    except Exception:  # noqa: BLE001
        chat_id = ""
    if not chat_id:
        return None
    #发审批单
    rid = publish_hitl_request(
        chat_id=chat_id, tool_name=tool_name, args_preview=args_preview
    )
    #阻塞等人
    decision = wait_hitl_decision(chat_id=chat_id, request_id=rid)
    if decision == "approve":
        return None
    return f"用户已拒绝执行危险工具 {tool_name}"
