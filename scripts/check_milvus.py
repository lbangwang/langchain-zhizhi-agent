#!/usr/bin/env python3
"""职责：探测 Milvus 是否可连（本机 pymilvus → MILVUS_HOST:MILVUS_PORT）。

技术点：ping_milvus；gRPC 连通性，非浏览器 HTTP。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from rag.milvus_client import milvus_uri, ping_milvus  # noqa: E402


def main() -> int:
    """功能：连接 Milvus 并列出 collection，失败则非 0 退出。

    技术点：ping_milvus；打印 MILVUS_ENABLED。
    """
    settings = get_settings()
    print(f"Milvus target: {milvus_uri()}")
    print(f"MILVUS_ENABLED={settings.milvus_enabled}")
    result = ping_milvus()
    if result["ok"]:
        print("OK: pymilvus connected")
        print(f"collections ({len(result['collections'])}): {result['collections']}")
        return 0
    print(f"FAIL: {result['error']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
