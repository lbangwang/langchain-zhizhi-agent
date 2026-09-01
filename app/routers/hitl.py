"""HITL 审批接口（W3 D3）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.hitl import submit_hitl_decision
from app.db import get_db
from app.deps import get_current_user
from app.models import AppUser, Conversation
from app.schemas import ApiResult

router = APIRouter(prefix="/conversations", tags=["HITL"])


class HitlDecisionRequest(BaseModel):
    request_id: str = Field(min_length=1)
    decision: str = Field(description="approve | reject")


@router.post("/{chat_id}/hitl/decide", response_model=ApiResult[dict])
def hitl_decide(
    chat_id: str,
    body: HitlDecisionRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[dict]:
    """功能：批准或拒绝危险工具（写文件 / PDF / Word）。

    技术点：校验会话归属；decision 写入 Redis，阻塞中的工具协程被唤醒。
    """
    conv = db.scalar(
        select(Conversation).where(
            Conversation.chat_id == chat_id,
            Conversation.user_id == current_user.id,
            Conversation.is_del == 0,
        )
    )
    if not conv:
        return ApiResult.fail("会话不存在")
    decision = body.decision.strip().lower()
    if decision not in {"approve", "reject"}:
        return ApiResult.fail("decision 须为 approve 或 reject")
    ok = submit_hitl_decision(
        chat_id=chat_id, request_id=body.request_id, decision=decision
    )
    if not ok:
        return ApiResult.fail("提交失败（可能 Redis 未启用）")
    return ApiResult.ok(
        {"chat_id": chat_id, "request_id": body.request_id, "decision": decision}
    )
