#!/bin/bash
# 容器入口：等 MySQL、套 schema、后台拉起图片搜索 MCP，再前台跑 uvicorn。
# 约定：SSE / HITL 依赖进程内状态，必须 --workers 1。
set -euo pipefail
cd /app

echo "[entrypoint] applying MySQL schema..."
python docker/init_schema.py

echo "[entrypoint] seeding preset users..."
# 必须 export：仅前缀 PYTHONPATH= 在部分镜像/entrypoint 组合下不会进子进程 sys.path
export PYTHONPATH=/app
python -c "import app; print('[entrypoint] import app ok')"
python /app/scripts/seed_users.py

echo "[entrypoint] starting MCP image-search on 127.0.0.1:8765"
python -m mcp_servers.image_search &

echo "[entrypoint] uvicorn 0.0.0.0:8124 (workers=1)"
exec uvicorn app.main:app --host 0.0.0.0 --port 8124 --workers 1
