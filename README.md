# 枝枝 AI Agent（Python 求职版）

仓库：`langchain-zhizhi-agent`

基于 **Python + LangChain / LangGraph + FastAPI + Milvus** 的可演示 Agent 平台。

> 目标：多模型路由、工具调用、Milvus RAG（检索优化 + 引用溯源）、MCP/Skill、会话持久化、可观测与 Docker 交付。

详细排期与验收见：[docs/python-roadmap.md](docs/python-roadmap.md)

---

## 当前状态

- ✅ 路线图与仓库骨架
- 🔄 W1 D1：FastAPI `/health`
- ⬜ W1～W4 按路线图推进

学习用 notebook 仍在 `zhizhi/demo/`，正式功能放在 `app/` / `agent/` / `rag/`。

---

## 快速启动（W1 D1）

```bash
cd /Users/zhizhi/PycharmProjects/zhizhi-ai-agent
cp .env.example .env   # 填入密钥

# 建议使用已有 conda 环境 zhizhi-ai-agent
pip install fastapi uvicorn python-dotenv

uvicorn app.main:app --reload --port 8124
```

健康检查：http://localhost:8124/health

基础设施（MySQL + Redis）：

```bash
docker compose up -d
```

Milvus 请使用官方 standalone compose（etcd + minio + milvus），或连接已部署的云服务器 `MILVUS_HOST`。

---

## 目录

```text
app/       FastAPI
agent/     LangGraph Agent / tools / middleware
rag/       Embedding + Milvus
mcp/       MCP servers
skills/    Skill 定义
evals/     评测
docs/      路线图与文档
zhizhi/    既有 demo / asset
```

---

## 与 Java 版

Java 完整作品在 `IdeaProjects/zhizhi-ai-agent`。本仓库为面向 AI 应用开发岗 JD 的 Python 主打作品。
