#!/usr/bin/env python3
"""职责：Embedding + Milvus 写入/检索演示脚本。

技术点：split_text；insert_chunks；search_raw_dict。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from rag.chunking import split_text
from rag.store import ensure_collection, insert_chunks, search_raw_dict


SAMPLE_DOC = """
枝枝 AI Agent 使用 Milvus 做知识库向量检索。
文档上传后会切分为 chunk，经 DashScope text-embedding-v3 编码后写入集合 zhizhi_kb。
对话时根据用户问题检索相关 chunk，注入提示词，并在回答末尾附加 __CITATIONS__ 引用。
检索优化包括：查询改写、多路召回 RRF 融合、以及 LLM Rerank。
Agent 侧提供 search_web、write_text_file、create_pdf_report 等工具，产物可下载。
""".strip()


def main() -> int:
    """功能：写入样例文档并按 query 检索，打印命中片段。

    技术点：可重复 delete+insert；MILVUS_ENABLED=false 则退出。
    """
    parser = argparse.ArgumentParser(description="Demo Milvus embed + search")
    parser.add_argument("--query", default="知识库检索如何引用文档")
    parser.add_argument("--user-id", default="demo_user_w2d2")
    parser.add_argument("--recreate", action="store_true", help="重建集合（危险）")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.milvus_enabled:
        print("MILVUS_ENABLED=false，请先在 .env 打开")
        return 1

    print(f"Milvus {settings.milvus_host}:{settings.milvus_port} collection={settings.milvus_collection}")
    ensure_collection(recreate=args.recreate)

    chunks = split_text(SAMPLE_DOC, chunk_size=120, chunk_overlap=20)
    doc_id = "demo_doc_w2d2_fixed01"
    # 先删再写，保证脚本可重复跑
    try:
        from rag.store import delete_by_doc_id

        delete_by_doc_id(doc_id)
    except Exception as exc:  # noqa: BLE001
        print(f"(skip delete) {exc}")

    ids = insert_chunks(
        doc_id=doc_id,
        filename="w2d2_demo.txt",
        user_id=args.user_id,
        texts=chunks,
    )
    print(f"写入 {len(ids)} 个 chunk")

    hits = search_raw_dict(args.query, user_id=args.user_id, top_k=4)
    print(f"\nQuery: {args.query}")
    for i, h in enumerate(hits, 1):
        print(f"[{i}] score={h['score']:.4f} file={h['filename']} idx={h['chunk_index']}")
        print(f"    {h['text'][:160].replace(chr(10), ' ')}")
    if not hits:
        print("无命中")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
