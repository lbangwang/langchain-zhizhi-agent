<template>
  <div class="home">
    <header class="topnav">
      <button type="button" class="brand brand-lockup" @click="$router.push('/')">
        <span class="brand-mark" aria-hidden="true" />
        <span>枝枝AI智能体</span>
      </button>

      <nav class="nav-links" aria-label="主导航">
        <a href="#" @click.prevent="goWorkspace('super')">工作台</a>
        <a href="#" @click.prevent="goWorkspace('multi')">多 Agent</a>
        <router-link to="/knowledge">知识库</router-link>
        <router-link to="/trace">Trace</router-link>
      </nav>

      <div class="nav-actions">
        <template v-if="user">
          <span class="nav-user">{{ user.nickname || user.username }}</span>
          <button type="button" class="btn btn-outline btn-sm" @click="onLogout">退出</button>
        </template>
        <router-link v-else class="btn btn-primary btn-sm" to="/login">登录</router-link>
      </div>
    </header>

    <main class="home-main">
      <section class="hero">
        <div class="hero-copy">
          <p class="hero-kicker">Python · FastAPI · LangGraph</p>
          <p class="hero-brand">枝枝AI智能体</p>
          <h1 class="hero-title">企业级 Agent 工作台</h1>
          <p class="hero-desc">
            覆盖对话、工具调用、知识库 RAG、人机确认与 Trace 回放。面试官场景看引用，超级智能体跑多步任务，多 Agent 讲清 Planner / Worker 协作。
          </p>
          <div class="hero-actions">
            <button type="button" class="btn btn-primary lg" @click="goWorkspace('super')">
              进入工作台
            </button>
            <button
              type="button"
              class="btn btn-outline lg"
              @click="user ? goWorkspace('interviewer') : goAuth('/login')"
            >
              {{ user ? '体验面试官小助手' : '登录后体验' }}
            </button>
          </div>
        </div>

        <aside class="hero-panel" aria-labelledby="highlights-title">
          <div class="hero-panel-inner">
            <div class="panel-row">
              <span class="dot" aria-hidden="true" />
              <h2 id="highlights-title" class="panel-label">本项目亮点</h2>
            </div>
            <ul class="highlight-list">
              <li>
                <strong>RAG + 引用溯源</strong>
                <span>知识库切片入库，对话展示来自哪篇文档</span>
              </li>
              <li>
                <strong>HITL 人机确认</strong>
                <span>写文件 / 生成 PDF 前可批准或拒绝</span>
              </li>
              <li>
                <strong>多 Agent 协作</strong>
                <span>Planner 拆步，Worker 逐步执行任务</span>
              </li>
              <li>
                <strong>可观测 Trace</strong>
                <span>单次请求步骤、耗时与运行状态可回看</span>
              </li>
            </ul>
            <div class="panel-chips">
              <span>思考</span>
              <span>工具</span>
              <span>产物</span>
              <span>RAG</span>
            </div>
          </div>
        </aside>
      </section>

      <!-- 模块一：能力入口（对齐 Java 版四卡） -->
      <section class="section" aria-labelledby="agents-title">
        <div class="section-head">
          <h2 id="agents-title">选择能力</h2>
          <p>从场景进入对应应用：面试官走 RAG，知识库入库，多 Agent / 超级智能体专注协作与工具。</p>
        </div>

        <div class="product-grid product-grid-4">
          <button type="button" class="product" @click="goWorkspace('interviewer')">
            <img class="product-avatar" src="/avatars/cc-interviewer.svg" alt="" />
            <h3>面试官小助手 CC</h3>
            <p>求职辅导与技术方案梳理，支持知识库引用卡片。</p>
          </button>

          <button type="button" class="product" @click="goWorkspace('multi')">
            <img class="product-avatar" src="/avatars/multi-agent.svg" alt="" />
            <h3>多 Agent</h3>
            <p>Planner 拆步，Worker 逐步执行，适合讲多智能体协作。</p>
          </button>

          <button type="button" class="product" @click="goWorkspace('super')">
            <img class="product-avatar" src="/avatars/super-agent.svg" alt="" />
            <h3>超级智能体</h3>
            <p>多步工具调用、HITL 审批与产物下载，专注任务执行。</p>
          </button>

          <button type="button" class="product" @click="goAuth('/knowledge')">
            <img class="product-avatar" src="/avatars/knowledge.svg" alt="" />
            <h3>知识库</h3>
            <p>上传文档切片入库，对话时展示「来自哪篇文档」。</p>
          </button>
        </div>
      </section>

      <!-- 模块二：三分钟演示 -->
      <section class="section demos" aria-labelledby="demos-title">
        <div class="section-head">
          <h2 id="demos-title">三分钟演示路径</h2>
          <p>按顺序点开即可走完核心功能。</p>
        </div>
        <ol class="demo-steps">
          <li>
            <button type="button" class="demo-step" @click="goAuth('/knowledge')">
              <strong>1 · RAG 提问看引用</strong>
              <span>知识库上传后，用面试官对话查看引用卡片</span>
            </button>
          </li>
          <li>
            <button type="button" class="demo-step" @click="goWorkspace('super')">
              <strong>2 · 多步 PDF + HITL</strong>
              <span>超级智能体生成 PDF，演示允许 / 拒绝</span>
            </button>
          </li>
          <li>
            <button type="button" class="demo-step" @click="goAuth('/trace')">
              <strong>3 · Trace 看耗时</strong>
              <span>查看 config_version、步骤与单次请求耗时</span>
            </button>
          </li>
        </ol>
      </section>
    </main>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { clearSession, getToken, loadUser } from '../api'

const router = useRouter()
const user = ref(null)

onMounted(() => {
  user.value = getToken() ? loadUser() : null
})

function onLogout() {
  clearSession()
  user.value = null
}

/** 需登录的入口：未登录则带 redirect 跳转登录 */
function goAuth(path) {
  if (!getToken()) {
    router.push({ path: '/login', query: { redirect: path } })
    return
  }
  router.push(path)
}

/** 从首页进入某个 Agent：带 new=1，工作台会新建该 Agent 的对话，避免串到上次会话 */
function goWorkspace(mode) {
  goAuth(`/workspace?mode=${mode}&new=1`)
}
</script>
