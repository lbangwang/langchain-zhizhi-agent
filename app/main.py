"""FastAPI 应用入口。

启动方式（任选其一）：
    # 像 Java 跑 main：直接运行本文件，或 IDE 右键 Run
    python -m app.main
    # 或命令行
    uvicorn app.main:app --reload --port 8124

优先托管 Vite 构建产物 `web/dist`；否则回退 CDN 版 `frontend/`。
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.langsmith_setup import configure_langsmith, langsmith_status

# 尽早写入 LANGSMITH_* 环境变量，供 ChatOpenAI / OpenAI wrap 读取
configure_langsmith()

ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = ROOT / "web" / "dist"
FRONTEND_DIR = ROOT / "frontend"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """功能：进程启动时打印 MySQL/Redis/Milvus/LangSmith/前端状态。

    技术点：FastAPI lifespan；yield 前是启动、yield 后是关闭（本项目关闭无额外清理）。
    """
    settings = get_settings()
    if settings.mysql_enabled:
        from app import models as _models  # noqa: F401

        print(
            f"[startup] MySQL enabled -> "
            f"{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}"
        )
    else:
        print("[startup] MySQL disabled (set MYSQL_ENABLED=true to open CRUD APIs)")
    if settings.redis_enabled:
        from app.redis_client import redis_ping

        ok = redis_ping()
        print(
            f"[startup] Redis enabled -> {settings.redis_host}:{settings.redis_port} "
            f"({'ok' if ok else 'UNREACHABLE'})"
        )
    else:
        print("[startup] Redis disabled (set REDIS_ENABLED=true for agent stop signal)")
    if settings.milvus_enabled:
        print(
            f"[startup] Milvus enabled -> {settings.milvus_host}:{settings.milvus_port} "
            "(run: python scripts/check_milvus.py)"
        )
    else:
        print("[startup] Milvus disabled (set MILVUS_ENABLED=true for RAG)")
    ls = configure_langsmith()
    if ls["enabled"]:
        print(f"[startup] LangSmith enabled -> project={ls['project']}")
    else:
        hint = {
            "flag_off": "set LANGSMITH_TRACING=true and LANGSMITH_API_KEY to enable",
            "missing_api_key": "LANGSMITH_TRACING=true but LANGSMITH_API_KEY empty",
            "package_missing": "pip install langsmith",
        }.get(str(ls["reason"]), str(ls["reason"]))
        print(f"[startup] LangSmith disabled ({hint})")
    if WEB_DIST.is_dir() and (WEB_DIST / "index.html").exists():
        print(f"[startup] Frontend = Vite dist ({WEB_DIST})")
    else:
        print(f"[startup] Frontend = CDN fallback ({FRONTEND_DIR})")
    yield


app = FastAPI(
    title="Zhizhi AI Agent",
    description="Python + LangChain/LangGraph Agent platform (enterprise portfolio)",
    version="0.2.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str | bool | None]:
    """功能：健康检查，给探活和演示看依赖是否通。

    技术点：不查 MySQL 连通性（只报开关）；Redis PING；Milvus ping；LangSmith 仅报是否启用。
    """
    settings = get_settings()
    redis_ok = False
    if settings.redis_enabled:
        from app.redis_client import redis_ping

        redis_ok = redis_ping()

    milvus_ok: bool | None = None
    milvus_error: str | None = None
    if settings.milvus_enabled:
        from rag.milvus_client import ping_milvus

        milvus = ping_milvus()
        milvus_ok = bool(milvus["ok"])
        milvus_error = milvus.get("error")

    return {
        "status": "ok",
        "mysql_enabled": settings.mysql_enabled,
        "redis_enabled": settings.redis_enabled,
        "redis_ok": redis_ok,
        "milvus_enabled": settings.milvus_enabled,
        "milvus_ok": milvus_ok if milvus_ok is not None else False,
        "milvus_uri": f"{settings.milvus_host}:{settings.milvus_port}",
        "milvus_error": milvus_error or "",
        "frontend": "vite" if WEB_DIST.is_dir() else "cdn",
        "langsmith_enabled": langsmith_status()["enabled"],
        "langsmith_project": langsmith_status()["project"] if langsmith_status()["enabled"] else "",
        "register_enabled": bool(settings.register_enabled),
    }


# 业务 API 先挂载
settings = get_settings()
if settings.mysql_enabled:
    from app.routers import (
        agent,
        artifacts,
        audits,
        auth,
        chat,
        conversations,
        hitl,
        knowledge,
        models,
        traces,
        users,
    )

    app.include_router(auth.router, prefix="/api")
    app.include_router(users.router, prefix="/api")
    app.include_router(conversations.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(agent.router, prefix="/api")
    app.include_router(hitl.router, prefix="/api")
    app.include_router(knowledge.router, prefix="/api")
    app.include_router(artifacts.router, prefix="/api")
    app.include_router(audits.router, prefix="/api")
    app.include_router(traces.router, prefix="/api")
    app.include_router(models.router, prefix="/api")
else:
    # MySQL 关闭时未挂载 /api/*；避免 POST 撞上 SPA 的 GET 兜底变成 405
    @app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def api_mysql_disabled(full_path: str) -> dict[str, str]:
        """功能：MySQL 关闭时拦截所有 /api，返回 503。

        技术点：避免 POST 落到 SPA GET 兜底变成 405，误导成「方法不对」。
        """
        from fastapi import HTTPException

        raise HTTPException(
            status_code=503,
            detail="MySQL 未启用：请在项目根目录 .env 设置 MYSQL_ENABLED=true 后重启",
        )


# 前端：优先 Vite dist（SPA history fallback）
if WEB_DIST.is_dir() and (WEB_DIST / "index.html").exists():
    assets = WEB_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="vite-assets")

    @app.get("/")
    def spa_index() -> FileResponse:
        """功能：返回 Vue 构建后的首页。

        技术点：托管 web/dist；history 路由由 spa_fallback 回退 index.html。
        """
        return FileResponse(WEB_DIST / "index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        """功能：前端刷新 /workspace 等路径时仍返回 index.html。

        技术点：不拦截 api/health/docs；真实静态文件优先，否则 SPA fallback。
        """
        # 不拦截 api / health / docs
        if full_path.startswith(("api/", "health", "docs", "openapi", "redoc")):
            from fastapi import HTTPException

            raise HTTPException(status_code=404)
        candidate = WEB_DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")

elif FRONTEND_DIR.exists():
    @app.get("/")
    def chat_page() -> FileResponse:
        """功能：没有 Vite dist 时回退 CDN 版 frontend/index.html。"""
        return FileResponse(FRONTEND_DIR / "index.html")

    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")


if __name__ == "__main__":
    # 等价于 Java 的 public static void main：IDE 直接 Run 本文件即可启动
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8124,
        reload=True,
    )
