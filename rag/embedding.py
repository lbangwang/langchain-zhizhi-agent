"""职责：Embedding——硅基流动 BAAI/bge-m3（OpenAI 兼容）；无 Key 时用确定性伪向量联调。

技术点：OpenAI 兼容 /v1/embeddings；批量≤32；维度 1024 对齐 Milvus schema。
"""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Sequence

from openai import OpenAI

from app.config import get_settings

# 硅基流动 embeddings 单次 input 数组上限为 32
_SILICONFLOW_EMBED_BATCH_SIZE = 32


def _fake_embed(text: str, dim: int) -> list[float]:
    """功能：无 API Key 时生成可复现伪向量（仅联调，非语义向量）。

    技术点：SHA256 种子；L2 归一化到 embedding_dim。
    """
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    vals: list[float] = []
    block = seed
    while len(vals) < dim:
        for i in range(0, len(block) - 3, 4):
            (num,) = struct.unpack(">I", block[i : i + 4])
            vals.append((num / 2**32) * 2 - 1)
            if len(vals) >= dim:
                break
        block = hashlib.sha256(block).digest()
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]


def _siliconflow_client() -> OpenAI | None:
    """功能：构造硅基流动 Embedding 客户端（OpenAI 兼容）；无 Key 返回 None。

    技术点：OpenAI SDK；maybe_wrap_openai 可选 LangSmith 打点。
    """
    settings = get_settings()
    if not settings.siliconflow_api_key:
        return None
    from app.langsmith_setup import maybe_wrap_openai

    client = OpenAI(
        api_key=settings.siliconflow_api_key,
        base_url=settings.siliconflow_base_url or "https://api.siliconflow.cn/v1",
    )
    return maybe_wrap_openai(client)


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """功能：批量文本转向量列表（按 ≤32 条分批）。

    技术点：bge-m3 固定 1024 维不传 dimensions；无客户端走伪向量。
    """
    settings = get_settings()
    dim = settings.embedding_dim
    items = [t if t.strip() else " " for t in texts]
    if not items:
        return []

    client = _siliconflow_client()
    if client is None:
        return [_fake_embed(t, dim) for t in items]

    model = settings.embedding_model or "BAAI/bge-m3"
    vectors: list[list[float]] = []
    for i in range(0, len(items), _SILICONFLOW_EMBED_BATCH_SIZE):
        batch = list(items[i : i + _SILICONFLOW_EMBED_BATCH_SIZE])
        # bge-m3 固定 1024 维，不要传 dimensions（仅 Qwen3-Embedding 支持）
        resp = client.embeddings.create(model=model, input=batch)
        data = sorted(resp.data, key=lambda x: x.index)
        vectors.extend(list(d.embedding) for d in data)
    return vectors


def embed_query(text: str) -> list[float]:
    """功能：把单条检索 query 编成向量。

    技术点：复用 embed_texts 取第一条。
    """
    return embed_texts([text])[0]
