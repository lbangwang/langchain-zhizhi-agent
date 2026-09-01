#!/usr/bin/env python3
"""职责：检索优化前后对比（5 条口语 case + 干扰文档）。

技术点：baseline dense vs rewrite+RRF+rerank；top1 是否含 gold 短语。
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
from rag.retrieve import retrieve, retrieve_baseline
from rag.store import delete_by_doc_id, ensure_collection, insert_chunks

USER_ID = "eval_user_w2d4"
DOC_IDS = ["eval_doc_w2d4_main", "eval_doc_w2d4_noise"]
LEGACY_DOC_IDS = ["eval_doc_w2d4_001"]

MAIN = """
# 枝枝知识库主文档

## 向量集合配置
正式知识库向量落在 Milvus 集合名称 zhizhi_kb，embedding 维度固定为 1024，度量方式为 IP。

## 引用展示
开启 RAG 后，助手会在正文后附加标记 __CITATIONS__，JSON 里有 filename 与 snippet，用来展示来自哪篇文档。

## 检索链路优化
口语问题会先做查询改写；改写结果与原文双路召回后用 Reciprocal Rank Fusion（简称 RRF）融合；最后 LLM Rerank 重排。

## 产物下载
Agent 调用 create_pdf_report 生成 PDF 后，会写入 artifact 表，下载地址形如 /api/artifacts/{id}/download。

## 停止机制
客户端调用 stop 接口后，Redis 写入停止键；Agent 循环检查到信号就不再进入后续 step。
""".strip()

# 干扰文档：提高「基线容易顶错」的概率
NOISE = """
# 杂项说明（干扰）
公司食堂菜单有西红柿炒蛋。办公室空调温度建议 26 度。
年会抽奖规则与 Agent 无关。打印机缺纸请联系行政。
常见缩写 FAQ：KPI、OKR、SLA。这里故意不提 Milvus 集合名。
关于停止：请先保存 Word 文档再关机，这与 Redis 停止信号无关。
下载：从网盘链接手动下载安装包，不是 artifact 接口。
""".strip()

# (口语 query, gold 短语 — 期望出现在优化后 top1)
CASES: list[tuple[str, str]] = [
    ("那个向量库集合叫啥，多少维来着？", "zhizhi_kb"),
    ("回答咋标明出处文档？", "__CITATIONS__"),
    ("检索那边 RRF 到底干啥用？", "RRF"),
    ("PDF 报告生成完从哪下？", "/api/artifacts/"),
    ("为啥我点停止后面步骤不跑了？", "Redis"),
]


def _top1_has(hits, gold: str) -> bool:
    """功能：判断 top1 片段是否包含 gold 短语。

    技术点：大小写不敏感子串匹配。
    """
    if not hits:
        return False
    text = hits[0].text if hasattr(hits[0], "text") else ""
    return gold.lower() in text.lower()


def seed_corpus() -> None:
    """功能：写入主文档 + 干扰文档到评测用户的 Milvus 集合。

    技术点：先按 doc_id 删除再 insert_chunks，保证可重复跑。
    """
    ensure_collection()
    for doc_id in [*DOC_IDS, *LEGACY_DOC_IDS]:
        try:
            delete_by_doc_id(doc_id)
        except Exception:  # noqa: BLE001
            pass
    main_chunks = split_text(MAIN, chunk_size=220, chunk_overlap=30)
    noise_chunks = split_text(NOISE, chunk_size=180, chunk_overlap=20)
    insert_chunks(
        doc_id=DOC_IDS[0],
        filename="w2d4_main.md",
        user_id=USER_ID,
        texts=main_chunks,
    )
    insert_chunks(
        doc_id=DOC_IDS[1],
        filename="w2d4_noise.md",
        user_id=USER_ID,
        texts=noise_chunks,
    )
    print(f"seeded main={len(main_chunks)} noise={len(noise_chunks)}")


def main() -> int:
    """功能：对比 dense 基线与 rewrite+RRF+rerank 的 top1 命中。

    技术点：--seed 先灌库；口语 query + 干扰文档。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.milvus_enabled:
        print("MILVUS_ENABLED=false")
        return 1

    if args.seed:
        seed_corpus()

    print("=" * 72)
    print("W2 D4：baseline dense vs rewrite+RRF+rerank（top1 是否含 gold）")
    print("=" * 72)

    wins = 0
    for i, (query, gold) in enumerate(CASES, 1):
        base = retrieve_baseline(query, user_id=USER_ID, top_k=4)
        opt, debug = retrieve(
            query,
            user_id=USER_ID,
            top_k=4,
            use_rewrite=True,
            use_rerank=True,
        )
        ok_base = _top1_has(base, gold)
        ok_opt = _top1_has(opt, gold)
        if ok_opt and not ok_base:
            verdict = "提升"
            wins += 1
        elif ok_opt and ok_base:
            verdict = "持平(均命中)"
            wins += 1
        elif not ok_opt and ok_base:
            verdict = "回退"
        else:
            verdict = "均未命中"

        print(f"\nCase {i}: {query}")
        print(f"  gold={gold!r} rewritten={debug.get('rewritten')}")
        print(f"  mode={debug.get('mode')} top1_hit base={ok_base} opt={ok_opt} => {verdict}")
        print("  baseline top1:", (base[0].text[:100].replace("\n", " ") if base else "(empty)"))
        print("  optimized top1:", (opt[0].text[:100].replace("\n", " ") if opt else "(empty)"))

    print("\n" + "=" * 72)
    print(
        f"总结：{wins}/5 条在优化后 top1 命中 gold（含持平）；"
        "口语 query + 干扰文档下，改写拓宽召回，RRF/Rerank 抑制噪声。"
    )
    print("若均未命中，请先：python evals/rag_compare.py --seed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
