<template>
  <section class="kb-page">
    <header class="kb-top">
      <button class="btn btn-outline btn-sm" type="button" @click="$router.push('/')">← 返回</button>
      <div class="kb-title-block">
        <h1>知识库</h1>
        <p>选文件或粘贴文本 → 调参预览 → 确认入库 → 对话中引用</p>
      </div>
      <button class="btn btn-outline btn-sm" type="button" :disabled="kbLoading" @click="refreshKnowledge">
        刷新
      </button>
    </header>

    <div class="kb-layout" :class="{ 'has-preview': previewOpen }">
      <aside class="kb-side" ref="sideRef">
        <section class="kb-card">
          <h2><span class="step">1</span> 上传 / 粘贴</h2>
          <div class="kb-source-tabs">
            <button type="button" :class="{ active: kbSource === 'paste' }" @click="kbSource = 'paste'">
              粘贴文本
            </button>
            <button type="button" :class="{ active: kbSource === 'file' }" @click="kbSource = 'file'">
              上传文件
            </button>
          </div>

          <template v-if="kbSource === 'paste'">
            <label class="kb-field">
              标题（可选）
              <input v-model="kbFilename" placeholder="例如：青甘大环线攻略.txt" />
            </label>
            <label class="kb-field">
              文本内容
              <textarea v-model="kbText" rows="8" placeholder="把文档内容粘贴到这里…" />
            </label>
          </template>
          <template v-else>
            <label class="kb-drop" @dragover.prevent @drop.prevent="onKbFileDrop">
              <input
                type="file"
                accept=".txt,.md,.csv,.json,.markdown,.pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                hidden
                @change="onKbFilePick"
              />
              <strong v-if="kbFileName">{{ kbFileName }}</strong>
              <template v-else>
                <strong>拖拽文件到此处，或点击选择</strong>
                <span>支持 .md / .txt / .pdf / .docx 等，≤10MB</span>
              </template>
            </label>
            <label class="kb-field">
              标题（可选，默认用文件名）
              <input v-model="kbFilename" placeholder="留空则使用文件名" />
            </label>
          </template>

          <div class="kb-strategy">
            <label class="kb-field">
              分割策略
              <select v-model="kbStrategy" @change="onKbStrategyChange">
                <option v-for="s in kbStrategies" :key="s.id" :value="s.id">
                  {{ s.name }}{{ s.badge ? '（' + s.badge + '）' : '' }}
                </option>
              </select>
            </label>
            <p class="kb-strategy-desc" v-if="kbCurrentStrategy">
              {{ kbCurrentStrategy.summary }}
              <span v-if="kbCurrentStrategy.suitable">适合：{{ kbCurrentStrategy.suitable }}</span>
            </p>
          </div>

          <div class="kb-params" v-if="kbCurrentStrategy && kbCurrentStrategy.params">
            <label v-for="p in kbCurrentStrategy.params" :key="p.key">
              {{ p.label }}
              <input
                type="number"
                v-model.number="kbParams[p.key]"
                :min="p.min"
                :max="p.max"
                :step="p.step || 1"
              />
              <small v-if="p.hint">{{ p.hint }}</small>
            </label>
          </div>

          <div class="kb-actions">
            <button class="btn btn-outline btn-sm" type="button" :disabled="kbLoading" @click="previewKb">
              重新预览
            </button>
            <button class="btn btn-primary btn-sm" type="button" :disabled="kbLoading" @click="confirmKbIngest">
              {{ kbLoading ? '处理中…' : '确认入库' }}
            </button>
          </div>
          <p v-if="stagingHint" class="kb-staging-hint">{{ stagingHint }}</p>
        </section>

        <section class="kb-card">
          <h2><span class="step">2</span> 文档</h2>
          <ul class="kb-doc-list" v-if="kbDocs.length">
            <li v-for="d in kbDocs" :key="d.id">
              <div>
                <strong>{{ d.filename }}</strong>
                <small>{{ d.char_count }} 字 · {{ d.chunk_count }} 切片 · {{ formatTime(d.create_date) }}</small>
              </div>
              <div class="kb-doc-actions">
                <button
                  type="button"
                  class="linkish"
                  :class="{ active: previewOpen && previewDocId === d.id }"
                  @click="toggleKbChunks(d)"
                >
                  {{ previewOpen && previewDocId === d.id ? '收起' : '切片' }}
                </button>
                <button type="button" class="del" @click="deleteKb(d.id)">删</button>
              </div>
            </li>
          </ul>
          <p class="kb-empty" v-else>暂无文档，先上传或粘贴文本入库。</p>
        </section>

        <section class="kb-card">
          <h2><span class="step">3</span> 试检索</h2>
          <label class="kb-field">
            <input
              v-model="kbSearchQuery"
              placeholder="例如：文档里提到的 MCP 是什么？"
              @keydown.enter.prevent="runKbSearch"
            />
          </label>
          <button class="btn btn-primary btn-sm" type="button" :disabled="kbSearching" @click="runKbSearch">
            {{ kbSearching ? '检索中…' : '检索' }}
          </button>
          <div class="kb-hit-scroll" v-if="kbHits.length">
            <ul class="kb-hit-list">
              <li v-for="(h, i) in kbHits" :key="i">
                <div class="kb-hit-meta">
                  <strong>{{ h.filename }}</strong>
                  <em>score {{ h.score }} · #{{ h.chunk_index }}</em>
                </div>
                <p class="kb-hit-text">{{ h.text }}</p>
              </li>
            </ul>
          </div>
        </section>
      </aside>

      <main
        v-if="previewOpen"
        class="kb-preview"
        :style="previewStyle"
      >
        <div class="kb-preview-head">
          <div>
            <h2>切片预览</h2>
            <p v-if="previewDocName" class="kb-preview-doc">{{ previewDocName }}</p>
          </div>
          <div class="kb-preview-head-actions">
            <span v-if="kbPreview.chunk_count">{{ kbPreview.chunk_count }} 片 · {{ kbPreview.char_count }} 字</span>
            <button type="button" class="btn btn-outline btn-sm" @click="closePreview">收起</button>
          </div>
        </div>
        <div class="kb-preview-scroll">
          <div class="kb-preview-empty" v-if="!kbPreview.chunks || !kbPreview.chunks.length">
            暂无切片内容。
          </div>
          <ol class="kb-chunk-list" v-else>
            <li v-for="c in kbPreview.chunks" :key="c.index">
              <header>
                <span>#{{ c.index }}</span>
                <em>{{ c.chars }} 字</em>
              </header>
              <pre>{{ c.text }}</pre>
            </li>
          </ol>
        </div>
      </main>
    </div>
  </section>
</template>

<script setup>
import { computed, inject, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { api, getToken } from '../api'

const showError = inject('showError', () => {})

const kbSource = ref('paste')
const kbDocs = ref([])
const kbFilename = ref('')
const kbText = ref('')
const kbFile = ref(null)
const kbFileName = ref('')
const kbStrategy = ref('recursive')
const kbStrategies = ref([])
const kbParams = reactive({ chunk_size: 800, chunk_overlap: 120 })
const kbLoading = ref(false)
const kbPreview = ref({ filename: '', char_count: 0, chunk_count: 0, chunks: [] })
const kbSearchQuery = ref('')
const kbHits = ref([])
const kbSearching = ref(false)

/** 仅在点击文档「切片」时展开右侧预览；收起后不占位 */
const previewOpen = ref(false)
const previewDocId = ref('')
const previewDocName = ref('')
const stagingHint = ref('')
const sideRef = ref(null)
const previewHeight = ref(null)
let sideObserver = null

const previewStyle = computed(() => {
  if (!previewHeight.value) return undefined
  return { height: `${previewHeight.value}px` }
})

function syncPreviewHeight() {
  const side = sideRef.value
  if (!side) return
  const h = Math.round(side.getBoundingClientRect().height)
  if (h > 0) previewHeight.value = h
}

function closePreview() {
  previewOpen.value = false
  previewDocId.value = ''
  previewDocName.value = ''
  kbPreview.value = { filename: '', char_count: 0, chunk_count: 0, chunks: [] }
}

const KB_STRATEGY_FALLBACK = [
  {
    id: 'recursive',
    name: '智能递归切分',
    badge: '推荐',
    summary: '按段落→句子→字词逐级切开，企业知识库最常用。',
    suitable: '通用制度、说明书、FAQ',
    params: [
      { key: 'chunk_size', label: '单块最大字数', default: 800, min: 100, max: 4000, step: 50, hint: '越大上下文越完整' },
      { key: 'chunk_overlap', label: '块间重叠字数', default: 120, min: 0, max: 800, step: 10, hint: '避免句子被截断' },
    ],
  },
  {
    id: 'paragraph',
    name: '按自然段落切分',
    badge: '',
    summary: '按空行分段并合并短段，适合公文叙述。',
    suitable: '规章制度、会议纪要',
    params: [
      { key: 'chunk_size', label: '段落合并上限（字）', default: 1000, min: 100, max: 4000, step: 50, hint: '' },
      { key: 'chunk_overlap', label: '短段合并阈值（字）', default: 80, min: 0, max: 500, step: 10, hint: '' },
    ],
  },
  {
    id: 'markdown',
    name: '按标题结构切分',
    badge: '',
    summary: '按标题切开后再切长章节，适合手册类文档。',
    suitable: '产品手册、技术方案',
    params: [
      { key: 'chunk_size', label: '章节内块大小（字）', default: 900, min: 100, max: 4000, step: 50, hint: '' },
      { key: 'chunk_overlap', label: '章节内重叠（字）', default: 100, min: 0, max: 800, step: 10, hint: '' },
    ],
  },
  {
    id: 'window',
    name: '按固定长度切分',
    badge: '',
    summary: '固定字数滑动窗口，规则简单。',
    suitable: '日志、流水文本',
    params: [
      { key: 'chunk_size', label: '每块字数', default: 500, min: 50, max: 3000, step: 50, hint: '' },
      { key: 'chunk_overlap', label: '滑动重叠字数', default: 50, min: 0, max: 500, step: 10, hint: '' },
    ],
  },
  {
    id: 'token',
    name: '按模型 Token 切分',
    badge: '进阶',
    summary: '按大模型 token 预算切块。',
    suitable: '严格控制上下文成本',
    params: [
      { key: 'chunk_size', label: '每块 Token 数', default: 400, min: 50, max: 2000, step: 20, hint: '' },
      { key: 'chunk_overlap', label: '重叠 Token 数', default: 40, min: 0, max: 400, step: 10, hint: '' },
    ],
  },
]

const kbCurrentStrategy = computed(() => {
  const list = kbStrategies.value || []
  return list.find((s) => s.id === kbStrategy.value) || list[0] || null
})

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString()
}

function applyStrategyDefaults(strategyId) {
  const meta =
    (kbStrategies.value || []).find((s) => s.id === strategyId) ||
    KB_STRATEGY_FALLBACK.find((s) => s.id === strategyId) ||
    KB_STRATEGY_FALLBACK[0]
  ;(meta.params || []).forEach((p) => {
    kbParams[p.key] = p.default
  })
}

function onKbStrategyChange() {
  applyStrategyDefaults(kbStrategy.value)
}

function kbChunkSizeValue() {
  return Number(kbParams.chunk_size) || 800
}

function kbOverlapValue() {
  return Number(kbParams.chunk_overlap) || 0
}

async function loadKb() {
  const res = await api('/api/knowledge')
  kbDocs.value = res.data || []
}

async function refreshKnowledge() {
  try {
    await loadKb()
    try {
      const res = await api('/api/knowledge/strategies')
      kbStrategies.value = res.data?.length ? res.data : KB_STRATEGY_FALLBACK
    } catch {
      kbStrategies.value = KB_STRATEGY_FALLBACK
    }
    if (!kbStrategies.value.some((s) => s.id === kbStrategy.value)) {
      kbStrategy.value = kbStrategies.value[0].id
    }
    const meta = kbStrategies.value.find((s) => s.id === kbStrategy.value)
    if (meta) {
      ;(meta.params || []).forEach((p) => {
        if (kbParams[p.key] == null) kbParams[p.key] = p.default
      })
    }
  } catch (e) {
    showError(e)
  }
}

async function resolveKbContent() {
  if (kbSource.value === 'file') {
    if (!kbFile.value) throw new Error('请先选择文件')
    const name = kbFilename.value.trim() || kbFile.value.name || kbFileName.value || 'upload.txt'
    return { filename: name }
  }
  const content = kbText.value.trim()
  if (!content) throw new Error('请粘贴文本内容')
  return { content, filename: kbFilename.value.trim() || 'note.txt' }
}

async function previewKb() {
  kbLoading.value = true
  stagingHint.value = ''
  try {
    let res
    if (kbSource.value === 'file') {
      if (!kbFile.value) throw new Error('请先选择文件')
      const form = new FormData()
      form.append('file', kbFile.value)
      form.append('strategy', kbStrategy.value)
      form.append('chunk_size', String(kbChunkSizeValue()))
      form.append('chunk_overlap', String(kbOverlapValue()))
      const resp = await fetch('/api/knowledge/preview-file', {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}` },
        body: form,
      })
      const data = await resp.json().catch(() => null)
      if (!resp.ok || (data && data.code !== 0)) {
        throw new Error((data && data.message) || '预览失败')
      }
      res = data
    } else {
      const { content, filename } = await resolveKbContent()
      res = await api('/api/knowledge/preview', {
        method: 'POST',
        body: JSON.stringify({
          content,
          filename,
          strategy: kbStrategy.value,
          chunk_size: kbChunkSizeValue(),
          chunk_overlap: kbOverlapValue(),
        }),
      })
    }
    kbPreview.value = res.data || { chunks: [] }
    const count = kbPreview.value.chunk_count ?? kbPreview.value.chunks?.length ?? 0
    stagingHint.value = `预览完成：约 ${count} 片。入库后请在文档列表点「切片」查看。`
  } catch (e) {
    showError(e)
  } finally {
    kbLoading.value = false
  }
}

async function confirmKbIngest() {
  kbLoading.value = true
  stagingHint.value = ''
  try {
    let data = null
    if (kbSource.value === 'file') {
      if (!kbFile.value) throw new Error('请先选择文件')
      const form = new FormData()
      form.append('file', kbFile.value)
      form.append('strategy', kbStrategy.value)
      form.append('chunk_size', String(kbChunkSizeValue()))
      form.append('chunk_overlap', String(kbOverlapValue()))
      const resp = await fetch('/api/knowledge/upload', {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}` },
        body: form,
      })
      data = await resp.json().catch(() => null)
      if (!resp.ok || (data && data.code !== 0)) {
        throw new Error((data && data.message) || '入库失败')
      }
    } else {
      const { content, filename } = await resolveKbContent()
      const form = new FormData()
      form.append('filename', filename)
      form.append('content', content)
      form.append('strategy', kbStrategy.value)
      form.append('chunk_size', String(kbChunkSizeValue()))
      form.append('chunk_overlap', String(kbOverlapValue()))
      const resp = await fetch('/api/knowledge/upload-text', {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}` },
        body: form,
      })
      data = await resp.json().catch(() => null)
      if (!resp.ok || (data && data.code !== 0)) {
        throw new Error((data && data.message) || '入库失败')
      }
    }
    kbText.value = ''
    kbFile.value = null
    kbFileName.value = ''
    await loadKb()
    stagingHint.value = '入库成功。在文档列表点击「切片」可预览切块。'
    // 入库后不自动打开右侧预览，需用户点「切片」
  } catch (e) {
    showError(e)
  } finally {
    kbLoading.value = false
  }
}

function onKbFilePick(e) {
  const file = e.target.files && e.target.files[0]
  if (!file) return
  kbFile.value = file
  kbFileName.value = file.name
  if (!kbFilename.value) kbFilename.value = file.name
}

function onKbFileDrop(e) {
  const file = e.dataTransfer?.files?.[0]
  if (!file) return
  kbFile.value = file
  kbFileName.value = file.name
  if (!kbFilename.value) kbFilename.value = file.name
  kbSource.value = 'file'
}

async function toggleKbChunks(doc) {
  // 同一文档再点「收起」：关闭右侧预览
  if (previewOpen.value && previewDocId.value === doc.id) {
    closePreview()
    return
  }
  try {
    const res = await api(`/api/knowledge/${doc.id}/chunks`)
    kbPreview.value = res.data || { chunks: [] }
    previewDocId.value = doc.id
    previewDocName.value = doc.filename || ''
    previewOpen.value = true
    await nextTick()
    syncPreviewHeight()
  } catch (e) {
    showError(e)
  }
}

async function runKbSearch() {
  const q = kbSearchQuery.value.trim()
  if (!q) {
    showError(new Error('请输入检索问题'))
    return
  }
  kbSearching.value = true
  try {
    const res = await api('/api/knowledge/search', {
      method: 'POST',
      body: JSON.stringify({ query: q, top_k: 5 }),
    })
    kbHits.value = res.data || []
    if (!kbHits.value.length) showError(new Error('无命中，可先入库文档再试'))
  } catch (e) {
    showError(e)
  } finally {
    kbSearching.value = false
  }
}

async function deleteKb(id) {
  if (!confirm('删除该知识库文档？')) return
  try {
    await api(`/api/knowledge/${id}`, { method: 'DELETE' })
    await loadKb()
    if (previewDocId.value === id) closePreview()
  } catch (e) {
    showError(e)
  }
}

onMounted(() => {
  refreshKnowledge()
  nextTick(() => {
    syncPreviewHeight()
    if (typeof ResizeObserver !== 'undefined' && sideRef.value) {
      sideObserver = new ResizeObserver(() => syncPreviewHeight())
      sideObserver.observe(sideRef.value)
    }
    window.addEventListener('resize', syncPreviewHeight)
  })
})

onUnmounted(() => {
  sideObserver?.disconnect()
  window.removeEventListener('resize', syncPreviewHeight)
})
</script>
