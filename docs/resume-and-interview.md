# 简历条目 + 模拟面试

## 项目简介（可直接粘贴）

**项目简介：** 面向求职演示的企业级 Agent 平台：多模型路由、LangGraph 工具调用、Milvus RAG、HITL 审批、可取消任务、产物交付与 Trace 可观测（含 Token），含 Planner-Worker 多 Agent；面试官 / 多 Agent / 超级智能体按类型隔离会话与产物。

**技术栈：** Python、FastAPI、LangChain / LangGraph、Vue 3、MySQL、Redis、Milvus、MCP、Skill、Tool Calling、SSE、Docker

- 基于 LangGraph `create_agent` 实现 ReAct 超级智能体，支持网页搜索、写 txt/PDF/Word、MCP 图片搜索等工具链；Skill（`SKILL.md`）注入 system prompt 指导何时搜/何时落盘；前端以 SSE（思考 / 工具 / 回答）+ 打字机展示推理过程。
- 设计危险工具 Human-in-the-Loop：写文件 / 生成 PDF、Word 前 SSE 推送确认，后端阻塞等待审批通过后才执行，拒绝或超时可区分状态，避免静默写盘。
- 落地会话持久化与鉴权：JWT、MySQL 按用户隔离会话/消息；三个 Agent 入口默认新建对应类型对话，历史与产物按 `agent_type` 过滤，避免串会话。Redis 停止信号支持前端中断后 Agent 不再继续 step；日配额超限返回 `QUOTA_EXCEEDED`。
- 构建 RAG 知识库全链路（上传/粘贴 → 切片 → Embedding → Milvus 检索，含查询改写与 RRF/Rerank），面试官对话展示「来自哪篇文档」的引用卡片；工具类 Agent 不走 RAG，避免检索噪声干扰任务。
- 实现产物与可观测：工具审计表、产物入库下载；单次任务 Trace（步骤、耗时）落库，统计页展示成功率、P95 与 Prompt/Completion/总 Tokens；可选接入 LangSmith（环境开关，默认关）与本地 Trace 双轨，便于对照 LLM/工具树。
- 扩展 MCP 图片搜索（可开关）与 Planner→Worker 多 Agent：Planner 拆步、多名 Worker 逐步流式执行并 HITL 导出，复用停止/Trace，适合讲解多智能体协作。

---

## 一句话条目（空间不够时用）

**枝枝 AI Agent（Python）** | FastAPI / LangChain / LangGraph / Milvus / Vue3  

企业向可演示 Agent：JWT 隔离；三个应用（面试官 RAG / 多 Agent / 超级智能体）会话与产物按类型隔离；SSE 打字机；Milvus RAG（改写 + RRF/Rerank + 引用）；超级智能体工具调用 + Skill + 写盘 HITL；Redis 停止与日配额；Trace（P95、Token）；评测门禁。

---

## 模拟问答

### Q1：和普通 ChatBot 差在哪？

可交付（产物）、可审计、可取消、可治理（配额 / HITL / 配置）、可回归（评测）、**多入口不串数据**。

### Q2：配置版本？

表 `agent_config` 存 prompt、工具白名单、超时、HITL。超级智能体启动加载 active，没有则建 v1。前端没有配置页，面试可讲表结构 + 运行时绑定，不要说「点了配置后台」。

### Q3：成本与失控？

日配额 Redis；`ToolCallLimitMiddleware`；配置/全局超时；HITL 只挡写盘；搜索不进 HITL。

### Q4：RAG 减幻觉？

改写扩召回 + RRF/Rerank；引用 `__CITATIONS__`；无命中如实说。面试官走 RAG，另外两个入口故意不走，避免工具任务被检索噪声带偏。

### Q5：停止？

Redis stop key；循环/工具入口检查；SSE 结束；前端 AbortController。

### Q6：错误码？

`QUOTA_EXCEEDED`、`AGENT_TIMEOUT`、`HITL_REJECTED`；SSE/HTTP 带 `code`，前端 Toast。

### Q7：评测门禁？

20 条关键词命中；`--fail-under` 低于阈值非 0 退出。

### Q8：多 Agent？

Planner 输出 JSON 步骤 → 多个 Worker 逐步流式 → deliver 用 HITL 写文件，不再多打一轮「总结模型」。

### Q9：Skill 在哪用？

`skills/*/SKILL.md` 拼进**超级智能体** system prompt，指导何时 `search_web` / 出 PDF。面试官和多 Agent **不加载**。

### Q10：三分钟 Demo？

① 知识库入库 → 面试官提问看引用 → ② 超级智能体 PDF + HITL → ③ 多 Agent 看拆步 → ④ Trace 看时延和 Token。  
不要演示「从面试官点进去却还是上一次旅游攻略」——产品上已按 Agent 隔离。

### Q11：Trace Token 从哪来？

对话走 OpenAI 兼容 `usage`；流式尽量 `include_usage`；LangGraph 回调/消息 `usage_metadata` 累加进根 span 的 meta。供应商不回 usage 时该次为 0。

### Q12：LangSmith 和自建 Trace 什么关系？

自建 Trace 给产品页（成功率、P95、Token）；LangSmith 给开发者看 LLM/工具树。`.env` `LANGSMITH_TRACING` 可关，没 Key 不会上报，Smith 挂了也不挡聊天。
