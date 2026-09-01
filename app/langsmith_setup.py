"""职责：LangSmith 可关闭观测——默认不上报，失败不影响主链路。

技术点：LANGSMITH_TRACING+API_KEY 才启用；SSE yield 不用 ContextVar.reset(token)。
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, Iterator

from app.config import get_settings

# 当前父 run id，供本地 Trace meta 回写 langsmith_run_id
_current_run_id: ContextVar[str | None] = ContextVar("langsmith_run_id", default=None)

_STATE: dict[str, Any] = {
    "configured": False,
    "enabled": False,
    "reason": "not_configured",
    "project": "",
}


def reset_langsmith_state() -> None:
    """功能：清掉配置缓存，下次重新读取 Settings（测试用）。

    技术点：模块级 _STATE；不改进程环境变量本身。
    """
    _STATE["configured"] = False
    _STATE["enabled"] = False
    _STATE["reason"] = "not_configured"
    _STATE["project"] = ""


def _force_env_off() -> None:
    """功能：把 LangSmith/LangChain 追踪环境变量写成 false。

    技术点：避免残留 LANGCHAIN_TRACING_V2 偷偷上报。
    """
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"


def configure_langsmith(*, force: bool = False) -> dict[str, Any]:
    """功能：按 Settings 打开或关闭 LangSmith，并同步进程环境变量。

    技术点：需 tracing=true 且有 API_KEY；缺包则关闭；force 用于单测重载。
    """
    if _STATE["configured"] and not force:
        return langsmith_status()

    settings = get_settings()
    want = bool(getattr(settings, "langsmith_tracing", False))
    key = (getattr(settings, "langsmith_api_key", "") or "").strip()
    project = (getattr(settings, "langsmith_project", "") or "").strip() or "zhizhi-ai-agent"
    endpoint = (
        getattr(settings, "langsmith_endpoint", "") or "https://api.smith.langchain.com"
    ).strip()
    hide_io = bool(getattr(settings, "langsmith_hide_io", False))

    if not want:
        _force_env_off()
        _STATE.update(
            configured=True, enabled=False, reason="flag_off", project=project
        )
        return langsmith_status()

    if not key:
        _force_env_off()
        _STATE.update(
            configured=True, enabled=False, reason="missing_api_key", project=project
        )
        return langsmith_status()

    try:
        import langsmith  # noqa: F401
    except ImportError:
        _force_env_off()
        _STATE.update(
            configured=True, enabled=False, reason="package_missing", project=project
        )
        return langsmith_status()

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGSMITH_API_KEY"] = key
    os.environ["LANGSMITH_ENDPOINT"] = endpoint
    os.environ["LANGSMITH_PROJECT"] = project
    os.environ["LANGCHAIN_PROJECT"] = project
    os.environ["LANGSMITH_HIDE_INPUTS"] = "true" if hide_io else "false"
    os.environ["LANGSMITH_HIDE_OUTPUTS"] = "true" if hide_io else "false"

    _STATE.update(configured=True, enabled=True, reason="ok", project=project)
    return langsmith_status()


def _ensure_configured() -> None:
    """功能：尚未 configure 时懒加载一次 LangSmith 开关。

    技术点：避免每个调用点重复读 Settings。
    """
    if not _STATE["configured"]:
        configure_langsmith()


def is_langsmith_enabled() -> bool:
    """功能：查询当前进程是否实际上报 LangSmith。

    技术点：读 _STATE.enabled，未配置则先 configure。
    """
    _ensure_configured()
    return bool(_STATE["enabled"])


def langsmith_status() -> dict[str, Any]:
    """功能：返回健康检查/启动日志用的状态快照（不含 Key）。

    技术点：enabled / reason / project。
    """
    return {
        "enabled": bool(_STATE["enabled"]),
        "reason": str(_STATE["reason"]),
        "project": str(_STATE["project"] or ""),
    }


def current_run_id() -> str | None:
    """功能：读取当前线程/协程里的 LangSmith 父 run id。

    技术点：ContextVar；未开启则为 None。
    """
    return _current_run_id.get()


def _set_run_id(rid: str | None) -> None:
    """功能：只 set 当前 run id，不用 ContextVar.reset(token)。

    技术点：async generator yield + to_thread 时 token 跨 Context，reset 会抛错打挂任务。
    """
    try:
        _current_run_id.set(rid)
    except Exception:  # noqa: BLE001
        pass


def _max_chars() -> int:
    """功能：读取上报到 LangSmith 的字符串截断上限。

    技术点：settings.langsmith_max_input_chars，下限 200。
    """
    try:
        n = int(getattr(get_settings(), "langsmith_max_input_chars", 4000) or 4000)
    except Exception:  # noqa: BLE001
        n = 4000
    return max(200, n)


def truncate_for_smith(obj: Any, *, limit: int | None = None) -> Any:
    """功能：递归截断过长字符串，避免把整篇知识库打到 LangSmith。

    技术点：str/dict/list 递归；列表最多 30 项。
    """
    cap = _max_chars() if limit is None else limit
    if isinstance(obj, str):
        if len(obj) <= cap:
            return obj
        return f"{obj[:cap]}...(+{len(obj) - cap} chars)"
    if isinstance(obj, dict):
        return {str(k): truncate_for_smith(v, limit=cap) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        clipped = [truncate_for_smith(v, limit=cap) for v in list(obj)[:30]]
        return clipped
    return obj


def _process_io(payload: Any) -> Any:
    """功能：traceable 的 process_inputs/outputs 回调，失败则返回占位。

    技术点：委托 truncate_for_smith。
    """
    try:
        return truncate_for_smith(payload)
    except Exception:  # noqa: BLE001
        return {"truncated": True}


def maybe_wrap_openai(client: Any) -> Any:
    """功能：给 OpenAI 兼容客户端打点；关闭或失败时返回原 client。

    技术点：langsmith.wrappers.wrap_openai。
    """
    _ensure_configured()
    if not is_langsmith_enabled() or client is None:
        return client
    try:
        from langsmith.wrappers import wrap_openai

        return wrap_openai(client)
    except Exception:  # noqa: BLE001
        return client


def traced(name: str, *, run_type: str = "chain"):
    """功能：函数级装饰器——关闭时零开销直跑；开启时交给 langsmith.traceable。

    技术点：懒缓存 traceable；异常则回退原函数。
    """

    def decorator(func):
        """功能：包一层 wrapper，按开关决定是否走 LangSmith。

        技术点：闭包缓存已包装函数。
        """
        cached: dict[str, Any] = {"fn": None}

        @wraps(func)
        def wrapper(*args, **kwargs):
            """功能：调用原函数或已包装的 traceable 版本。

            技术点：未启用则直跑；包装失败吞异常。
            """
            _ensure_configured()
            if not is_langsmith_enabled():
                return func(*args, **kwargs)
            try:
                if cached["fn"] is None:
                    from langsmith import traceable

                    cached["fn"] = traceable(
                        name=name,
                        run_type=run_type,
                        process_inputs=_process_io,
                        process_outputs=_process_io,
                    )(func)
                return cached["fn"](*args, **kwargs)
            except Exception:  # noqa: BLE001
                return func(*args, **kwargs)

        return wrapper

    return decorator


def capture_parent() -> Any:
    """功能：取出当前 RunTree，供 to_thread 工作线程挂回父 run。

    技术点：get_current_run_tree；未开启返回 None。
    """
    if not is_langsmith_enabled():
        return None
    try:
        from langsmith.run_helpers import get_current_run_tree

        return get_current_run_tree()
    except Exception:  # noqa: BLE001
        return None


@contextmanager
def adopt_parent(parent: Any) -> Iterator[None]:
    """功能：在子线程里挂上父 run，使 LLM/工具 span 能嵌套。

    技术点：langsmith.tracing_context；parent 为空则空跑。
    """
    if parent is None or not is_langsmith_enabled():
        yield
        return
    try:
        from langsmith import tracing_context

        with tracing_context(parent=parent):
            yield
    except Exception:  # noqa: BLE001
        yield


class LangSmithSpan:
    """职责：手动启停的父 run，避免给整段 async generator 加一层 with 缩进。

    技术点：不用 with trace() 跨 SSE yield；只 set 不 reset ContextVar。
    """

    def __init__(self) -> None:
        """功能：初始化空 span（未 post 前 run_id 为 None）。

        技术点：close 可重复调用（_closed 守卫）。
        """
        self.run_id: str | None = None
        self.parent: Any = None
        self._old_ctx: dict[str, Any] | None = None
        self._closed = False

    def meta(self) -> dict[str, str]:
        """功能：返回写入本地 Trace meta 的 langsmith_run_id。

        技术点：无 run 则空 dict。
        """
        return {"langsmith_run_id": self.run_id} if self.run_id else {}

    def close(self) -> None:
        """功能：结束 RunTree（end+patch）并恢复旧 tracing 上下文。

        技术点：显式成功收尾，避免生成器清理异常写进 error；_set_run_id(None)。
        """
        if self._closed:
            return
        self._closed = True
        run = self.parent
        try:
            if run is not None and hasattr(run, "end"):
                # 显式成功收尾：不要把生成器清理时的异常写进 error
                run.end()
                if hasattr(run, "patch"):
                    run.patch()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._old_ctx is not None:
                from langsmith.run_helpers import _set_tracing_context

                _set_tracing_context(self._old_ctx)
        except Exception:  # noqa: BLE001
            pass
        self.parent = None
        self._old_ctx = None
        _set_run_id(None)


def start_span(
    *,
    name: str,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
) -> LangSmithSpan:
    """功能：开始一条 LangSmith 父 run；关闭时务必 span.close()。

    技术点：RunTree.post；失败返回已关闭空 span，不影响主链路。
    """
    span = LangSmithSpan()
    _ensure_configured()
    if not is_langsmith_enabled():
        return span
    try:
        from langsmith.run_helpers import _set_tracing_context, get_tracing_context
        from langsmith.run_trees import RunTree
        from langsmith.utils import get_tracer_project

        old_ctx = get_tracing_context()
        tags_ = list(tags or [])
        meta = dict(truncate_for_smith(metadata or {}) or {})
        project = str(_STATE.get("project") or get_tracer_project() or "default")
        run = RunTree(
            name=name,
            run_type="chain",
            inputs=truncate_for_smith(inputs or {}) or {},
            extra={"metadata": {**meta, "ls_method": "span"}},
            tags=tags_,
            project_name=project,
        )
        run.post()
        span.parent = run
        span.run_id = str(getattr(run, "id", "") or "")
        span._old_ctx = old_ctx
        merged_meta = {**(old_ctx.get("metadata") or {}), **meta}
        _set_tracing_context(
            {
                **old_ctx,
                "parent": run,
                "tags": tags_ or old_ctx.get("tags"),
                "metadata": merged_meta,
                "project_name": project,
            }
        )
        _set_run_id(span.run_id)
    except Exception:  # noqa: BLE001
        try:
            span.close()
        except Exception:  # noqa: BLE001
            pass
        span = LangSmithSpan()
        span._closed = True
        _set_run_id(None)
    return span


@contextmanager
def langsmith_trace(
    *,
    name: str,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
) -> Iterator[str | None]:
    """功能：包一层父 run（chain）；关闭或异常时 yield None，调用方无需分支。

    技术点：适合非流式 chat；流式路径请用 start_span+close，勿跨 yield reset。
    """
    span = start_span(name=name, tags=tags, metadata=metadata, inputs=inputs)
    try:
        yield span.run_id
    finally:
        span.close()
