/** 前端可选大模型，value 与后端 model 参数一致（Key 取自服务端 .env） */
export const MODEL_OPTIONS = [
  { id: 'qwen', label: '千问' },
  { id: 'doubao', label: '豆包' },
  { id: 'deepseek', label: 'DeepSeek' },
]

export const DEFAULT_MODEL = 'qwen'

export const MODEL_STORAGE_KEY = 'zhizhi_selected_model'

export function loadSelectedModel() {
  try {
    const v = localStorage.getItem(MODEL_STORAGE_KEY) || ''
    if (MODEL_OPTIONS.some((m) => m.id === v)) return v
  } catch {
    /* ignore */
  }
  return DEFAULT_MODEL
}

export function saveSelectedModel(id) {
  try {
    localStorage.setItem(MODEL_STORAGE_KEY, id)
  } catch {
    /* ignore */
  }
}
