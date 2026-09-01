# 生产镜像：先构建 Vue 工作台，再装 Python 依赖，由 FastAPI 托管 web/dist。
# 构建：docker compose -f docker-compose.prod.yml build
# 本机拉 Docker Hub 超时时，compose.local.yml 会传入国内镜像前缀。

ARG NODE_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.12-slim

# ---------- 前端 ----------
FROM ${NODE_IMAGE} AS frontend
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --registry=https://registry.npmmirror.com
COPY web/ ./
RUN npm run build

# 每个 FROM 前再声明一次 ARG，BuildKit 才能吃到 compose 传入的镜像前缀
ARG PYTHON_IMAGE=python:3.12-slim
# ---------- 后端 ----------
FROM ${PYTHON_IMAGE} AS app
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

# wqy-microhei：PDF 中文。apt 走阿里云，避免 ECS 直连 deb.debian.org 卡几十分钟。
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' /etc/apt/sources.list.d/debian.sources; \
      sed -i 's|https://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' /etc/apt/sources.list.d/debian.sources; \
      sed -i 's|http://security.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' /etc/apt/sources.list.d/debian.sources; \
      sed -i 's|https://security.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list; \
      sed -i 's|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends gcc fonts-wqy-microhei; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir \
        -i https://mirrors.aliyun.com/pypi/simple/ \
        --trusted-host mirrors.aliyun.com \
        -r requirements.txt

COPY . .
COPY --from=frontend /web/dist /app/web/dist
RUN chmod +x docker/entrypoint.sh \
    && mkdir -p /app/data/artifacts

EXPOSE 8124
CMD ["bash", "/app/docker/entrypoint.sh"]
