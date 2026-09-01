"""职责：文档切分策略（企业常用，面向业务可读）。

技术点：LangChain TextSplitter；recursive/paragraph/markdown/window/token 多策略。
"""

from __future__ import annotations

from typing import Any

from langchain_text_splitters import (
    CharacterTextSplitter,
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
    TokenTextSplitter,
)


# 策略元数据：前端下拉 + 动态参数表单
STRATEGY_DEFS: list[dict[str, Any]] = [
    {
        "id": "recursive",
        "name": "智能递归切分",
        "badge": "推荐",
        "summary": "按段落→句子→字词逐级切开，兼顾语义完整与长度可控，企业知识库最常用。",
        "suitable": "通用制度、说明书、FAQ、混合格式文档",
        "params": [
            {
                "key": "chunk_size",
                "label": "单块最大字数",
                "default": 800,
                "min": 100,
                "max": 4000,
                "step": 50,
                "hint": "越大上下文越完整，但检索颗粒越粗",
            },
            {
                "key": "chunk_overlap",
                "label": "块间重叠字数",
                "default": 120,
                "min": 0,
                "max": 800,
                "step": 10,
                "hint": "相邻块重复一段，避免句子被拦腰截断",
            },
        ],
    },
    {
        "id": "paragraph",
        "name": "按自然段落切分",
        "badge": "",
        "summary": "优先按空行分段，短段落自动合并；适合公文、周报、叙述性正文。",
        "suitable": "规章制度、会议纪要、文章正文",
        "params": [
            {
                "key": "chunk_size",
                "label": "段落合并上限（字）",
                "default": 1000,
                "min": 100,
                "max": 4000,
                "step": 50,
                "hint": "超过此长度的段落会再细分",
            },
            {
                "key": "chunk_overlap",
                "label": "短段合并阈值（字）",
                "default": 80,
                "min": 0,
                "max": 500,
                "step": 10,
                "hint": "短于该阈值的段落会尝试与下一段合并",
            },
        ],
    },
    {
        "id": "markdown",
        "name": "按标题结构切分",
        "badge": "",
        "summary": "先按一至三级标题切开，再对过长章节二次切分；适合带目录的 Markdown / 技术文档。",
        "suitable": "README、产品手册、技术方案、Wiki",
        "params": [
            {
                "key": "chunk_size",
                "label": "章节内块大小（字）",
                "default": 900,
                "min": 100,
                "max": 4000,
                "step": 50,
                "hint": "单个标题下内容过长时按此长度再切",
            },
            {
                "key": "chunk_overlap",
                "label": "章节内重叠（字）",
                "default": 100,
                "min": 0,
                "max": 800,
                "step": 10,
                "hint": "二次切分时的重叠量",
            },
        ],
    },
    {
        "id": "window",
        "name": "按固定长度切分",
        "badge": "",
        "summary": "按固定字数滑动窗口切分，规则简单可预期；语义边界较弱。",
        "suitable": "日志、流水文本、无清晰段落结构的内容",
        "params": [
            {
                "key": "chunk_size",
                "label": "每块字数",
                "default": 500,
                "min": 50,
                "max": 3000,
                "step": 50,
                "hint": "每块目标长度",
            },
            {
                "key": "chunk_overlap",
                "label": "滑动重叠字数",
                "default": 50,
                "min": 0,
                "max": 500,
                "step": 10,
                "hint": "窗口每次前进时保留的重叠",
            },
        ],
    },
    {
        "id": "token",
        "name": "按模型 Token 切分",
        "badge": "进阶",
        "summary": "按大模型 token 预算切块，便于控制提示词长度；适合对上下文窗口敏感的场景。",
        "suitable": "长文喂给大模型、严格控制上下文成本",
        "params": [
            {
                "key": "chunk_size",
                "label": "每块 Token 数",
                "default": 400,
                "min": 50,
                "max": 2000,
                "step": 20,
                "hint": "约等于模型侧 token；中文场景可略小于字数",
            },
            {
                "key": "chunk_overlap",
                "label": "重叠 Token 数",
                "default": 40,
                "min": 0,
                "max": 400,
                "step": 10,
                "hint": "块之间重叠的 token 数量",
            },
        ],
    },
]

# 兼容旧接口
STRATEGY_CHOICES = tuple((d["id"], d["name"]) for d in STRATEGY_DEFS)


def get_strategy_def(strategy_id: str) -> dict[str, Any] | None:
    """功能：按 id/别名查找切分策略元数据（前端下拉用）。

    技术点：别名映射 character→window；未知 id 回退第一条（recursive）。
    """
    key = (strategy_id or "").lower().strip()
    aliases = {
        "recursivecharacter": "recursive",
        "character": "window",  # 对外不再单独展示 Character，映射到固定长度
        "charactertext": "window",
        "md": "markdown",
        "markdownheader": "markdown",
        "tokens": "token",
        "char": "window",
        "langchain": "recursive",
    }
    key = aliases.get(key, key)
    for item in STRATEGY_DEFS:
        if item["id"] == key:
            return item
    return STRATEGY_DEFS[0]


def default_params_for(strategy_id: str) -> dict[str, int]:
    """功能：返回某策略的默认 chunk_size / chunk_overlap。

    技术点：从 STRATEGY_DEFS.params 取 default。
    """
    meta = get_strategy_def(strategy_id) or STRATEGY_DEFS[0]
    return {p["key"]: int(p["default"]) for p in meta.get("params", [])}


def split_by_paragraph(
    text: str,
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 80,
) -> list[str]:
    """功能：按空行分段，过长段再切窗；短段可与下一段合并。

    技术点：自然段落；不足阈值合并；超长回退 split_window。
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    paras = [p.strip() for p in cleaned.replace("\r\n", "\n").split("\n\n") if p.strip()]
    if not paras:
        return split_window(cleaned, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    merged: list[str] = []
    buf = ""
    for p in paras:
        if not buf:
            buf = p
            continue
        if len(buf) < max(40, chunk_overlap) and len(buf) + 1 + len(p) <= chunk_size:
            buf = f"{buf}\n\n{p}"
            continue
        if len(buf) + 1 + len(p) <= chunk_size:
            buf = f"{buf}\n\n{p}"
        else:
            merged.extend(
                split_window(buf, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            )
            buf = p
    if buf:
        merged.extend(
            split_window(buf, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        )
    return merged


def split_window(
    text: str,
    *,
    chunk_size: int = 500,
    chunk_overlap: int = 80,
) -> list[str]:
    """功能：按固定字符长度滑动窗口切分。

    技术点：chunk_overlap 滑动；无语义边界，适合日志类文本。
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    size = max(50, int(chunk_size))
    overlap = max(0, min(int(chunk_overlap), size - 1))
    if len(cleaned) <= size:
        return [cleaned]

    chunks: list[str] = []
    start = 0
    n = len(cleaned)
    while start < n:
        end = min(start + size, n)
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(0, end - overlap)
    return chunks


def split_recursive(
    text: str,
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 80,
) -> list[str]:
    """功能：用 LangChain RecursiveCharacterTextSplitter 按段落→句子→字词逐级切。

    技术点：RecursiveCharacterTextSplitter；中文分隔符（。！？；）。
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=max(50, int(chunk_size)),
        chunk_overlap=max(0, int(chunk_overlap)),
        # 中文友好：段落 / 句号 / 换行 / 空白 / 字符
        separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""],
        length_function=len,
        is_separator_regex=False,
    )
    return [c.strip() for c in splitter.split_text(text) if c and c.strip()]


def split_character(
    text: str,
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 80,
) -> list[str]:
    """功能：按双换行分隔符切分再合并到目标长度。

    技术点：CharacterTextSplitter；separator=\\n\\n。
    """
    splitter = CharacterTextSplitter(
        separator="\n\n",
        chunk_size=max(50, int(chunk_size)),
        chunk_overlap=max(0, int(chunk_overlap)),
        length_function=len,
        is_separator_regex=False,
    )
    return [c.strip() for c in splitter.split_text(text) if c and c.strip()]


def split_markdown_headers(
    text: str,
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 80,
) -> list[str]:
    """功能：先按 Markdown 一至三级标题拆，再对过长块做 Recursive 二次切分。

    技术点：MarkdownHeaderTextSplitter；失败则整篇走 recursive。
    """
    headers = [("#", "h1"), ("##", "h2"), ("###", "h3")]
    try:
        md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers)
        docs = md_splitter.split_text(text)
        parts = []
        for d in docs:
            meta = " / ".join(str(v) for v in (d.metadata or {}).values() if v)
            body = (d.page_content or "").strip()
            if meta and body:
                parts.append(f"{meta}\n{body}")
            elif body:
                parts.append(body)
        joined = "\n\n".join(parts) if parts else text
    except Exception:  # noqa: BLE001
        joined = text
    return split_recursive(
        joined, chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )


def split_token(
    text: str,
    *,
    chunk_size: int = 400,
    chunk_overlap: int = 40,
) -> list[str]:
    """功能：按近似 token 预算切块；无 tiktoken 时退回字符估算。

    技术点：TokenTextSplitter；失败按 1 token≈2 中文字符改走 recursive。
    """
    try:
        splitter = TokenTextSplitter(
            chunk_size=max(50, int(chunk_size)),
            chunk_overlap=max(0, int(chunk_overlap)),
        )
        return [c.strip() for c in splitter.split_text(text) if c and c.strip()]
    except Exception:  # noqa: BLE001
        # 约 1 token ≈ 2 中文字符的粗估
        return split_recursive(
            text,
            chunk_size=max(50, int(chunk_size) * 2),
            chunk_overlap=max(0, int(chunk_overlap) * 2),
        )


def split_document(
    text: str,
    *,
    strategy: str = "recursive",
    chunk_size: int = 800,
    chunk_overlap: int = 80,
) -> list[str]:
    """功能：统一切分入口，按 strategy 分发到各 splitter。

    技术点：recursive/paragraph/markdown/window/token/character；兼容旧前端别名。
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    key = (strategy or "recursive").lower().strip()
    # 兼容旧前端取值
    aliases = {
        "recursivecharacter": "recursive",
        "recursive_character": "recursive",
        "langchain": "recursive",
        "char": "window",
        "chars": "window",
    }
    key = aliases.get(key, key)

    if key in {"window"}:
        return split_window(
            cleaned, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
    if key in {"paragraph"}:
        return split_by_paragraph(
            cleaned, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
    if key in {"character", "charactertext"}:
        return split_character(
            cleaned, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
    if key in {"markdown", "md", "markdownheader"}:
        return split_markdown_headers(
            cleaned, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
    if key in {"token", "tokens"}:
        return split_token(
            cleaned, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
    # 默认 recursive
    return split_recursive(
        cleaned, chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )


# 兼容旧名
split_text = split_window
