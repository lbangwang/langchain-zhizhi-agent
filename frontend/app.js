/**
 * 枝枝 AI Agent — 前端（Java 版风格：首页 / 登录 / 三栏工作台）
 *
 * 视图：home | login | register | workspace
 * 鉴权：Bearer JWT；续聊：/api/conversations/{chatId}/chat
 */
const { createApp, ref, computed, nextTick, onMounted } = Vue;

const TOKEN_KEY = "zhizhi_access_token";
const USER_KEY = "zhizhi_user";
const CHAT_KEY = "zhizhi_chat_id";

const app = createApp({
  setup() {
    const view = ref("home");
    const registerEnabled = ref(false);

    async function loadAuthFeatures() {
      try {
        const r = await fetch("/api/auth/features");
        const d = await r.json();
        registerEnabled.value = !!d.register_enabled;
      } catch {
        registerEnabled.value = false;
      }
      if (!registerEnabled.value && view.value === "register") {
        view.value = "login";
      }
    }
    loadAuthFeatures();

    const token = ref(localStorage.getItem(TOKEN_KEY) || "");
    const user = ref(JSON.parse(localStorage.getItem(USER_KEY) || "null"));
    const conversations = ref([]);
    const chatId = ref(localStorage.getItem(CHAT_KEY) || "");
    const messages = ref([]);
    const draft = ref("");
    const loading = ref(false);
    const booting = ref(true);
    const error = ref("");
    const rightTab = ref("think");
    const agentRunning = ref(false);
    const planSteps = ref([]);
    const agentStatus = ref("");
    const zoneLogs = ref({ think: [], tool: [], answer: [] });
    const hitlPending = ref(null);
    const artifacts = ref([]);
    const traces = ref([]);
    const traceDetail = ref([]);
    const lastTraceId = ref("");

    function safeList(v) {
      return Array.isArray(v) ? v : [];
    }

    /** 模板里用方法取列表，避免 computed 解包异常导致白屏 */
    function getThinkLogs() {
      return safeList(zoneLogs.value && zoneLogs.value.think);
    }
    function getToolLogs() {
      return safeList(zoneLogs.value && zoneLogs.value.tool);
    }
    function getAnswerLogs() {
      return safeList(zoneLogs.value && zoneLogs.value.answer);
    }

    function latestAssistantText() {
      for (let i = messages.value.length - 1; i >= 0; i -= 1) {
        const m = messages.value[i];
        if (m && m.role === "assistant" && m.content) {
          return displayContent(m.content);
        }
      }
      return "";
    }

    function setRightTab(tab) {
      const allowed = { think: 1, tool: 1, answer: 1, artifact: 1 };
      rightTab.value = allowed[tab] ? tab : "think";
      if (rightTab.value === "artifact") {
        loadArtifacts().catch(() => {});
      }
    }

    function formatJson(obj) {
      if (obj == null || obj === "") return "";
      try {
        return JSON.stringify(obj, null, 2);
      } catch (e) {
        return String(obj);
      }
    }

    function resetZoneLogs() {
      zoneLogs.value = { think: [], tool: [], answer: [] };
    }

    function pushZoneLog(zone, title, detail) {
      const z = zone === "tool" || zone === "answer" ? zone : "think";
      const cur = zoneLogs.value || { think: [], tool: [], answer: [] };
      const next = {
        think: safeList(cur.think).slice(),
        tool: safeList(cur.tool).slice(),
        answer: safeList(cur.answer).slice(),
      };
      next[z].push({
        title: String(title || z),
        detail: String(detail || "").slice(0, 2000),
      });
      if (next[z].length > 40) next[z] = next[z].slice(-40);
      zoneLogs.value = next;
    }

    function hydrateZonesFromMessages(list) {
      resetZoneLogs();
      const arr = Array.isArray(list) ? list : [];
      for (const m of arr.slice(-6)) {
        if (!m) continue;
        if (m.role === "user") {
          pushZoneLog("think", "用户提问", m.content || "");
        } else if (m.role === "assistant") {
          const text = displayContent(m.content || "");
          pushZoneLog("think", "生成回答", "模型已产出回复");
          pushZoneLog("answer", "回答", text.slice(0, 1200));
        }
      }
    }

    const kbDocs = ref([]);
    const kbSource = ref("paste"); // paste | file
    const kbFilename = ref("");
    const kbText = ref("");
    const kbFile = ref(null);
    const kbFileName = ref("");
    const kbStrategy = ref("recursive");
    const kbStrategies = ref([]);
    const kbParams = ref({ chunk_size: 800, chunk_overlap: 120 });
    const kbLoading = ref(false);
    const kbPreview = ref({ filename: "", char_count: 0, chunk_count: 0, chunks: [] });
    const kbSearchQuery = ref("");
    const kbHits = ref([]);
    const kbSearching = ref(false);

    const authForm = ref({ username: "", password: "", nickname: "" });
    const authLoading = ref(false);
    const pendingView = ref("workspace");

    const isAuthed = computed(() => !!token.value && !!user.value);

    const kbCurrentStrategy = computed(() => {
      const list = kbStrategies.value || [];
      return list.find((s) => s.id === kbStrategy.value) || list[0] || null;
    });

    const KB_STRATEGY_FALLBACK = [
      {
        id: "recursive",
        name: "智能递归切分",
        badge: "推荐",
        summary: "按段落→句子→字词逐级切开，企业知识库最常用。",
        suitable: "通用制度、说明书、FAQ",
        params: [
          { key: "chunk_size", label: "单块最大字数", default: 800, min: 100, max: 4000, step: 50, hint: "越大上下文越完整" },
          { key: "chunk_overlap", label: "块间重叠字数", default: 120, min: 0, max: 800, step: 10, hint: "避免句子被截断" },
        ],
      },
      {
        id: "paragraph",
        name: "按自然段落切分",
        badge: "",
        summary: "按空行分段并合并短段，适合公文叙述。",
        suitable: "规章制度、会议纪要",
        params: [
          { key: "chunk_size", label: "段落合并上限（字）", default: 1000, min: 100, max: 4000, step: 50, hint: "" },
          { key: "chunk_overlap", label: "短段合并阈值（字）", default: 80, min: 0, max: 500, step: 10, hint: "" },
        ],
      },
      {
        id: "markdown",
        name: "按标题结构切分",
        badge: "",
        summary: "按标题切开后再切长章节，适合手册类文档。",
        suitable: "产品手册、技术方案",
        params: [
          { key: "chunk_size", label: "章节内块大小（字）", default: 900, min: 100, max: 4000, step: 50, hint: "" },
          { key: "chunk_overlap", label: "章节内重叠（字）", default: 100, min: 0, max: 800, step: 10, hint: "" },
        ],
      },
      {
        id: "window",
        name: "按固定长度切分",
        badge: "",
        summary: "固定字数滑动窗口，规则简单。",
        suitable: "日志、流水文本",
        params: [
          { key: "chunk_size", label: "每块字数", default: 500, min: 50, max: 3000, step: 50, hint: "" },
          { key: "chunk_overlap", label: "滑动重叠字数", default: 50, min: 0, max: 500, step: 10, hint: "" },
        ],
      },
      {
        id: "token",
        name: "按模型 Token 切分",
        badge: "进阶",
        summary: "按大模型 token 预算切块。",
        suitable: "严格控制上下文成本",
        params: [
          { key: "chunk_size", label: "每块 Token 数", default: 400, min: 50, max: 2000, step: 20, hint: "" },
          { key: "chunk_overlap", label: "重叠 Token 数", default: 40, min: 0, max: 400, step: 10, hint: "" },
        ],
      },
    ];

    function applyStrategyDefaults(strategyId) {
      const meta =
        (kbStrategies.value || []).find((s) => s.id === strategyId) ||
        KB_STRATEGY_FALLBACK.find((s) => s.id === strategyId) ||
        KB_STRATEGY_FALLBACK[0];
      const next = {};
      (meta.params || []).forEach((p) => {
        next[p.key] = p.default;
      });
      kbParams.value = next;
    }

    function onKbStrategyChange() {
      applyStrategyDefaults(kbStrategy.value);
    }

    function kbChunkSizeValue() {
      return Number(kbParams.value.chunk_size) || 800;
    }

    function kbOverlapValue() {
      return Number(kbParams.value.chunk_overlap) || 0;
    }

    function parseCitations(content) {
      if (!content || typeof content !== "string") return [];
      const marker = "__CITATIONS__";
      const idx = content.indexOf(marker);
      if (idx < 0) return [];
      const raw = content.slice(idx + marker.length).trim();
      try {
        const arr = JSON.parse(raw);
        return Array.isArray(arr) ? arr : [];
      } catch {
        return [];
      }
    }

    function displayContent(content) {
      if (!content) return "";
      const marker = "__CITATIONS__";
      const idx = content.indexOf(marker);
      return idx >= 0 ? content.slice(0, idx).trimEnd() : content;
    }

    function saveSession(accessToken, userData) {
      token.value = accessToken;
      user.value = userData;
      localStorage.setItem(TOKEN_KEY, accessToken);
      localStorage.setItem(USER_KEY, JSON.stringify(userData));
    }

    function clearSession() {
      token.value = "";
      user.value = null;
      conversations.value = [];
      messages.value = [];
      chatId.value = "";
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      localStorage.removeItem(CHAT_KEY);
    }

    function showError(err) {
      error.value = err?.message || String(err);
      setTimeout(() => {
        if (error.value === (err?.message || String(err))) error.value = "";
      }, 4200);
    }

    async function api(path, options = {}) {
      const headers = {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      };
      if (token.value && !options.skipAuth) {
        headers.Authorization = `Bearer ${token.value}`;
      }
      const resp = await fetch(path, { ...options, headers });
      const data = await resp.json().catch(() => null);
      if (resp.status === 401) {
        clearSession();
        if (view.value === "workspace") view.value = "login";
        throw new Error((data && data.detail) || "未登录或 token 无效");
      }
      if (!resp.ok) {
        const detail =
          (data && (data.detail || data.message)) || `HTTP ${resp.status}`;
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      if (data && typeof data.code === "number" && data.code !== 0) {
        throw new Error(data.message || "业务失败");
      }
      return data;
    }

    function goAuth(mode) {
      view.value = mode;
    }

    async function enterWorkspace() {
      if (!isAuthed.value) {
        pendingView.value = "workspace";
        view.value = "login";
        return;
      }
      view.value = "workspace";
      await afterLogin();
    }

    async function enterKnowledge() {
      if (!isAuthed.value) {
        pendingView.value = "knowledge";
        view.value = "login";
        return;
      }
      view.value = "knowledge";
      await refreshKnowledge();
    }

    async function enterTrace() {
      if (!isAuthed.value) {
        pendingView.value = "trace";
        view.value = "login";
        return;
      }
      view.value = "trace";
      await loadTraces();
    }

    async function loadTraces() {
      try {
        const res = await api("/api/traces?limit=40");
        traces.value = res.data || [];
      } catch (err) {
        showError(err);
      }
    }

    async function selectTrace(traceId) {
      try {
        const res = await api(`/api/traces/${traceId}`);
        traceDetail.value = res.data || [];
      } catch (err) {
        showError(err);
      }
    }

    async function decideHitl(decision) {
      if (!hitlPending.value || !chatId.value) return;
      try {
        await api(`/api/conversations/${chatId.value}/hitl/decide`, {
          method: "POST",
          body: JSON.stringify({
            request_id: hitlPending.value.request_id,
            decision,
          }),
        });
        pushZoneLog(
          "tool",
          `HITL ${decision}`,
          hitlPending.value.tool_name || ""
        );
        hitlPending.value = null;
      } catch (err) {
        showError(err);
      }
    }

    async function submitAuth() {
      const usernameVal = authForm.value.username.trim();
      const passwordVal = authForm.value.password;
      if (!usernameVal || !passwordVal) {
        showError(new Error("请输入用户名和密码"));
        return;
      }
      authLoading.value = true;
      try {
        const isRegister = view.value === "register";
        const path = isRegister ? "/api/auth/register" : "/api/auth/login";
        const body = isRegister
          ? {
              username: usernameVal,
              password: passwordVal,
              nickname: authForm.value.nickname.trim() || usernameVal,
            }
          : { username: usernameVal, password: passwordVal };
        const res = await api(path, {
          method: "POST",
          body: JSON.stringify(body),
          skipAuth: true,
        });
        saveSession(res.data.access_token, res.data.user);
        authForm.value = { username: "", password: "", nickname: "" };
        const next = pendingView.value || "workspace";
        pendingView.value = "workspace";
        if (next === "knowledge") {
          view.value = "knowledge";
          await refreshKnowledge();
        } else if (next === "trace") {
          view.value = "trace";
          await loadTraces();
        } else {
          view.value = "workspace";
          await afterLogin();
        }
      } catch (err) {
        showError(err);
      } finally {
        authLoading.value = false;
      }
    }

    function logout() {
      clearSession();
      view.value = "home";
    }

    function formatTime(iso) {
      if (!iso) return "";
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return "";
      const mm = String(d.getMonth() + 1).padStart(2, "0");
      const dd = String(d.getDate()).padStart(2, "0");
      const hh = String(d.getHours()).padStart(2, "0");
      const mi = String(d.getMinutes()).padStart(2, "0");
      return `${mm}-${dd} ${hh}:${mi}`;
    }

    async function loadConversations() {
      const res = await api("/api/conversations");
      conversations.value = res.data || [];
    }

    async function loadMessages(id) {
      if (!id) {
        messages.value = [];
        resetZoneLogs();
        return;
      }
      const res = await api(`/api/conversations/${id}/messages`);
      messages.value = res.data || [];
      hydrateZonesFromMessages(messages.value);
      await nextTick();
      const box = document.querySelector(".messages");
      if (box) box.scrollTop = box.scrollHeight;
    }

    async function selectChat(id) {
      chatId.value = id;
      localStorage.setItem(CHAT_KEY, id);
      await loadMessages(id);
    }

    async function createChat() {
      loading.value = true;
      try {
        const res = await api("/api/conversations", {
          method: "POST",
          body: JSON.stringify({
            title: "新对话",
            agent_type: "SUPER_AGENT",
            model: "qwen-plus",
          }),
        });
        await loadConversations();
        await selectChat(res.data.chat_id);
      } catch (err) {
        showError(err);
      } finally {
        loading.value = false;
      }
    }

    async function removeChat(id) {
      if (!confirm("确认删除该会话？")) return;
      try {
        await api(`/api/conversations/${id}`, { method: "DELETE" });
        if (chatId.value === id) {
          chatId.value = "";
          messages.value = [];
          localStorage.removeItem(CHAT_KEY);
        }
        await loadConversations();
      } catch (err) {
        showError(err);
      }
    }

    async function sendMessage() {
      const text = draft.value.trim();
      if (!text || loading.value || agentRunning.value) return;
      if (!chatId.value) {
        await createChat();
        if (!chatId.value) return;
      }
      loading.value = true;
      draft.value = "";
      resetZoneLogs();
      pushZoneLog("think", "用户提问", text);
      rightTab.value = "think";

      const tmpUserId = `tmp-user-${Date.now()}`;
      const tmpAsstId = `tmp-asst-${Date.now()}`;
      messages.value.push({
        id: tmpUserId,
        role: "user",
        content: text,
      });
      messages.value.push({
        id: tmpAsstId,
        role: "assistant",
        content: "",
        streaming: true,
      });
      await nextTick();
      const box = document.querySelector(".messages");
      if (box) box.scrollTop = box.scrollHeight;

      try {
        const resp = await fetch(`/api/conversations/${chatId.value}/chat/stream`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token.value}`,
          },
          body: JSON.stringify({ content: text, use_rag: true }),
        });
        if (resp.status === 401) {
          clearSession();
          view.value = "login";
          throw new Error("未登录或 token 无效");
        }
        if (!resp.ok) {
          const errBody = await resp.json().catch(() => null);
          throw new Error(
            (errBody && (errBody.detail || errBody.message)) || `HTTP ${resp.status}`
          );
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let gotDone = false;

        const asst = () => messages.value.find((m) => m.id === tmpAsstId);

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const chunks = buffer.split("\n\n");
          buffer = chunks.pop() || "";
          for (const chunk of chunks) {
            const line = chunk
              .split("\n")
              .map((l) => l.trim())
              .find((l) => l.startsWith("data:"));
            if (!line) continue;
            const payload = JSON.parse(line.slice(5).trim());
            if (payload.type === "user_message" && payload.message) {
              const u = messages.value.find((m) => m.id === tmpUserId);
              if (u) Object.assign(u, payload.message);
              if (payload.title) {
                const hit = conversations.value.find((c) => c.chat_id === chatId.value);
                if (hit) hit.title = payload.title;
              }
            } else if (payload.type === "status") {
              const a = asst();
              if (a && !a.content) a.statusHint = payload.message || "";
              pushZoneLog(payload.zone || "think", "状态", payload.message || "");
            } else if (payload.type === "memory_summary") {
              pushZoneLog("think", "记忆摘要", payload.summary || "");
            } else if (payload.type === "delta") {
              const a = asst();
              if (a) {
                a.statusHint = "";
                a.content = (a.content || "") + (payload.content || "");
                a.streaming = true;
              }
              await nextTick();
              if (box) box.scrollTop = box.scrollHeight;
            } else if (payload.type === "done") {
              gotDone = true;
              if (payload.trace_id) lastTraceId.value = payload.trace_id;
              if (payload.memory_summary) {
                pushZoneLog("think", "记忆摘要", payload.memory_summary);
              }
              const raw =
                (payload.assistant_message && payload.assistant_message.content) ||
                "";
              const clean = displayContent(raw);
              pushZoneLog("answer", "回答", clean.slice(0, 1200) || "（空回答）");
              rightTab.value = "answer";
              const a = asst();
              if (a && payload.assistant_message) {
                Object.assign(a, payload.assistant_message, { streaming: false, statusHint: "" });
              } else if (a) {
                a.streaming = false;
                a.statusHint = "";
              }
              if (payload.title) {
                const hit = conversations.value.find((c) => c.chat_id === chatId.value);
                if (hit) {
                  hit.title = payload.title;
                  hit.update_date =
                    (payload.assistant_message && payload.assistant_message.create_date) ||
                    hit.update_date;
                }
              }
            } else if (payload.type === "error") {
              throw new Error(payload.message || "流式对话失败");
            }
          }
        }

        if (!gotDone) {
          const a = asst();
          if (a) a.streaming = false;
        }
      } catch (err) {
        draft.value = text;
        messages.value = messages.value.filter(
          (m) => m.id !== tmpUserId && m.id !== tmpAsstId
        );
        showError(err);
      } finally {
        loading.value = false;
        await nextTick();
        const box2 = document.querySelector(".messages");
        if (box2) box2.scrollTop = box2.scrollHeight;
      }
    }

    function upsertPlanStep(evt) {
      const idx = evt.index;
      const existing = planSteps.value.find((s) => s.index === idx);
      if (existing) {
        existing.status = evt.status;
        existing.detail = evt.detail;
        existing.title = evt.title;
        existing.kind = evt.kind;
      } else {
        planSteps.value.push({
          index: idx,
          kind: evt.kind,
          title: evt.title,
          detail: evt.detail,
          status: evt.status,
        });
      }
      planSteps.value = [...planSteps.value].sort((a, b) => a.index - b.index);
      const zone =
        evt.zone ||
        (evt.kind === "answer" ? "answer" : evt.kind === "tool" ? "tool" : "think");
      if (evt.status === "done" || evt.status === "running") {
        pushZoneLog(zone, evt.title, evt.detail);
        if (rightTab.value !== "artifact") rightTab.value = zone;
      }
    }

    const agentAbort = ref(null);

    async function runAgent() {
      return startAgentRun(false);
    }

    async function runMultiAgent() {
      return startAgentRun(true);
    }

    async function startAgentRun(multiAgent) {
      const text = draft.value.trim();
      if (!text || loading.value || agentRunning.value) return;
      if (!chatId.value) {
        await createChat();
        if (!chatId.value) return;
      }
      const task = text;
      draft.value = "";
      agentRunning.value = true;
      agentStatus.value = "running";
      planSteps.value = [];
      zoneLogs.value = { think: [], tool: [], answer: [] };
      hitlPending.value = null;
      rightTab.value = "think";
      if (agentAbort.value) {
        try {
          agentAbort.value.abort();
        } catch (_e) {
          /* ignore */
        }
      }
      agentAbort.value = new AbortController();
      messages.value.push({
        id: `tmp-user-${Date.now()}`,
        role: "user",
        content: multiAgent ? `【多 Agent】${task}` : task,
      });

      try {
        const resp = await fetch(`/api/conversations/${chatId.value}/agent/run`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token.value}`,
          },
          body: JSON.stringify({
            content: task,
            use_tools: true,
            multi_agent: !!multiAgent,
          }),
          signal: agentAbort.value.signal,
        });
        if (resp.status === 401) {
          clearSession();
          view.value = "login";
          throw new Error("未登录或 token 无效");
        }
        if (!resp.ok) {
          const errBody = await resp.json().catch(() => null);
          throw new Error(
            (errBody && (errBody.detail || errBody.message)) || `HTTP ${resp.status}`
          );
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const chunks = buffer.split("\n\n");
          buffer = chunks.pop() || "";
          for (const chunk of chunks) {
            const line = chunk
              .split("\n")
              .map((l) => l.trim())
              .find((l) => l.startsWith("data:"));
            if (!line) continue;
            const payload = JSON.parse(line.slice(5).trim());
            if (payload.type === "step") {
              upsertPlanStep(payload);
            } else if (payload.type === "hitl_required") {
              hitlPending.value = payload;
              rightTab.value = "tool";
              pushZoneLog(
                "tool",
                "HITL 待确认",
                `${payload.tool_name}: ${payload.args_preview || ""}`
              );
            } else if (payload.type === "stopped") {
              agentStatus.value = "stopped";
              agentRunning.value = false;
              hitlPending.value = null;
              messages.value.push({
                id: `tmp-stop-${Date.now()}`,
                role: "assistant",
                content: payload.message || "任务已停止",
              });
            } else if (payload.type === "done") {
              agentStatus.value = "done";
              if (payload.trace_id) lastTraceId.value = payload.trace_id;
              pushZoneLog("answer", "最终回答", payload.answer || "完成");
              rightTab.value = "answer";
              messages.value.push({
                id: `tmp-done-${Date.now()}`,
                role: "assistant",
                content: payload.answer || "完成",
              });
              await loadArtifacts();
            } else if (payload.type === "error") {
              showError(new Error(payload.message || "Agent 错误"));
              pushZoneLog("think", "错误", payload.message || "Agent 错误");
              agentStatus.value = "error";
            } else if (payload.type === "persisted") {
              await loadMessages(chatId.value);
              await loadConversations();
              rightTab.value = "artifact";
              await loadArtifacts();
            }
          }
        }
        if (agentStatus.value !== "stopped" && agentStatus.value !== "error") {
          rightTab.value = "artifact";
          await loadArtifacts();
        }
      } catch (err) {
        if (err && err.name === "AbortError") {
          agentStatus.value = "stopped";
          hitlPending.value = null;
        } else {
          draft.value = task;
          showError(err);
          agentStatus.value = "";
        }
      } finally {
        agentRunning.value = false;
        agentAbort.value = null;
        await nextTick();
        const box = document.querySelector(".messages");
        if (box) box.scrollTop = box.scrollHeight;
      }
    }

    async function stopAgent() {
      if (!chatId.value) return;
      // 先解锁 UI，避免「停止了却还锁着多步运行」
      agentRunning.value = false;
      agentStatus.value = "stopped";
      hitlPending.value = null;
      try {
        if (agentAbort.value) {
          agentAbort.value.abort();
          agentAbort.value = null;
        }
      } catch (_e) {
        /* ignore */
      }
      try {
        await api(`/api/conversations/${chatId.value}/agent/stop`, {
          method: "POST",
        });
        pushZoneLog("think", "已停止", "用户点击停止，任务已取消");
      } catch (err) {
        showError(err);
      }
    }

    async function loadArtifacts() {
      try {
        // 优先当前会话；若为空则展示该用户全部产物，避免「有文件但栏空」
        const q = chatId.value ? `?chat_id=${encodeURIComponent(chatId.value)}` : "";
        let res = await api(`/api/artifacts${q}`);
        let list = res.data || [];
        if (!list.length && chatId.value) {
          res = await api("/api/artifacts");
          list = res.data || [];
        }
        artifacts.value = list;
      } catch (err) {
        showError(err);
      }
    }

    async function downloadArtifact(a) {
      try {
        const resp = await fetch(a.download_url, {
          headers: { Authorization: `Bearer ${token.value}` },
        });
        if (!resp.ok) throw new Error("下载失败");
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = a.filename || "artifact.bin";
        link.click();
        URL.revokeObjectURL(url);
      } catch (err) {
        showError(err);
      }
    }

    async function loadKb() {
      try {
        const res = await api("/api/knowledge");
        kbDocs.value = res.data || [];
      } catch (err) {
        showError(err);
      }
    }

    async function refreshKnowledge() {
      await loadKb();
      try {
        const res = await api("/api/knowledge/strategies");
        kbStrategies.value = res.data && res.data.length ? res.data : KB_STRATEGY_FALLBACK;
      } catch {
        kbStrategies.value = KB_STRATEGY_FALLBACK;
      }
      if (!kbStrategies.value.some((s) => s.id === kbStrategy.value)) {
        kbStrategy.value = kbStrategies.value[0].id;
      }
      // 仅在参数键缺失时套默认，避免刷新冲掉用户已调参数
      const meta = kbStrategies.value.find((s) => s.id === kbStrategy.value);
      if (meta) {
        const next = { ...kbParams.value };
        (meta.params || []).forEach((p) => {
          if (next[p.key] == null) next[p.key] = p.default;
        });
        kbParams.value = next;
      }
    }

    async function readKbFileAsText(file) {
      return await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => reject(new Error("读取文件失败"));
        reader.readAsText(file, "UTF-8");
      });
    }

    async function resolveKbContent() {
      if (kbSource.value === "file") {
        if (!kbFile.value) throw new Error("请先选择文件");
        const text = await readKbFileAsText(kbFile.value);
        const name =
          kbFilename.value.trim() || kbFile.value.name || kbFileName.value || "upload.txt";
        return { content: text, filename: name };
      }
      const content = kbText.value.trim();
      if (!content) throw new Error("请粘贴文本内容");
      const name = kbFilename.value.trim() || "note.txt";
      return { content, filename: name };
    }

    async function previewKb() {
      kbLoading.value = true;
      try {
        let res;
        if (kbSource.value === "file") {
          if (!kbFile.value) throw new Error("请先选择文件");
          const form = new FormData();
          form.append("file", kbFile.value);
          form.append("strategy", kbStrategy.value);
          form.append("chunk_size", String(kbChunkSizeValue()));
          form.append("chunk_overlap", String(kbOverlapValue()));
          const resp = await fetch("/api/knowledge/preview-file", {
            method: "POST",
            headers: { Authorization: `Bearer ${token.value}` },
            body: form,
          });
          const data = await resp.json().catch(() => null);
          if (!resp.ok || (data && data.code !== 0)) {
            throw new Error((data && data.message) || "预览失败");
          }
          res = data;
        } else {
          const { content, filename } = await resolveKbContent();
          res = await api("/api/knowledge/preview", {
            method: "POST",
            body: JSON.stringify({
              content,
              filename,
              strategy: kbStrategy.value,
              chunk_size: kbChunkSizeValue(),
              chunk_overlap: kbOverlapValue(),
            }),
          });
        }
        kbPreview.value = res.data || { chunks: [] };
      } catch (err) {
        showError(err);
      } finally {
        kbLoading.value = false;
      }
    }

    async function confirmKbIngest() {
      kbLoading.value = true;
      try {
        let data = null;
        if (kbSource.value === "file") {
          if (!kbFile.value) throw new Error("请先选择文件");
          const form = new FormData();
          form.append("file", kbFile.value);
          form.append("strategy", kbStrategy.value);
          form.append("chunk_size", String(kbChunkSizeValue()));
          form.append("chunk_overlap", String(kbOverlapValue()));
          const resp = await fetch("/api/knowledge/upload", {
            method: "POST",
            headers: { Authorization: `Bearer ${token.value}` },
            body: form,
          });
          data = await resp.json().catch(() => null);
          if (!resp.ok || (data && data.code !== 0)) {
            throw new Error((data && data.message) || "入库失败");
          }
        } else {
          const { content, filename } = await resolveKbContent();
          const form = new FormData();
          form.append("filename", filename);
          form.append("content", content);
          form.append("strategy", kbStrategy.value);
          form.append("chunk_size", String(kbChunkSizeValue()));
          form.append("chunk_overlap", String(kbOverlapValue()));
          const resp = await fetch("/api/knowledge/upload-text", {
            method: "POST",
            headers: { Authorization: `Bearer ${token.value}` },
            body: form,
          });
          data = await resp.json().catch(() => null);
          if (!resp.ok || (data && data.code !== 0)) {
            throw new Error((data && data.message) || "入库失败");
          }
        }
        kbText.value = "";
        kbFile.value = null;
        kbFileName.value = "";
        await loadKb();
        if (data.data && data.data.id) {
          await viewKbChunks(data.data);
        } else {
          await previewKb();
        }
      } catch (err) {
        showError(err);
      } finally {
        kbLoading.value = false;
      }
    }

    function onKbFilePick(e) {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      kbFile.value = file;
      kbFileName.value = file.name;
      if (!kbFilename.value) kbFilename.value = file.name;
    }

    function onKbFileDrop(e) {
      const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (!file) return;
      kbFile.value = file;
      kbFileName.value = file.name;
      if (!kbFilename.value) kbFilename.value = file.name;
      kbSource.value = "file";
    }

    async function viewKbChunks(doc) {
      try {
        const res = await api(`/api/knowledge/${doc.id}/chunks`);
        kbPreview.value = res.data || { chunks: [] };
      } catch (err) {
        showError(err);
      }
    }

    async function runKbSearch() {
      const q = kbSearchQuery.value.trim();
      if (!q) {
        showError(new Error("请输入检索问题"));
        return;
      }
      kbSearching.value = true;
      try {
        const res = await api("/api/knowledge/search", {
          method: "POST",
          body: JSON.stringify({ query: q, top_k: 5 }),
        });
        kbHits.value = res.data || [];
        if (!kbHits.value.length) showError(new Error("无命中，可先入库文档再试"));
      } catch (err) {
        showError(err);
      } finally {
        kbSearching.value = false;
      }
    }

    async function deleteKb(id) {
      if (!confirm("删除该知识库文档？")) return;
      try {
        await api(`/api/knowledge/${id}`, { method: "DELETE" });
        await loadKb();
        if (kbPreview.value && kbPreview.value.chunks) {
          kbPreview.value = { filename: "", char_count: 0, chunk_count: 0, chunks: [] };
        }
      } catch (err) {
        showError(err);
      }
    }

    function onKeydown(e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    }

    async function afterLogin() {
      await loadConversations();
      if (chatId.value) {
        const exists = conversations.value.some((c) => c.chat_id === chatId.value);
        if (exists) await loadMessages(chatId.value);
        else {
          chatId.value = "";
          localStorage.removeItem(CHAT_KEY);
        }
      }
      if (!chatId.value && conversations.value.length) {
        await selectChat(conversations.value[0].chat_id);
      }
    }

    onMounted(async () => {
      try {
        await api("/health", { skipAuth: true });
        if (token.value) {
          const me = await api("/api/auth/me");
          user.value = me.data;
          localStorage.setItem(USER_KEY, JSON.stringify(me.data));
          // 已登录默认进首页，由用户点「进入工作台」
          view.value = "home";
        }
      } catch (err) {
        if (token.value) clearSession();
        // 首页仍可浏览；仅在 API 异常时提示
        if (!String(err.message || "").includes("MySQL")) {
          /* ignore soft boot errors on home */
        }
      } finally {
        booting.value = false;
      }
    });

    return {
      view,
      registerEnabled,
      token,
      user,
      conversations,
      chatId,
      messages,
      draft,
      loading,
      booting,
      error,
      rightTab,
      agentRunning,
      planSteps,
      agentStatus,
      zoneLogs,
      hitlPending,
      artifacts,
      traces,
      traceDetail,
      lastTraceId,
      getThinkLogs,
      getToolLogs,
      getAnswerLogs,
      latestAssistantText,
      kbDocs,
      kbSource,
      kbFilename,
      kbText,
      kbFileName,
      kbStrategy,
      kbStrategies,
      kbCurrentStrategy,
      kbParams,
      kbLoading,
      kbPreview,
      kbSearchQuery,
      kbHits,
      kbSearching,
      authForm,
      authLoading,
      isAuthed,
      parseCitations,
      displayContent,
      formatJson,
      setRightTab,
      goAuth,
      enterWorkspace,
      enterKnowledge,
      enterTrace,
      submitAuth,
      logout,
      formatTime,
      selectChat,
      createChat,
      removeChat,
      sendMessage,
      runAgent,
      runMultiAgent,
      stopAgent,
      loadArtifacts,
      downloadArtifact,
      decideHitl,
      loadTraces,
      selectTrace,
      refreshKnowledge,
      previewKb,
      confirmKbIngest,
      onKbFilePick,
      onKbFileDrop,
      onKbStrategyChange,
      viewKbChunks,
      runKbSearch,
      deleteKb,
      onKeydown,
    };
  },
});

app.config.errorHandler = (err, _instance, info) => {
  console.error("[vue]", info, err);
  try {
    const el = document.querySelector(".toast");
    // 不卸载整页：仅打日志；错误提示由业务 showError 负责
  } catch (_e) {
    /* ignore */
  }
};

app.mount("#app");
