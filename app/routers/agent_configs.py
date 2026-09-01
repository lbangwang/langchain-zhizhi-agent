"""Agent 配置版本 API（企业级治理）。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agent.config_store import (
    activate_version,
    ensure_default_config,
    list_configs,
    upsert_active_config,
)
from app.deps import get_current_user
from app.errors import CONFIG_NOT_FOUND
from app.models import AppUser
from app.quota import get_quota_status
from app.schemas import (
    AgentConfigResponse,
    AgentConfigUpdateRequest,
    ApiResult,
    QuotaResponse,
)

router = APIRouter(prefix="/agent-configs", tags=["Agent 配置"])


def _to_resp(row) -> AgentConfigResponse:
    """功能：配置表行 → API 响应（tools_json 转 list）。

    技术点：JSON 反序列化失败当空列表，避免整页 500。
    """
    tools: list[str] = []
    if getattr(row, "tools_json", None):
        try:
            tools = json.loads(row.tools_json) or []
        except json.JSONDecodeError:
            tools = []
    return AgentConfigResponse(
        id=row.id,
        version=row.version,
        name=row.name,
        system_prompt=row.system_prompt,
        tools=tools if isinstance(tools, list) else [],
        max_tool_calls=row.max_tool_calls,
        timeout_seconds=row.timeout_seconds,
        hitl_enabled=bool(row.hitl_enabled),
        is_active=bool(row.is_active),
        create_date=row.create_date,
        update_date=row.update_date,
    )


@router.get("/active", response_model=ApiResult[AgentConfigResponse])
def get_active(current_user: AppUser = Depends(get_current_user)) -> ApiResult[AgentConfigResponse]:
    """功能：取当前激活的 agent_config，没有则创建 v1。

    技术点：ensure_default_config；缺表时内存默认（见 config_store）。
    """
    ensure_default_config(current_user.id)
    rows = list_configs(current_user.id)
    active = next((r for r in rows if r.is_active), None)
    if not active:
        return ApiResult.fail(CONFIG_NOT_FOUND.message)
    return ApiResult.ok(_to_resp(active))


@router.get("", response_model=ApiResult[list[AgentConfigResponse]])
def list_all(current_user: AppUser = Depends(get_current_user)) -> ApiResult[list[AgentConfigResponse]]:
    """功能：列出该用户全部配置版本。

    技术点：JWT 隔离；Swagger 可讲版本治理，前端配置页未做。
    """
    ensure_default_config(current_user.id)
    return ApiResult.ok([_to_resp(r) for r in list_configs(current_user.id)])


@router.put("/active", response_model=ApiResult[AgentConfigResponse])
def update_active(
    body: AgentConfigUpdateRequest,
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[AgentConfigResponse]:
    """功能：更新激活配置，默认可 bump 新版本。

    技术点：写库后按 version 再读 ORM，保证返回带 id。
    """
    cfg = upsert_active_config(
        current_user.id,
        system_prompt=body.system_prompt,
        tools=body.tools,
        max_tool_calls=body.max_tool_calls,
        timeout_seconds=body.timeout_seconds,
        hitl_enabled=body.hitl_enabled,
        name=body.name,
        bump_version=body.bump_version,
    )
    # 再读 ORM 行以便返回 id
    rows = list_configs(current_user.id)
    active = next((r for r in rows if r.version == cfg.version), None)
    if not active:
        return ApiResult.fail("更新失败")
    return ApiResult.ok(_to_resp(active))


class ActivateBody(BaseModel):
    version: str = Field(min_length=1)


@router.post("/activate", response_model=ApiResult[AgentConfigResponse])
def activate(
    body: ActivateBody,
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[AgentConfigResponse]:
    """功能：把某个历史 version 设为激活。

    技术点：同用户下其它版本 is_active 关掉。
    """
    cfg = activate_version(current_user.id, body.version)
    if not cfg:
        return ApiResult.fail(CONFIG_NOT_FOUND.message)
    rows = list_configs(current_user.id)
    active = next((r for r in rows if r.version == cfg.version), None)
    if not active:
        return ApiResult.fail(CONFIG_NOT_FOUND.message)
    return ApiResult.ok(_to_resp(active))


@router.get("/quota", response_model=ApiResult[QuotaResponse])
def quota(current_user: AppUser = Depends(get_current_user)) -> ApiResult[QuotaResponse]:
    """功能：查询当前用户 Agent 日配额余量。

    技术点：读 Redis 计数；未开 Redis 时 remaining=limit。
    """
    st = get_quota_status(current_user.id)
    return ApiResult.ok(QuotaResponse(**st))
