"""职责：Trace 记录——单次请求耗时与步骤，写入 MySQL TraceSpan。

技术点：根 span + step；bind_usage 绑 token 袋；结束时写入 meta_json。
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import select

from app.db import SessionLocal
from app.models import TraceSpan
from app.usage import bind_usage, pop_usage
from app.utils import new_id, utcnow


def start_trace(
    *,
    user_id: str,
    chat_id: str | None,
    name: str,
    meta: dict | None = None,
) -> str:
    """功能：创建根 span，返回 trace_id；同时绑定本次请求的 token 用量袋。

    技术点：MySQL TraceSpan kind=root；bind_usage ContextVar。
    """
    trace_id = new_id()
    bind_usage(trace_id)
    if SessionLocal is None:
        return trace_id
    with SessionLocal() as db:
        db.add(
            TraceSpan(
                id=new_id(),
                trace_id=trace_id,
                parent_id=None,
                user_id=user_id,
                chat_id=chat_id,
                name=name,
                kind="root",
                status="running",
                started_at=utcnow(),
                ended_at=None,
                duration_ms=None,
                meta_json=json.dumps(meta or {}, ensure_ascii=False),
            )
        )
        db.commit()
    return trace_id


def finish_trace(
    trace_id: str,
    *,
    status: str = "ok",
    meta_update: dict | None = None,
    duration_ms: int | None = None,
) -> None:
    """功能：结束根 span，并把本次累计的 prompt/completion/total tokens 写入 meta。

    技术点：pop_usage；顺带记下 langsmith_run_id 便于对照 WebUI。
    """
    token_meta = pop_usage(trace_id)
    merged = dict(meta_update or {})
    if token_meta:
        merged.update(token_meta)
    # 双轨：本地 Trace 记下 LangSmith run id，便于对照 WebUI
    try:
        from app.langsmith_setup import current_run_id

        ls_id = current_run_id()
        if ls_id and "langsmith_run_id" not in merged:
            merged["langsmith_run_id"] = ls_id
    except Exception:  # noqa: BLE001
        pass
    if SessionLocal is None or not trace_id:
        return
    with SessionLocal() as db:
        row = db.scalar(
            select(TraceSpan)
            .where(TraceSpan.trace_id == trace_id, TraceSpan.kind == "root")
            .order_by(TraceSpan.started_at.asc())
        )
        if not row:
            return
        now = utcnow()
        row.ended_at = now
        row.status = status
        if duration_ms is not None:
            row.duration_ms = duration_ms
        elif row.started_at:
            row.duration_ms = int((now - row.started_at).total_seconds() * 1000)
        if merged:
            try:
                old = json.loads(row.meta_json or "{}")
            except json.JSONDecodeError:
                old = {}
            old.update(merged)
            row.meta_json = json.dumps(old, ensure_ascii=False)
        db.commit()


def add_step(
    trace_id: str,
    *,
    user_id: str,
    chat_id: str | None,
    name: str,
    status: str = "ok",
    duration_ms: int | None = None,
    meta: dict | None = None,
) -> None:
    """功能：追加一条已结束的 step span（工具步、planner 等）。

    技术点：kind=step；立即写 started_at/ended_at。
    """
    if SessionLocal is None or not trace_id:
        return
    with SessionLocal() as db:
        db.add(
            TraceSpan(
                id=new_id(),
                trace_id=trace_id,
                parent_id=None,
                user_id=user_id,
                chat_id=chat_id,
                name=name,
                kind="step",
                status=status,
                started_at=utcnow(),
                ended_at=utcnow(),
                duration_ms=duration_ms,
                meta_json=json.dumps(meta or {}, ensure_ascii=False),
            )
        )
        db.commit()


@contextmanager
def timed_step(
    trace_id: str,
    *,
    user_id: str,
    chat_id: str | None,
    name: str,
    meta: dict | None = None,
) -> Iterator[dict[str, Any]]:
    """功能：上下文管理器记录子步骤耗时，结束时 add_step。

    技术点：perf_counter；异常时 status=error 仍落库再抛出。
    """
    bag: dict[str, Any] = {"meta": dict(meta or {})}
    t0 = time.perf_counter()
    status = "ok"
    try:
        yield bag
    except Exception:
        status = "error"
        raise
    finally:
        ms = int((time.perf_counter() - t0) * 1000)
        add_step(
            trace_id,
            user_id=user_id,
            chat_id=chat_id,
            name=name,
            status=status,
            duration_ms=ms,
            meta=bag.get("meta"),
        )
