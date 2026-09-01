"""统一业务错误码（企业级 Phase2）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppError:
    """可序列化到 HTTP / SSE 的业务错误。"""

    code: str
    message: str

    def to_dict(self) -> dict:
        """功能：转成 SSE / JSON 错误事件（type=error）。

        技术点：与前端约定用 code 分支，而不是只看 HTTP 状态码。
        """
        return {"type": "error", "code": self.code, "message": self.message}


# --- 预定义 ---
AGENT_TIMEOUT = AppError("AGENT_TIMEOUT", "任务超时，请缩短任务或提高超时配置后重试")
HITL_REJECTED = AppError("HITL_REJECTED", "用户拒绝执行危险工具")
HITL_TIMEOUT = AppError("HITL_TIMEOUT", "人工确认超时，已自动拒绝")
QUOTA_EXCEEDED = AppError("QUOTA_EXCEEDED", "今日 Agent 运行次数已达配额上限")
RAG_EMPTY = AppError("RAG_EMPTY", "知识库未检索到相关片段")
CONFIG_NOT_FOUND = AppError("CONFIG_NOT_FOUND", "Agent 配置版本不存在")
AGENT_STOPPED = AppError("AGENT_STOPPED", "任务已停止")
AGENT_FAILED = AppError("AGENT_FAILED", "Agent 运行失败")
REDIS_REQUIRED = AppError("REDIS_REQUIRED", "Redis 未启用，无法运行可取消 Agent")
REGISTER_DISABLED = AppError("REGISTER_DISABLED", "当前环境已关闭注册，请使用已有账号登录")
