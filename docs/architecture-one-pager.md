# 枝枝 AI Agent — 一页架构（面试口述）

约 3～5 分钟。先画图，再点三个入口，最后收治理。

---

## 一句话

FastAPI + LangChain/LangGraph + Milvus + Vue3：三个 Agent **按类型隔离会话和产物**；RAG 可引用；超级智能体能工具调用、HITL、Skill；全程 JWT、可停止、可 Trace（含 Token）。

---

## 口述画图

```text
浏览器 Vue3
  首页选 Agent ──new=1──► 工作台（该类型空白对话）
       │ JWT + SSE
       ▼
FastAPI
  ├── 面试官  /chat/stream + RAG（改写 / RRF / Rerank + 引用）
  ├── 多 Agent  Planner → Worker → HITL 导出
  ├── 超级智能体  create_agent + 工具 + Skill 注入 + HITL
  ├── 知识库 / 产物(按 agent_type) / Trace(量·时延·Token)
  └── Redis：停止 · HITL 等待 · 日配额
       │
       ├─ MySQL  用户 / 会话(agent_type) / 消息 / 产物 / 审计 / Trace / agent_config
       └─ Milvus 知识库向量
```

**四句话收口：**

1. **隔离**：JWT `user_id`；首页进 Agent 新建该类型对话；历史和产物按 `agent_type` 过滤。  
2. **可控**：停止、写盘 HITL、超时、日配额、工具次数上限。  
3. **可证**：引用卡片、`config_version`、审计 CSV、Trace（P95 + Prompt/Completion Tokens）；LangSmith 可关，和本地 Trace 双轨。  
4. **可配**：超级智能体启动加载 `agent_config`（缺表时内存默认，避免 1146 把任务打死）。

---

## Skill / MCP 用在哪

| 机制 | 实际挂载点 |
|------|------------|
| Skill（`skills/*/SKILL.md`） | **只**拼进超级智能体 system prompt，面试官 / 多 Agent **不读** |
| MCP 图片搜索 | 超级智能体工具 `search_images` |
| RAG | **只**面试官对话（`use_rag`） |

---

## 演示顺序（对着页面讲）

| # | 点哪里 | 讲什么 |
|---|--------|--------|
| 1 | 知识库 → 面试官 | 切片入库、提问出引用；强调不和工具 Agent 串会话 |
| 2 | 超级智能体 | 「搜资料生成 PDF」；HITL；产物栏只有本 Agent 文件；可提 Skill |
| 3 | 多 Agent | Planner 拆步、Worker 流式；导出仍 HITL |
| 4 | Trace | 成功/失败/停止、平均与 P95、Token；点一条看步骤 |

配置页前端未做：版本在表里，Swagger 可讲 `agent_config`，不要说「点配置页 bump」。

---

## 被追问时

- **成本？** Redis 日配额 + `max_tool_calls` + 超时。  
- **工具失控？** 白名单 + 仅写盘 HITL + 中间件限次。  
- **幻觉？** 改写召回 + Rerank + 引用；无命中说没检索到。  
- **停止？** Redis stop；SSE 结束；前端 AbortController。
