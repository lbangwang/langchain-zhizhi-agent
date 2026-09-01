"""大模型列表：供前端下拉展示千问 / 豆包 / DeepSeek。"""

from __future__ import annotations

from fastapi import APIRouter

from app.model_router import DEFAULT_MODEL, list_model_options
from app.schemas import ApiResult

router = APIRouter(prefix="/models", tags=["大模型"])


@router.get("", response_model=ApiResult[dict])
def get_models() -> ApiResult[dict]:
    """功能：返回模型下拉项及 Key 是否已配置。

    技术点：不把 API Key 回给前端，只给 available 布尔值。
    """
    return ApiResult.ok(
        {
            "default": DEFAULT_MODEL,
            "items": list_model_options(),
        }
    )
