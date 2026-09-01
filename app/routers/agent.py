"""职责：Agent 多步运行与停止——SSE 推 step，Redis 写停止信号。

技术点：SSE agent/run；request_stop；配额；create_agent / 多 Agent / 演示循环三路。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.loop import run_cancellable_agent
from agent.multi_agent import run_multi_agent
from agent.react_agent import run_tool_agent
from app.config import get_settings
from app.model_router import normalize_model_id
from app.db import get_db
from app.deps import get_current_user
from app.errors import QUOTA_EXCEEDED, REDIS_REQUIRED
from app.logging_json import log_event
from app.models import AppUser, Conversation, Message
from app.quota import check_and_consume_quota
from app.schemas import AgentRunRequest, ApiResult
from app.stop_signal import request_stop
from app.utils import conversation_title, is_placeholder_title, new_id, public_reply_text, utcnow

router = APIRouter(prefix="/conversations", tags=["Agent 停止信号"])


def _require_redis_enabled() -> None:
    """功能：未开 Redis 时直接 503，Agent 停止信号依赖 Redis。

    技术点：REDIS_REQUIRED 错误码。
    """
    if not get_settings().redis_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": REDIS_REQUIRED.code, "message": REDIS_REQUIRED.message},
        )


def _get_owned_conversation(
    db: Session, chat_id: str, user_id: str
) -> Conversation | None:
    """功能：按 chat_id 取当前用户未删除会话。

    技术点：归属校验；软删 is_del=0。
    """
    return db.scalar(
        select(Conversation).where(
            Conversation.chat_id == chat_id,
            Conversation.user_id == user_id,
            Conversation.is_del == 0,
        )
    )


@router.post("/{chat_id}/agent/stop", response_model=ApiResult[dict])
def stop_agent(
    chat_id: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[dict]:
    """功能：请求停止指定会话上正在运行的 Agent 循环。

    技术点：Redis request_stop；校验会话归属。
    """
    _require_redis_enabled()
    conv = _get_owned_conversation(db, chat_id, current_user.id)
    if not conv:
        return ApiResult.fail("会话不存在")
    request_stop(chat_id)
    return ApiResult.ok({"chat_id": chat_id, "stop": True})


@router.post("/{chat_id}/agent/run")
async def run_agent(
    chat_id: str,
    body: AgentRunRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> StreamingResponse:
    """功能：以 SSE 流式运行可取消多步 Agent（演示 / 真工具 / 多 Agent）。

    技术点：SSE；配额 check_and_consume_quota；先落用户消息再开流。
    """
    # 1. 校验 Redis 就没法点停止
    _require_redis_enabled()

    #空任务没意义
    task = body.content.strip()
    if not task:
        raise HTTPException(status_code=400, detail="任务内容不能为空")

    #2. Redis INCR zhizhi:quota:agent:{user}:{日期}，超限再 DECR 回滚
    ok_quota, quota_st = check_and_consume_quota(current_user.id)
    if not ok_quota:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": QUOTA_EXCEEDED.code,
                "message": QUOTA_EXCEEDED.message,
                "quota": quota_st,
            },
        )

    #3. 防越权
    conv = _get_owned_conversation(db, chat_id, current_user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    user_id = current_user.id
    conversation_pk = conv.id
    use_tools = bool(body.use_tools)
    multi_agent = bool(body.multi_agent)
    model_id = normalize_model_id(body.model or conv.model)

    #4. 先落用户消息（便于刷新后回看）
    now = utcnow()
    user_msg = Message(
        id=new_id(),
        conversation_id=conversation_pk,
        role="user",
        content=task,
        metadata_json=json.dumps(
            {
                "mode": "multi_agent" if multi_agent else "agent",
                "use_tools": use_tools,
                "multi_agent": multi_agent,
                "model": model_id,
            },
            ensure_ascii=False,
        ),
        create_date=now,
        create_by=user_id,
        update_date=now,
        update_by=user_id,
        is_del=0,
    )
    if is_placeholder_title(conv.title):
        conv.title = conversation_title(conv.agent_type, task)
    conv.model = model_id
    conv.update_date = now
    conv.update_by = user_id
    db.add(user_msg)
    db.commit()

    async def event_stream() -> AsyncIterator[str]:
        """功能：把内部 Agent 事件转成 SSE；结束时写入 assistant 消息。

        技术点：跨 await 不用请求 Session；public_reply_text 脱敏路径。
        """
        final_text = ""
        stopped = False
        try:
            if multi_agent:
                stream = run_multi_agent(
                    chat_id=chat_id, user_id=user_id, task=task, model=model_id
                )
            elif use_tools:
                stream = run_tool_agent(
                    chat_id=chat_id, user_id=user_id, task=task, model=model_id
                )
            else:
                stream = run_cancellable_agent(chat_id=chat_id, task=task)
            async for event in stream:
                if event.get("type") == "delta" and event.get("content"):
                    event["content"] = public_reply_text(str(event["content"]))
                elif event.get("type") == "done":
                    event["answer"] = public_reply_text(str(event.get("answer") or ""))
                    final_text = str(event.get("answer") or "")
                elif event.get("type") == "stopped":
                    stopped = True
                    final_text = public_reply_text(str(event.get("message") or "任务已停止"))
                elif event.get("type") == "error":
                    stopped = True
                    final_text = public_reply_text(str(event.get("message") or "Agent 错误"))
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            err = {
                "type": "error",
                "code": "AGENT_FAILED",
                "message": f"运行失败：{exc}（可点停止后重试，或缩短任务）",
            }
            log_event(
                "agent.run.error",
                user_id=user_id,
                chat_id=chat_id,
                code="AGENT_FAILED",
            )
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
            final_text = err["message"]
            stopped = True

        # 流结束后落库助手摘要（新 Session，避免跨 await 复用请求 Session）
        try:
            from app.db import SessionLocal

            if SessionLocal is None:
                return
            with SessionLocal() as session:
                reply_time = utcnow()
                assistant = Message(
                    id=new_id(),
                    conversation_id=conversation_pk,
                    role="assistant",
                    content=public_reply_text(final_text or ("任务已停止" if stopped else "完成")),
                    metadata_json=json.dumps(
                        {
                            "mode": "multi_agent" if multi_agent else "agent",
                            "use_tools": use_tools,
                            "multi_agent": multi_agent,
                            "stopped": stopped,
                        },
                        ensure_ascii=False,
                    ),
                    create_date=reply_time,
                    create_by="assistant",
                    update_date=reply_time,
                    update_by="assistant",
                    is_del=0,
                )
                owned = session.scalar(
                    select(Conversation).where(Conversation.id == conversation_pk)
                )
                if owned:
                    owned.update_date = reply_time
                session.add(assistant)
                session.commit()
                done_meta = {
                    "type": "persisted",
                    "assistant_message_id": assistant.id,
                    "stopped": stopped,
                }
                yield f"data: {json.dumps(done_meta, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            err = {"type": "error", "message": f"落库失败: {exc}"}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
