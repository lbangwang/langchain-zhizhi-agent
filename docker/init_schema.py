"""职责：容器启动时用 PyMySQL 建库并执行 db/*.sql（不依赖宿主机 mysql 客户端）。

技术点：等待连通；CREATE DATABASE；按序执行 schema；重复 ALTER 忽略 1060/1061。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILES = [
    "schema.sql",
    "schema_w2.sql",
    "schema_w2_patch_content_type.sql",
    "schema_w3.sql",
    "schema_w4.sql",
]


def _env(name: str, default: str) -> str:
    """功能：读环境变量，空串视为未设置并回退默认值。"""
    val = os.environ.get(name)
    return default if val is None or val == "" else val


def _connect(*, database: str | None = None, retries: int = 40):
    """功能：带重试连接 MySQL，等容器健康后再建表。

    技术点：pymysql；connect_timeout；失败 sleep 2s。
    """
    host = _env("MYSQL_HOST", "127.0.0.1")
    port = int(_env("MYSQL_PORT", "3306"))
    user = _env("MYSQL_USER", "root")
    password = _env("MYSQL_PASSWORD", "root")
    last: Exception | None = None
    for i in range(retries):
        try:
            return pymysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                charset="utf8mb4",
                autocommit=True,
                connect_timeout=5,
            )
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"[init-schema] waiting MySQL {host}:{port} ({i + 1}/{retries}): {exc}")
            time.sleep(2)
    raise RuntimeError(f"MySQL 不可达: {last}") from last


def _strip_sql_comments(sql: str) -> str:
    """功能：去掉整行 -- 注释，避免首条 CREATE 因文件头注释被误跳过。"""
    lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _run_sql(cur, sql: str) -> None:
    """功能：执行一份 SQL 文件（多语句）；列已存在类错误只告警不退出。"""
    for stmt in _strip_sql_comments(sql).split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            cur.execute(stmt)
        except pymysql.err.OperationalError as exc:
            # 1060 duplicate column / 1061 duplicate key
            if exc.args and exc.args[0] in {1060, 1061}:
                print(f"[init-schema] skip (already applied): {exc.args[1]}")
                continue
            raise


def main() -> int:
    """功能：确保数据库存在并套用 W1～W4 schema。"""
    db_name = _env("MYSQL_DATABASE", "zhizhi_ai_agent")
    conn = _connect(database=None)
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
            "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    conn.close()

    conn = _connect(database=db_name)
    with conn.cursor() as cur:
        for name in SCHEMA_FILES:
            path = ROOT / "db" / name
            if not path.is_file():
                print(f"[init-schema] missing {path}, skip")
                continue
            print(f"[init-schema] applying {name}")
            _run_sql(cur, path.read_text(encoding="utf-8"))
    conn.close()
    print("[init-schema] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
