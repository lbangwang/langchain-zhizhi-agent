"""职责：基础评测集 20 条，按关键词命中率做发布门禁。

技术点：chat_completion；通过率低于阈值 exit 1。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.llm import chat_completion  # noqa: E402

CASES_PATH = Path(__file__).with_name("cases_basic.json")


def load_cases() -> list[dict]:
    """功能：从 cases_basic.json 加载评测用例。

    技术点：与脚本同目录 JSON。
    """
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def score_case(case: dict, answer: str) -> tuple[bool, str]:
    """功能：按期望关键词命中率给单条答案打分。

    技术点：命中不少于半数关键词即通过。
    """
    expect = case.get("expect_keywords") or []
    if not expect:
        return True, "no keywords"
    hit = [k for k in expect if k.lower() in answer.lower()]
    ok = len(hit) >= max(1, (len(expect) + 1) // 2)
    return ok, f"hit={hit}"


def run(limit: int | None = None, fail_under: float = 0.6) -> int:
    """功能：跑评测集并打印 PASS/FAIL；通过率低于阈值返回 1。

    技术点：发布门禁；记录平均延迟。
    """
    cases = load_cases()
    if limit:
        cases = cases[:limit]
    passed = 0
    latencies: list[float] = []
    print("=" * 64)
    print(f"basic evals: {len(cases)} cases  fail_under={fail_under}")
    print("=" * 64)
    for i, case in enumerate(cases, 1):
        prompt = case["prompt"]
        t0 = time.perf_counter()
        try:
            answer = chat_completion([{"role": "user", "content": prompt}])
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}] FAIL {case['id']}: LLM error {exc}")
            continue
        ms = (time.perf_counter() - t0) * 1000
        latencies.append(ms)
        ok, detail = score_case(case, answer)
        passed += int(ok)
        flag = "PASS" if ok else "FAIL"
        print(
            f"[{i}] {flag} {case['id']} {ms:.0f}ms {detail} | "
            f"{re.sub(r'\\s+', ' ', answer)[:80]}"
        )
    print("-" * 64)
    avg = sum(latencies) / len(latencies) if latencies else 0
    rate = passed / len(cases) if cases else 0.0
    print(f"passed {passed}/{len(cases)} ({rate:.0%})  avg_latency={avg:.0f}ms")
    # 评测门禁：通过率低于阈值则非 0 退出（发布前回归）
    return 0 if rate + 1e-9 >= fail_under else 1


def main() -> int:
    """功能：解析 CLI 并执行基础评测。

    技术点：argparse --limit / --fail-under。
    """
    parser = argparse.ArgumentParser(description="基础评测 / 发布门禁")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--fail-under",
        type=float,
        default=0.6,
        help="通过率低于该阈值则 exit 1（默认 0.6）",
    )
    args = parser.parse_args()
    return run(args.limit, fail_under=args.fail_under)


if __name__ == "__main__":
    raise SystemExit(main())
