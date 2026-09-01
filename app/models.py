"""ORM 模型（W1 D2：用户 / 会话 / 消息）。

约定：
- 业务主键多为 32 位字符串（UUID 去横线），见 `app.utils.new_id`
- 删除一律软删：`is_del=1`，查询默认过滤 `is_del==0`
- 审计字段：`create_date` / `update_date` / `create_by` / `update_by`
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AppUser(Base):
    """功能：用户表 app_user，登录与数据隔离的根。

    技术点：CHAR(32) 主键；password_hash 不明文；is_del 软删；JWT sub 对应该 id。
    """

    __tablename__ = "app_user"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # 32 位业务主键
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 1=正常 0=禁用
    create_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    create_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    update_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    update_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_del: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0=未删 1=已删
    enterprise_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 预留多租户


class Conversation(Base):
    """功能：会话表；一条对话线程。

    技术点：id 主键、chat_id 对外唯一；agent_type 隔离面试官/多Agent/超级智能体。
    """

    __tablename__ = "conversation"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    agent_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 如 SUPER_AGENT
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 选用模型名
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 1=进行中 0=归档
    create_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    create_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    update_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    update_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_del: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enterprise_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Message(Base):
    """功能：消息表，挂在 conversation.id 下。

    技术点：列名 metadata 与 SQLAlchemy 冲突，属性叫 metadata_json 再 mapped_column 映射。
    """

    __tablename__ = "message"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # user/assistant/system/tool
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)
    create_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    create_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    update_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    update_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_del: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enterprise_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class KbDocument(Base):
    """功能：知识库文档元数据（正文向量在 Milvus）。

    技术点：MySQL 存文件名/切片数；按 user_id 隔离。
    """

    __tablename__ = "kb_document"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    create_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    create_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    update_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    update_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_del: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ToolAudit(Base):
    """功能：工具调用审计行（搜了什么、写了什么）。

    技术点：只存 preview 截断，避免整段大文件进库。
    """

    __tablename__ = "tool_audit"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    chat_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    input_preview: Mapped[str | None] = mapped_column(String(512), nullable=True)
    output_preview: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ok", nullable=False)
    config_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    create_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Artifact(Base):
    """功能：Agent 生成的 txt/pdf/docx 产物元数据。

    技术点：storage_path 在磁盘；下载接口按 user_id 校验。
    """

    __tablename__ = "artifact"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    chat_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    create_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_del: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class TraceSpan(Base):
    """功能：一次请求的 Trace 片段（根 + 步骤）。

    技术点：kind=root/step；meta_json 存 token、langsmith_run_id；按 user_id 查。
    """

    __tablename__ = "trace_span"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    parent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    chat_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="root", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ok", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentConfig(Base):
    """功能：超级智能体配置版本（prompt、工具白名单、HITL、超时）。

    技术点：tools_json 存列表；is_active 标记当前版；缺表时内存默认。
    """

    __tablename__ = "agent_config"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), default="default", nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    tools_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_tool_calls: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=180, nullable=False)
    hitl_enabled: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    create_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    update_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_del: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
