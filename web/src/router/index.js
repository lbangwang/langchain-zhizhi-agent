import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '../api'
import HomeView from '../views/HomeView.vue'
import LoginView from '../views/LoginView.vue'
import WorkspaceView from '../views/WorkspaceView.vue'
import KnowledgeView from '../views/KnowledgeView.vue'
import TraceView from '../views/TraceView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/login', name: 'login', component: LoginView },
    { path: '/register', name: 'register', component: LoginView, props: { mode: 'register' } },
    { path: '/workspace', name: 'workspace', component: WorkspaceView, meta: { auth: true } },
    { path: '/knowledge', name: 'knowledge', component: KnowledgeView, meta: { auth: true } },
    { path: '/trace', name: 'trace', component: TraceView, meta: { auth: true } },
  ],
})

router.beforeEach(async (to) => {
  if (to.name === 'register') {
    try {
      const res = await fetch('/api/auth/features')
      const data = await res.json()
      if (!data.register_enabled) {
        return { name: 'login', query: to.query }
      }
    } catch {
      return { name: 'login', query: to.query }
    }
  }
  if (to.meta.auth && !getToken()) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  return true
})

export default router
