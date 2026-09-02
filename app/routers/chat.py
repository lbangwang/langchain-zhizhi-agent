"""职责：对话续聊——可选知识库检索注入 + __CITATIONS__。

技术点：SSE chat/stream；可选 RAG；JWT 用户隔离；软删会话过滤。
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, get_db
from app.deps import get_current_user
from app.llm import chat_completion, chat_completion_stream
from app.model_router import normalize_model_id
from app.models import AppUser, Conversation, Message
from app.schemas import ApiResult, ChatRequest, ChatResponse, MessageResponse
from app.langsmith_setup import langsmith_trace, start_span
from app.trace import finish_trace as _finish_trace, start_trace, timed_step
from app.utils import conversation_title, is_placeholder_title, new_id, utcnow
from agent.memory import summarize_and_trim
from rag.citations import (
    CITATIONS_MARKER,
    build_citations,
    format_context,
    rag_system_prompt,
    retrieve_for_user,
)

router = APIRouter(prefix="/conversations", tags=["对话续聊"])


def _to_message_response(msg: Message) -> MessageResponse:
    """功能：把 ORM 消息转成 API 响应模型。

    技术点：metadata_json 原样透出。
    """
    return MessageResponse(
        id=msg.id,
        conversation_id=msg.conversation_id,
        role=msg.role,
        content=msg.content,
        metadata=msg.metadata_json,
        create_date=msg.create_date,
        update_date=msg.update_date,
    )


def _sse(payload: dict) -> str:
    """功能：把 dict 编码成 SSE `data: ...\\n\\n` 一行。

    技术点：SSE；ensure_ascii=False。
    """
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _get_owned_conv(db: Session, chat_id: str, user_id: str) -> Conversation | None:
    """功能：按 chat_id 取当前用户未删除会话。

    技术点：归属校验 user_id；软删 is_del=0。
    """
    return db.scalar(
        select(Conversation).where(
            Conversation.chat_id == chat_id,
            Conversation.user_id == user_id,
            Conversation.is_del == 0,
        )
    )


def _save_user_turn(
    *,
    db: Session,
    conv: Conversation,
    content: str,
    user_id: str,
) -> tuple[Message, list[dict[str, str]]]:
    """功能：落库用户消息并返回含本轮 user 的历史，供 LLM 续聊。

    技术点：占位标题替换；过滤软删消息；commit 后刷新。
    """
    now = utcnow()
    user_msg = Message(
        id=new_id(),
        conversation_id=conv.id,
        role="user",
        content=content,
        metadata_json=None,
        create_date=now,
        create_by=user_id,
        update_date=now,
        update_by=user_id,
        is_del=0,
    )
    db.add(user_msg)
    if is_placeholder_title(conv.title):
        conv.title = conversation_title(conv.agent_type, content)
    db.flush()

    history_rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conv.id, Message.is_del == 0)
        .order_by(Message.create_date.asc())
    ).all()
    llm_messages = [
        {"role": m.role, "content": m.content}
        for m in history_rows
        if m.role in {"user", "assistant", "system"}
    ]
    db.commit()
    db.refresh(user_msg)
    db.refresh(conv)
    return user_msg, llm_messages


@router.post("/{chat_id}/chat", response_model=ApiResult[ChatResponse])
def chat(
    chat_id: str,
    body: ChatRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[ChatResponse]:
    """功能：发送用户消息并生成助手回复（非流式，兼容旧客户端）。

    技术点：可选 RAG 注入 system；__CITATIONS__；JWT 用户。
    """
    content = body.content.strip()
    if not content:
        return ApiResult.fail("消息不能为空")

    conv = _get_owned_conv(db, chat_id, current_user.id)
    if not conv:
        return ApiResult.fail("会话不存在")

    try:
        user_msg, llm_messages = _save_user_turn(
            db=db, conv=conv, content=content, user_id=current_user.id
        )
        settings = get_settings()
        model_id = normalize_model_id(body.model or conv.model)
        if conv.model != model_id:
            conv.model = model_id
            db.commit()
        use_rag = bool(body.use_rag and settings.milvus_enabled)
        citations: list[dict] = []
        rag_debug: dict | None = None
        tags = ["chat"]
        if use_rag:
            tags.append("interviewer")
        if conv.agent_type:
            tags.append(str(conv.agent_type).lower())
        with langsmith_trace(
            name="chat",
            tags=tags,
            metadata={"chat_id": chat_id, "user_id": current_user.id, "model": model_id},
            inputs={"content": content[:400]},
        ):
            if use_rag:
                chunks, rag_debug = retrieve_for_user(content, current_user.id)
                citations = build_citations(chunks)
                llm_messages = [
                    {"role": "system", "content": rag_system_prompt(format_context(chunks))},
                    *[m for m in llm_messages if m["role"] != "system"],
                ]
            assistant_text = chat_completion(llm_messages, model=model_id)
        if use_rag and citations:
            assistant_text = (
                f"{assistant_text.rstrip()}\n\n{CITATIONS_MARKER}\n"
                f"{json.dumps(citations, ensure_ascii=False)}"
            )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return ApiResult.fail(f"模型/检索调用失败: {exc}")

    reply_time = utcnow()
    assistant_msg = Message(
        id=new_id(),
        conversation_id=conv.id,
        role="assistant",
        content=assistant_text,
        metadata_json=json.dumps(
            {"citations": citations, "rag": rag_debug},
            ensure_ascii=False,
        )
        if use_rag
        else None,
        create_date=reply_time,
        create_by="assistant",
        update_date=reply_time,
        update_by="assistant",
        is_del=0,
    )
    db.add(assistant_msg)
    owned = db.scalar(select(Conversation).where(Conversation.id == conv.id))
    if owned:
        owned.update_date = reply_time
        owned.update_by = current_user.id
    db.commit()
    db.refresh(user_msg)
    db.refresh(assistant_msg)
    db.refresh(conv)

    return ApiResult.ok(
        ChatResponse(
            chat_id=conv.chat_id,
            title=conv.title,
            user_message=_to_message_response(user_msg),
            assistant_message=_to_message_response(assistant_msg),
            citations=citations or None,
            rag_debug=rag_debug,
        )
    )


@router.post("/{chat_id}/chat/stream")
def chat_stream(
    chat_id: str,
    body: ChatRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> StreamingResponse:
    """功能：SSE 流式续聊——先推状态，再逐 token 打字机，最后落库。

    技术点：SSE；可选 RAG；短记忆 summarize_and_trim；新 Session 落库。
    """
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="消息不能为空")

    user_id = current_user.id
    conv = _get_owned_conv(db, chat_id, user_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    try:
        #llm_messages：当前回话的历史消息
        user_msg, llm_messages = _save_user_turn(
            db=db, conv=conv, content=content, user_id=user_id
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=f"准备对话失败: {exc}") from exc

    conversation_pk = conv.id
    chat_id_out = conv.chat_id
    title_out = conv.title
    agent_type = conv.agent_type or ""
    user_payload = _to_message_response(user_msg).model_dump(mode="json")
    want_rag = bool(body.use_rag and get_settings().milvus_enabled)
    model_id = normalize_model_id(body.model or conv.model)
    if conv.model != model_id:
        conv.model = model_id
        db.commit()

    def event_stream() -> Iterator[str]:
        """功能：生成 SSE 事件：记忆压缩、可选检索、token delta、done。

        技术点：同步生成器；start_span 不跨 yield reset；timed_step 记 Trace。
        """
        trace_id = start_trace(
            user_id=user_id,
            chat_id=chat_id_out,
            name="chat.stream",
            meta={"content": content[:200], "model": model_id},
        )
        ls_tags = ["chat.stream"]
        if want_rag:
            ls_tags.append("interviewer")
        if agent_type:
            ls_tags.append(str(agent_type).lower())
        ls_span = start_span(
            name="chat.stream",
            tags=ls_tags,
            metadata={
                "chat_id": chat_id_out,
                "local_trace_id": trace_id,
                "user_id": user_id,
                "model": model_id,
            },
            inputs={"content": content[:400]},
        )

        def finish_trace(tid: str, **kwargs) -> None:
            """功能：结束本次 chat.stream 的本地 Trace 并关闭 LangSmith span。

            技术点：合并 langsmith_run_id；finally span.close。
            """
            extra = dict(kwargs.pop("meta_update", None) or {})
            extra.update(ls_span.meta())
            try:
                _finish_trace(tid, meta_update=extra or None, **kwargs)
            finally:
                ls_span.close()

        yield _sse(
            {
                "type": "user_message",
                "message": user_payload,
                "title": title_out,
                "trace_id": trace_id,
            }
        )

        citations: list[dict] = []
        rag_debug: dict | None = None
        memory_summary: str | None = None
        final_messages = list(llm_messages)

        # W3 D1：长对话摘要压缩
        yield _sse(
            {
                "type": "status",
                "zone": "think",
                "message": "检查上下文 / 短记忆压缩…",
            }
        )
        with timed_step(
            trace_id, user_id=user_id, chat_id=chat_id_out, name="memory.summarize"
        ):
            final_messages, memory_summary = summarize_and_trim(final_messages)
        if memory_summary:
            yield _sse(
                {
                    "type": "status",
                    "zone": "think",
                    "message": "已压缩较早对话为摘要，继续续聊",
                }
            )
            yield _sse(
                {
                    "type": "memory_summary",
                    "zone": "think",
                    "summary": memory_summary[:600],
                }
            )

        if want_rag:
            yield _sse(
                {
                    "type": "status",
                    "zone": "think",
                    "message": "正在检索知识库…",
                }
            )
            try:
                with timed_step(
                    trace_id, user_id=user_id, chat_id=chat_id_out, name="rag.retrieve"
                ):
                    chunks, rag_debug = retrieve_for_user(content, user_id)
                citations = build_citations(chunks)
                final_messages = [
                    {
                        "role": "system",
                        "content": rag_system_prompt(format_context(chunks)),
                    },
                    *[m for m in final_messages if m["role"] != "system"],
                ]
            except Exception as exc:  # noqa: BLE001
                finish_trace(trace_id, status="error", meta_update={"error": str(exc)})
                yield _sse({"type": "error", "message": f"检索失败: {exc}"})
                return
            yield _sse(
                {
                    "type": "status",
                    "zone": "think",
                    "message": "开始生成回答…",
                }
            )
        else:
            yield _sse(
                {
                    "type": "status",
                    "zone": "think",
                    "message": "开始生成回答…",
                }
            )

        parts: list[str] = []
        try:
            with timed_step(
                trace_id, user_id=user_id, chat_id=chat_id_out, name="llm.stream"
            ):
                for delta in chat_completion_stream(final_messages, model=model_id):
                    parts.append(delta)
                    yield _sse({"type": "delta", "zone": "answer", "content": delta})
        except Exception as exc:  # noqa: BLE001
            finish_trace(trace_id, status="error", meta_update={"error": str(exc)})
            yield _sse({"type": "error", "message": f"模型调用失败: {exc}"})
            return

        body_only = "".join(parts).strip() or "（模型返回空内容）"
        assistant_text = body_only
        if want_rag and citations:
            cite_block = (
                f"\n\n{CITATIONS_MARKER}\n{json.dumps(citations, ensure_ascii=False)}"
            )
            assistant_text = f"{body_only}{cite_block}"
            yield _sse({"type": "delta", "zone": "answer", "content": cite_block})

        try:
            if SessionLocal is None:
                finish_trace(trace_id, status="error", meta_update={"error": "db_disabled"})
                yield _sse({"type": "error", "message": "数据库未启用"})
                return
            with SessionLocal() as session:
                reply_time = utcnow()
                meta = {
                    "citations": citations,
                    "rag": rag_debug,
                    "memory_summary": memory_summary,
                    "trace_id": trace_id,
                }
                assistant = Message(
                    id=new_id(),
                    conversation_id=conversation_pk,
                    role="assistant",
                    content=assistant_text,
                    metadata_json=json.dumps(meta, ensure_ascii=False),
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
                    owned.update_by = user_id
                session.add(assistant)
                session.commit()
                session.refresh(assistant)
                finish_trace(
                    trace_id,
                    status="ok",
                    meta_update={"assistant_id": assistant.id},
                )
                yield _sse(
                    {
                        "type": "done",
                        "chat_id": chat_id_out,
                        "title": title_out,
                        "assistant_message": _to_message_response(assistant).model_dump(
                            mode="json"
                        ),
                        "citations": citations or None,
                        "rag_debug": rag_debug,
                        "memory_summary": memory_summary,
                        "trace_id": trace_id,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            finish_trace(trace_id, status="error", meta_update={"error": str(exc)})
            yield _sse({"type": "error", "message": f"落库失败: {exc}"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
