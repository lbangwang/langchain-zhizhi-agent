/**
 * API 封装：Bearer JWT + 统一错误码解析。
 */
const TOKEN_KEY = 'zhizhi_access_token'
const USER_KEY = 'zhizhi_user'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function saveSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  localStorage.removeItem('zhizhi_chat_id')
  localStorage.removeItem('zhizhi_chat_id_INTERVIEWER')
  localStorage.removeItem('zhizhi_chat_id_MULTI_AGENT')
  localStorage.removeItem('zhizhi_chat_id_SUPER_AGENT')
}

export function loadUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}

export async function api(path, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  }
  const token = getToken()
  if (token && !options.skipAuth) {
    headers.Authorization = `Bearer ${token}`
  }
  const resp = await fetch(path, { ...options, headers })
  const data = await resp.json().catch(() => null)
  if (resp.status === 401) {
    clearSession()
    const err = new Error((data && data.detail) || '未登录或 token 无效')
    err.code = 'UNAUTHORIZED'
    throw err
  }
  if (!resp.ok) {
    const detail = data && data.detail
    if (detail && typeof detail === 'object' && detail.code) {
      const err = new Error(detail.message || detail.code)
      err.code = detail.code
      err.quota = detail.quota
      throw err
    }
    const msg =
      (typeof detail === 'string' && detail) ||
      (data && data.message) ||
      `HTTP ${resp.status}`
    const err = new Error(msg)
    err.code = data?.code || 'HTTP_ERROR'
    throw err
  }
  if (data && typeof data.code === 'number' && data.code !== 0) {
    const err = new Error(data.message || '业务失败')
    err.code = String(data.code)
    throw err
  }
  return data
}

export function formatError(err) {
  if (!err) return ''
  return err.code ? `[${err.code}] ${err.message}` : err.message || String(err)
}
