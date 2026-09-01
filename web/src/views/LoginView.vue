<template>
  <section class="auth-page">
    <div class="auth-card">
      <h1>{{ isRegister ? '注册' : '登录' }}</h1>
      <p>{{ isRegister ? '创建账号后进入工作台' : '使用已有账号登录工作台' }}</p>
      <form @submit.prevent="submit">
        <label v-if="isRegister">
          昵称
          <input v-model="form.nickname" placeholder="可选" />
        </label>
        <label>
          用户名
          <input v-model="form.username" required autocomplete="username" />
        </label>
        <label>
          密码
          <input v-model="form.password" type="password" required autocomplete="current-password" />
        </label>
        <button class="btn btn-primary" type="submit" :disabled="loading">
          {{ loading ? '提交中…' : isRegister ? '注册并进入' : '登录' }}
        </button>
      </form>
      <button v-if="registerEnabled" type="button" class="linkish" @click="toggle">
        {{ isRegister ? '已有账号？去登录' : '没有账号？去注册' }}
      </button>
      <router-link to="/">返回首页</router-link>
    </div>
  </section>
</template>

<script setup>
import { computed, inject, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, saveSession } from '../api'

const props = defineProps({ mode: { type: String, default: '' } })
const route = useRoute()
const router = useRouter()
const showError = inject('showError', () => {})

const registerEnabled = ref(false)
const isRegister = computed(
  () => registerEnabled.value && (props.mode === 'register' || route.name === 'register')
)
const form = reactive({ username: '', password: '', nickname: '' })
const loading = ref(false)

async function loadFeatures() {
  try {
    const res = await fetch('/api/auth/features')
    const data = await res.json()
    registerEnabled.value = !!data.register_enabled
  } catch {
    registerEnabled.value = false
  }
  if (!registerEnabled.value && route.name === 'register') {
    router.replace({ name: 'login', query: route.query })
  }
}

function toggle() {
  if (!registerEnabled.value) return
  router.push(isRegister.value ? '/login' : '/register')
}

async function submit() {
  loading.value = true
  try {
    const path = isRegister.value ? '/api/auth/register' : '/api/auth/login'
    const body = isRegister.value
      ? {
          username: form.username.trim(),
          password: form.password,
          nickname: form.nickname.trim() || form.username.trim(),
        }
      : { username: form.username.trim(), password: form.password }
    const res = await api(path, {
      method: 'POST',
      body: JSON.stringify(body),
      skipAuth: true,
    })
    saveSession(res.data.access_token, res.data.user)
    router.replace(route.query.redirect || '/workspace')
  } catch (e) {
    showError(e)
  } finally {
    loading.value = false
  }
}

onMounted(loadFeatures)
</script>
