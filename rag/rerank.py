"""职责：bge-reranker-v2-m3 精排（硅基流动 /v1/rerank）。

技术点：HTTP POST /rerank；按 rag_score 阈值过滤；不足 top_k 不补齐。
"""

from __future__ import annotations

import httpx

from app.config import get_settings
from rag.store import RetrievedChunk


def bge_rerank(
    query: str,
    chunks: list[RetrievedChunk],
    *,
    top_k: int,
) -> list[RetrievedChunk]:
    """功能：用 bge-reranker 按相关性重排，仅保留分数 ≥ rag_score 的片段。

    技术点：硅基 /v1/rerank；低分丢弃；不够 top_k 也不用原序补齐；失败回退截断。
    """
    if len(chunks) <= 1:
        return chunks[:top_k]

    settings = get_settings()
    if not settings.siliconflow_api_key:
        return chunks[:top_k]

    base = (settings.siliconflow_base_url or "https://api.siliconflow.cn/v1").rstrip("/")
    model = settings.rerank_model or "BAAI/bge-reranker-v2-m3"
    documents = [(c.text or "")[:2000] for c in chunks]
    # 相关度下限：低于此分的不进入返回列表
    rag_score = float(getattr(settings, "rag_score", None) or 0.5)

    try:
        # 可参考硅基平台 API 文档：对全部候选打分，再本地按阈值与 top_k 截断
        resp = httpx.post(
            f"{base}/rerank",
            headers={
                "Authorization": f"Bearer {settings.siliconflow_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "query": query,
                "documents": documents,
                "top_n": len(documents),
                "return_documents": False,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        # 常见字段：results = [{index, relevance_score}, ...]
        results = data.get("results") or data.get("data") or []
        ordered: list[RetrievedChunk] = []
        seen: set[int] = set()
        for item in results:
            idx = int(item.get("index", -1))
            if not (0 <= idx < len(chunks)) or idx in seen:
                continue
            seen.add(idx)
            c = chunks[idx]
            score = float(item.get("relevance_score") or item.get("score") or c.score)
            # 相似度不足阈值：直接跳过，不补齐
            if score < rag_score:
                continue
            ordered.append(
                RetrievedChunk(
                    id=c.id,
                    doc_id=c.doc_id,
                    filename=c.filename,
                    chunk_index=c.chunk_index,
                    text=c.text,
                    user_id=c.user_id,
                    score=score,
                )
            )
            if len(ordered) >= top_k:
                break
        # 可能少于 top_k：只返回达标片段，不再用原序补足
        return ordered
    except Exception:  # noqa: BLE001
        return chunks[:top_k]
