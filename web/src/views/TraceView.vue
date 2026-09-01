<template>
  <section class="kb-page trace-page">
    <header class="kb-top">
      <button class="btn btn-outline btn-sm" type="button" @click="$router.push('/')">← 返回</button>
      <div class="kb-title-block">
        <h1>Trace</h1>
        <p>单次请求耗时与步骤 · 量、成功率、时延与 Token 消耗</p>
      </div>
      <button class="btn btn-outline btn-sm" type="button" @click="load">刷新</button>
    </header>
    <div class="trace-stats" v-if="stats">
      <div class="trace-stat">
        <span>总请求</span>
        <strong>{{ stats.total }}</strong>
      </div>
      <div class="trace-stat">
        <span>成功</span>
        <strong>{{ stats.ok }}</strong>
      </div>
      <div class="trace-stat">
        <span>失败</span>
        <strong>{{ stats.error }}</strong>
      </div>
      <div class="trace-stat">
        <span>停止</span>
        <strong>{{ stats.stopped }}</strong>
      </div>
      <div class="trace-stat">
        <span>成功率</span>
        <strong>{{ stats.success_rate }}%</strong>
      </div>
      <div class="trace-stat">
        <span>平均耗时</span>
        <strong>{{ formatDuration(stats.avg_duration_ms) }}</strong>
      </div>
      <div class="trace-stat">
        <span>P95 耗时</span>
        <strong>{{ formatDuration(stats.p95_duration_ms) }}</strong>
      </div>
      <div class="trace-stat">
        <span>Prompt Tokens</span>
        <strong>{{ formatTokens(stats.prompt_tokens) }}</strong>
      </div>
      <div class="trace-stat">
        <span>Completion Tokens</span>
        <strong>{{ formatTokens(stats.completion_tokens) }}</strong>
      </div>
      <div class="trace-stat">
        <span>总 Tokens</span>
        <strong>{{ formatTokens(stats.total_tokens) }}</strong>
      </div>
    </div>
    <div class="trace-layout">
      <aside class="trace-side">
        <section class="kb-card trace-card">
          <h2>最近 Trace</h2>
          <ul class="trace-list" v-if="traces.length">
            <li
              v-for="t in traces"
              :key="t.id"
              :class="{ active: t.trace_id === selectedId }"
              @click="select(t)"
            >
              <strong>{{ displayName(t.name) }}</strong>
              <small>
                {{ formatDuration(t.duration_ms) }} · {{ t.status }}
                <template v-if="tokenTotal(t)"> · Token {{ formatTokens(tokenTotal(t)) }}</template>
              </small>
            </li>
          </ul>
          <p class="kb-empty" v-else>暂无 Trace</p>
        </section>
      </aside>
      <main class="kb-preview trace-detail">
        <div class="kb-preview-head">
          <div>
            <h2>{{ selected ? displayName(selected.name) : '详情' }}</h2>
            <p v-if="selected" class="kb-preview-doc">
              {{ formatDuration(selected.duration_ms) }} · {{ selected.status }}
              <template v-if="tokenTotal(selected)"> · Token {{ formatTokens(tokenTotal(selected)) }}</template>
              <template v-if="selected.started_at"> · {{ formatTime(selected.started_at) }}</template>
            </p>
          </div>
        </div>
        <div class="kb-preview-scroll">
          <div class="kb-preview-empty" v-if="!selectedId">
            点击左侧一条 Trace，步骤详情会显示在这里。
          </div>
          <p class="kb-empty" v-else-if="loadingDetail">加载中…</p>
          <ol class="kb-chunk-list" v-else-if="detail.length">
            <li v-for="s in detail" :key="s.id">
              <header>
                <span>{{ s.kind }} · {{ displayName(s.name) }}</span>
                <em>{{ formatDuration(s.duration_ms) }}</em>
              </header>
              <pre v-if="s.meta && Object.keys(s.meta).length">{{ JSON.stringify(s.meta, null, 2) }}</pre>
            </li>
          </ol>
          <div class="kb-preview-empty" v-else>该 Trace 暂无步骤明细。</div>
        </div>
      </main>
    </div>
  </section>
</template>

<script setup>
import { inject, onMounted, ref } from 'vue'
import { api } from '../api'

const showError = inject('showError', () => {})
const traces = ref([])
const detail = ref([])
const selectedId = ref('')
const selected = ref(null)
const loadingDetail = ref(false)
const stats = ref(null)

const NAME_LABEL = {
  'multi_agent.run': '多 Agent',
  'chat.stream': '流式对话',
  'agent.run': '超级智能体',
}

function displayName(name) {
  return NAME_LABEL[name] || name || '未命名'
}

function formatDuration(ms) {
  if (ms == null || Number.isNaN(Number(ms))) return '-'
  const n = Number(ms)
  if (n >= 1000) return `${(n / 1000).toFixed(1)} s`
  return `${n} ms`
}

function formatTokens(n) {
  const v = Number(n)
  if (!Number.isFinite(v)) return '0'
  return v.toLocaleString()
}

function tokenTotal(item) {
  const meta = item && item.meta
  if (!meta) return 0
  const total = Number(meta.total_tokens)
  if (Number.isFinite(total) && total > 0) return total
  const prompt = Number(meta.prompt_tokens) || 0
  const completion = Number(meta.completion_tokens) || 0
  return prompt + completion
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString()
}

async function load() {
  try {
    const [listRes, statRes] = await Promise.all([
      api('/api/traces?limit=40'),
      api('/api/traces/stats'),
    ])
    traces.value = listRes.data || []
    stats.value = statRes.data || null
    if (selectedId.value && !traces.value.some((t) => t.trace_id === selectedId.value)) {
      selectedId.value = ''
      selected.value = null
      detail.value = []
    }
  } catch (e) {
    showError(e)
  }
}

async function select(t) {
  selectedId.value = t.trace_id
  selected.value = t
  loadingDetail.value = true
  try {
    const res = await api(`/api/traces/${t.trace_id}`)
    detail.value = res.data || []
  } catch (e) {
    showError(e)
    detail.value = []
  } finally {
    loadingDetail.value = false
  }
}

onMounted(load)
</script>
