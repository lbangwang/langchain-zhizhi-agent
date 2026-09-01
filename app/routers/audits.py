"""工具调用审计查询（W2 D5）+ CSV 导出（企业级）。"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import AppUser, ToolAudit
from app.schemas import ApiResult, ToolAuditResponse

router = APIRouter(prefix="/audits", tags=["工具审计"])


@router.get("/tools", response_model=ApiResult[list[ToolAuditResponse]])
def list_tool_audits(
    chat_id: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[list[ToolAuditResponse]]:
    """功能：列出当前用户工具调用审计。

    技术点：按 user_id 隔离；limit 夹在 1～200，防一次拉爆。
    """
    limit = max(1, min(limit, 200))
    q = select(ToolAudit).where(ToolAudit.user_id == current_user.id)
    if chat_id:
        q = q.where(ToolAudit.chat_id == chat_id)
    rows = db.scalars(q.order_by(ToolAudit.create_date.desc()).limit(limit)).all()
    return ApiResult.ok([ToolAuditResponse.model_validate(r) for r in rows])


@router.get("/tools/export")
def export_tool_audits(
    chat_id: str | None = None,
    limit: int = 500,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> StreamingResponse:
    """功能：导出工具审计 CSV（合规 / 面试演示）。

    技术点：utf-8-sig 方便 Excel；StreamingResponse 当附件下载。
    """
    limit = max(1, min(limit, 2000))
    q = select(ToolAudit).where(ToolAudit.user_id == current_user.id)
    if chat_id:
        q = q.where(ToolAudit.chat_id == chat_id)
    rows = db.scalars(q.order_by(ToolAudit.create_date.desc()).limit(limit)).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "chat_id",
            "tool_name",
            "status",
            "config_version",
            "input_preview",
            "output_preview",
            "create_date",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.id,
                r.chat_id or "",
                r.tool_name,
                r.status,
                getattr(r, "config_version", None) or "",
                (r.input_preview or "").replace("\n", " ")[:500],
                (r.output_preview or "").replace("\n", " ")[:500],
                r.create_date.isoformat() if r.create_date else "",
            ]
        )
    data = buf.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="tool_audits.csv"',
        },
    )
