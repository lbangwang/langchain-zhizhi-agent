"""API 请求 / 响应 Schema（Pydantic）。

统一外层包装 `ApiResult`：`code==0` 表示成功，非 0 为业务失败。
这样 HTTP 状态码可保持 200，前端按 `code` 分支处理（与 Java 版习惯对齐）。
"""

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResult(BaseModel, Generic[T]):
    """通用 API 返回体。"""

    code: int = 0
    message: str = "ok"
    data: T | None = None

    @classmethod
    def ok(cls, data: T | None = None, message: str = "ok") -> "ApiResult[T]":
        """功能：构造成功响应（code=0）。

        技术点：classmethod；泛型 T 对应 data 类型；HTTP 仍可为 200。
        """
        return cls(code=0, message=message, data=data)

    @classmethod
    def fail(cls, message: str, code: int = 1) -> "ApiResult[Any]":
        """功能：构造业务失败（默认 code=1，data=None）。

        技术点：与 401/403 区分：鉴权失败用 HTTP 状态码，业务失败用 code 字段。
        """
        return cls(code=code, message=message, data=None)


class CreateUserRequest(BaseModel):
    """创建用户请求体（受保护；推荐走 /api/auth/register）。"""

    username: str = Field(min_length=1, max_length=64, description="登录名，全局唯一")
    nickname: str | None = Field(default=None, max_length=64, description="昵称，缺省用 username")
    password: str | None = Field(default=None, min_length=6, max_length=72, description="明文密码，服务端哈希")
    create_by: str | None = Field(default=None, description="创建人标识")


class RegisterRequest(BaseModel):
    """注册请求。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=72)
    nickname: str | None = Field(default=None, max_length=64)


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=72)


class UserResponse(BaseModel):
    """用户对外字段（不含 password_hash）。"""

    id: str
    username: str
    nickname: str | None = None
    status: int
    create_date: datetime
    update_date: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """登录/注册成功后的 token 与用户信息。"""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class CreateConversationRequest(BaseModel):
    """创建会话请求体。

    `user_id` 已废弃：归属一律取自 JWT，客户端传入会被忽略。
    """

    agent_type: str = Field(default="SUPER_AGENT", max_length=32, description="智能体类型")
    title: str = Field(default="新对话", max_length=128, description="会话标题")
    model: str | None = Field(default=None, max_length=64, description="选用模型")
    chat_id: str | None = Field(
        default=None,
        min_length=32,
        max_length=32,
        description="可选；不传则服务端生成",
    )
    create_by: str | None = None


class UpdateConversationRequest(BaseModel):
    """更新会话：仅提交需要修改的字段。"""

    title: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=64)
    status: int | None = Field(default=None, description="1=进行中 0=归档")
    update_by: str | None = None


class ConversationResponse(BaseModel):
    """会话对外字段。"""

    id: str
    chat_id: str
    user_id: str | None
    agent_type: str
    title: str
    model: str | None
    status: int
    create_date: datetime
    update_date: datetime

    model_config = {"from_attributes": True}


class CreateMessageRequest(BaseModel):
    """追加消息请求体。"""

    role: str = Field(min_length=1, max_length=32, description="user/assistant/system/tool")
    content: str = Field(description="消息正文")
    metadata: str | None = Field(default=None, description="可选 JSON 字符串（思考链/工具摘要等）")
    create_by: str | None = None


class MessageResponse(BaseModel):
    """消息对外字段。

    注意：ORM 字段名是 `metadata_json`，此处对外仍暴露为 `metadata`。
    """

    id: str
    conversation_id: str
    role: str
    content: str
    metadata: str | None = None
    create_date: datetime
    update_date: datetime

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    """续聊请求：发送一条用户文本。"""

    content: str = Field(min_length=1, description="用户输入")
    use_rag: bool = Field(default=True, description="是否注入知识库检索")
    model: str | None = Field(
        default=None,
        max_length=64,
        description="大模型：qwen / doubao / deepseek（Key 取自 .env）",
    )


class ChatResponse(BaseModel):
    """续聊响应：回传本轮 user/assistant 消息，以及可能更新后的标题。"""

    chat_id: str
    title: str
    user_message: MessageResponse
    assistant_message: MessageResponse
    citations: list[dict] | None = None
    rag_debug: dict | None = None


class AgentRunRequest(BaseModel):
    """多步 Agent 运行请求。"""

    content: str = Field(min_length=1, description="用户任务描述")
    use_tools: bool = Field(
        default=True,
        description="true=LangGraph create_react_agent 真工具；false=演示步进循环",
    )
    multi_agent: bool = Field(
        default=False,
        description="true=Planner→Worker 多 Agent 最小链路（W4 D3）",
    )
    model: str | None = Field(
        default=None,
        max_length=64,
        description="大模型：qwen / doubao / deepseek",
    )


class KbDocumentResponse(BaseModel):
    """知识库文档列表项。"""

    id: str
    filename: str
    content_type: str | None
    char_count: int
    chunk_count: int
    create_date: datetime

    model_config = {"from_attributes": True}


class ArtifactResponse(BaseModel):
    """产物元数据。"""

    id: str
    filename: str
    content_type: str | None
    byte_size: int
    chat_id: str | None
    create_date: datetime
    download_url: str | None = None

    model_config = {"from_attributes": True}


class ToolAuditResponse(BaseModel):
    """工具审计条目。"""

    id: str
    tool_name: str
    input_preview: str | None
    output_preview: str | None
    status: str
    config_version: str | None = None
    chat_id: str | None
    create_date: datetime

    model_config = {"from_attributes": True}


class AgentConfigResponse(BaseModel):
    """Agent 配置版本。"""

    id: str
    version: str
    name: str
    system_prompt: str | None
    tools: list[str]
    max_tool_calls: int
    timeout_seconds: int
    hitl_enabled: bool
    is_active: bool
    create_date: datetime
    update_date: datetime


class AgentConfigUpdateRequest(BaseModel):
    """更新并 bump 新版本。"""

    system_prompt: str | None = None
    tools: list[str] | None = None
    max_tool_calls: int | None = Field(default=None, ge=1, le=32)
    timeout_seconds: int | None = Field(default=None, ge=30, le=600)
    hitl_enabled: bool | None = None
    name: str | None = None
    bump_version: bool = True


class QuotaResponse(BaseModel):
    used: int
    limit: int
    remaining: int
    enforced: bool | None = None
