"""职责：知识库——上传 / 切分 / 试检索 / 删除（独立功能页）。

技术点：Milvus 入库；多策略 chunk；软删文档并清理向量；user_id 隔离。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user
from app.models import AppUser, KbDocument
from app.schemas import ApiResult, KbDocumentResponse
from app.utils import new_id, utcnow
from rag.chunking import STRATEGY_DEFS, split_document
from rag.loaders import extract_text_from_bytes
from rag.retrieve import retrieve
from rag.store import delete_by_doc_id, insert_chunks, list_chunks_by_doc

router = APIRouter(prefix="/knowledge", tags=["知识库"])


class PreviewRequest(BaseModel):
    """职责：切分预览请求体（不入库）。

    技术点：Pydantic；strategy + chunk_size/overlap。
    """

    content: str = Field(min_length=1)
    filename: str = "note.txt"
    strategy: str = Field(
        default="recursive",
        description="recursive|paragraph|markdown|window|token",
    )
    chunk_size: int = Field(default=800, ge=50, le=4000)
    chunk_overlap: int = Field(default=80, ge=0, le=1000)


class PreviewResponse(BaseModel):
    """职责：切分预览/已入库切片的响应体。wo m

    技术点：含 chunks 列表（index/text/chars）。
    """
    filename: str
    char_count: int
    chunk_count: int
    chunks: list[dict]


class SearchRequest(BaseModel):
    """职责：试检索请求体。

    技术点：query + top_k。
    """

    query: str = Field(min_length=1)
    top_k: int = Field(default=4, ge=1, le=20)


class SearchHit(BaseModel):
    """职责：单条试检索命中。

    技术点：doc_id/filename/chunk_index/text/score。
    """
    doc_id: str
    filename: str
    chunk_index: int
    text: str
    score: float


def _decode_upload(raw: bytes, filename: str) -> str:
    """功能：兼容旧调用，按扩展名把上传字节解成纯文本。

    技术点：委托 rag.loaders.extract_text_from_bytes。
    """
    return extract_text_from_bytes(raw, filename)


@router.get("/strategies", response_model=ApiResult[list[dict]])
def list_strategies(
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[list[dict]]:
    """功能：返回切分策略（中文名称、说明、差异化参数定义）。

    技术点：STRATEGY_DEFS 供前端动态表单。
    """
    _ = current_user
    return ApiResult.ok(STRATEGY_DEFS)


def _ingest_text(
    *,
    db: Session,
    user: AppUser,
    filename: str,
    text: str,
    content_type: str | None,
    strategy: str,
    chunk_size: int,
    chunk_overlap: int,
) -> ApiResult[KbDocumentResponse]:
    """功能：切分文本、写入 Milvus，并登记 KbDocument 行。

    技术点：split_document；insert_chunks；content_type 截断防 VARCHAR 溢出。
    """
    settings = get_settings()
    if not settings.milvus_enabled:
        return ApiResult.fail("Milvus 未启用：请设置 MILVUS_ENABLED=true")
    cleaned = (text or "").strip()
    if not cleaned:
        return ApiResult.fail("内容为空")
    chunks = split_document(
        cleaned,
        strategy=strategy,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    if not chunks:
        return ApiResult.fail("未能切分出有效文本")

    doc_id = new_id()
    try:
        insert_chunks(
            doc_id=doc_id,
            filename=filename,
            user_id=user.id,
            texts=chunks,
        )
    except Exception as exc:  # noqa: BLE001
        return ApiResult.fail(f"写入 Milvus 失败: {exc}")

    # docx MIME 很长（可达 70+）；当前库字段若仍是 VARCHAR(64) 需截断，避免 DataError
    safe_ctype = (content_type or "")[:64] or None

    now = utcnow()
    doc = KbDocument(
        id=doc_id,
        user_id=user.id,
        filename=filename[:256],
        content_type=safe_ctype,
        char_count=len(cleaned),
        chunk_count=len(chunks),
        status=1,
        create_date=now,
        create_by=user.id,
        update_date=now,
        update_by=user.id,
        is_del=0,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return ApiResult.ok(KbDocumentResponse.model_validate(doc))


@router.get("", response_model=ApiResult[list[KbDocumentResponse]])
def list_documents(
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[list[KbDocumentResponse]]:
    """功能：列出当前用户知识库文档。

    技术点：按 user_id 隔离；软删 is_del=0。
    """
    rows = db.scalars(
        select(KbDocument)
        .where(KbDocument.user_id == current_user.id, KbDocument.is_del == 0)
        .order_by(KbDocument.create_date.desc())
    ).all()
    return ApiResult.ok([KbDocumentResponse.model_validate(r) for r in rows])


@router.post("/preview", response_model=ApiResult[PreviewResponse])
def preview_chunks(
    body: PreviewRequest,
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[PreviewResponse]:
    """功能：按参数预览切片，不写库（粘贴文本）。

    技术点：split_document；不碰 Milvus。
    """
    _ = current_user
    chunks = split_document(
        body.content,
        strategy=body.strategy,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
    )
    return ApiResult.ok(
        PreviewResponse(
            filename=body.filename or "note.txt",
            char_count=len(body.content.strip()),
            chunk_count=len(chunks),
            chunks=[
                {"index": i, "text": t, "chars": len(t)} for i, t in enumerate(chunks)
            ],
        )
    )


@router.post("/preview-file", response_model=ApiResult[PreviewResponse])
async def preview_file_chunks(
    file: UploadFile = File(...),
    strategy: str = Form(default="recursive"),
    chunk_size: int = Form(default=800),
    chunk_overlap: int = Form(default=80),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[PreviewResponse]:
    """功能：上传文件仅预览切片（支持 PDF/docx），不入库。

    技术点：extract_text_from_bytes；10MB 限制。
    """
    _ = current_user
    filename = file.filename or "upload.txt"
    raw = await file.read()
    if not raw:
        return ApiResult.fail("空文件")
    if len(raw) > 10 * 1024 * 1024:
        return ApiResult.fail("文件超过 10MB")
    try:
        text = extract_text_from_bytes(raw, filename)
    except ValueError as exc:
        return ApiResult.fail(str(exc))
    except Exception as exc:  # noqa: BLE001
        return ApiResult.fail(f"解析文件失败: {exc}")
    chunks = split_document(
        text,
        strategy=strategy,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return ApiResult.ok(
        PreviewResponse(
            filename=filename,
            char_count=len(text),
            chunk_count=len(chunks),
            chunks=[
                {"index": i, "text": t, "chars": len(t)} for i, t in enumerate(chunks)
            ],
        )
    )


@router.post("/search", response_model=ApiResult[list[SearchHit]])
def search_knowledge(
    body: SearchRequest,
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[list[SearchHit]]:
    """功能：试检索当前用户知识库相关片段。

    技术点：retrieve（rewrite+RRF+rerank）；user_id 过滤。
    """
    settings = get_settings()
    if not settings.milvus_enabled:
        return ApiResult.fail("Milvus 未启用")
    try:
        hits, _debug = retrieve(
            body.query.strip(),
            user_id=current_user.id,
            top_k=body.top_k,
        )
    except Exception as exc:  # noqa: BLE001
        return ApiResult.fail(f"检索失败: {exc}")
    return ApiResult.ok(
        [
            SearchHit(
                doc_id=h.doc_id,
                filename=h.filename,
                chunk_index=h.chunk_index,
                text=h.text,
                score=round(float(h.score), 4),
            )
            for h in hits
        ]
    )


@router.get("/{doc_id}/chunks", response_model=ApiResult[PreviewResponse])
def get_document_chunks(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[PreviewResponse]:
    """功能：查看某文档已入库切片。

    技术点：归属校验；list_chunks_by_doc query（非向量检索）。
    """
    doc = db.scalar(
        select(KbDocument).where(
            KbDocument.id == doc_id,
            KbDocument.user_id == current_user.id,
            KbDocument.is_del == 0,
        )
    )
    if not doc:
        return ApiResult.fail("文档不存在")
    try:
        chunks = list_chunks_by_doc(doc_id, user_id=current_user.id)
    except Exception as exc:  # noqa: BLE001
        return ApiResult.fail(f"读取切片失败: {exc}")
    return ApiResult.ok(
        PreviewResponse(
            filename=doc.filename,
            char_count=doc.char_count,
            chunk_count=len(chunks),
            chunks=[
                {
                    "index": c.chunk_index,
                    "text": c.text,
                    "chars": len(c.text),
                }
                for c in chunks
            ],
        )
    )


@router.post("/upload", response_model=ApiResult[KbDocumentResponse])
async def upload_document(
    file: UploadFile = File(...),
    strategy: str = Form(default="recursive"),
    chunk_size: int = Form(default=800),
    chunk_overlap: int = Form(default=80),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[KbDocumentResponse]:
    """功能：上传文档（txt/md/csv/json/pdf/docx），切分后写入 Milvus。

    技术点：extract_text_from_bytes；_ingest_text。
    """
    filename = file.filename or "upload.txt"
    raw = await file.read()
    if not raw:
        return ApiResult.fail("空文件")
    if len(raw) > 10 * 1024 * 1024:
        return ApiResult.fail("文件超过 10MB")
    try:
        text = extract_text_from_bytes(raw, filename)
    except ValueError as exc:
        return ApiResult.fail(str(exc))
    except Exception as exc:  # noqa: BLE001
        return ApiResult.fail(f"解析文件失败: {exc}")
    return _ingest_text(
        db=db,
        user=current_user,
        filename=filename,
        text=text,
        content_type=file.content_type,
        strategy=strategy,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


@router.post("/upload-text", response_model=ApiResult[KbDocumentResponse])
def upload_text(
    filename: str = Form(default="note.txt"),
    content: str = Form(...),
    strategy: str = Form(default="recursive"),
    chunk_size: int = Form(default=800),
    chunk_overlap: int = Form(default=80),
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[KbDocumentResponse]:
    """功能：粘贴纯文本入库。

    技术点：Form 字段；委托 _ingest_text。
    """
    return _ingest_text(
        db=db,
        user=current_user,
        filename=filename or "note.txt",
        text=content,
        content_type="text/plain",
        strategy=strategy,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


@router.delete("/{doc_id}", response_model=ApiResult[None])
def delete_document(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
) -> ApiResult[None]:
    """功能：软删文档并清理 Milvus 向量。

    技术点：归属校验；delete_by_doc_id；is_del=1。
    """
    doc = db.scalar(
        select(KbDocument).where(
            KbDocument.id == doc_id,
            KbDocument.user_id == current_user.id,
            KbDocument.is_del == 0,
        )
    )
    if not doc:
        return ApiResult.fail("文档不存在")
    try:
        delete_by_doc_id(doc_id)
    except Exception as exc:  # noqa: BLE001
        return ApiResult.fail(f"清理向量失败: {exc}")
    doc.is_del = 1
    doc.update_date = utcnow()
    doc.update_by = current_user.id
    db.commit()
    return ApiResult.ok(None)
