#!/usr/bin/env bash
# 本机 Docker：docker-compose.local.yml（宿主机 8125 / 3307 / 6380）。
# 用法（仓库根目录）：
#   bash scripts/docker-local.sh check|up|logs|health|down|rebuild
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
COMPOSE=(docker compose -f docker-compose.local.yml)
APP_URL="http://127.0.0.1:8125"
APP_CONTAINER="zhizhi-local-app"

red() { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }

need_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    red "未找到 docker CLI。请先：brew install colima docker docker-compose"
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    red "Docker 引擎未运行。"
    echo "若用 Colima：colima start --cpu 4 --memory 8 --disk 60 --arch aarch64"
    echo "若用 Docker Desktop：先打开应用程序，等到菜单栏鲸鱼就绪。"
    exit 1
  fi
}

port_busy() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print; exit 0}'
}

cmd_check() {
  need_docker
  green "Docker 引擎正常。"
  docker version --format 'Client {{.Client.Version}} / Server {{.Server.Version}}' 2>/dev/null || docker version
  echo
  if [[ ! -f .env ]]; then
    red "缺少 .env。请：cp .env.example .env  然后填模型 Key。"
    exit 1
  fi
  green "找到 .env"
  echo
  echo "本机 Docker 映射端口（与手动 8124/3306/6379 错开）："
  for p in 8125 3307 6380; do
    hit="$(port_busy "$p" || true)"
    if [[ -n "${hit}" ]]; then
      yellow "  :$p 已被占用 — $hit"
    else
      echo "  :$p 空闲"
    fi
  done
  echo
  echo "手动启动常用端口（占用没关系，本套 compose 不占用它们）："
  for p in 8124 3306 6379; do
    hit="$(port_busy "$p" || true)"
    if [[ -n "${hit}" ]]; then
      echo "  :$p 占用中（预期可与 Docker 并存）— $hit"
    else
      echo "  :$p 空闲"
    fi
  done
  echo
  echo "本机 Docker 容器："
  docker ps -a --filter name=zhizhi-local- --format '  {{.Names}}\t{{.Status}}\t{{.Ports}}' || true
}

cmd_up() {
  need_docker
  if [[ ! -f .env ]]; then
    red "缺少 .env"
    exit 1
  fi
  if docker ps --format '{{.Names}}' | grep -qx "$APP_CONTAINER"; then
    yellow "${APP_CONTAINER} 已在跑。浏览器：${APP_URL}/"
    exit 0
  fi
  echo "构建并启动本机 Docker（首次 10～20 分钟）…"
  "${COMPOSE[@]}" up -d --build
  echo
  green "已启动。浏览器打开 ${APP_URL}/"
  echo "日志：bash scripts/docker-local.sh logs"
  echo "探活：bash scripts/docker-local.sh health"
}

cmd_logs() {
  need_docker
  "${COMPOSE[@]}" logs -f --tail=80 app
}

cmd_health() {
  need_docker
  echo "=== compose ps ==="
  "${COMPOSE[@]}" ps
  echo
  echo "=== GET ${APP_URL}/health ==="
  curl -sS --max-time 5 "${APP_URL}/health" || {
    red "8125 无响应。看：bash scripts/docker-local.sh logs"
    exit 1
  }
  echo
}

cmd_down() {
  need_docker
  "${COMPOSE[@]}" down
  green "已停止本机 Docker 容器（数据卷还在）。"
  echo "若要连库数据一起删：docker compose -f docker-compose.local.yml down -v"
}

cmd_rebuild() {
  need_docker
  "${COMPOSE[@]}" up -d --build
  green "已按当前代码重建。打开 ${APP_URL}/"
}

usage() {
  cat <<'EOF'
本机 Docker（端口 8125 / 3307 / 6380，不和手动 8124 / 3306 / 6379 冲突）：

  bash scripts/docker-local.sh check    引擎 / .env / 端口
  bash scripts/docker-local.sh up       构建并启动
  bash scripts/docker-local.sh logs     跟应用日志
  bash scripts/docker-local.sh health   探活
  bash scripts/docker-local.sh rebuild  改代码后重建
  bash scripts/docker-local.sh down     停止（保留数据卷）

说明见 docs/deploy-local-mac.md
EOF
}

case "${1:-}" in
  check) cmd_check ;;
  up) cmd_up ;;
  logs) cmd_logs ;;
  health) cmd_health ;;
  down) cmd_down ;;
  rebuild) cmd_rebuild ;;
  *) usage; exit 1 ;;
esac
