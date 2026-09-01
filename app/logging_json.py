"""结构化 JSON 日志（企业级 Phase2）。"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """功能：把 logging.LogRecord 打成一行 JSON（便于采集）。

    技术点：从 record 上摘业务字段（chat_id、trace_id 等）；ensure_ascii=False 保中文。
    """

    def format(self, record: logging.LogRecord) -> str:
        """功能：LogRecord → JSON 字符串。

        技术点：覆盖 Formatter.format；异常栈放在 exc 字段。
        """
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("request_id", "chat_id", "trace_id", "user_id", "code", "config_version", "model"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def get_logger(name: str = "zhizhi") -> logging.Logger:
    """功能：拿到带 JsonFormatter 的 logger（只加一次 handler）。

    技术点：propagate=False 避免和 root logger 打两遍。
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def log_event(
    msg: str,
    *,
    level: int = logging.INFO,
    request_id: str | None = None,
    chat_id: str | None = None,
    trace_id: str | None = None,
    user_id: str | None = None,
    code: str | None = None,
    config_version: str | None = None,
    model: str | None = None,
) -> None:
    """功能：写一条带 user/chat/trace 等字段的业务日志。

    技术点：通过 logger extra 传到 Formatter；新字段要先扩参数再打，避免静默丢失。
    """
    logger = get_logger()
    extra = {
        "request_id": request_id or "",
        "chat_id": chat_id or "",
        "trace_id": trace_id or "",
        "user_id": user_id or "",
        "code": code or "",
        "config_version": config_version or "",
        "model": model or "",
    }
    logger.log(level, msg, extra=extra)
