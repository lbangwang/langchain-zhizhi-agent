"""职责：检索优化——查询改写 + 多路召回 RRF 融合 + 简易 LLM Rerank。

技术点：rewrite；RRF；LLM rerank；@traced 可选 LangSmith。
"""

from __future__ import annotations

from collections import defaultdict

from app.config import get_settings
from app.langsmith_setup import traced
from app.llm import chat_completion
from rag.rerank import bge_rerank
from rag.store import RetrievedChunk, search_dense


def rewrite_query(query: str) -> str:
    """功能：用 LLM 把口语问题改写成更适合向量检索的短查询；失败回退原文。

    技术点：chat_completion；只取第一行，避免模型夹带解释。
    """
    prompt = [
        {
            "role": "user",
            "content": (
                "你是检索查询改写器。把用户问题改写成更适合向量检索的短查询，"
                "保留关键实体与意图，不要回答问题。只输出改写后的查询。\n"
                f"用户问题：{query}"
            ),
        }
    ]
    try:
        out = chat_completion(prompt).strip().splitlines()[0].strip()
        return out or query
    except Exception:  # noqa: BLE001
        return query


def _rrf_fuse(
    ranked_lists: list[list[RetrievedChunk]],
    *,
    k: int = 60,
    top_k: int = 4,
) -> list[RetrievedChunk]:
    """功能：用 Reciprocal Rank Fusion 融合多路召回列表。

    技术点：RRF score=1/(k+rank)；同 id 保留更高 dense score 的原文。
    """
    scores: dict[str, float] = defaultdict(float)
    best: dict[str, RetrievedChunk] = {}
    for ranked in ranked_lists:
        for rank, chunk in enumerate(ranked, start=1):
            scores[chunk.id] += 1.0 / (k + rank)
            prev = best.get(chunk.id)
            if prev is None or chunk.score > prev.score:
                best[chunk.id] = chunk
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    fused: list[RetrievedChunk] = []
    for cid, rrf_score in ordered:
        c = best[cid]
        fused.append(
            RetrievedChunk(
                id=c.id,
                doc_id=c.doc_id,
                filename=c.filename,
                chunk_index=c.chunk_index,
                text=c.text,
                user_id=c.user_id,
                score=rrf_score,
            )
        )
    return fused


def llm_rerank(query: str, chunks: list[RetrievedChunk], *, top_k: int) -> list[RetrievedChunk]:
    """功能：让 LLM 按与问题相关性重排候选片段。

    技术点：输出逗号分隔序号；解析失败回退原顺序截断。
    """
    if len(chunks) <= 1:
        return chunks[:top_k]
    numbered = "\n\n".join(
        f"[{i}] ({c.filename}) {c.text[:280]}" for i, c in enumerate(chunks, start=1)
    )
    prompt = [
        {
            "role": "user",
            "content": (
                f"问题：{query}\n\n候选片段：\n{numbered}\n\n"
                f"请按与问题相关性从高到低输出最多 {top_k} 个序号，"
                "仅输出逗号分隔数字，例如：2,1,3"
            ),
        }
    ]
    try:
        raw = chat_completion(prompt)
        idxs: list[int] = []
        for part in raw.replace("，", ",").split(","):
            part = "".join(ch for ch in part if ch.isdigit())
            if part:
                idxs.append(int(part))
        picked: list[RetrievedChunk] = []
        seen: set[int] = set()
        for i in idxs:
            if 1 <= i <= len(chunks) and i not in seen:
                seen.add(i)
                picked.append(chunks[i - 1])
            if len(picked) >= top_k:
                break
        # 补齐
        for i, c in enumerate(chunks, start=1):
            if i not in seen:
                picked.append(c)
            if len(picked) >= top_k:
                break
        return picked[:top_k]
    except Exception:  # noqa: BLE001
        return chunks[:top_k]


@traced("rag.retrieve", run_type="retriever")
def retrieve(
    query: str,
    *,
    user_id: str | None = None,
    top_k: int | None = None,
    use_rewrite: bool | None = None,
    use_rerank: bool | None = None,
) -> tuple[list[RetrievedChunk], dict]:
    """功能：统一检索入口：dense 召回，可选改写双路 RRF，再可选 LLM rerank。

    技术点：rewrite + RRF + rerank；返回 (chunks, debug_info)。
    """
    settings = get_settings()
    k = top_k or settings.rag_top_k
    do_rewrite = settings.rag_use_rewrite if use_rewrite is None else use_rewrite
    do_rerank = settings.rag_use_rerank if use_rerank is None else use_rerank

    debug: dict = {"query": query, "rewritten": None, "mode": "dense"}

    # 基线：原 query dense：把问题变成向量，在 Milvus 里找最相似的文档块；先召回8条
    baseline = search_dense(query, user_id=user_id, top_k=max(k, 8))

    ranked_lists = [baseline]
    if do_rewrite:
        #用户问题改写，把用户的语句改写成适合大模型的语句
        rewritten = rewrite_query(query)
        debug["rewritten"] = rewritten
        if rewritten.strip() and rewritten.strip() != query.strip():
            #将改写前和改写后检索到文档存入变量中ranked_lists
            ranked_lists.append(
                search_dense(rewritten, user_id=user_id, top_k=max(k, 8))
            )
            debug["mode"] = "rewrite+rrf"

    #合并两个查询出来的片段（两路排名靠前、综合分数较高、相同ID去最高的）
    fused = _rrf_fuse(ranked_lists, top_k=max(k, 8)) if len(ranked_lists) > 1 else baseline

    if do_rerank and fused:
        backend = (settings.rag_rerank_backend or "bge").lower()
        if backend == "bge":
            #精排模型
            fused = bge_rerank(query, fused, top_k=k)
            debug["mode"] = f"{debug['mode']}+bge_rerank"
        elif backend == "llm":
            # 精排：让 LLM 按与问题相关性重排候选片段
            fused = llm_rerank(query, fused, top_k=k)
            debug["mode"] = f"{debug['mode']}+llm_rerank"
    else:
        fused = fused[:k]

    debug["hit_count"] = len(fused)
    return fused, debug


def retrieve_baseline(query: str, *, user_id: str | None = None, top_k: int = 4):
    """功能：仅做稠密向量检索，供评测对比优化链路。

    技术点：search_dense；无 rewrite/RRF/rerank。
    """
    return search_dense(query, user_id=user_id, top_k=top_k)
