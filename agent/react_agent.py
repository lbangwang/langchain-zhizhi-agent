"""职责：用 LangGraph/LangChain create_agent 跑真工具，事件形态对齐 W1 SSE。

技术点：create_agent；ToolCallLimit / Summarization 中间件；HITL；停止/超时取消。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware, ToolCallLimitMiddleware
from langchain_openai import ChatOpenAI

from agent.config_store import AgentRuntimeConfig, get_active_config
from agent.hitl import clear_hitl_pending, get_hitl_pending, iter_hitl_while_waiting
from agent.skills_loader import skills_system_block
from agent.sse_delta import iter_answer_deltas
from agent.tools import (
    CORE_TOOLS,
    current_chat_id,
    current_config_version,
    current_user_id,
)
from app.config import get_settings
from app.errors import AGENT_TIMEOUT
from app.logging_json import log_event
from app.model_router import resolve_llm
from app.stop_signal import clear_stop, is_stopped
from app.langsmith_setup import adopt_parent, start_span
from app.trace import add_step, finish_trace as _finish_trace, start_trace
from app.usage import harvest_langchain_messages, langchain_usage_callback


def _build_chat_model(model_id: str | None = None) -> ChatOpenAI:
    """功能：按前端 model（qwen/doubao/deepseek）构建 ChatOpenAI。

    技术点：resolve_llm 路由 Key；langchain_usage_callback 记 token。
    """
    settings = get_settings()
    timeout = float(getattr(settings, "llm_timeout_seconds", 60) or 60)
    resolved = resolve_llm(model_id, settings)
    kwargs: dict[str, Any] = {
        "model": resolved.model,
        "api_key": resolved.api_key,
        "base_url": resolved.base_url,
        "temperature": 0.3,
        "timeout": timeout,
    }
    cb = langchain_usage_callback()
    if cb is not None:
        kwargs["callbacks"] = [cb]
    try:
        return ChatOpenAI(**kwargs, stream_usage=True)
    except TypeError:
        return ChatOpenAI(**kwargs)


def build_tool_agent(cfg: AgentRuntimeConfig | None = None, model_id: str | None = None):
    """功能：构建带搜索/写文件/PDF/图片搜索工具的 Agent（含配置版本）。

    技术点：create_agent；工具白名单过滤；ToolCallLimitMiddleware。
    """
    model = _build_chat_model(model_id)
    skill_block = skills_system_block()
    cfg = cfg or AgentRuntimeConfig(
        version="v1",
        name="default",
        system_prompt="",
        tools=[t.name for t in CORE_TOOLS],
        max_tool_calls=8,
        timeout_seconds=180,
        hitl_enabled=True,
    )
    base_prompt = (cfg.system_prompt or "").strip() or (
        "你是枝枝 AI 多步 Agent，必须通过工具完成可交付产物。\n"
        "Skill：system 仅含目录索引；需要细则时先 load_skill(skill_id)，单轮最多 2 次。\n"
        "效率：search_web≤2、search_images≤1；按用户要求调用 "
        "write_text_file / create_pdf_report / create_doc_report（Word .docx）。"
    )
    # skill_block 仅为索引，全文由 load_skill 按需加载（方案 B）
    system_prompt = (
        f"{base_prompt}\n"
        f"{skill_block}\n"
        f"（config_version={cfg.version}）"
    )
    # 按配置白名单过滤工具
    name_set = set(cfg.tools or [])
    tools = [t for t in CORE_TOOLS if getattr(t, "name", None) in name_set] or list(
        CORE_TOOLS
    )
    # 旧版 DB 白名单可能无 load_skill：强制并入，否则索引无法按需展开
    if not any(getattr(t, "name", None) == "load_skill" for t in tools):
        tools = [
            t for t in CORE_TOOLS if getattr(t, "name", None) == "load_skill"
        ] + list(tools)
    middleware: list = [
        ToolCallLimitMiddleware(
            run_limit=max(1, int(cfg.max_tool_calls or 8)),
            exit_behavior="continue",
        ),
    ]
    try:
        middleware.append(
            SummarizationMiddleware(
                model=model,
                trigger=("messages", 16),
                keep=("messages", 8),
            )
        )
    except Exception:  # noqa: BLE001
        pass

    return create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=middleware,
    )


def _task_wants_export(task: str) -> bool:
    """功能：根据任务文案判断用户是否要求导出文件。

    技术点：关键词匹配（pdf/docx/报告/导出等）。
    """
    t = (task or "").lower()
    keys = (
        "pdf", "doc", "docx", "txt", "word", "文档",
        "报告", "攻略", "导出", "纪要", "生成文件", "写入",
    )
    return any(k in t for k in keys)


def _force_export_from_answer(title: str, body: str, task: str) -> str:
    """功能：模型漏调写文件工具时按用户指定格式兜底落盘。

    技术点：infer_export_format；invoke_export 含 HITL。
    """
    from agent.tools import infer_export_format, invoke_export

    return invoke_export(
        infer_export_format(task),
        title[:80] or "任务报告",
        (body or "")[:12000] or "（正文为空）",
    )


def _collect_tool_names(messages: list) -> set[str]:
    """功能：从 LangChain 消息里收集实际调用过的工具名。

    技术点：解析 AIMessage.tool_calls 与 ToolMessage.name。
    """
    names: set[str] = set()
    for msg in messages:
        msg_type = getattr(msg, "type", "") or ""
        if msg_type == "tool":
            name = getattr(msg, "name", None)
            if name:
                names.add(str(name))
        if msg_type == "ai" and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                if name:
                    names.add(str(name))
    return names


def _extract_final_answer(result: dict[str, Any]) -> str:
    """功能：从 create_agent 的 messages 里抽出最终助手正文。

    技术点：倒序跳过 ToolMessage；优先无 tool_calls 的 AIMessage。
    """
    messages = result.get("messages") or []
    for msg in reversed(messages):
        content = getattr(msg, "content", None)
        if isinstance(content, str) and content.strip():
            role = getattr(msg, "type", None) or getattr(msg, "role", None)
            if role in {"tool", "ToolMessage"}:
                continue
            if role in {"ai", "assistant", None} and not getattr(msg, "tool_calls", None):
                return content.strip()
            if role in {"ai", "assistant"} and not getattr(msg, "tool_calls", None):
                return content.strip()
    for msg in reversed(messages):
        content = getattr(msg, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
    return "任务完成"


def _classify_step_kind(title: str, kind: str) -> str:
    """功能：把步骤 kind/title 映射到前端分区 think / tool / answer。

    技术点：前端 zone 三分区；含「工具/结果」归 tool。
    """
    if kind == "answer":
        return "answer"
    if "工具" in title or "结果" in title or kind == "tool":
        return "tool"
    return "think"


async def run_tool_agent(
    *,
    chat_id: str,
    user_id: str,
    task: str,
    model: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """功能：异步生成工具 Agent 事件流（规划、工具步、HITL、打字机、done）。

    技术点：create_agent.invoke 放 to_thread；轮询 HITL pending；停止/超时 cancel。
    """
    # 清除上次停止标记、否则信任我立刻停止
    clear_stop(chat_id)
    current_user_id.set(user_id)
    current_chat_id.set(chat_id)
    cfg = get_active_config(user_id)
    current_config_version.set(cfg.version)
    # 配置级 HITL 覆盖全局开关（临时写入 settings 风格：用 context 更干净）
    import agent.hitl as hitl_mod

    hitl_mod._runtime_hitl_override = cfg.hitl_enabled  # type: ignore[attr-defined]

    import time

    started = time.monotonic()
    timeout = float(cfg.timeout_seconds or get_settings().agent_timeout_seconds)
    trace_id = start_trace(
        user_id=user_id,
        chat_id=chat_id,
        name="agent.run",
        meta={"task": task[:200], "config_version": cfg.version, "model": model},
    )
    log_event(
        "agent.run.start",
        user_id=user_id,
        chat_id=chat_id,
        trace_id=trace_id,
        config_version=cfg.version,
        model=model,
    )
    # 可关：未开 LangSmith 时 span 为空操作；结束时写入 langsmith_run_id
    ls_span = start_span(
        name="agent.run",
        tags=["super-agent", "create_agent"],
        metadata={
            "chat_id": chat_id,
            "local_trace_id": trace_id,
            "user_id": user_id,
            "model": model or "",
            "config_version": cfg.version,
        },
        inputs={"task": task[:400]},
    )

    def finish_trace(tid: str, **kwargs: Any) -> None:
        """功能：结束本次 Agent 运行的本地 Trace，并关闭 LangSmith span。

        技术点：合并 langsmith_run_id；finally 保证 span.close。
        """
        extra = dict(kwargs.pop("meta_update", None) or {})
        extra.update(ls_span.meta())
        try:
            _finish_trace(tid, meta_update=extra or None, **kwargs)
        finally:
            ls_span.close()

    yield {
        "type": "start",
        "chat_id": chat_id,
        "total_steps": 0,
        "task": task,
        "mode": "create_agent",
        "trace_id": trace_id,
        "config_version": cfg.version,
        "model": model,
    }
    yield {
        "type": "step",
        "index": 0,
        "kind": "think",
        "zone": "think",
        "title": "思考 · 规划",
        "detail": f"[{cfg.version}] 分析任务并选择工具：{task[:120]}",
        "status": "running",
    }

    if is_stopped(chat_id):
        finish_trace(trace_id, status="stopped")
        yield {
            "type": "stopped",
            "at_index": 0,
            "message": "任务开始前已停止",
        }
        return

    agent = build_tool_agent(cfg, model_id=model)
    step_index = 0
    seen_hitl: set[str] = set()

    def _invoke() -> dict[str, Any]:
        """功能：在工作线程里 invoke create_agent。

        技术点：to_thread 会丢 ContextVar，用 adopt_parent 把父 run 挂回。
        """
        # to_thread 会丢 contextvar，这里把父 run 挂回工作线程
        with adopt_parent(ls_span.parent):
            return agent.invoke({"messages": [{"role": "user", "content": task}]})

    invoke_task = asyncio.create_task(asyncio.to_thread(_invoke))
    while not invoke_task.done():
        # HITL：工具线程写入 pending 后，这里推给前端
        pending = get_hitl_pending(chat_id)
        if pending:
            rid = str(pending.get("request_id") or "")
            if rid and rid not in seen_hitl:
                seen_hitl.add(rid)
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
        if is_stopped(chat_id):
            # 立刻结束 SSE：不再 await 整段 invoke（否则前端会卡在 agentRunning）
            clear_hitl_pending(chat_id)
            finish_trace(trace_id, status="stopped")
            yield {
                "type": "stopped",
                "at_index": step_index or 1,
                "message": "已停止。后台模型回合将被丢弃，可重新发起任务。",
            }
            # 取消等待；线程内工具会因 is_stopped 跳过后续写操作
            invoke_task.cancel()
            return
        if time.monotonic() - started > timeout:
            clear_hitl_pending(chat_id)
            finish_trace(trace_id, status="timeout")
            log_event(
                "agent.run.timeout",
                user_id=user_id,
                chat_id=chat_id,
                trace_id=trace_id,
                code=AGENT_TIMEOUT.code,
                config_version=cfg.version,
            )
            yield AGENT_TIMEOUT.to_dict()
            yield {
                "type": "stopped",
                "at_index": step_index or 1,
                "message": "因超时已结束",
                "code": AGENT_TIMEOUT.code,
            }
            invoke_task.cancel()
            return
        await asyncio.sleep(0.25)

    try:
        result = invoke_task.result()
    except Exception as exc:  # noqa: BLE001
        finish_trace(trace_id, status="error", meta_update={"error": str(exc)})
        yield {"type": "error", "message": str(exc)}
        return

    yield {
        "type": "step",
        "index": 0,
        "kind": "think",
        "zone": "think",
        "title": "思考 · 规划",
        "detail": "规划完成，开始执行工具",
        "status": "done",
    }

    messages = result.get("messages") or []
    harvest_langchain_messages(messages)
    for msg in messages:
        msg_type = getattr(msg, "type", "") or ""
        if msg_type == "ai" and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                step_index += 1
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "tool")
                args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                yield {
                    "type": "step",
                    "index": step_index,
                    "kind": "tool",
                    "zone": "tool",
                    "title": f"工具 · {name}",
                    "detail": str(args)[:240],
                    "status": "done",
                }
                add_step(
                    trace_id,
                    user_id=user_id,
                    chat_id=chat_id,
                    name=f"tool:{name}",
                    meta={"args": str(args)[:200]},
                )
        elif msg_type == "tool":
            step_index += 1
            name = getattr(msg, "name", "tool")
            content = getattr(msg, "content", "") or ""
            yield {
                "type": "step",
                "index": step_index,
                "kind": "tool",
                "zone": "tool",
                "title": f"结果 · {name}",
                "detail": str(content)[:280],
                "status": "done",
            }

    answer = _extract_final_answer(result)
    called = _collect_tool_names(messages)
    export_tools = {"create_pdf_report", "create_doc_report", "write_text_file"}

    if _task_wants_export(task) and not (called & export_tools) and not is_stopped(chat_id):
        from agent.tools import infer_export_format

        fmt = infer_export_format(task)
        step_index += 1
        yield {
            "type": "step",
            "index": step_index,
            "kind": "tool",
            "zone": "tool",
            "title": f"工具 · 导出 {fmt}",
            "detail": "模型未主动导出，系统按用户指定格式兜底（需人工批准）…",
            "status": "running",
        }
        try:
            short_title = task.strip().splitlines()[0][:40]
            export_task = asyncio.create_task(
                asyncio.to_thread(_force_export_from_answer, short_title, answer, task)
            )
            async for event in iter_hitl_while_waiting(chat_id, export_task):
                yield event
            export_out = str(await export_task)
            yield {
                "type": "step",
                "index": step_index,
                "kind": "tool",
                "zone": "tool",
                "title": f"结果 · 导出 {fmt}",
                "detail": export_out[:280],
                "status": "done",
            }
            answer = f"{answer.rstrip()}\n\n——\n{export_out}"
        except Exception as exc:  # noqa: BLE001
            yield {
                "type": "step",
                "index": step_index,
                "kind": "tool",
                "zone": "tool",
                "title": f"结果 · 导出 {fmt}",
                "detail": f"兜底导出失败: {exc}",
                "status": "done",
            }

    if is_stopped(chat_id):
        finish_trace(trace_id, status="stopped")
        yield {
            "type": "stopped",
            "at_index": step_index + 1,
            "message": "任务结束前收到停止信号",
        }
        return

    step_index += 1
    yield {
        "type": "step",
        "index": step_index,
        "kind": "answer",
        "zone": "answer",
        "title": "回答",
        "detail": answer[:200],
        "status": "done",
    }
    finish_trace(
        trace_id,
        status="ok",
        meta_update={
            "answer_preview": answer[:200],
            "tools": sorted(called),
            "config_version": cfg.version,
        },
    )
    # 打字机：先推 delta，再 done（前端边收边渲染）
    async for delta in iter_answer_deltas(answer):
        yield delta
    yield {
        "type": "done",
        "answer": answer,
        "total_steps": step_index,
        "mode": "create_agent",
        "trace_id": trace_id,
        "config_version": cfg.version,
    }
