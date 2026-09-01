"""数据库引擎与 Session 依赖。

仅在 `MYSQL_ENABLED=true` 时创建引擎；否则 CRUD 路由不会注册，
调用 `get_db()` 会抛出明确错误，避免静默连错库。
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# 模块加载时按开关初始化；禁用时保持为 None
engine = None
SessionLocal: sessionmaker[Session] | None = None

if settings.mysql_enabled:
    engine = create_engine(
        settings.database_url,
        # 取连接前探测，降低「连接已被服务端断开」导致的首请求失败
        pool_pre_ping=True,
        # 定时回收连接，避免 MySQL wait_timeout 后拿到僵死连接
        pool_recycle=3600,
        connect_args=settings.mysql_connect_args,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """功能：所有 ORM 模型的基类。

    技术点：SQLAlchemy 2.0 DeclarativeBase。
    """

    pass


def get_db() -> Generator[Session, None, None]:
    """功能：FastAPI 依赖，每个请求借出一个 Session，结束必关。

    技术点：生成器 + yield（Depends 会在请求结束后跑 finally）；
    pool_pre_ping / pool_recycle 在模块加载建引擎时已配置。
    """
    if SessionLocal is None:
        raise RuntimeError("MySQL is disabled. Set MYSQL_ENABLED=true in .env")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
