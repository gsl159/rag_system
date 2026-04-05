import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 120_000 })

// 请求拦截：自动带 token
http.interceptors.request.use(cfg => {
  const token = localStorage.getItem('rag_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// 响应拦截：统一解构，同时把顶层 trace_id 合并进 data
http.interceptors.response.use(
  r => {
    const body = r.data
    // 标准结构 {code, message, data, trace_id}
    if (body && typeof body === 'object' && 'code' in body && 'data' in body) {
      const result = body.data
      // 把 trace_id 合并到 data 对象，方便页面读取
      if (result && typeof result === 'object' && body.trace_id) {
        result.trace_id = result.trace_id || body.trace_id
      }
      return result
    }
    return body
  },
  e => {
    const detail = e?.response?.data?.message || e?.response?.data?.detail || e.message || '请求失败'
    if (e?.response?.status === 401) {
      localStorage.removeItem('rag_token')
      localStorage.removeItem('rag_user')
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(detail)
  }
)

// ── Auth ─────────────────────────────────────
export const apiLogin   = (username, password) => http.post('/auth/login', { username, password })
export const apiLogout  = ()                   => http.post('/auth/logout')
export const apiMe      = ()                   => http.get('/auth/me')

// ── Chat ─────────────────────────────────────
export const apiChat = (question, session_id) => http.post('/chat/', { question, session_id })
// 修复：SSE 通过 query param 传 token，因为 EventSource 不支持自定义 Header
export const streamUrl = (question) => {
  const token = localStorage.getItem('rag_token') || ''
  return `/api/chat/stream?question=${encodeURIComponent(question)}&token=${encodeURIComponent(token)}`
}

// ── Upload ───────────────────────────────────
export const apiUpload    = (fd)              => http.post('/upload/', fd)
export const apiListDocs  = (skip=0, limit=30)=> http.get('/upload/docs', { params: { skip, limit } })
export const apiGetDoc    = (id)              => http.get(`/upload/docs/${id}`)
export const apiDeleteDoc = (id)              => http.delete(`/upload/docs/${id}`)

// ── Feedback ─────────────────────────────────
export const apiFeedback      = (data) => http.post('/feedback/', data)
export const apiFeedbackStats = ()     => http.get('/feedback/stats')

// ── Metrics ──────────────────────────────────
export const apiOverview     = ()       => http.get('/metrics/overview')
export const apiRagMetrics   = (days=7) => http.get('/metrics/rag', { params: { days } })
export const apiCacheMetrics = ()       => http.get('/metrics/cache')
export const apiDocMetrics   = ()       => http.get('/metrics/docs')
export const apiQPS          = ()       => http.get('/metrics/qps')

// ── Audit ────────────────────────────────────
export const apiAuditLogs = (page=1, limit=20, action='') =>
  http.get('/audit/', { params: { page, limit, action } })

// ── Health（不需要 token，用单独 axios 实例）────
export const apiHealth = () =>
  axios.get('/api/health').then(r => {
    const b = r.data
    return (b && 'data' in b) ? b.data : b
  })
