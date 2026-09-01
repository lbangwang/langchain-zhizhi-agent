"""职责：SSE 回答打字机——把最终 answer 拆成 delta 事件推给前端。

技术点：按 chunk 切块 + asyncio.sleep；事件形态与 chat/stream 的 delta 一致。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any


async def iter_answer_deltas(
    answer: str,
    *,
    chunk_size: int = 12,
    delay_seconds: float = 0.018,
) -> AsyncIterator[dict[str, Any]]:
    """功能：将完整 answer 按块 yield 为 delta 事件，夹带短延迟形成打字机节奏。

    技术点：SSE delta；asyncio.sleep 控速。
    """
    text = answer or ""
    if not text:
        return
    size = max(1, int(chunk_size))
    delay = max(0.0, float(delay_seconds))
    for i in range(0, len(text), size):
        yield {
            "type": "delta",
            "zone": "answer",
            "content": text[i : i + size],
        }
        if delay:
            await asyncio.sleep(delay)
