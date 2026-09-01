"""Trace 查询接口与列表（W3 D5）。"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import AppUser, TraceSpan
from app.schemas import ApiResult

router = APIRouter(prefix="/traces", tags=["Trace"])


class TraceItem(BaseModel):
    id: str
    trace_id: str
    name: str
    kind: str
    status: str
    chat_id: str | None
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    meta: dict | None = None


class TraceStats(BaseModel):
    """当前用户可观测汇总（量、成功率、时延、Token 消耗）。"""

    total: int
    ok: int
    error: int
    stopped: int
    success_rate: float
    avg_duration_ms: int | None
    p95_duration_ms: int | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    by_name: dict[str, int]


def _percentile(sorted_vals: list[int], p: float) -> int | None:
    """功能：已排序数组上取百分位（P95 时延）。

    技术点：最近邻下标，空列表返回 None。
    """
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, max(0, int(round((p / 100) * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def _tokens_from_meta(meta_json: str | None) -> tuple[int, int, int]:
    """功能：从根 span meta_json 读三类 token。

    技术点：JSON 解析失败当 0；旧 Trace 没有 usage 字段也是 0。
    """
    if not meta_json:
        return 0, 0, 0
    try:
        data = json.loads(meta_json)
    except json.JSONDecodeError:
        return 0, 0, 0
    if not isinstance(data, dict):
        return 0, 0, 0
    prompt = int(data.get("prompt_tokens") or 0)
    completion = int(data.get("completion_tokens") or 0)
    total = int(data.get("total_tokens") or 0)
    if not total:
        total = prompt + completion
    return prompt, completion, total


@router.get("/stats", response_model=ApiResult[TraceStats])
def trace_stats(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[TraceStats]:
    """功能：聚合当前用户 Trace 统计（量、成功率、P95、Token）。

    技术点：必须注册在 /{trace_id} 之前；只统计 kind=root；按 user_id 隔离。
    """
    rows = db.scalars(
        select(TraceSpan)
        .where(TraceSpan.user_id == current_user.id, TraceSpan.kind == "root")
        .order_by(TraceSpan.started_at.desc())
        .limit(500)
    ).all()
    total = len(rows)
    ok = sum(1 for r in rows if (r.status or "") == "ok")
    error = sum(1 for r in rows if (r.status or "") in {"error", "timeout"})
    stopped = sum(1 for r in rows if (r.status or "") in {"stopped", "cancelled"})
    durs = sorted(int(r.duration_ms) for r in rows if r.duration_ms is not None and r.duration_ms >= 0)
    by_name: dict[str, int] = {}
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    for r in rows:
        key = r.name or "unknown"
        by_name[key] = by_name.get(key, 0) + 1
        p, c, t = _tokens_from_meta(r.meta_json)
        prompt_tokens += p
        completion_tokens += c
        total_tokens += t
    avg = int(sum(durs) / len(durs)) if durs else None
    return ApiResult.ok(
        TraceStats(
            total=total,
            ok=ok,
            error=error,
            stopped=stopped,
            success_rate=round((ok / total) * 100, 1) if total else 0.0,
            avg_duration_ms=avg,
            p95_duration_ms=_percentile(durs, 95),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            by_name=by_name,
        )
    )


@router.get("", response_model=ApiResult[list[TraceItem]])
def list_traces(
    limit: int = 30,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[list[TraceItem]]:
    """功能：最近根 Trace 列表（左侧列表）。

    技术点：kind=root；按 started_at 倒序。
    """
    limit = max(1, min(limit, 100))
    rows = db.scalars(
        select(TraceSpan)
        .where(TraceSpan.user_id == current_user.id, TraceSpan.kind == "root")
        .order_by(TraceSpan.started_at.desc())
        .limit(limit)
    ).all()
    return ApiResult.ok([_to_item(r) for r in rows])


@router.get("/{trace_id}", response_model=ApiResult[list[TraceItem]])
def get_trace(
    trace_id: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[list[TraceItem]]:
    """功能：一次 Trace 的全部 span（右侧详情步骤）。

    技术点：同一 trace_id + user_id，防偷看别人的步骤。
    """
    rows = db.scalars(
        select(TraceSpan)
        .where(TraceSpan.trace_id == trace_id, TraceSpan.user_id == current_user.id)
        .order_by(TraceSpan.started_at.asc())
    ).all()
    if not rows:
        return ApiResult.fail("Trace 不存在")
    return ApiResult.ok([_to_item(r) for r in rows])


def _to_item(row: TraceSpan) -> TraceItem:
    """功能：ORM span → 前端 TraceItem。

    技术点：meta_json 反序列化；坏 JSON 放进 raw 字段。
    """
    meta = None
    if row.meta_json:
        try:
            meta = json.loads(row.meta_json)
        except json.JSONDecodeError:
            meta = {"raw": row.meta_json}
    return TraceItem(
        id=row.id,
        trace_id=row.trace_id,
        name=row.name,
        kind=row.kind,
        status=row.status,
        chat_id=row.chat_id,
        started_at=row.started_at,
        ended_at=row.ended_at,
        duration_ms=row.duration_ms,
        meta=meta,
    )
