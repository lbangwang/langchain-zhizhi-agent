"""会话与消息 CRUD 路由（W1 D2 + D4 JWT）。

- 所有接口需 Bearer token
- 归属用户一律取自 JWT，禁止伪造他人 `user_id`
- 对外路径使用业务字段 `chat_id`；消息外键挂会话表主键 `conversation.id`
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import AppUser, Conversation, Message
from app.schemas import (
    ApiResult,
    ConversationResponse,
    CreateConversationRequest,
    CreateMessageRequest,
    MessageResponse,
    UpdateConversationRequest,
)
from app.utils import new_id, utcnow

router = APIRouter(prefix="/conversations", tags=["会话与消息"])


def _get_owned_conversation(
    db: Session, chat_id: str, user_id: str
) -> Conversation | None:
    """功能：按 chat_id + JWT 用户取未删除会话（越权直接当不存在）。

    技术点：归属校验写在 WHERE，不要先查再比 user_id（避免时序漏洞习惯）。
    """
    return db.scalar(
        select(Conversation).where(
            Conversation.chat_id == chat_id,
            Conversation.user_id == user_id,
            Conversation.is_del == 0,
        )
    )


def _to_message_response(msg: Message) -> MessageResponse:
    """功能：消息 ORM → 响应模型。

    技术点：库字段 metadata_json 对外叫 metadata，避免和 SQLAlchemy metadata 冲突。
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


@router.post("", response_model=ApiResult[ConversationResponse])
def create_conversation(
    body: CreateConversationRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[ConversationResponse]:
    """功能：为当前用户新建会话（首页进 Agent 会打这个）。

    技术点：chat_id 对外、id 做主键；user_id 只取 JWT，忽略请求体伪造。
    """
    chat_id = body.chat_id or new_id()
    if db.scalar(
        select(Conversation).where(Conversation.chat_id == chat_id, Conversation.is_del == 0)
    ):
        return ApiResult.fail("chat_id 已存在")

    now = utcnow()
    create_by = body.create_by or current_user.id
    conv = Conversation(
        id=new_id(),
        chat_id=chat_id,
        user_id=current_user.id,
        agent_type=body.agent_type,
        title=body.title,
        model=body.model,
        status=1,
        create_date=now,
        create_by=create_by,
        update_date=now,
        update_by=create_by,
        is_del=0,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return ApiResult.ok(ConversationResponse.model_validate(conv))


@router.get("", response_model=ApiResult[list[ConversationResponse]])
def list_conversations(
    agent_type: str | None = Query(default=None, description="可选：按智能体类型过滤"),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[list[ConversationResponse]]:
    """功能：列当前用户会话，可按 agent_type 过滤（工作台隔离历史）。

    技术点：Query 可选参数；按 update_date 倒序。
    """
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == current_user.id, Conversation.is_del == 0)
        .order_by(Conversation.update_date.desc())
    )
    if agent_type:
        stmt = stmt.where(Conversation.agent_type == agent_type)
    rows = db.scalars(stmt).all()
    return ApiResult.ok([ConversationResponse.model_validate(r) for r in rows])


@router.get("/{chat_id}", response_model=ApiResult[ConversationResponse])
def get_conversation(
    chat_id: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[ConversationResponse]:
    """功能：查单个会话详情。

    技术点：走 _get_owned_conversation，别人的 chat_id 返回不存在。
    """
    conv = _get_owned_conversation(db, chat_id, current_user.id)
    if not conv:
        return ApiResult.fail("会话不存在")
    return ApiResult.ok(ConversationResponse.model_validate(conv))


@router.put("/{chat_id}", response_model=ApiResult[ConversationResponse])
def update_conversation(
    chat_id: str,
    body: UpdateConversationRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[ConversationResponse]:
    """功能：部分更新标题 / 模型 / 状态。

    技术点：Pydantic 可选字段 None 表示不改（PATCH 语义用 PUT 实现）。
    """
    conv = _get_owned_conversation(db, chat_id, current_user.id)
    if not conv:
        return ApiResult.fail("会话不存在")

    if body.title is not None:
        conv.title = body.title
    if body.model is not None:
        conv.model = body.model
    if body.status is not None:
        conv.status = body.status
    conv.update_date = utcnow()
    conv.update_by = body.update_by or current_user.id
    db.commit()
    db.refresh(conv)
    return ApiResult.ok(ConversationResponse.model_validate(conv))


@router.delete("/{chat_id}", response_model=ApiResult[None])
def delete_conversation(
    chat_id: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[None]:
    """功能：软删会话，并级联软删其下未删除消息。

    技术点：is_del=1 而非 DELETE；避免残留消息被列表读出。
    """
    conv = _get_owned_conversation(db, chat_id, current_user.id)
    if not conv:
        return ApiResult.fail("会话不存在")

    now = utcnow()
    uid = current_user.id
    conv.is_del = 1
    conv.update_date = now
    conv.update_by = uid

    messages = db.scalars(
        select(Message).where(Message.conversation_id == conv.id, Message.is_del == 0)
    ).all()
    for msg in messages:
        msg.is_del = 1
        msg.update_date = now
        msg.update_by = uid

    db.commit()
    return ApiResult.ok(None)


@router.post("/{chat_id}/messages", response_model=ApiResult[MessageResponse])
def add_message(
    chat_id: str,
    body: CreateMessageRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[MessageResponse]:
    """功能：向会话追加一条消息，并刷新会话时间。

    技术点：消息外键挂 conversation.id（主键），路径仍用 chat_id。
    """
    conv = _get_owned_conversation(db, chat_id, current_user.id)
    if not conv:
        return ApiResult.fail("会话不存在")

    now = utcnow()
    create_by = body.create_by or current_user.id
    msg = Message(
        id=new_id(),
        conversation_id=conv.id,
        role=body.role,
        content=body.content,
        metadata_json=body.metadata,
        create_date=now,
        create_by=create_by,
        update_date=now,
        update_by=create_by,
        is_del=0,
    )
    conv.update_date = now
    conv.update_by = create_by
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return ApiResult.ok(_to_message_response(msg))


@router.get("/{chat_id}/messages", response_model=ApiResult[list[MessageResponse]])
def list_messages(
    chat_id: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[list[MessageResponse]]:
    """功能：按时间正序列出未删除消息（工作台拉历史）。

    技术点：软删过滤；正序方便聊天气泡从上往下排。
    """
    conv = _get_owned_conversation(db, chat_id, current_user.id)
    if not conv:
        return ApiResult.fail("会话不存在")

    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conv.id, Message.is_del == 0)
        .order_by(Message.create_date.asc())
    ).all()
    return ApiResult.ok([_to_message_response(m) for m in rows])
