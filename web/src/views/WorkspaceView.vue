<template>
  <section class="workspace-page" :data-mode="mode">
    <div class="workspace-shell">
      <button
        v-if="historyOpen"
        class="sidebar-backdrop"
        type="button"
        aria-label="关闭历史"
        @click="historyOpen = false"
      />
      <button
        v-if="panelOpen"
        class="panel-backdrop"
        type="button"
        aria-label="关闭面板"
        @click="panelOpen = false"
      />

      <aside class="col col-left" :class="{ open: historyOpen }">
        <div class="panel-head">
          <h3>历史会话</h3>
          <button class="btn btn-outline btn-sm" @click="createChat">＋ 新对话</button>
        </div>
        <ul class="history-list">
          <li v-for="c in conversations" :key="c.chat_id">
            <div
              class="history-item"
              :class="{ active: c.chat_id === chatId }"
              @click="selectChat(c.chat_id)"
            >
              <div>
                <div class="title">{{ historyTitle(c) }}</div>
                <div class="meta">{{ formatTime(c.update_date) }}</div>
              </div>
            </div>
          </li>
        </ul>
      </aside>

      <main class="col col-center">
        <div class="center-top">
          <div class="center-top-left">
            <button class="history-toggle" type="button" @click="historyOpen = !historyOpen">历史</button>
            <button class="back" type="button" @click="$router.push('/')">← 返回</button>
          </div>
          <div class="title-block">
            <strong>
              <img class="title-avatar" :src="aiAvatar" alt="" />
              {{ workspaceTitle }}
            </strong>
            <span class="sid">{{ chatId ? '会话 ' + chatId.slice(0, 8) + '…' : '未选择' }}</span>
          </div>
          <div class="center-top-right">
            <button class="panel-toggle" type="button" @click="panelOpen = !panelOpen">面板</button>
            <router-link class="btn btn-outline btn-sm" to="/knowledge">知识库</router-link>
            <button class="btn btn-outline btn-sm" type="button" @click="logout">退出</button>
          </div>
        </div>

        <div class="messages" ref="msgBox">
          <div class="empty-state" v-if="!messages.length">
            <img class="empty-avatar" :src="aiAvatar" alt="" />
            <strong>{{ workspaceTitle }}</strong>
            {{ emptyHint }}
          </div>
          <div
            v-for="(m, index) in messages"
            :key="m.id"
            :class="['message-row', m.role === 'user' ? 'message-row-user' : 'message-row-ai']"
          >
            <div :class="['message-item', m.role === 'user' ? 'message-user' : 'message-ai']">
              <img
                class="avatar"
                :src="m.role === 'user' ? userAvatar : aiAvatar"
                :alt="m.role === 'user' ? '用户头像' : 'Agent 头像'"
              />
              <div v-if="m.role === 'user'" class="bubble">
                <p class="bubble-text">{{ m.content }}</p>
              </div>
              <div v-else class="bubble" :class="{ streaming: m.streaming }">
                <p class="bubble-text">{{ displayContent(m.content) }}<span v-if="m.streaming" class="caret" aria-hidden="true" /></p>
              </div>
            </div>

            <div
              v-if="m.role === 'user' && m.content && editingIndex !== index"
              class="user-actions"
            >
              <button
                type="button"
                class="action-btn"
                title="复制"
                aria-label="复制"
                :disabled="loading || agentRunning"
                @click="copyUserMessage(m.content, index)"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <rect x="9" y="9" width="11" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.8" />
                  <path
                    d="M6 15H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                  />
                </svg>
              </button>
              <button
                type="button"
                class="action-btn"
                title="修改后发送"
                aria-label="修改后发送"
                :disabled="loading || agentRunning"
                @click="editUserMessage(index)"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M12 20h9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
                  <path
                    d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4L16.5 3.5z"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linejoin="round"
                  />
                </svg>
              </button>
              <span v-if="copiedIndex === index" class="copied-tip">已复制</span>
            </div>

            <div v-if="m.role === 'user' && editingIndex === index" class="inline-edit">
              <textarea
                ref="editInputRef"
                v-model="editText"
                class="edit-textarea"
                rows="3"
                @keydown.meta.enter.prevent="confirmEditAndSend"
                @keydown.ctrl.enter.prevent="confirmEditAndSend"
              />
              <div class="edit-footer">
                <button type="button" class="edit-cancel" @click="closeEdit">取消</button>
                <button
                  type="button"
                  class="btn btn-primary btn-sm"
                  :disabled="!editText.trim() || loading || agentRunning"
                  @click="confirmEditAndSend"
                >
                  发送
                </button>
              </div>
            </div>
          </div>
        </div>

        <div class="composer-wrap">
          <div v-if="hitlPending" class="hitl-banner">
            <div>
              <strong>写入文件需确认</strong>
              <p>工具：{{ hitlPending.tool_name }}</p>
              <small>{{ hitlPending.args_preview }}</small>
            </div>
            <div class="hitl-actions">
              <button class="btn btn-primary btn-sm" type="button" @click="decideHitl('approve')">批准</button>
              <button class="btn btn-stop btn-sm" type="button" @click="decideHitl('reject')">拒绝</button>
            </div>
          </div>
          <form class="composer" @submit.prevent="sendMessage">
            <textarea
              v-model="draft"
              rows="3"
              :placeholder="composerPlaceholder"
              :disabled="loading || agentRunning"
              @keydown.enter.exact.prevent="onComposerEnter"
            />
            <div class="composer-bar">
              <div class="composer-left">
                <label class="model-select-wrap" title="选择大模型">
                  <select
                    v-model="selectedModel"
                    class="model-select"
                    :disabled="loading || agentRunning"
                    aria-label="选择大模型"
                    @change="onModelChange"
                  >
                    <option v-for="m in modelOptions" :key="m.id" :value="m.id">
                      {{ m.label }}
                    </option>
                  </select>
                </label>
              </div>
              <div class="composer-actions">
                <button
                  v-if="mode === 'super'"
                  class="btn btn-outline btn-sm"
                  type="button"
                  :disabled="loading || agentRunning || !draft.trim()"
                  @click="runAgent(false)"
                >
                  多步运行
                </button>
                <button
                  v-if="mode === 'multi'"
                  class="btn btn-outline btn-sm"
                  type="button"
                  :disabled="loading || agentRunning || !draft.trim()"
                  @click="runAgent(true)"
                >
                  多 Agent
                </button>
                <button
                  v-if="agentRunning"
                  class="btn btn-stop btn-sm"
                  type="button"
                  @click="stopAgent"
                >
                  停止
                </button>
                <button
                  class="send-btn"
                  type="submit"
                  :disabled="loading || agentRunning || !draft.trim()"
                >
                  ↑
                </button>
              </div>
            </div>
          </form>
        </div>
      </main>

      <aside class="col col-right" :class="{ open: panelOpen }">
        <div class="right-tabs">
          <button type="button" :class="{ active: rightTab === 'think' }" @click="rightTab = 'think'">思考</button>
          <button type="button" :class="{ active: rightTab === 'tool' }" @click="rightTab = 'tool'">工具</button>
          <button type="button" :class="{ active: rightTab === 'answer' }" @click="rightTab = 'answer'">回答</button>
          <button type="button" :class="{ active: rightTab === 'artifact' }" @click="openArtifacts">产物</button>
        </div>
        <div class="right-body">
          <div v-if="hitlPending" class="hitl-card">
            <strong>HITL 待确认</strong>
            <p>工具：{{ hitlPending.tool_name }}</p>
            <small>{{ hitlPending.args_preview }}</small>
            <div class="hitl-actions">
              <button class="btn btn-primary btn-sm" type="button" @click="decideHitl('approve')">批准</button>
              <button class="btn btn-stop btn-sm" type="button" @click="decideHitl('reject')">拒绝</button>
            </div>
          </div>
          <div v-if="rightTab === 'think'">
            <div v-if="!zoneLogs.think.length" class="plan-empty">思考日志显示在这里。</div>
            <ul class="zone-log" v-else>
              <li v-for="(l, i) in zoneLogs.think" :key="'t'+i"><strong>{{ l.title }}</strong><p>{{ l.detail }}</p></li>
            </ul>
          </div>
          <div v-else-if="rightTab === 'tool'">
            <div v-if="!zoneLogs.tool.length" class="plan-empty">工具日志显示在这里。</div>
            <ul class="zone-log" v-else>
              <li v-for="(l, i) in zoneLogs.tool" :key="'o'+i"><strong>{{ l.title }}</strong><p>{{ l.detail }}</p></li>
            </ul>
          </div>
          <div v-else-if="rightTab === 'answer'">
            <div v-if="!zoneLogs.answer.length" class="plan-empty">回答摘要显示在这里。</div>
            <ul class="zone-log" v-else>
              <li v-for="(l, i) in zoneLogs.answer" :key="'a'+i"><strong>{{ l.title }}</strong><p>{{ l.detail }}</p></li>
            </ul>
          </div>
          <div v-else>
            <div v-if="!artifacts.length" class="plan-empty">暂无产物。</div>
            <ul class="artifact-list" v-else>
              <li v-for="a in artifacts" :key="a.id">
                <div>
                  <strong>{{ a.filename }}</strong>
                  <small>{{ a.byte_size }} bytes</small>
                </div>
                <a class="btn btn-outline btn-sm" href="#" @click.prevent="downloadArtifact(a)">下载</a>
              </li>
            </ul>
          </div>
        </div>
      </aside>
    </div>
  </section>
</template>

<script setup>
import { computed, inject, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, clearSession, getToken } from '../api'
import {
  DEFAULT_MODEL,
  MODEL_OPTIONS,
  loadSelectedModel,
  saveSelectedModel,
} from '../constants/models'

const showError = inject('showError', () => {})
const router = useRouter()
const route = useRoute()

/** 入口模式：interviewer（RAG）/ multi / super（均不走 RAG） */
const mode = computed(() => {
  const m = String(route.query.mode || 'super')
  if (m === 'interviewer' || m === 'love') return 'interviewer'
  if (m === 'multi') return 'multi'
  return 'super'
})

const workspaceTitle = computed(() => {
  if (mode.value === 'interviewer') return '面试官小助手'
  if (mode.value === 'multi') return '多 Agent'
  return '超级智能体'
})

const aiAvatar = computed(() => {
  if (mode.value === 'interviewer') return '/avatars/cc-interviewer.svg'
  if (mode.value === 'multi') return '/avatars/multi-agent.svg'
  return '/avatars/super-agent.svg'
})

const userAvatar = computed(() =>
  mode.value === 'interviewer' ? '/avatars/love-user.svg' : '/avatars/agent-user.svg'
)

const agentType = computed(() => {
  if (mode.value === 'interviewer') return 'INTERVIEWER'
  if (mode.value === 'multi') return 'MULTI_AGENT'
  return 'SUPER_AGENT'
})

const emptyHint = computed(() => {
  if (mode.value === 'interviewer') return '先在知识库入库，再提问；回答会结合 RAG 引用与模型总结。'
  if (mode.value === 'multi') return '描述任务后点「多 Agent」，看 Planner / Worker 协作（不走 RAG）。'
  return '描述任务后点「多步运行」生成 PDF 等产物，可演示 HITL（不走 RAG）。'
})

/** 输入框占位：按 Agent 核心能力提示用户怎么提问 */
const composerPlaceholder = computed(() => {
  if (mode.value === 'interviewer') return '说说你的求职目标或面试问题…'
  if (mode.value === 'multi') return '例如：规划并完成：写 intro.txt，内容为一句话项目介绍'
  return '描述你需要完成的任务，例如：搜索资料并生成 PDF 报告…'
})

const modeHint = computed(() =>
  mode.value === 'multi' ? '多 Agent · 不用 RAG' : '超级智能体 · 不用 RAG'
)

const conversations = ref([])
const chatId = ref('')
const messages = ref([])
const draft = ref('')
const loading = ref(false)
const agentRunning = ref(false)
const useRag = ref(mode.value === 'interviewer')
const selectedModel = ref(loadSelectedModel())
const modelOptions = MODEL_OPTIONS
const rightTab = ref('think')
const zoneLogs = reactive({ think: [], tool: [], answer: [] })
const hitlPending = ref(null)
const artifacts = ref([])
const agentAbort = ref(null)
const msgBox = ref(null)
const editInputRef = ref(null)
const editingIndex = ref(-1)
const editText = ref('')
const copiedIndex = ref(-1)

watch(mode, (m) => {
  useRag.value = m === 'interviewer'
})

function onModelChange() {
  saveSelectedModel(selectedModel.value || DEFAULT_MODEL)
}

/** Enter 发送；Shift+Enter 换行（由浏览器默认处理） */
function onComposerEnter() {
  if (loading.value || agentRunning.value || !draft.value.trim()) return
  sendMessage()
}

/** 与 CSS 断点对齐：历史 ≥960 常显，面板 ≥1100 常显 */
const historyOpen = ref(typeof window !== 'undefined' ? window.innerWidth >= 960 : true)
const panelOpen = ref(typeof window !== 'undefined' ? window.innerWidth >= 1100 : true)

function syncSidePanels() {
  const w = window.innerWidth
  historyOpen.value = w >= 960
  panelOpen.value = w >= 1100
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString()
}

function displayContent(content) {
  if (!content) return ''
  const idx = content.indexOf('__CITATIONS__')
  let text = idx >= 0 ? content.slice(0, idx).trimEnd() : content
  // 去掉后端路径 / artifact_id，下载请走右侧「产物」
  text = text
    .replace(/artifact_id=[A-Za-z0-9]+/g, '')
    .replace(/\/api\/artifacts\/[A-Za-z0-9_\-./]+/g, '')
    .replace(/（Word 文档 \.docx，可用 Word\/WPS 打开）/g, '')
    .replace(/可通过/g, '')
    .replace(/，\s*下载\s*/g, '，')
    .replace(/[，,]{2,}/g, '，')
  return text.replace(/^[，,\s]+|[，,\s]+$/g, '').trim()
}

function isBlankChatTitle(title) {
  const raw = String(title || '').trim()
  const stripped = raw.replace(/^【[^】]+】/, '').trim()
  return !stripped || stripped === '新对话' || stripped === '新会话'
}

function chatStorageKey(type = agentType.value) {
  return `zhizhi_chat_id_${type}`
}

function persistChatId(id) {
  chatId.value = id || ''
  if (!id) {
    localStorage.removeItem('zhizhi_chat_id')
    localStorage.removeItem(chatStorageKey())
    return
  }
  localStorage.setItem('zhizhi_chat_id', id)
  localStorage.setItem(chatStorageKey(), id)
}

function historyTitle(c) {
  const raw = String(c?.title || '').trim()
  const type = String(c?.agent_type || '')
  const prefix =
    type === 'MULTI_AGENT' ? '【多Agent】' : type === 'SUPER_AGENT' ? '【超级智能体】' : type === 'INTERVIEWER' ? '【面试官】' : ''
  if (!prefix) return raw || '新对话'
  if (raw.startsWith('【')) return raw
  if (!raw || raw === '新对话' || raw === '新会话' || raw === '多 Agent' || raw === '面试官小助手' || raw === '超级智能体') {
    return `${prefix}新对话`
  }
  return `${prefix}${raw}`
}

/**
 * 打字机写入指定气泡。
 * 必须改 `messages.value[index]`（响应式代理），不能改 push 前的普通对象，
 * 否则 Vue 不重绘，看起来像等流结束才一次性出全文。
 */
function createTypewriter(index) {
  let queue = ''
  let raf = 0
  let stopped = false

  const paint = () => {
    raf = 0
    if (stopped) return
    const cur = messages.value[index]
    if (!cur || !queue) return
    const take = queue.slice(0, queue.length > 240 ? 8 : 3)
    queue = queue.slice(take.length)
    messages.value[index] = {
      ...cur,
      content: (cur.content || '') + take,
      streaming: true,
    }
    if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight
    if (queue) raf = requestAnimationFrame(paint)
  }

  return {
    push(text) {
      if (stopped || !text) return
      queue += text
      if (!raf) raf = requestAnimationFrame(paint)
    },
    async finish(extra = {}) {
      stopped = true
      if (raf) cancelAnimationFrame(raf)
      raf = 0
      const cur = messages.value[index]
      if (!cur) return
      let content = `${cur.content || ''}${queue}`
      queue = ''
      if (extra.replace && extra.content != null) content = extra.content
      const rest = { ...extra }
      delete rest.replace
      delete rest.content
      messages.value[index] = { ...cur, ...rest, content, streaming: false }
      await nextTick()
      if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight
    },
  }
}

function pushZone(zone, title, detail) {
  const z = zone === 'tool' || zone === 'answer' ? zone : 'think'
  zoneLogs[z] = [...zoneLogs[z], { title, detail: String(detail || '').slice(0, 2000) }].slice(-40)
}

/** 复制用户气泡文案 */
async function copyUserMessage(content, index) {
  const text = String(content || '')
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  copiedIndex.value = index
  setTimeout(() => {
    if (copiedIndex.value === index) copiedIndex.value = -1
  }, 1600)
}

/** 打开行内编辑，修改后可重新发送 */
function editUserMessage(index) {
  if (loading.value || agentRunning.value) return
  const msg = messages.value[index]
  if (!msg || msg.role !== 'user') return
  editingIndex.value = index
  editText.value = msg.content || ''
  nextTick(() => {
    const el = Array.isArray(editInputRef.value) ? editInputRef.value[0] : editInputRef.value
    el?.focus()
    el?.select()
  })
}

function closeEdit() {
  editingIndex.value = -1
  editText.value = ''
}

async function confirmEditAndSend() {
  const text = editText.value.trim()
  if (!text || loading.value || agentRunning.value) return
  closeEdit()
  draft.value = text
  await sendMessage()
}

async function loadConversations() {
  const res = await api(`/api/conversations?agent_type=${encodeURIComponent(agentType.value)}`)
  conversations.value = res.data || []
}

async function loadMessages(id) {
  if (!id) {
    messages.value = []
    return
  }
  const res = await api(`/api/conversations/${id}/messages`)
  messages.value = res.data || []
  await nextTick()
  if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight
}

async function selectChat(id) {
  persistChatId(id)
  artifacts.value = []
  await loadMessages(id)
  if (rightTab.value === 'artifact') await openArtifacts()
  if (window.innerWidth < 960) historyOpen.value = false
}

/** 从首页点进某个 Agent（?new=1）时开新对话；刷新则恢复该 Agent 上次会话，绝不串到别的 Agent。 */
let bootToken = 0
async function bootWorkspace() {
  const token = ++bootToken
  artifacts.value = []
  const wantNew = String(route.query.new || '') === '1' || String(route.query.new || '') === 'true'
  await loadConversations()
  if (token !== bootToken) return

  if (wantNew) {
    const unused = conversations.value.find(
      (c) => String(c.agent_type || '') === agentType.value && isBlankChatTitle(c.title)
    )
    if (unused) await selectChat(unused.chat_id)
    else await createChat()
    if (token !== bootToken) return
    if (route.query.new != null && route.query.new !== '') {
      const q = { ...route.query }
      delete q.new
      await router.replace({ query: q })
    }
    return
  }

  const saved = localStorage.getItem(chatStorageKey()) || chatId.value
  const current = conversations.value.find((c) => c.chat_id === saved)
  if (current) {
    await selectChat(current.chat_id)
    return
  }
  if (conversations.value[0]) {
    await selectChat(conversations.value[0].chat_id)
    return
  }
  await createChat()
}

async function createChat() {
  const res = await api('/api/conversations', {
    method: 'POST',
    body: JSON.stringify({
      title: '新对话',
      agent_type: agentType.value,
      model: selectedModel.value || DEFAULT_MODEL,
    }),
  })
  await loadConversations()
  await selectChat(res.data.chat_id)
  if (window.innerWidth < 960) historyOpen.value = false
}

function logout() {
  clearSession()
  router.push('/')
}

async function sendMessage() {
  const text = draft.value.trim()
  if (!text || loading.value || agentRunning.value) return
  if (!chatId.value) await createChat()
  loading.value = true
  draft.value = ''
  zoneLogs.think = []
  zoneLogs.tool = []
  zoneLogs.answer = []
  pushZone('think', '用户提问', text)
  rightTab.value = 'think'
  const tmpUser = { id: `u-${Date.now()}`, role: 'user', content: text }
  messages.value.push(tmpUser, { id: `a-${Date.now()}`, role: 'assistant', content: '', streaming: true })
  const asstIndex = messages.value.length - 1
  const typer = createTypewriter(asstIndex)
  try {
    const resp = await fetch(`/api/conversations/${chatId.value}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${getToken()}`,
      },
      body: JSON.stringify({
        content: text,
        use_rag: useRag.value,
        model: selectedModel.value || DEFAULT_MODEL,
      }),
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const chunks = buffer.split(/\r?\n\r?\n/)
      buffer = chunks.pop() || ''
      for (const chunk of chunks) {
        const line = chunk.split('\n').map((l) => l.trim()).find((l) => l.startsWith('data:'))
        if (!line) continue
        const payload = JSON.parse(line.slice(5).trim())
        if (payload.type === 'status') pushZone(payload.zone || 'think', '状态', payload.message)
        if (payload.type === 'delta') typer.push(payload.content || '')
        if (payload.type === 'done') {
          const saved = payload.assistant_message
          await typer.finish(saved?.id ? { id: saved.id } : {})
          const shown = displayContent(messages.value[asstIndex]?.content || '')
          pushZone('answer', '回答', shown.slice(0, 1200))
          rightTab.value = 'answer'
          if (payload.trace_id) pushZone('think', 'trace', payload.trace_id)
        }
        if (payload.type === 'error') {
          await typer.finish()
          const err = new Error(payload.message || '对话失败')
          err.code = payload.code
          throw err
        }
      }
    }
    await typer.finish()
    await loadConversations()
  } catch (e) {
    await typer.finish()
    draft.value = text
    showError(e)
  } finally {
    loading.value = false
  }
}

async function runAgent(multiAgent) {
  const text = draft.value.trim()
  if (!text || loading.value || agentRunning.value) return
  if (!chatId.value) await createChat()
  const task = text
  draft.value = ''
  agentRunning.value = true
  zoneLogs.think = []
  zoneLogs.tool = []
  zoneLogs.answer = []
  hitlPending.value = null
  rightTab.value = 'think'
  if (agentAbort.value) try { agentAbort.value.abort() } catch { /* */ }
  agentAbort.value = new AbortController()
  const tmpUser = {
    id: `u-${Date.now()}`,
    role: 'user',
    content: task,
  }
  messages.value.push(tmpUser, { id: `a-${Date.now()}`, role: 'assistant', content: '', streaming: true })
  const asstIndex = messages.value.length - 1
  const typer = createTypewriter(asstIndex)
  try {
    const resp = await fetch(`/api/conversations/${chatId.value}/agent/run`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${getToken()}`,
      },
      body: JSON.stringify({
        content: task,
        use_tools: true,
        multi_agent: !!multiAgent,
        model: selectedModel.value || DEFAULT_MODEL,
      }),
      signal: agentAbort.value.signal,
    })
    if (resp.status === 429) {
      const body = await resp.json().catch(() => null)
      const detail = body?.detail
      const err = new Error(detail?.message || '配额超限')
      err.code = detail?.code || 'QUOTA_EXCEEDED'
      throw err
    }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let gotDelta = false
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const chunks = buffer.split(/\r?\n\r?\n/)
      buffer = chunks.pop() || ''
      for (const chunk of chunks) {
        const line = chunk.split('\n').map((l) => l.trim()).find((l) => l.startsWith('data:'))
        if (!line) continue
        const payload = JSON.parse(line.slice(5).trim())
        if (payload.type === 'step') {
          const zone = payload.zone || (payload.kind === 'answer' ? 'answer' : payload.kind === 'tool' ? 'tool' : 'think')
          pushZone(zone, payload.title, payload.detail)
          if (rightTab.value !== 'artifact') rightTab.value = zone
        } else if (payload.type === 'delta') {
          gotDelta = true
          typer.push(payload.content || '')
        } else if (payload.type === 'hitl_required') {
          hitlPending.value = payload
          rightTab.value = 'tool'
          if (window.innerWidth < 1100) panelOpen.value = true
          pushZone('tool', 'HITL 待确认', `${payload.tool_name}: ${payload.args_preview || ''}`)
        } else if (payload.type === 'stopped') {
          agentRunning.value = false
          await typer.finish({ content: payload.message || '已停止', replace: true })
        } else if (payload.type === 'done') {
          if (!gotDelta && payload.answer) typer.push(payload.answer)
          await typer.finish()
          pushZone('answer', '最终回答', payload.answer || messages.value[asstIndex]?.content || '')
          if (payload.config_version) pushZone('think', 'config_version', payload.config_version)
          rightTab.value = 'answer'
          await openArtifacts()
        } else if (payload.type === 'error') {
          await typer.finish()
          const err = new Error(payload.message || 'Agent 错误')
          err.code = payload.code
          showError(err)
          pushZone('think', '错误', `[${payload.code || ''}] ${payload.message}`)
        } else if (payload.type === 'persisted') {
          const cur = messages.value[asstIndex]
          if (cur && payload.assistant_message_id) {
            messages.value[asstIndex] = { ...cur, id: payload.assistant_message_id }
          }
          await loadConversations()
        }
      }
    }
    await typer.finish()
  } catch (e) {
    await typer.finish()
    if (e?.name !== 'AbortError') {
      draft.value = task
      showError(e)
    }
  } finally {
    agentRunning.value = false
    agentAbort.value = null
  }
}

async function stopAgent() {
  agentRunning.value = false
  hitlPending.value = null
  try { agentAbort.value?.abort() } catch { /* */ }
  agentAbort.value = null
  try {
    await api(`/api/conversations/${chatId.value}/agent/stop`, { method: 'POST' })
    pushZone('think', '已停止', '用户取消')
  } catch (e) {
    showError(e)
  }
}

async function decideHitl(decision) {
  if (!hitlPending.value || !chatId.value) return
  try {
    await api(`/api/conversations/${chatId.value}/hitl/decide`, {
      method: 'POST',
      body: JSON.stringify({ request_id: hitlPending.value.request_id, decision }),
    })
    pushZone('tool', `HITL ${decision}`, hitlPending.value.tool_name || '')
    hitlPending.value = null
  } catch (e) {
    showError(e)
  }
}

async function openArtifacts() {
  rightTab.value = 'artifact'
  if (window.innerWidth < 1100) panelOpen.value = true
  try {
    const params = new URLSearchParams()
    params.set('agent_type', agentType.value)
    const res = await api(`/api/artifacts?${params.toString()}`)
    artifacts.value = res.data || []
  } catch (e) {
    artifacts.value = []
    showError(e)
  }
}

async function downloadArtifact(a) {
  const resp = await fetch(a.download_url, { headers: { Authorization: `Bearer ${getToken()}` } })
  if (!resp.ok) throw new Error('下载失败')
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = a.filename
  link.click()
  URL.revokeObjectURL(url)
}

onMounted(async () => {
  syncSidePanels()
  window.addEventListener('resize', syncSidePanels)
  try {
    await bootWorkspace()
  } catch (e) {
    showError(e)
  }
})

watch(
  () => `${mode.value}|${route.query.new || ''}`,
  async (now, prev) => {
    if (!prev || now === prev) return
    try {
      await bootWorkspace()
    } catch (e) {
      showError(e)
    }
  }
)

onUnmounted(() => {
  window.removeEventListener('resize', syncSidePanels)
})
</script>
