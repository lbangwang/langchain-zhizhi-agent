"""应用配置：从环境变量 / `.env` 加载。

本模块是配置的唯一入口。业务代码应通过 `get_settings()` 读取配置，
不要在代码中硬编码主机、密码等敏感信息。

`.env` 固定按「项目根目录」解析，避免 IDE / uvicorn 工作目录不是仓库根时
读不到配置，导致 MYSQL_ENABLED 仍为默认 false、登录接口未挂载（表现为 405）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# app/config.py → 上一级即仓库根
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """运行时配置（pydantic-settings）。

    字段名会自动映射为大写环境变量，例如 `mysql_host` <- `MYSQL_HOST`。
    `extra="ignore"`：`.env` 里多余的键（如 LLM Key）不会报错。
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- MySQL ---
    mysql_enabled: bool = False  # false 时不建引擎、不挂载 CRUD 路由
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "zhizhi_ai_agent"
    # 本地 MySQL 8 常用：关闭 SSL；部分 PyMySQL 版本支持公钥检索
    mysql_ssl_disabled: bool = True
    mysql_allow_public_key_retrieval: bool = True

    # --- LLM（W1 D3 简易续聊；后续 Agent/SSE 会复用） ---
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model_name: str = "qwen-plus"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    # 火山方舟 / 豆包（ARK_API_KEY 与 DOUBAO_API_KEY 通常填同一个）
    ark_api_key: str = ""
    doubao_api_key: str = ""
    doubao_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    doubao_model: str = ""

    # --- JWT（W1 D4） ---
    jwt_secret: str = "change-me-in-production"
    jwt_expire_minutes: int = 10080  # 默认 7 天
    jwt_algorithm: str = "HS256"
    # false：关闭 /auth/register 与公开注册页，避免生产环境刷账号耗 token
    register_enabled: bool = False

    # --- Redis（W1 D5 停止信号） ---
    redis_enabled: bool = False
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_password: str = ""
    redis_database: int = 0
    # Agent 每步模拟耗时（秒），便于演示「点停止后不再继续」
    agent_step_delay_seconds: float = 1.2

    # --- Milvus（W2 RAG） ---
    milvus_enabled: bool = False
    milvus_host: str = "127.0.0.1"
    milvus_port: int = 19530
    milvus_collection: str = "zhizhi_kb"
    # 可选：Milvus 用户名/密码（未开启鉴权可留空）
    milvus_user: str = ""
    milvus_password: str = ""

    # --- Embedding / RAG（W2：硅基流动 BAAI/bge-m3） ---
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    rag_top_k: int = 4
    rag_use_rewrite: bool = True
    rag_use_rerank: bool = True
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rag_rerank_backend: str = "bge"  # bge | llm | off
    #相似值
    rag_score:float= 0.7

    # --- Tools / 产物 ---
    tavily_api_key: str = ""
    artifacts_dir: str = "data/artifacts"

    # --- W3 中间件 / HITL / Trace / MCP ---
    memory_summarize_trigger: int = 12  # 对话消息条数达此阈值触发摘要
    memory_keep_recent: int = 8
    hitl_enabled: bool = True
    hitl_timeout_seconds: float = 180.0  # 等人点批准；过短会在 UI 未操作时被当成拒绝
    mcp_enabled: bool = True
    mcp_image_search_url: str = "http://127.0.0.1:8765/search"
    skills_dir: str = "skills"

    # --- W4 稳定性 / 企业治理 ---
    agent_timeout_seconds: float = 180.0
    llm_timeout_seconds: float = 60.0
    agent_daily_quota: int = 50

    # --- LangSmith（默认可关；true 且有 Key 才实际上报，见 app/langsmith_setup.py） ---
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    # 兼容旧变量 LANGCHAIN_PROJECT
    langsmith_project: str = Field(
        default="zhizhi-ai-agent",
        validation_alias=AliasChoices("LANGSMITH_PROJECT", "LANGCHAIN_PROJECT"),
    )
    # 上报前截断过长 Prompt/上下文，避免单条 trace 过大
    langsmith_max_input_chars: int = 4000
    # true 时只上报结构、不传输入输出正文（演示排查时保持 false）
    langsmith_hide_io: bool = False

    @property
    def llm_ready(self) -> bool:
        """功能：判断是否至少配好一个云端模型 Key（否则走本地占位回复）。

        技术点：千问 / DeepSeek / 豆包（需 Key+接入点 ID）三选一即可。
        """
        doubao_ok = bool((self.doubao_api_key or self.ark_api_key) and self.doubao_model)
        return bool(self.dashscope_api_key or self.deepseek_api_key or doubao_ok)

    @property
    def redis_url(self) -> str:
        """功能：拼 redis:// 连接串给 redis-py。

        技术点：密码 quote_plus，避免 @ : 特殊字符拆坏 URL。
        """
        auth = f":{quote_plus(self.redis_password)}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_database}"

    @property
    def database_url(self) -> str:
        """功能：拼 SQLAlchemy MySQL 连接串（PyMySQL 驱动）。

        技术点：mysql+pymysql；用户名密码 URL 编码；charset=utf8mb4。
        """
        user = quote_plus(self.mysql_user)
        password = quote_plus(self.mysql_password)
        return (
            f"mysql+pymysql://{user}:{password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            "?charset=utf8mb4"
        )

    @property
    def mysql_connect_args(self) -> dict[str, bool]:
        """功能：按本机 PyMySQL 版本过滤 connect 参数。

        技术点：inspect.signature 丢掉不支持的关键字，避免启动直接报错。
        """
        import inspect

        import pymysql

        supported = set(inspect.signature(pymysql.connect).parameters)
        args: dict[str, bool] = {}
        if "ssl_disabled" in supported:
            args["ssl_disabled"] = self.mysql_ssl_disabled
        if "allow_public_key_retrieval" in supported:
            args["allow_public_key_retrieval"] = self.mysql_allow_public_key_retrieval
        return args


@lru_cache
def get_settings() -> Settings:
    """功能：读取 .env 得到全局配置单例。

    技术点：pydantic-settings；lru_cache 进程内只解析一次，改 .env 需重启。
    """
    return Settings()
