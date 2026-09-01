"""产物列表与下载（W2 D5）。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import AppUser, Artifact, Conversation
from app.schemas import ApiResult, ArtifactResponse

router = APIRouter(prefix="/artifacts", tags=["产物"])


def _to_resp(row: Artifact) -> ArtifactResponse:
    """功能：产物 ORM → 响应（带下载 URL）。

    技术点：download_url 给前端，不把磁盘 storage_path 暴露出去。
    """
    return ArtifactResponse(
        id=row.id,
        filename=row.filename,
        content_type=row.content_type,
        byte_size=row.byte_size,
        chat_id=row.chat_id,
        create_date=row.create_date,
        download_url=f"/api/artifacts/{row.id}/download",
    )


@router.get("", response_model=ApiResult[list[ArtifactResponse]])
def list_artifacts(
    chat_id: str | None = None,
    agent_type: str | None = Query(default=None, description="按会话所属智能体隔离，如 MULTI_AGENT"),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[list[ArtifactResponse]]:
    """功能：列当前用户产物，可按会话或 agent_type 隔离。

    技术点：join conversation 按 agent_type 过滤，避免面试官看到多 Agent 的 PDF。
    """
    stmt = select(Artifact).where(
        Artifact.user_id == current_user.id,
        Artifact.is_del == 0,
    )
    if chat_id:
        stmt = stmt.where(Artifact.chat_id == chat_id)
    if agent_type:
        # 经会话表归属：artifact.chat_id → conversation.agent_type
        stmt = stmt.join(
            Conversation,
            Conversation.chat_id == Artifact.chat_id,
        ).where(
            Conversation.user_id == current_user.id,
            Conversation.is_del == 0,
            Conversation.agent_type == agent_type,
        )
    rows = db.scalars(stmt.order_by(Artifact.create_date.desc())).all()
    return ApiResult.ok([_to_resp(r) for r in rows])


@router.get("/{artifact_id}/download")
def download_artifact(
    artifact_id: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    """功能：下载产物文件。

    技术点：FileResponse；校验 user_id；库有记录但磁盘丢了返回 404。
    """
    row = db.scalar(
        select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.user_id == current_user.id,
            Artifact.is_del == 0,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="产物不存在")
    path = Path(row.storage_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件已丢失")
    return FileResponse(
        path,
        media_type=row.content_type or "application/octet-stream",
        filename=row.filename,
    )
