"""职责：Agent 配置版本存储与加载（企业级治理 Phase1）。

技术点：MySQL 版本行；is_active 切换；表缺失回退内存默认。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.db import SessionLocal
from app.logging_json import log_event
from app.models import AgentConfig
from app.utils import new_id, utcnow

DEFAULT_SYSTEM_PROMPT = (
    "你是枝枝 AI 多步 Agent，必须通过工具完成可交付产物。\n"
    "效率：search_web≤2、search_images≤1；按用户格式调用 write_text_file / create_pdf_report / create_doc_report。"
)

DEFAULT_TOOLS = [
    "search_web",
    "write_text_file",
    "create_pdf_report",
    "create_doc_report",
    "search_images",
]


@dataclass
class AgentRuntimeConfig:
    """职责：运行时生效的配置快照（prompt / 工具白名单 / HITL / 超时）。

    技术点：dataclass；与 AgentConfig 行解耦，便于无库降级。
    """

    version: str
    name: str
    system_prompt: str
    tools: list[str]
    max_tool_calls: int
    timeout_seconds: int
    hitl_enabled: bool


def _in_memory_default() -> AgentRuntimeConfig:
    """功能：表不存在或未开库时返回内置默认配置，保证超级智能体仍能跑。

    技术点：内存快照；不写库。
    """
    return AgentRuntimeConfig(
        version="v1",
        name="default",
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        tools=DEFAULT_TOOLS[:],
        max_tool_calls=8,
        timeout_seconds=180,
        hitl_enabled=True,
    )


def _is_missing_table(exc: BaseException) -> bool:
    """功能：判断是否为「表不存在」类错误，便于回退内存配置。

    技术点：MySQL 1146；doesn't exist 文案兼容。
    """
    msg = str(exc).lower()
    return "1146" in msg or "doesn't exist" in msg


def _row_to_runtime(row: AgentConfig) -> AgentRuntimeConfig:
    """功能：把 ORM 行转成运行时配置快照。

    技术点：tools_json 解析；非法 JSON 回退默认工具列表。
    """
    tools = DEFAULT_TOOLS[:]
    if row.tools_json:
        try:
            parsed = json.loads(row.tools_json)
            if isinstance(parsed, list) and parsed:
                tools = [str(x) for x in parsed]
        except json.JSONDecodeError:
            pass
    return AgentRuntimeConfig(
        version=row.version,
        name=row.name,
        system_prompt=(row.system_prompt or DEFAULT_SYSTEM_PROMPT).strip(),
        tools=tools,
        max_tool_calls=int(row.max_tool_calls or 8),
        timeout_seconds=int(row.timeout_seconds or 180),
        hitl_enabled=bool(row.hitl_enabled),
    )


def ensure_default_config(user_id: str) -> AgentRuntimeConfig:
    """功能：确保用户有一条激活配置；没有则创建 v1。

    技术点：软删过滤 is_del；表未建时回退内存默认，避免 1146。
    """
    if SessionLocal is None:
        return _in_memory_default()
    try:
        with SessionLocal() as db:
            row = db.scalar(
                select(AgentConfig).where(
                    AgentConfig.user_id == user_id,
                    AgentConfig.is_active == 1,
                    AgentConfig.is_del == 0,
                )
            )
            if row:
                return _row_to_runtime(row)
            now = utcnow()
            row = AgentConfig(
                id=new_id(),
                user_id=user_id,
                version="v1",
                name="default",
                system_prompt=DEFAULT_SYSTEM_PROMPT,
                tools_json=json.dumps(DEFAULT_TOOLS, ensure_ascii=False),
                max_tool_calls=8,
                timeout_seconds=180,
                hitl_enabled=1,
                is_active=1,
                create_date=now,
                update_date=now,
                is_del=0,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return _row_to_runtime(row)
    except (ProgrammingError, OperationalError) as exc:
        if not _is_missing_table(exc):
            raise
        log_event(
            "agent_config.table_missing",
            user_id=user_id,
            code="SCHEMA_MISSING",
        )
        return _in_memory_default()


def get_active_config(user_id: str) -> AgentRuntimeConfig:
    """功能：读取当前用户激活中的 Agent 配置。

    技术点：委托 ensure_default_config，无激活行时自动建 v1。
    """
    return ensure_default_config(user_id)


def list_configs(user_id: str) -> list[AgentConfig]:
    """功能：列出当前用户全部未删除的配置版本。

    技术点：按 user_id 隔离；软删 is_del=0。
    """
    if SessionLocal is None:
        return []
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(AgentConfig)
                .where(AgentConfig.user_id == user_id, AgentConfig.is_del == 0)
                .order_by(AgentConfig.update_date.desc())
            ).all()
        )


def upsert_active_config(
    user_id: str,
    *,
    system_prompt: str | None = None,
    tools: list[str] | None = None,
    max_tool_calls: int | None = None,
    timeout_seconds: int | None = None,
    hitl_enabled: bool | None = None,
    name: str | None = None,
    bump_version: bool = True,
) -> AgentRuntimeConfig:
    """功能：更新当前激活配置；默认生成新 version 并切换激活。

    技术点：bump_version 插新行并把旧行 is_active=0；否则原地改激活行。
    """
    current = ensure_default_config(user_id)
    if SessionLocal is None:
        return current

    with SessionLocal() as db:
        active = db.scalar(
            select(AgentConfig).where(
                AgentConfig.user_id == user_id,
                AgentConfig.is_active == 1,
                AgentConfig.is_del == 0,
            )
        )
        now = utcnow()
        new_version = current.version
        if bump_version:
            # v1 -> v2；或时间戳后缀
            if current.version.startswith("v") and current.version[1:].isdigit():
                new_version = f"v{int(current.version[1:]) + 1}"
            else:
                new_version = now.strftime("v%Y%m%d%H%M%S")

        prompt = system_prompt if system_prompt is not None else current.system_prompt
        tool_list = tools if tools is not None else current.tools
        max_calls = max_tool_calls if max_tool_calls is not None else current.max_tool_calls
        timeout = timeout_seconds if timeout_seconds is not None else current.timeout_seconds
        hitl = current.hitl_enabled if hitl_enabled is None else hitl_enabled
        cfg_name = name if name is not None else current.name

        if bump_version:
            if active:
                active.is_active = 0
                active.update_date = now
            row = AgentConfig(
                id=new_id(),
                user_id=user_id,
                version=new_version,
                name=cfg_name,
                system_prompt=prompt,
                tools_json=json.dumps(tool_list, ensure_ascii=False),
                max_tool_calls=max_calls,
                timeout_seconds=timeout,
                hitl_enabled=1 if hitl else 0,
                is_active=1,
                create_date=now,
                update_date=now,
                is_del=0,
            )
            db.add(row)
        else:
            if not active:
                return ensure_default_config(user_id)
            active.system_prompt = prompt
            active.tools_json = json.dumps(tool_list, ensure_ascii=False)
            active.max_tool_calls = max_calls
            active.timeout_seconds = timeout
            active.hitl_enabled = 1 if hitl else 0
            active.name = cfg_name
            active.update_date = now
            row = active

        db.commit()
        db.refresh(row)
        return _row_to_runtime(row)


def activate_version(user_id: str, version: str) -> AgentRuntimeConfig | None:
    """功能：把指定历史版本切为当前激活配置。

    技术点：先整用户 is_active=0，再点亮目标 version；找不到返回 None。
    """
    if SessionLocal is None:
        return None
    with SessionLocal() as db:
        target = db.scalar(
            select(AgentConfig).where(
                AgentConfig.user_id == user_id,
                AgentConfig.version == version,
                AgentConfig.is_del == 0,
            )
        )
        if not target:
            return None
        now = utcnow()
        db.execute(
            update(AgentConfig)
            .where(AgentConfig.user_id == user_id, AgentConfig.is_del == 0)
            .values(is_active=0, update_date=now)
        )
        target.is_active = 1
        target.update_date = now
        db.commit()
        db.refresh(target)
        return _row_to_runtime(target)
