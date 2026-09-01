"""职责：Milvus 向量库——建表 / 写入 / 检索 / 按文档删除。

技术点：IVF_FLAT + IP；embedding 写入；user_id 过滤；VARCHAR 截断。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    utility,
)

from app.config import get_settings
from app.utils import new_id
from rag.embedding import embed_query, embed_texts
from rag.milvus_client import connect_milvus, disconnect_milvus


@dataclass
class RetrievedChunk:
    """职责：检索结果一条（id/doc_id/filename/text/score 等）。

    技术点：dataclass；score 在 RRF 后会被换成融合分。
    """

    id: str
    doc_id: str
    filename: str
    chunk_index: int
    text: str
    user_id: str
    score: float


def _schema(dim: int) -> CollectionSchema:
    """功能：按 embedding 维度构造知识库 Collection schema。

    技术点：VARCHAR 主键；FLOAT_VECTOR dim 与 bge-m3 1024 对齐。
    """
    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=32),
        FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="filename", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="chunk_index", dtype=DataType.INT64),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=6000),
        FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
    ]
    return CollectionSchema(fields=fields, description="zhizhi knowledge chunks")


def ensure_collection(*, recreate: bool = False) -> Collection:
    """功能：确保集合存在、已建 IVF_FLAT 索引并 load。

    技术点：recreate 会 drop；metric IP；nlist=128。
    """
    settings = get_settings()
    connect_milvus()
    name = settings.milvus_collection
    if recreate and utility.has_collection(name):
        utility.drop_collection(name)
    if not utility.has_collection(name):
        col = Collection(name=name, schema=_schema(settings.embedding_dim))
        col.create_index(
            field_name="embedding",
            index_params={
                "index_type": "IVF_FLAT",
                "metric_type": "IP",
                "params": {"nlist": 128},
            },
        )
    col = Collection(name)
    col.load()
    return col


def insert_chunks(
    *,
    doc_id: str,
    filename: str,
    user_id: str,
    texts: list[str],
) -> list[str]:
    """功能：把若干文本 chunk 向量化后写入 Milvus，返回 chunk id 列表。

    技术点：embed_texts 批量；text 截断适配 VARCHAR(6000)；flush。
    """
    if not texts:
        return []
    settings = get_settings()
    col = ensure_collection()
    ids = [new_id() for _ in texts]
    vectors = embed_texts(texts)
    # 截断过长文本以适配 VARCHAR
    safe_texts = [t[:5900] for t in texts]
    entities = [
        ids,
        [doc_id] * len(texts),
        [filename[:250]] * len(texts),
        list(range(len(texts))),
        safe_texts,
        [user_id] * len(texts),
        vectors,
    ]
    col.insert(entities)
    col.flush()
    return ids


def delete_by_doc_id(doc_id: str) -> None:
    """功能：按文档 id 删除该文档全部向量。

    技术点：Milvus expr 删除；随后 flush。
    """
    col = ensure_collection()
    col.delete(expr=f'doc_id == "{doc_id}"')
    col.flush()


def search_dense(
    query: str,
    *,
    user_id: str | None = None,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """功能：稠密向量检索，可按 user_id 过滤只搜当前用户文档。

    技术点：IP + nprobe=16；expr 过滤 user_id。
    """
    settings = get_settings()
    k = top_k or settings.rag_top_k
    col = ensure_collection()
    vector = embed_query(query)
    expr = f'user_id == "{user_id}"' if user_id else None
    hits = col.search(
        data=[vector],
        anns_field="embedding",
        param={"metric_type": "IP", "params": {"nprobe": 16}},
        limit=k,
        expr=expr,
        output_fields=["doc_id", "filename", "chunk_index", "text", "user_id"],
    )
    results: list[RetrievedChunk] = []
    for hit in hits[0]:
        entity = hit.entity
        results.append(
            RetrievedChunk(
                id=str(hit.id),
                doc_id=entity.get("doc_id"),
                filename=entity.get("filename"),
                chunk_index=int(entity.get("chunk_index") or 0),
                text=entity.get("text") or "",
                user_id=entity.get("user_id") or "",
                score=float(hit.score),
            )
        )
    return results


def search_raw_dict(query: str, **kwargs: Any) -> list[dict[str, Any]]:
    """功能：把稠密检索结果转成便于脚本打印的 dict 列表。

    技术点：委托 search_dense。
    """
    return [
        {
            "id": c.id,
            "doc_id": c.doc_id,
            "filename": c.filename,
            "chunk_index": c.chunk_index,
            "text": c.text,
            "score": c.score,
        }
        for c in search_dense(query, **kwargs)
    ]


def list_chunks_by_doc(doc_id: str, *, user_id: str | None = None) -> list[RetrievedChunk]:
    """功能：按文档列出已入库切片（试览用，不做向量检索）。

    技术点：col.query + expr；可选 user_id 归属校验；按 chunk_index 排序。
    """
    col = ensure_collection()
    expr = f'doc_id == "{doc_id}"'
    if user_id:
        expr = f'{expr} and user_id == "{user_id}"'
    rows = col.query(
        expr=expr,
        output_fields=["doc_id", "filename", "chunk_index", "text", "user_id"],
        limit=512,
    )
    chunks: list[RetrievedChunk] = []
    for row in rows:
        chunks.append(
            RetrievedChunk(
                id=str(row.get("id") or ""),
                doc_id=row.get("doc_id") or "",
                filename=row.get("filename") or "",
                chunk_index=int(row.get("chunk_index") or 0),
                text=row.get("text") or "",
                user_id=row.get("user_id") or "",
                score=0.0,
            )
        )
    chunks.sort(key=lambda c: c.chunk_index)
    return chunks
