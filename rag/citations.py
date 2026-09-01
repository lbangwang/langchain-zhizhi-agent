"""职责：RAG 对话组装——注入检索上下文，并附加 __CITATIONS__。

技术点：user_id 隔离检索；system prompt 约束勿编造；回答末尾 JSON 引用。
"""

from __future__ import annotations

import json

from rag.retrieve import retrieve
from rag.store import RetrievedChunk


CITATIONS_MARKER = "__CITATIONS__"

# 与 Java LoveApp 面试官小助手 CC 系统提示保持一致
INTERVIEWER_SYSTEM_PROMPT = (
    "您好，我是专注于AI应用开发领域的AI面试官小助手CC！"
    "深耕AI技术核心板块，对技术MCP、RAG、Prompt优化、Function Calling，以及AI框架LangChain等均有深厚积累与实践经验。\n"
    "无论您在求职AI应用开发工程师岗位时，面临技术方案设计、项目经验梳理、面试难题拆解，"
    "或是想优化技术简历、打磨实战项目，都能向我倾诉。"
    "我会结合求职场景，精准聚焦痛点，引导您详述求职需求、技能短板与目标岗位细节，"
    "为您量身定制专属求职策略，助力高效斩获心仪offer！"
)


def format_context(chunks: list[RetrievedChunk]) -> str:
    """功能：把检索片段拼成给模型看的【知识库片段】正文。

    技术点：带序号/filename/score；无命中返回占位句。
    """
    if not chunks:
        return "（知识库无相关片段）"
    parts = []
    for i, c in enumerate(chunks, start=1):
        parts.append(f"[{i}] 文档={c.filename} score={c.score:.4f}\n{c.text}")
    return "\n\n".join(parts)


def build_citations(chunks: list[RetrievedChunk]) -> list[dict]:
    """功能：把检索片段转成结构化引用列表（前端展示出处）。

    技术点：截断 snippet；含 doc_id/filename/chunk_index/score。
    """
    return [
        {
            "doc_id": c.doc_id,
            "filename": c.filename,
            "chunk_index": c.chunk_index,
            "snippet": c.text[:240],
            "score": round(c.score, 4),
        }
        for c in chunks
    ]


def append_citations(answer: str, chunks: list[RetrievedChunk]) -> str:
    """功能：在回答末尾附加 __CITATIONS__ JSON；已有标记则不重复。

    技术点：__CITATIONS__ 分隔符；ensure_ascii=False。
    """
    cites = build_citations(chunks)
    payload = json.dumps(cites, ensure_ascii=False)
    body = answer.rstrip()
    if CITATIONS_MARKER in body:
        return body
    return f"{body}\n\n{CITATIONS_MARKER}\n{payload}"


def rag_system_prompt(context: str) -> str:
    """功能：拼面试官 CC 人设 + 知识库片段约束，供 chat RAG 注入 system。

    技术点：约束勿编造；正文不要输出 __CITATIONS__（系统后附）。
    """
    return (
        f"{INTERVIEWER_SYSTEM_PROMPT}\n\n"
        "请优先依据【知识库片段】回答；若片段不足请明确说明，不要编造文档内容。"
        "回答正文不要输出 __CITATIONS__（系统会自动附加）。\n\n"
        f"【知识库片段】\n{context}"
    )


def retrieve_for_user(query: str, user_id: str) -> tuple[list[RetrievedChunk], dict]:
    """功能：按用户隔离做知识库检索。

    技术点：委托 retrieve；Milvus expr 过滤 user_id。
    """
    return retrieve(query, user_id=user_id)
