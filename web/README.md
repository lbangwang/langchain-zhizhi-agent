# 枝枝 AI Agent 前端（Vue 3 + Vite）

工作台 SPA，构建后由 FastAPI 托管 `web/dist`。

## 页面

| 路由 | 说明 |
|------|------|
| `/` | 首页，选面试官 / 多 Agent / 超级智能体 / 知识库 |
| `/login` `/register` | JWT |
| `/workspace?mode=` | `interviewer` \| `multi` \| `super`；首页进入带 `new=1` 新建该类型对话 |
| `/knowledge` | 知识库 |
| `/trace` | Trace 列表、详情、统计（含 Token） |

开发：`npm install && npm run dev`（`/api` 代理 `http://127.0.0.1:8124`）。  
上线：`npm run build`，在**仓库根**启动 uvicorn。
