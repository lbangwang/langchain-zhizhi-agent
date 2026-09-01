"""通用工具函数：业务 ID、UTC 时间、会话标题、对外回复脱敏。

技术点：UUID4；naive UTC（对齐 MySQL DATETIME）；正则去掉产物内部路径。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4


def new_id() -> str:
    """功能：生成 32 位业务主键（无横线 UUID）。

    技术点：uuid4().hex；表字段 CHAR(32)，与前端 userId / chatId 同一套。
    """
    return uuid4().hex


def utcnow() -> datetime:
    """功能：取当前 UTC 时间，去掉 tzinfo 后写入 MySQL。

    技术点：DATETIME 不带时区；全程 naive UTC，避免本机时区混进库。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


# 创建会话时的占位标题；收到用户第一问后应改成「【模式】首问」
_PLACEHOLDER_TITLES = frozenset(
    {
        "",
        "新对话",
        "新会话",
        "面试官小助手",
        "多 Agent",
        "多Agent",
        "超级智能体",
    }
)

_TITLE_PREFIX = {
    "MULTI_AGENT": "【多Agent】",
    "SUPER_AGENT": "【超级智能体】",
    "INTERVIEWER": "【面试官】",
}

_STRIP_PREFIXES = (
    "【多 Agent】",
    "【多Agent】",
    "【超级智能体】",
    "【面试官】",
)

# 用户气泡里不应出现的内部路径 / 库字段
_ARTIFACT_NOISE = re.compile(
    r"artifact_id=[A-Za-z0-9]+"
    r"|/api/artifacts/[A-Za-z0-9_\-./]+"
    r"|（Word 文档 \.docx，可用 Word/WPS 打开）"
)


def is_placeholder_title(title: str | None) -> bool:
    """功能：判断会话标题是否还是创建时的占位名（应用第一问覆盖）。

    技术点：frozenset 成员检测；空标题也视为占位。
    """
    return (title or "").strip() in _PLACEHOLDER_TITLES


def conversation_title(agent_type: str | None, first_question: str) -> str:
    """功能：用「【模式】首问摘要」生成历史列表标题。

    技术点：按 agent_type 加前缀；循环剥已有【】避免重复；超 28 字截断。
    """
    q = " ".join((first_question or "").strip().split())
    changed = True
    while changed:
        changed = False
        for p in _STRIP_PREFIXES:
            if q.startswith(p):
                q = q[len(p) :].lstrip()
                changed = True
    if len(q) > 28:
        q = q[:28] + "…"
    prefix = _TITLE_PREFIX.get((agent_type or "").upper(), "")
    if not q:
        return f"{prefix}新对话" if prefix else "新对话"
    return f"{prefix}{q}" if prefix else q


def public_reply_text(text: str) -> str:
    """功能：给前端展示前去掉 artifact_id、下载 URL 等内部细节。

    技术点：正则替换；折叠多余逗号空格，避免脱敏后标点难看。
    """
    cleaned = _ARTIFACT_NOISE.sub("", text or "")
    cleaned = re.sub(r"可通过", "", cleaned)
    cleaned = re.sub(r"，\s*下载\s*，", "，", cleaned)
    cleaned = re.sub(r"，\s*下载\s*", "，", cleaned)
    cleaned = re.sub(r"[，,]{2,}", "，", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip(" ，,")
