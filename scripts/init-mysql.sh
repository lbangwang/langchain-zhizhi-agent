#!/usr/bin/env bash
# Init MySQL database + schema for W1 D2
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:-root}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-root}"
MYSQL_DATABASE="${MYSQL_DATABASE:-zhizhi_ai_agent}"

echo "Creating database ${MYSQL_DATABASE} on ${MYSQL_HOST}:${MYSQL_PORT} ..."

if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -q '^zhizhi-mysql$'; then
  docker exec -i zhizhi-mysql mysql -u"${MYSQL_USER}" -p"${MYSQL_PASSWORD}" -e \
    "CREATE DATABASE IF NOT EXISTS \`${MYSQL_DATABASE}\` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
  docker exec -i zhizhi-mysql mysql -u"${MYSQL_USER}" -p"${MYSQL_PASSWORD}" "${MYSQL_DATABASE}" \
    < "${ROOT_DIR}/db/schema.sql"
else
  mysql -h"${MYSQL_HOST}" -P"${MYSQL_PORT}" -u"${MYSQL_USER}" -p"${MYSQL_PASSWORD}" -e \
    "CREATE DATABASE IF NOT EXISTS \`${MYSQL_DATABASE}\` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
  mysql -h"${MYSQL_HOST}" -P"${MYSQL_PORT}" -u"${MYSQL_USER}" -p"${MYSQL_PASSWORD}" "${MYSQL_DATABASE}" \
    < "${ROOT_DIR}/db/schema.sql"
fi

echo "Applying schema patches (W2–W4, IF NOT EXISTS) ..."
for patch in schema_w2.sql schema_w2_patch_content_type.sql schema_w3.sql schema_w4.sql; do
  f="${ROOT_DIR}/db/${patch}"
  [ -f "$f" ] || continue
  # W4 含 ALTER；列已存在时允许失败
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -q '^zhizhi-mysql$'; then
    docker exec -i zhizhi-mysql mysql -u"${MYSQL_USER}" -p"${MYSQL_PASSWORD}" "${MYSQL_DATABASE}" < "$f" \
      || echo "note: ${patch} had a non-fatal error (duplicate column is ok)"
  else
    mysql -h"${MYSQL_HOST}" -P"${MYSQL_PORT}" -u"${MYSQL_USER}" -p"${MYSQL_PASSWORD}" "${MYSQL_DATABASE}" < "$f" \
      || echo "note: ${patch} had a non-fatal error (duplicate column is ok)"
  fi
done

echo "Done. Set MYSQL_ENABLED=true in .env and restart uvicorn."
