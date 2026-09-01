"""职责：写入生产预置账号（密码 PBKDF2 哈希，不明文入库）。

技术点：按 username upsert；已存在则更新密码与启用状态。容器启动时由 entrypoint 调用。
"""

from __future__ import annotations

import sys
from pathlib import Path

# python scripts/seed_users.py 时 sys.path[0] 是 scripts/，加仓库根才能 import app
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 预置账号：部署后用这些登录。勿把明文密码写进前端或日志。
SEED_USERS: tuple[tuple[str, str, str], ...] = (
    ("zhizhi", "123456", "枝枝"),
    ("lbwcc", "lhh123..", "lbwcc"),
    ("admin", "ad23..", "管理员"),
)


def main() -> int:
    """功能：把 SEED_USERS 写入 app_user；MySQL 未启用则跳过。"""
    from sqlalchemy import select

    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import AppUser
    from app.security import hash_password
    from app.utils import new_id, utcnow

    settings = get_settings()
    if not settings.mysql_enabled or SessionLocal is None:
        print("[seed-users] MYSQL_ENABLED=false，跳过")
        return 0

    now = utcnow()
    created = 0
    updated = 0
    with SessionLocal() as db:
        for username, password, nickname in SEED_USERS:
            row = db.scalar(
                select(AppUser).where(AppUser.username == username, AppUser.is_del == 0)
            )
            if row is None:
                db.add(
                    AppUser(
                        id=new_id(),
                        username=username,
                        password_hash=hash_password(password),
                        nickname=nickname,
                        status=1,
                        create_date=now,
                        create_by="seed",
                        update_date=now,
                        update_by="seed",
                        is_del=0,
                    )
                )
                created += 1
                print(f"[seed-users] created {username}")
            else:
                row.password_hash = hash_password(password)
                row.nickname = nickname
                row.status = 1
                row.update_date = now
                row.update_by = "seed"
                updated += 1
                print(f"[seed-users] updated {username}")
        db.commit()
    print(f"[seed-users] done created={created} updated={updated}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
