"""职责：Planner → 多名 Worker 的多 Agent 链路，每步结果立即流式展示。

技术点：Planner LLM 拆步；Worker 轻量执行；deliver 走 HITL 写文件；SSE delta。
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from agent.hitl import iter_hitl_while_waiting
from agent.sse_delta import iter_answer_deltas
from agent.tools import infer_export_format
from app.langsmith_setup import adopt_parent, start_span
from app.llm import chat_completion
from app.stop_signal import clear_stop, is_stopped
from app.trace import add_step, finish_trace as _finish_trace, start_trace


def _fallback_steps(task: str) -> list[dict[str, str]]:
    """功能：Planner 失败时给出启发式三步计划，保证链路仍能跑完。

    技术点：research → draft → deliver 固定动作。
    """
    short = (task or "").strip()[:40] or "任务"
    return [
        {"id": "1", "title": "调研要点", "action": "research"},
        {"id": "2", "title": f"撰写「{short}」", "action": "draft"},
        {"id": "3", "title": "导出文件", "action": "deliver"},
    ]


def _plan_steps(task: str, model: str | None = None) -> list[dict[str, str]]:
    """功能：让 Planner 模型把任务拆成 2～3 个可执行子步骤。

    技术点：约束 JSON 数组；解析失败回退启发式；末步强制 deliver。
    """
    prompt = [
        {
            "role": "user",
            "content": (
                "你是任务规划 Planner。把用户任务拆成 2～3 个可执行子步骤。\n"
                "只输出 JSON 数组，每项含 id/title/action，action 只能是：\n"
                "research（调研）、draft（写正文）、deliver（导出文件）。\n"
                "最后一步必须是 deliver。不要解释。\n\n"
                f"任务：{task}"
            ),
        }
    ]
    raw = chat_completion(prompt, model=model).strip()
    m = re.search(r"\[[\s\S]*\]", raw)
    if not m:
        return _fallback_steps(task)
    try:
        data = json.loads(m.group(0))
        steps: list[dict[str, str]] = []
        for i, item in enumerate(data[:3], 1):
            if not isinstance(item, dict):
                continue
            #todo
            action = str(item.get("action") or "draft").lower()
            if action not in {"research", "draft", "deliver"}:
                action = "draft"
            steps.append(
                {
                    "id": str(item.get("id") or i),
                    "title": str(item.get("title") or f"步骤{i}")[:80],
                    "action": action,
                }
            )
        if not steps:
            return _fallback_steps(task)
        if steps[-1]["action"] != "deliver":
            steps.append({"id": str(len(steps) + 1), "title": "导出文件", "action": "deliver"})
        return steps[:3]
    except json.JSONDecodeError:
        return _fallback_steps(task)


def _worker_execute(
    step: dict[str, str], task: str, notes: str, model: str | None = None
) -> str:
    """功能：对单步做轻量 LLM 执行（research/draft）；deliver 不走这里。

    技术点：chat_completion；不调用写文件工具，交付交给后续 HITL。
    """
    action = (step.get("action") or "draft").lower()
    title = step.get("title") or "子任务"
    if action == "research":
        instruction = (
            f"作为调研 Worker，完成「{title}」。\n"
            f"总任务：{task}\n"
            "用中文列要点（若相关：行程/美食/注意/结构），不超过 280 字。不要调用工具。"
        )
    else:
        instruction = (
            f"作为撰稿 Worker，完成「{title}」。\n"
            f"总任务：{task}\n已有调研：{notes or '无'}\n"
            "写完整中文正文（可含小标题），先结论后细节，不超过 700 字。不要调用工具。"
        )
    return chat_completion([{"role": "user", "content": instruction}], model=model).strip()


async def run_multi_agent(
    *,
    chat_id: str,
    user_id: str,
    task: str,
    model: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """功能：跑完 Planner LLM → 多名 Worker → HITL 写文件，并流式推送事件。

    技术点：SSE；asyncio.to_thread；Redis HITL；MySQL Trace + LangSmith span。
    """
    #1. 清除redis标记
    clear_stop(chat_id)
    #2. 保存Trace 可观测
    trace_id = start_trace(
        user_id=user_id,
        chat_id=chat_id,
        name="multi_agent.run",
        meta={"task": task[:200], "model": model},
    )
    #3.langSmith记录数据
    ls_span = start_span(
        name="multi_agent.run",
        tags=["multi-agent"],
        metadata={
            "chat_id": chat_id,
            "local_trace_id": trace_id,
            "user_id": user_id,
            "model": model or "",
        },
        inputs={"task": task[:400]},
    )

    def finish_trace(tid: str, **kwargs: Any) -> None:
        """功能：结束本次多 Agent 的本地 Trace，并关闭 LangSmith span。

        技术点：合并 langsmith_run_id 到 meta；finally 保证 span.close。
        """
        #取出值并转化为字典，删除之前的值，如果没有就为None
        extra = dict(kwargs.pop("meta_update", None) or {})
        #合并字典
        extra.update(ls_span.meta())
        try:
            #更新最新trace数据
            _finish_trace(tid, meta_update=extra or None, **kwargs)
        finally:
            ls_span.close()

    #4. 打印右侧标题
    yield {
        "type": "start",
        "chat_id": chat_id,
        "mode": "multi_agent",
        "task": task,
        "trace_id": trace_id,
    }
    yield {
        "type": "step",
        "index": 1,
        "kind": "think",
        "zone": "think",
        "title": "Planner · 拆解任务",
        "detail": "正在规划子步骤…",
        "status": "running",
    }
    yield {
        "type": "delta",
        "zone": "answer",
        "content": "【多 Agent】Planner 正在拆解任务…\n",
    }

    #5. 停止生成，关闭资源，更新trace，关闭langSmith
    if is_stopped(chat_id):
        finish_trace(trace_id, status="stopped")
        yield {"type": "stopped", "message": "任务开始前已停止"}
        return

    #6. 在工作线程里执行 Planner，并挂回 LangSmith 父 run
    try:
        def _plan() -> list[dict[str, str]]:
            """功能：在工作线程里执行 Planner，并挂回 LangSmith 父 run。

            技术点：adopt_parent；asyncio.to_thread 会丢 ContextVar。
            """
            with adopt_parent(ls_span.parent):
                return _plan_steps(task, model)

        #等待异步完成；在线程池里跑同步函数 _plan，避免阻塞整个 async 事件循环
        steps = await asyncio.to_thread(_plan)
    except Exception as exc:  # noqa: BLE001
        #出现异常，更新异常数据
        finish_trace(trace_id, status="error", meta_update={"error": str(exc)})
        yield {"type": "error", "message": f"Planner 失败: {exc}"}
        return

    #7. 再次检查是否停止
    if is_stopped(chat_id):
        finish_trace(trace_id, status="stopped")
        yield {"type": "stopped", "message": "规划后已停止"}
        return

    #8. 打印右边数据
    plan_text = " → ".join(s["title"] for s in steps)
    yield {
        "type": "step",
        "index": 1,
        "kind": "think",
        "zone": "think",
        "title": "Planner · 计划就绪",
        "detail": plan_text,
        "status": "done",
    }
    #追加一条已结束的 step span
    add_step(
        trace_id,
        user_id=user_id,
        chat_id=chat_id,
        name="planner",
        meta={"steps": steps},
    )
    yield {
        "type": "delta",
        "zone": "answer",
        "content": f"计划：{plan_text}\n\n",
    }

    # 9. 循环获取每步骤执行结果
    notes_parts: list[str] = []
    draft = ""
    step_index = 1
    for i, step in enumerate(steps, 1):
        if is_stopped(chat_id):
            finish_trace(trace_id, status="stopped")
            yield {
                "type": "stopped",
                "at_index": step_index,
                "message": "已停止（Planner/Worker 链路）",
            }
            return
        action = (step.get("action") or "draft").lower()
        # deliver 交给后面的 HITL 写文件，避免再打一轮「建议调用工具」的模型
        if action == "deliver":
            continue
        step_index = i + 1
        yield {
            "type": "step",
            "index": step_index,
            "kind": "tool",
            "zone": "tool",
            "title": f"Worker · {step['title']}",
            "detail": f"action={action}",
            "status": "running",
        }
        try:
            def _work() -> str:
                """功能：在工作线程里执行单个 Worker 步骤。

                技术点：adopt_parent 挂回父 run；闭包捕获当前 step。
                """
                with adopt_parent(ls_span.parent):
                    return _worker_execute(step, task, "\n".join(notes_parts), model)

            out = await asyncio.to_thread(_work)
        except Exception as exc:  # noqa: BLE001
            yield {
                "type": "step",
                "index": step_index,
                "kind": "tool",
                "zone": "tool",
                "title": f"Worker · {step['title']}",
                "detail": f"失败: {exc}",
                "status": "done",
            }
            continue
        notes_parts.append(f"## {step['title']}\n{out}")
        if action == "draft" or not draft:
            draft = out
        yield {
            "type": "step",
            "index": step_index,
            "kind": "tool",
            "zone": "tool",
            "title": f"Worker · {step['title']}",
            "detail": out[:280],
            "status": "done",
        }
        add_step(
            trace_id,
            user_id=user_id,
            chat_id=chat_id,
            name=f"worker:{action}",
            meta={"title": step.get("title")},
        )
        # 每步立刻流式展示，用户不用干等后续 Worker
        header = f"### {step['title']}\n"
        async for delta in iter_answer_deltas(header + out + "\n\n", chunk_size=16, delay_seconds=0.008):
            yield delta

    body_for_file = "\n\n".join(notes_parts).strip() or draft or "（无 Worker 输出）"
    if not draft:
        draft = body_for_file

    if is_stopped(chat_id):
        finish_trace(trace_id, status="stopped")
        yield {"type": "stopped", "message": "交付前已停止"}
        return

    export_fmt = infer_export_format(task)
    fmt_label = {"txt": "TXT 文本", "pdf": "PDF", "docx": "Word 文档(.docx)"}.get(
        export_fmt, export_fmt
    )
    export_out = ""
    step_index += 1
    yield {
        "type": "step",
        "index": step_index,
        "kind": "tool",
        "zone": "tool",
        "title": f"Worker · 导出 {fmt_label}",
        "detail": "写文件需人工批准，请在确认框选择同意或拒绝",
        "status": "running",
    }
    yield {
        "type": "delta",
        "zone": "answer",
        "content": f"——\n即将写入{fmt_label}，请在下方「批准 / 拒绝」后再继续。\n",
    }

    from agent.tools import current_chat_id, current_user_id, invoke_export
    from app.utils import public_reply_text

    current_user_id.set(user_id)
    current_chat_id.set(chat_id)
    title = task.strip().splitlines()[0][:80] or "报告"

    def _export() -> str:
        """功能：按推断格式调用写文件工具（含 HITL）。

        技术点：invoke_export；copy_context 把 ContextVar 带进 to_thread。
        """
        return invoke_export(export_fmt, title, body_for_file[:12000])

    #复制上下文
    ctx = contextvars.copy_context()
    #创建后台任务，和主线程并发跑
    export_task = asyncio.create_task(asyncio.to_thread(ctx.run, _export))
    async for event in iter_hitl_while_waiting(chat_id, export_task):
        yield event
    try:
            export_out = public_reply_text(str(await export_task))
    except Exception as exc:  # noqa: BLE001
        export_out = f"导出失败: {exc}"

    yield {
        "type": "step",
        "index": step_index,
        "kind": "tool",
        "zone": "tool",
        "title": f"Worker · 导出 {fmt_label}",
        "detail": export_out[:280],
        "status": "done",
    }
    if export_out:
        async for delta in iter_answer_deltas(f"\n{export_out}\n", chunk_size=20, delay_seconds=0.01):
            yield delta

    if is_stopped(chat_id):
        finish_trace(trace_id, status="stopped")
        yield {"type": "stopped", "message": "汇总前已停止"}
        return

    answer = f"【多 Agent 完成】\nPlanner：{plan_text}\n\n{draft}"
    if export_out:
        answer = f"{answer}\n\n——\n{export_out}"
    finish_trace(trace_id, status="ok", meta_update={"plan": plan_text})
    yield {
        "type": "step",
        "index": step_index + 1,
        "kind": "answer",
        "zone": "answer",
        "title": "汇总回答",
        "detail": answer[:200],
        "status": "done",
    }
    yield {
        "type": "done",
        "answer": answer,
        "mode": "multi_agent",
        "trace_id": trace_id,
        "total_steps": step_index + 1,
    }
