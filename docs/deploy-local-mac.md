# 本机 Mac Docker 演练（上云前先在这里把坑打一遍）

编排：**[`docker-compose.local.yml`](../docker-compose.local.yml)**（端口已错开）。  
入口：[`scripts/docker-local.sh`](../scripts/docker-local.sh)。  
上云仍用 [`docker-compose.prod.yml`](../docker-compose.prod.yml)（8124 / 3306 / 6379）。

**第一次不要起 Milvus。** 先保证能打开页面、注册、三条 Agent 能对话。

---

## 端口对照（故意不和手动启动抢）

| 服务 | 手动 / 本机进程 | 本机 Docker 映射到 Mac | 容器内部 |
|------|-----------------|------------------------|----------|
| 应用 | http://127.0.0.1:**8124** | http://127.0.0.1:**8125** | 8124 |
| MySQL | **3306** | **3307** | 3306 |
| Redis | **6379** | **6380** | 6379 |

容器名：`zhizhi-local-app` / `zhizhi-local-mysql` / `zhizhi-local-redis`，不会覆盖 `zhizhi-mysql`。  
两套可以同时开：Pycharm 继续打 8124，浏览器另开 8125 看 Docker 版。

`.env` 里 `MYSQL_HOST=127.0.0.1` **不用改**：Docker 应用连的是 compose 服务名 `mysql`，不是宿主机。

---

## 0. 和「本机 uvicorn」的区别

| | conda / uvicorn | 本机 Docker |
|--|-----------------|-------------|
| 进程 | 你自己的 Python | `zhizhi-local-app` |
| MySQL/Redis | 本机 3306/6379 | 容器，映射 3307/6380 |
| 前端 | 要自己 `npm run build` | 镜像构建阶段打进 `web/dist` |
| MCP 图片搜索 | 另开 `python -m mcp_servers.image_search` | **应用容器里自动起** 8765 |
| 访问 | http://127.0.0.1:8124 | http://127.0.0.1:**8125** |

---

## 1. 引擎：Colima（Docker Desktop 下不下来就用这个）

官网 DMG 若 `Connection reset`，不要反复装 Desktop。

```bash
brew uninstall --cask docker-desktop 2>/dev/null || true
brew install colima docker docker-compose

colima start --cpu 4 --memory 8 --disk 60 --arch aarch64
docker info
docker compose version
```

开机后若 `Cannot connect to the Docker daemon`，再执行 `colima start`。卡在下镜像时给终端加代理后再 start。

### 拉镜像超时（`registry-1.docker.io` context deadline exceeded）

直连 Docker Hub 在国内常超时。本机 `docker-compose.local.yml` 已把 mysql / redis / node / python 改成 `docker.m.daocloud.io/...` 前缀，直接重新：

```bash
bash scripts/docker-local.sh up
```

若 DaoCloud 也超时，可把该文件里的 `docker.m.daocloud.io` 全部换成 `docker.1ms.run` 后再 `up`。

可选：Docker Desktop → Settings → Docker Engine，加上后点 Apply & Restart（对本机所有 `docker pull` 生效）：

```json
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.1ms.run"
  ]
}
```

---

## 2. 开跑前检查

```bash
cd /Users/zhizhi/PycharmProjects/zhizhi-ai-agent
bash scripts/docker-local.sh check
```

**不必**停本机 uvicorn / MySQL / Redis。只要 **8125、3307、6380** 空闲即可。

`.env` 至少一个模型 Key。第一次建议：

```bash
MILVUS_ENABLED=false
LANGSMITH_TRACING=false
```

`MYSQL_PASSWORD` / `REDIS_PASSWORD` 与 compose 一致即可（默认 `root`）。

---

## 3. 启动

```bash
bash scripts/docker-local.sh up
```

等价于：`docker compose -f docker-compose.local.yml up -d --build`

首次 10～20 分钟。日志：

```bash
bash scripts/docker-local.sh logs
```

看到 `[init-schema] done`、`MySQL enabled -> mysql:3306`、`Redis ... (ok)`、`Frontend = Vite dist` 后打开：

**http://127.0.0.1:8125/**

```bash
bash scripts/docker-local.sh health
```

---

## 4. 本机验收清单

1. 打开 8125 首页，注册/登录（和 8124 手动环境的用户库是分开的）。  
2. 面试官发一句。  
3. 超级智能体导出 txt + HITL。  
4. 点停止。  
5. `curl http://127.0.0.1:8125/health`

---

## 5. 本机会踩、上云同样会踩的问题

| 现象 | 本机 | 云上 |
|------|------|------|
| `Cannot connect to the Docker daemon` | 没 `colima start` | ECS Docker 没起来 |
| `8125 already allocated` | 换过端口仍被占 | 改 `docker-compose.local.yml` 映射 |
| 打开了 8124 以为 Docker 没起 | Docker 在 **8125** | 云上 prod 才是 8124 |
| 页面 503 | schema / MySQL 未就绪 | 看 app 日志 |
| Agent 停止无效 | Redis 密码不一致 | `REDIS_HOST` 覆盖失败 |
| 知识库失败 | 容器里 `MILVUS_HOST=127.0.0.1` 是自己 | 用真实 IP 或 `host.docker.internal` |
| 改 `.env` 不生效 | 没 recreate | `--force-recreate` |
| 改代码不生效 | 没 rebuild | `bash scripts/docker-local.sh rebuild` |

---

## 6. 日常命令

```bash
bash scripts/docker-local.sh logs
bash scripts/docker-local.sh health
bash scripts/docker-local.sh rebuild
bash scripts/docker-local.sh down
docker compose -f docker-compose.local.yml exec app sh
```

---

## 7. 本机 OK 之后上云

拷 `Dockerfile`、`docker-compose.prod.yml`、`.env`（云上改密码和 `JWT_SECRET`）。云上端口回到 8124/3306/6379。见 [deploy-aliyun.md](deploy-aliyun.md)。
