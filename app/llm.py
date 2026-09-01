"""简易 LLM 调用（支持千问 / 豆包 / DeepSeek 切换）。

优先按请求中的 `model`（qwen|doubao|deepseek）走 `app.model_router`；
未传时默认千问。Key 均未配置时返回本地占位回复，便于前端演示。
"""

from __future__ import annotations

from collections.abc import Iterator

from openai import OpenAI

from app.config import Settings, get_settings
from app.langsmith_setup import traced
from app.model_router import DEFAULT_MODEL, build_openai_client, normalize_model_id
from app.usage import record_usage_raw


def resolve_llm_client(
    settings: Settings | None = None,
    model: str | None = None,
) -> tuple[OpenAI | None, str, str]:
    """功能：按 model 拿到 OpenAI 客户端；所选不可用则回退其它供应商。

    技术点：OpenAI 兼容协议；全部失败 client=None，上层走占位回复。
    """
    settings = settings or get_settings()
    mid = normalize_model_id(model)
    try:
        return build_openai_client(mid, settings)
    except RuntimeError:
        # 所选模型不可用时，尝试回退到已配置的供应商
        for fallback in (DEFAULT_MODEL, "deepseek", "doubao"):
            if fallback == mid:
                continue
            try:
                return build_openai_client(fallback, settings)
            except RuntimeError:
                continue
        return None, "", "echo"


def _prepare_messages(
    messages: list[dict[str, str]],
    settings: Settings,
    model: str | None = None,
) -> tuple[OpenAI | None, str, list[dict[str, str]]]:
    """功能：补上默认 system，并解析 client/模型名。

    技术点：已有 system 则不重复插入，避免盖掉 RAG 面试官人设。
    """
    client, model_name, _provider = resolve_llm_client(settings, model=model)
    has_system = any(m.get("role") == "system" for m in messages)
    final_messages = (
        messages
        if has_system
        else [
            {
                "role": "system",
                "content": "你是枝枝 AI 助手，回答简洁有用。",
            },
            *messages,
        ]
    )
    return client, model_name, final_messages


@traced("llm.chat_completion", run_type="chain")
def chat_completion(
    messages: list[dict[str, str]],
    settings: Settings | None = None,
    model: str | None = None,
) -> str:
    """功能：非流式 chat.completions，返回完整助手文本。

    技术点：OpenAI SDK；record_usage_raw 记 token；无 Key 本地占位。
    """
    settings = settings or get_settings()
    client, model_name, final_messages = _prepare_messages(messages, settings, model=model)
    if client is None:
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        return (
            f"（本地占位回复，未配置可用模型 Key）\n"
            f"已收到：{last_user[:200]}"
        )

    resp = client.chat.completions.create(
        model=model_name,
        messages=final_messages,
        temperature=0.7,
    )
    record_usage_raw(getattr(resp, "usage", None))
    content = resp.choices[0].message.content or ""
    return content.strip() or "（模型返回空内容）"


def chat_completion_stream(
    messages: list[dict[str, str]],
    settings: Settings | None = None,
    model: str | None = None,
) -> Iterator[str]:
    """功能：流式输出文本 delta，供 SSE 打字机。

    技术点：生成器 yield；stream_options.include_usage 记 token，网关不认则降级。
    """
    settings = settings or get_settings()
    client, model_name, final_messages = _prepare_messages(messages, settings, model=model)
    if client is None:
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        text = (
            f"（本地占位回复，未配置可用模型 Key）\n"
            f"已收到：{last_user[:200]}"
        )
        for ch in text:
            yield ch
        return

    create_kwargs: dict = {
        "model": model_name,
        "messages": final_messages,
        "temperature": 0.7,
        "stream": True,
    }
    try:
        # 末包带 usage；部分兼容网关不认该参数，失败则退回普通流
        stream = client.chat.completions.create(
            **create_kwargs,
            stream_options={"include_usage": True},
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "stream_options" in msg or "unexpected" in msg or "unknown" in msg:
            stream = client.chat.completions.create(**create_kwargs)
        else:
            raise
    last_usage = None
    for chunk in stream:
        usage = getattr(chunk, "usage", None)
        if usage:
            last_usage = usage
        try:
            delta = chunk.choices[0].delta.content or ""
        except (AttributeError, IndexError, KeyError):
            delta = ""
        if delta:
            yield delta
    record_usage_raw(last_usage)
