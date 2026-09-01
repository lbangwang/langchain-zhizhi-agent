"""职责：LLM Token 用量采集，写入 Trace meta 供统计页汇总。

技术点：ContextVar + trace_id 索引 UsageBag，避免线程切换丢上下文。

约定：
- 一次 Trace 对应一个 `UsageBag`（ContextVar + trace_id 索引，避免线程切换丢上下文）。
- `chat_completion` / LangChain `on_llm_end` 把供应商返回的 usage 累加进去。
- `finish_trace` 把袋中数字写入根 span 的 `meta_json`，供统计页汇总。
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

_usage_bag: ContextVar["UsageBag | None"] = ContextVar("llm_usage_bag", default=None)
# finish_trace 时按 trace_id 取袋，不依赖调用栈是否仍持有 ContextVar
_bags_by_trace: dict[str, "UsageBag"] = {}


@dataclass
class UsageBag:
    """职责：单次请求内各次 LLM 调用的累计 token。

    技术点：prompt/completion/total 三字段；由 ContextVar 挂到当前 Trace。
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int | None = None,
    ) -> None:
        """功能：把一次 LLM 的 token 累加进当前袋。

        技术点：未给 total 时用 prompt+completion；无活动 Trace 时上层不调用。
        """
        p = int(prompt_tokens or 0)
        c = int(completion_tokens or 0)
        t = int(total_tokens) if total_tokens is not None else p + c
        self.prompt_tokens += p
        self.completion_tokens += c
        self.total_tokens += t

    def as_meta(self) -> dict[str, int]:
        """功能：转成写入 Trace meta_json 的三个整数字段。

        技术点：prompt_tokens / completion_tokens / total_tokens。
        """
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


def bind_usage(trace_id: str) -> UsageBag:
    """功能：开始一次 Trace 的 token 统计。

    技术点：ContextVar 给当前协程；dict 按 trace_id 索引，避免线程切换丢袋。
    """
    bag = UsageBag()
    _usage_bag.set(bag)
    if trace_id:
        _bags_by_trace[trace_id] = bag
    return bag


def pop_usage(trace_id: str | None) -> dict[str, int]:
    """功能：结束 Trace 时取出累计 token 并解绑。

    技术点：优先按 trace_id 从 dict 取，再回退 ContextVar。
    """
    bag = _bags_by_trace.pop(trace_id, None) if trace_id else None
    if bag is None:
        bag = _usage_bag.get()
    _usage_bag.set(None)
    if bag is None:
        return {}
    return bag.as_meta()


def record_usage(
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int | None = None,
) -> None:
    """功能：把一次 usage 记入当前袋；没有活动 Trace 则忽略。

    技术点：全 0 不记，避免空包污染统计。
    """
    bag = _usage_bag.get()
    if bag is None:
        return
    if not prompt_tokens and not completion_tokens and not total_tokens:
        return
    bag.add(prompt_tokens, completion_tokens, total_tokens)


def parse_usage(raw: Any) -> tuple[int, int, int]:
    """功能：从 OpenAI / LangChain 各种 usage 形态解析三个整数。

    技术点：兼容 prompt_tokens 与 input_tokens 两套字段名。
    """
    if raw is None:
        return 0, 0, 0
    if not isinstance(raw, dict):
        raw = {
            "prompt_tokens": getattr(raw, "prompt_tokens", None),
            "completion_tokens": getattr(raw, "completion_tokens", None),
            "total_tokens": getattr(raw, "total_tokens", None),
            "input_tokens": getattr(raw, "input_tokens", None),
            "output_tokens": getattr(raw, "output_tokens", None),
        }
    prompt = int(raw.get("prompt_tokens") or raw.get("input_tokens") or 0)
    completion = int(raw.get("completion_tokens") or raw.get("output_tokens") or 0)
    total = int(raw.get("total_tokens") or 0)
    if not total:
        total = prompt + completion
    return prompt, completion, total


def record_usage_raw(raw: Any) -> None:
    """功能：解析供应商 usage 对象并记入当前袋。

    技术点：parse_usage 兼容多字段名后再 record_usage。
    """
    prompt, completion, total = parse_usage(raw)
    record_usage(prompt, completion, total)


def harvest_langchain_messages(messages: list[Any]) -> None:
    """功能：invoke 结束后从 AIMessage 补记 token（回调没记到时）。

    技术点：袋里已有数字则跳过，避免与 on_llm_end 重复累加。
    """
    bag = _usage_bag.get()
    if bag is None or bag.total_tokens or bag.prompt_tokens:
        return
    for msg in messages:
        meta = getattr(msg, "usage_metadata", None)
        if meta:
            record_usage_raw(meta)
            continue
        resp_meta = getattr(msg, "response_metadata", None) or {}
        if isinstance(resp_meta, dict):
            record_usage_raw(resp_meta.get("token_usage") or resp_meta.get("usage"))


def langchain_usage_callback():
    """功能：构造 LangChain 回调，每次 LLM 结束写 token。

    技术点：BaseCallbackHandler.on_llm_end；未安装 langchain 则返回 None。
    """
    try:
        from langchain_core.callbacks import BaseCallbackHandler
    except ImportError:  # pragma: no cover
        return None

    class LlmUsageCallback(BaseCallbackHandler):
        """职责：把 LLMResult / AIMessage 上的 usage 记入当前 Trace。

        技术点：BaseCallbackHandler.on_llm_end。
        """

        def on_llm_end(self, response: Any, **kwargs: Any) -> None:  # noqa: ARG002
            """功能：LLM 结束时从 llm_output 或 usage_metadata 累加 token。

            技术点：优先 token_usage；再扫 generations 上的 AIMessage。
            """
            llm_output = getattr(response, "llm_output", None) or {}
            if isinstance(llm_output, dict):
                raw = llm_output.get("token_usage") or llm_output.get("usage")
                if raw:
                    record_usage_raw(raw)
                    return
            generations = getattr(response, "generations", None) or []
            for gen_list in generations:
                for gen in gen_list or []:
                    msg = getattr(gen, "message", None)
                    meta = getattr(msg, "usage_metadata", None) if msg is not None else None
                    if meta:
                        record_usage_raw(meta)

    return LlmUsageCallback()
