# 枝枝 AI Agent — 功能对照（已交付）

原 3～4 周冲刺计划已全部落地。本文只保留 **和代码一致的能力说明**，不再写每日开工清单。

技术栈：**Python + LangChain / LangGraph + FastAPI + Milvus + Vue3 + MCP/Skill**。

---

## 1. 简历一句话

可演示的企业向 Agent：多模型路由、工具调用、**Milvus RAG（改写 / RRF / Rerank + 引用）**、MCP/Skill、会话按 Agent 隔离、HITL、Trace（时延 + Token）、评测门禁；FastAPI + Docker Compose 可本地拉起。

---

## 2. 与 Java 版

| | 定位 |
|--|------|
| Java 版 | 已完成的 Spring AI 产品向作品 |
| **本仓库** | **主投 Python / LangChain 岗**：同一产品能力，栈换成 FastAPI + LangGraph + Milvus |

面试讲迁移与工程取舍，不讲「又造了一个聊天框」。

---

## 3. 交付对照（对 JD）

### 已做（可演示）

| 能力 | 现状 |
|------|------|
| FastAPI + `.env` | `/health`；密钥不入库 |
| JWT | 无 token → 401；数据按用户隔离 |
| 会话 MySQL | `agent_type`：`INTERVIEWER` / `MULTI_AGENT` / `SUPER_AGENT` |
| Redis 停止 | 超级智能体可取消 |
| LangGraph `create_agent` | 超级智能体多步工具 + SSE |
| Milvus RAG | 上传/粘贴、切片策略、引用卡片 |
| 检索优化 | 查询改写 + RRF；可选 LLM Rerank |
| 审计 / 产物 | `tool_audit`；txt / pdf / docx；产物 API 按 `agent_type` 过滤 |
| Trace | 列表、步骤、统计（成功率、P95、Token） |
| Compose | `docker-compose.yml`（MySQL+Redis）；Milvus 另文件或远程 |
| HITL | 写 txt/pdf/docx 前批准 |
| MCP | `mcp_servers/image_search` |
| Skill | `skills/*/SKILL.md` → **仅超级智能体** prompt |
| 多 Agent | Planner LLM → 多 Worker → HITL 交付 |
| 评测 | `evals/cases_basic.json` 20 条 + `--fail-under` |
| 前端 | `web/`：首页 / 登录 / 工作台 / 知识库 / Trace |

### 明确不做

计费后台、Dify 级可视化编排、Computer Use、前端配置中心（`agent_config` 在库里，无独立配置页）。

LangSmith：默认关（`LANGSMITH_TRACING=false`）；打开后与自建 Trace 双轨，失败不影响主链路。演示可不讲。

---

## 4. 运行时结构

```text
web/（Vue3）
    JWT + SSE
FastAPI
  ├── 面试官 chat.stream + rag/
  ├── 多 Agent agent/multi_agent.py
  ├── 超级智能体 agent/react_agent.py
  │     ├── tools + MCP
  │     ├── skills_loader → system prompt
  │     ├── config_store（agent_config，缺表则内存默认）
  │     └── Middleware：摘要 / 工具次数 / HITL
  └── Redis：stop / HITL / 配额
```

环境变量以仓库根目录 **`.env.example`** 为准（勿在文档里再抄一份过期表）。

建表：`bash scripts/init-mysql.sh`（`schema.sql` + W2～W4，含 `agent_config`）。只导 W1 会在超级智能体启动时报 1146。

---

## 5. 三个演示场景

1. **知识库 RAG**：入库 → 面试官提问 → 引用。  
2. **超级智能体**：搜索 + 生成 PDF → HITL → 产物（仅本 Agent）。  
3. **停止 / Trace**：长任务停止；Trace 看步骤、耗时、Token。

---

## 6. 仓库（实际）

```text
app/  agent/  rag/  web/  frontend/
mcp_servers/  skills/  evals/  tests/  docs/  db/  scripts/
zhizhi/demo/     # 学习笔记，非正式产品
```

---

## 7. 已知边界（面试可主动说）

- Token 统计依赖模型返回 usage；**新请求**才会写入 Trace meta，旧数据可能为 0。  
- Skill 不是独立运行时，是 Markdown 说明注入超级智能体。  
- 首页进 Agent 会 `new=1` 开该类型空白对话；刷新同一模式会恢复该类型上次会话。
