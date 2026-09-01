# 阿里云 Docker 部署

把「枝枝 AI Agent」整包打成容器：`app`（FastAPI + Vue dist）+ MySQL + Redis。  
Milvus 很吃内存，**优先复用已有实例**（`.env` 里填 `MILVUS_HOST`），不要默认和业务挤在同一台 2G 机器上。

编排文件：[`docker-compose.prod.yml`](../docker-compose.prod.yml)  
镜像：[`Dockerfile`](../Dockerfile)（多阶段：Node 构建前端 + Python 3.12）

---

## 1. 需要准备的环境

### 1.1 阿里云侧

| 项 | 建议 | 说明 |
|----|------|------|
| ECS | Ubuntu 22.04 或 Alibaba Cloud Linux 3 | 轻量应用服务器也可以，同样装 Docker |
| 规格（无本机 Milvus） | **2 核 4G** 起，演示建议 **2 核 8G** | 应用 + MySQL + Redis；LLM 在云端，不占 GPU |
| 规格（本机再起 Milvus） | **4 核 8G 起**，更好 **4 核 16G** | etcd + MinIO + Milvus standalone 很吃内存 |
| 磁盘 | 系统盘 **40G+** | 镜像 + pip 层 + MySQL 数据；知识库大文件另加 |
| 带宽 | 3～5 Mbps | SSE 长连接，过小会觉得「打字机卡」 |
| 公网 IP / 域名 | 至少一个 | 域名可后续再绑；先用 `http://公网IP:8124` 验收 |
| 安全组 | 见下表 | **不要**把数据库端口对 `0.0.0.0/0` |

安全组入方向（最小集）：

| 端口 | 来源 | 用途 |
|------|------|------|
| 22 | 你的办公网 IP | SSH |
| 8124 | `0.0.0.0/0` 或仅自己 IP | 验收应用（上 Nginx 后可关掉） |
| 80 / 443 | `0.0.0.0/0` | 上 Nginx / 证书后用 |

**不要对公网开放：** 3306（MySQL）、6379（Redis）、19530（Milvus）、9000/9001（MinIO）。  
`docker-compose.prod.yml` 已把 MySQL/Redis 绑在 `127.0.0.1`，容器之间走内部网络。

若知识库用**另一台机器上的 Milvus**：在 **Milvus 那台**的安全组放行 **本 ECS 的内网/公网 IP → 19530**，不要对全世界开放。

### 1.2 本机 / 代码

- 能 SSH 到 ECS（密钥或密码）
- 仓库能上去：`git clone`，或本机 `rsync` / `scp`
- **不要把 `.env` 提交进 git**；在服务器上单独创建

### 1.3 必须准备的 Key（写入服务器 `.env`）

至少配 **一个对话模型**，否则只能走占位回复：

| 变量 | 用途 | 没有会怎样 |
|------|------|------------|
| `DASHSCOPE_API_KEY` | 通义 | 选 qwen 失败 |
| `DEEPSEEK_API_KEY` | DeepSeek | 选 deepseek 失败 |
| `DOUBAO_API_KEY` / `ARK_API_KEY` | 豆包 | 选 doubao 失败 |
| `JWT_SECRET` | 登录 Token | **生产必须改掉** `change-me-in-production` |
| `MYSQL_PASSWORD` / `REDIS_PASSWORD` | 容器内库密码 | 与 compose 一致；不要再用弱密码上公网 |

按功能可选：

| 变量 | 用途 |
|------|------|
| `SILICONFLOW_API_KEY` | 知识库 Embedding（BGE-M3）；没它 RAG 入库/检索会挂 |
| `TAVILY_API_KEY` | 超级智能体 `search_web`；没有会返回占位文案 |
| `MILVUS_ENABLED` + `MILVUS_HOST` | 面试官知识库；关着也能登录、跑 Agent，只是不能 RAG |
| `LANGSMITH_TRACING` + `LANGSMITH_API_KEY` | 可选观测；建议生产先 `false` |

出网：ECS 要能访问 DashScope / DeepSeek / 方舟 / 硅基流动（及可选 LangSmith、Tavily）。阿里云默认有公网即可。

### 1.4 服务器上要装的软件

只需 **Docker + Compose 插件**（不必装本机 Python / Node / MySQL）：

```bash
# Ubuntu 示例
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
# 重新登录 SSH 后 docker 才免 sudo
docker compose version
```

国内拉镜像慢时，配 Docker 镜像加速（阿里云容器镜像服务控制台可拿专属地址），写入 `/etc/docker/daemon.json` 后 `sudo systemctl restart docker`。

---

## 2. 部署架构（这套 compose 实际跑什么）

```text
浏览器  →  ECS:8124  →  zhizhi-app
                          ├── FastAPI + web/dist
                          ├── 同容器 127.0.0.1:8765 图片搜索 MCP
                          ├── mysql:3306
                          └── redis:6379
Milvus（可选，另一台或本机 compose）← 仅面试官 RAG
LLM / Embedding（公网 API）
```

容器内会 **覆盖** `.env` 里的 `MYSQL_HOST` / `REDIS_HOST` 为服务名 `mysql` / `redis`（`127.0.0.1` 在容器里指向自己，连不上旁边的库）。

---

## 3. 逐步操作

### 步骤 1：买 ECS、配安全组、SSH 上去

1. 控制台创建实例，系统选 Ubuntu 22.04，规格按第 1 节。
2. 安全组按上表放行。
3. `ssh root@你的公网IP`（或 `ecs-user`）。

### 步骤 2：安装 Docker

见 1.4。执行 `docker run hello-world` 确认能拉镜像。

### 步骤 3：把代码放到服务器

```bash
# 方式 A：git（把远程换成你的仓库）
cd /opt
git clone <你的仓库 URL> zhizhi-ai-agent
cd zhizhi-ai-agent

# 方式 B：本机打包上传
# tar czf /tmp/zhizhi.tgz --exclude=.git --exclude=web/node_modules --exclude=.venv .
# scp /tmp/zhizhi.tgz root@公网IP:/opt/
# 服务器：mkdir -p /opt/zhizhi-ai-agent && tar xzf zhizhi.tgz -C /opt/zhizhi-ai-agent
```

### 步骤 4：写生产 `.env`

```bash
cd /opt/zhizhi-ai-agent
cp .env.example .env
nano .env   # 或 vim
```

**生产必改（示例，请换成自己的值）：**

```bash
JWT_SECRET=<随机长字符串>
MYSQL_ENABLED=true
MYSQL_HOST=mysql
MYSQL_PASSWORD=<强密码>
MYSQL_DATABASE=zhizhi_ai_agent

REDIS_ENABLED=true
REDIS_HOST=redis
REDIS_PASSWORD=<强密码>

# 至少填一个
DASHSCOPE_API_KEY=sk-...
# DEEPSEEK_API_KEY=
# DOUBAO_API_KEY=

# 知识库：已有远程 Milvus 就开；没有就先 false
MILVUS_ENABLED=false
# MILVUS_ENABLED=true
# MILVUS_HOST=47.97.253.89
# MILVUS_PORT=19530

SILICONFLOW_API_KEY=          # RAG 必填
TAVILY_API_KEY=               # 联网搜索选填
HITL_ENABLED=true
LANGSMITH_TRACING=false
```

`MYSQL_PASSWORD` / `REDIS_PASSWORD` 必须与 compose 里 MySQL/Redis 容器使用的密码一致（compose 从 `.env` 读这两个变量）。

### 步骤 5：构建并启动

首次构建要拉 Node/Python 镜像并 `pip install`，**10～20 分钟**都正常。

```bash
cd /opt/zhizhi-ai-agent
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f app
```

启动日志里应看到类似：

- `[init-schema] done`
- `[startup] MySQL enabled -> mysql:3306/...`
- `[startup] Redis enabled -> redis:6379 (ok)`
- `[startup] Frontend = Vite dist (...)`

### 步骤 6：验收

在浏览器打开：`http://<公网IP>:8124/`

```bash
curl -sS http://127.0.0.1:8124/health
```

期望：`mysql_enabled: true`，`redis_ok: true`。  
注册一个账号 → 进面试官/超级智能体发一条消息。

若 `MILVUS_ENABLED=true`，再执行：

```bash
docker compose -f docker-compose.prod.yml exec app python scripts/check_milvus.py
```

### 步骤 7（推荐）：Nginx + HTTPS

安全组放行 80/443，安装 nginx，反代到 `127.0.0.1:8124`。SSE 必须关缓冲：

```nginx
server {
    listen 80;
    server_name your.domain.com;

    client_max_body_size 32m;

    location / {
        proxy_pass http://127.0.0.1:8124;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

证书可用阿里云免费 DV，或 `certbot --nginx`。之后可把安全组 8124 收回，只留 80/443。

---

## 4. 日常运维

```bash
# 看日志
docker compose -f docker-compose.prod.yml logs -f app

# 改 .env 后重启应用（不必重建镜像）
docker compose -f docker-compose.prod.yml up -d app --force-recreate

# 改了 Python / 前端代码：重建镜像
docker compose -f docker-compose.prod.yml up -d --build

# 停
docker compose -f docker-compose.prod.yml down
# 停并且删数据卷（会话/用户会没）——慎用
# docker compose -f docker-compose.prod.yml down -v
```

数据在 Docker volume：`zhizhi_mysql_data`、`zhizhi_artifacts`。换机器前先 `docker run --rm -v zhizhi_mysql_data:/var/lib/mysql ...` 备份，或 `mysqldump`。

---

## 5. 常见问题

| 现象 | 原因 / 处理 |
|------|-------------|
| 页面能开但登录 503 | `MYSQL_ENABLED` 没变成 true，或 app 连的仍是 127.0.0.1；看 compose 是否覆盖了 `MYSQL_HOST=mysql` |
| Agent 点停止无效 / 429 很怪 | Redis 未通；`health` 里 `redis_ok` 应为 true |
| 知识库上传失败 | `MILVUS_ENABLED`、`MILVUS_HOST`、硅基流动 Key；安全组 19530 是否只对这台 ECS 开放 |
| 构建卡在 pip | 用 Dockerfile 里的阿里云 PyPI；或 ECS 换更大带宽 |
| PDF 中文方框 | 镜像已装 `fonts-wqy-microhei`；确认用的是本 Dockerfile 构建的 `zhizhi-app` |
| 流式输出一会卡住 | Nginx 开了 `proxy_buffering`；或安全组/SLB 空闲超时过短 |
| 一台 2G 再起 Milvus OOM | 把 Milvus 放到更大的机器，或先 `MILVUS_ENABLED=false` |

---

## 6. 和本地开发 compose 的区别

| | `docker-compose.yml` | `docker-compose.prod.yml` |
|--|----------------------|---------------------------|
| 内容 | 只有 MySQL + Redis | 加上 **应用镜像** |
| 端口 | 3306/6379 默认对外 | 只绑 `127.0.0.1` |
| 前端 | 需本机 `npm run build` | 镜像构建阶段打进 `web/dist` |
| schema | 本机 `bash scripts/init-mysql.sh` | 容器启动时 `docker/init_schema.py` |
