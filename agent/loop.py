"""职责：可取消的多步 Agent 演示循环（W1 D5）。

技术点：Redis is_stopped；分片 sleep；SSE 事件流。W2 真工具在 react_agent。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from app.config import get_settings
from app.stop_signal import clear_stop, is_stopped
from agent.sse_delta import iter_answer_deltas


StepKind = Literal["plan", "tool", "think", "answer"]


@dataclass(frozen=True)
class AgentStep:
    """职责：演示循环中的单步定义（kind / title / detail）。

    技术点：frozen dataclass；kind 映射前端 think/tool/answer 分区。
    """

    kind: StepKind
    title: str
    detail: str


def build_demo_steps(task: str) -> list[AgentStep]:
    """功能：根据用户任务生成演示用固定 5 步计划，便于点停止验收。

    技术点：无真实工具调用；仅模拟 plan/tool/think/answer。
    """
    short = task.strip()[:80] or "（空任务）"
    return [
        AgentStep("plan", "规划", f"拆解任务：{short}"),
        AgentStep("tool", "工具 · 检索", "模拟调用 search 工具收集信息…"),
        AgentStep("tool", "工具 · 处理", "模拟调用处理器整理中间结果…"),
        AgentStep("think", "思考", "汇总工具结果并起草回答…"),
        AgentStep("answer", "回答", f"已完成对「{short}」的多步处理。"),
    ]


async def _sleep_interruptible(chat_id: str, seconds: float) -> bool:
    """功能：可中断睡眠，期间收到停止信号则返回 True。

    技术点：拆成小片 asyncio.sleep，提高点停止响应速度。
    """
    # 拆成小片 sleep，提高「点停止」响应速度
    slices = max(1, int(seconds / 0.15))
    slice_len = seconds / slices
    for _ in range(slices):
        if is_stopped(chat_id):
            return True
        await asyncio.sleep(slice_len)
    return is_stopped(chat_id)


async def run_cancellable_agent(
    *,
    chat_id: str,
    task: str,
) -> AsyncIterator[dict[str, Any]]:
    """功能：异步生成演示 Agent 事件流（start/step/stopped/done + 打字机 delta）。

    技术点：每步前后轮询 is_stopped；结束后 iter_answer_deltas 推 SSE 打字机。
    """
    settings = get_settings()
    delay = max(0.2, float(settings.agent_step_delay_seconds))
    steps = build_demo_steps(task)

    clear_stop(chat_id)
    yield {
        "type": "start",
        "chat_id": chat_id,
        "total_steps": len(steps),
        "task": task,
    }

    for index, step in enumerate(steps, start=1):
        # 进入下一步前检查
        if is_stopped(chat_id):
            yield {
                "type": "stopped",
                "at_index": index,
                "message": f"已在第 {index} 步开始前停止，后续 step 不会执行",
            }
            return

        yield {
            "type": "step",
            "index": index,
            "kind": step.kind,
            "title": step.title,
            "detail": step.detail,
            "status": "running",
        }

        # 模拟耗时工作；期间可被停止
        if await _sleep_interruptible(chat_id, delay):
            yield {
                "type": "stopped",
                "at_index": index,
                "message": f"已在第 {index} 步执行中停止，不会继续后续 step",
            }
            return

        yield {
            "type": "step",
            "index": index,
            "kind": step.kind,
            "title": step.title,
            "detail": step.detail,
            "status": "done",
        }

    # 全部完成后再检查一次（理论上不应再停）
    if is_stopped(chat_id):
        yield {
            "type": "stopped",
            "at_index": len(steps) + 1,
            "message": "任务结束前收到停止信号",
        }
        return

    final = steps[-1].detail if steps else "完成"
    async for delta in iter_answer_deltas(final):
        yield delta
    yield {
        "type": "done",
        "answer": final,
        "total_steps": len(steps),
    }
