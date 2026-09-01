"""职责：Milvus 连接辅助（连通性探测与建立/断开）。

技术点：pymilvus gRPC（host:port，非 HTTP 页面）；list_collections 作 ping。
"""

from __future__ import annotations

from typing import Any

from pymilvus import connections, utility

from app.config import get_settings

_ALIAS = "default"


def milvus_uri() -> str:
    """功能：返回人类可读的 Milvus host:port 描述。

    技术点：读 Settings.milvus_host/port。
    """
    s = get_settings()
    return f"{s.milvus_host}:{s.milvus_port}"


def connect_milvus(*, alias: str = _ALIAS, timeout: float = 10.0) -> None:
    """功能：建立到 Milvus 的连接（已连接则先断开再连）。

    技术点：pymilvus connections.connect；可选 user/password。
    """
    settings = get_settings()
    if connections.has_connection(alias):
        connections.disconnect(alias)

    kwargs: dict[str, Any] = {
        "alias": alias,
        "host": settings.milvus_host,
        "port": str(settings.milvus_port),
        "timeout": timeout,
    }
    if settings.milvus_user:
        kwargs["user"] = settings.milvus_user
        kwargs["password"] = settings.milvus_password

    connections.connect(**kwargs)


def disconnect_milvus(*, alias: str = _ALIAS) -> None:
    """功能：断开指定 alias 的 Milvus 连接；不存在则忽略。

    技术点：connections.has_connection 再 disconnect。
    """
    if connections.has_connection(alias):
        connections.disconnect(alias)


def ping_milvus(*, alias: str = _ALIAS, timeout: float = 10.0) -> dict[str, Any]:
    """功能：连通性探测：connect + list_collections，返回 ok/host/port/collections/error。

    技术点：pymilvus utility.list_collections；finally 断开避免泄漏。
    """
    settings = get_settings()
    result: dict[str, Any] = {
        "ok": False,
        "host": settings.milvus_host,
        "port": settings.milvus_port,
        "collections": [],
        "error": None,
    }
    try:
        connect_milvus(alias=alias, timeout=timeout)
        names = list(utility.list_collections(using=alias))
        result["collections"] = names
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
    finally:
        try:
            disconnect_milvus(alias=alias)
        except Exception:  # noqa: BLE001
            pass
    return result
