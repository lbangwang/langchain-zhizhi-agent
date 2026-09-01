"""大模型路由：前端 model 参数 → 配置文件中的 Key / Base URL / 模型名。

前端约定（与 Java 版一致）：
- `qwen`：通义千问（DASHSCOPE_* / MODEL_NAME）
- `deepseek`：DeepSeek（DEEPSEEK_*）
- `doubao`：豆包 / 火山方舟（DOUBAO_* 或 ARK_API_KEY）
"""

from __future__ import annotations

from dataclasses import dataclass

from openai import OpenAI

from app.config import Settings, get_settings

# 前端展示用 id
MODEL_QWEN = "qwen"
MODEL_DEEPSEEK = "deepseek"
MODEL_DOUBAO = "doubao"
DEFAULT_MODEL = MODEL_QWEN

_ALIASES = {
    "qwen": MODEL_QWEN,
    "qwen-plus": MODEL_QWEN,
    "dashscope": MODEL_QWEN,
    "tongyi": MODEL_QWEN,
    "deepseek": MODEL_DEEPSEEK,
    "deepseek-chat": MODEL_DEEPSEEK,
    "doubao": MODEL_DOUBAO,
    "ark": MODEL_DOUBAO,
    "volc": MODEL_DOUBAO,
}


@dataclass(frozen=True)
class ResolvedLlm:
    """解析后的 LLM 连接信息。"""

    provider: str
    model: str
    api_key: str
    base_url: str


def normalize_model_id(model_param: str | None) -> str:
    """功能：把前端/会话里的模型名归一成 qwen / deepseek / doubao。

    技术点：别名表 + 前缀判断；空值回落到 DEFAULT_MODEL（千问）。
    """
    if not model_param or not str(model_param).strip():
        return DEFAULT_MODEL
    key = str(model_param).strip().lower()
    if key in _ALIASES:
        return _ALIASES[key]
    # 已是完整模型名时：尽量归类
    if key.startswith("qwen"):
        return MODEL_QWEN
    if key.startswith("deepseek"):
        return MODEL_DEEPSEEK
    if key.startswith("doubao") or "seed" in key:
        return MODEL_DOUBAO
    return DEFAULT_MODEL


def _doubao_api_key(settings: Settings) -> str:
    """功能：读取豆包 Key（兼容 DOUBAO_API_KEY 与 ARK_API_KEY）。

    技术点：火山方舟两套环境变量名，谁配了用谁。
    """
    return (settings.doubao_api_key or settings.ark_api_key or "").strip()


def resolve_llm(
    model_param: str | None = None,
    settings: Settings | None = None,
) -> ResolvedLlm:
    """功能：按模型 id 解析出真实 model 名、Key、base_url。

    技术点：缺 Key 抛 RuntimeError，由上层回退或占位回复。
    """
    settings = settings or get_settings()
    mid = normalize_model_id(model_param)

    if mid == MODEL_DEEPSEEK:
        if not settings.deepseek_api_key:
            raise RuntimeError("未配置 DEEPSEEK_API_KEY，无法使用 DeepSeek")
        return ResolvedLlm(
            provider=MODEL_DEEPSEEK,
            model=settings.deepseek_model or "deepseek-chat",
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )

    if mid == MODEL_DOUBAO:
        key = _doubao_api_key(settings)
        if not key:
            raise RuntimeError("未配置 DOUBAO_API_KEY / ARK_API_KEY，无法使用豆包")
        model = (settings.doubao_model or "").strip()
        if not model:
            raise RuntimeError("未配置 DOUBAO_MODEL（火山方舟接入点 ID）")
        return ResolvedLlm(
            provider=MODEL_DOUBAO,
            model=model,
            api_key=key,
            base_url=settings.doubao_base_url,
        )

    # 默认千问
    if not settings.dashscope_api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY，无法使用千问")
    return ResolvedLlm(
        provider=MODEL_QWEN,
        model=settings.model_name or "qwen-plus",
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
    )


def build_openai_client(
    model_param: str | None = None,
    settings: Settings | None = None,
) -> tuple[OpenAI, str, str]:
    """功能：构造 OpenAI 兼容客户端（可被 LangSmith wrap）。

    技术点：OpenAI SDK + 自定义 base_url；maybe_wrap_openai 可关。
    """
    resolved = resolve_llm(model_param, settings)
    client = OpenAI(api_key=resolved.api_key, base_url=resolved.base_url)
    # 可关：未开 LangSmith 时原样返回
    from app.langsmith_setup import maybe_wrap_openai

    return maybe_wrap_openai(client), resolved.model, resolved.provider


def list_model_options(settings: Settings | None = None) -> list[dict]:
    """功能：前端模型下拉；available 表示 .env 是否已配 Key。

    技术点：不回传 Key；豆包还要有接入点 ID 才算 available。
    """
    settings = settings or get_settings()
    return [
        {
            "id": MODEL_QWEN,
            "label": "千问",
            "available": bool(settings.dashscope_api_key),
        },
        {
            "id": MODEL_DOUBAO,
            "label": "豆包",
            "available": bool(_doubao_api_key(settings) and settings.doubao_model),
        },
        {
            "id": MODEL_DEEPSEEK,
            "label": "DeepSeek",
            "available": bool(settings.deepseek_api_key),
        },
    ]
