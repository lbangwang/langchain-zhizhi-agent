"""职责：短记忆压缩——长对话超阈值时摘要旧消息，保留近轮续聊。

技术点：LLM 摘要；旧消息换成一条 system；保留最近 keep_recent 轮。
"""

from __future__ import annotations

from app.config import get_settings
from app.llm import chat_completion


def should_summarize(messages: list[dict[str, str]], *, trigger: int | None = None) -> bool:
    """功能：判断 user/assistant 条数是否达到摘要阈值。

    技术点：不计 system；阈值来自 settings.memory_summarize_trigger。
    """
    settings = get_settings()
    limit = trigger if trigger is not None else settings.memory_summarize_trigger
    # 不计 system
    n = sum(1 for m in messages if m.get("role") in {"user", "assistant"})
    return n >= limit


def summarize_and_trim(
    messages: list[dict[str, str]],
    *,
    keep_recent: int | None = None,
) -> tuple[list[dict[str, str]], str | None]:
    """功能：把较早对话压成一条摘要 system，只保留最近若干轮原文。

    技术点：LLM chat_completion 摘要；去掉旧【对话历史摘要】避免叠层。
    """
    settings = get_settings()
    keep = keep_recent if keep_recent is not None else settings.memory_keep_recent
    if not should_summarize(messages):
        return messages, None

    # 分离已有 system / 对话
    systems = [m for m in messages if m.get("role") == "system"]
    dialog = [m for m in messages if m.get("role") in {"user", "assistant"}]
    if len(dialog) <= keep:
        return messages, None

    older = dialog[:-keep]
    recent = dialog[-keep:]
    blob = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in older)
    prompt = [
        {
            "role": "user",
            "content": (
                "请将以下多轮对话压缩为简洁中文摘要，保留用户目标、关键事实、未完成事项。"
                "不要编造。只输出摘要正文。\n\n"
                f"{blob}"
            ),
        }
    ]
    try:
        summary = chat_completion(prompt).strip()
    except Exception:  # noqa: BLE001
        summary = "（摘要失败，已截断较早消息）"

    summary_msg = {
        "role": "system",
        "content": f"【对话历史摘要】\n{summary}",
    }
    # 保留非摘要类 system（如 RAG），去掉旧摘要
    other_systems = [
        m
        for m in systems
        if not str(m.get("content") or "").startswith("【对话历史摘要】")
    ]
    return [*other_systems, summary_msg, *recent], summary
