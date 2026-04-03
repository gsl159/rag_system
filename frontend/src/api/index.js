import axios from 'axios'

const http = axios.create({
  baseURL: '/api',
  timeout: 120_000,
})

// 响应拦截：统一提取 data
http.interceptors.response.use(
  r  => r.data,
  e  => Promise.reject(e?.response?.data?.detail || e.message || '请求失败')
)

// ── Chat ─────────────────────────────────────
export const apiChat        = (question, session_id) => http.post('/chat/', { question, session_id })
export const streamUrl      = (question) => `/api/chat/stream?question=${encodeURIComponent(question)}`

// ── Upload ───────────────────────────────────
export const apiUpload      = (formData)  => http.post('/upload/', formData)
export const apiListDocs    = (skip=0, limit=30) => http.get('/upload/docs', { params: { skip, limit } })
export const apiDeleteDoc   = (id)        => http.delete(`/upload/docs/${id}`)

// ── Feedback ─────────────────────────────────
export const apiFeedback    = (data)      => http.post('/feedback/', data)
export const apiFeedbackStats = ()        => http.get('/feedback/stats')

// ── Metrics ──────────────────────────────────
export const apiOverview    = ()          => http.get('/metrics/overview')
export const apiRagMetrics  = (days=7)   => http.get('/metrics/rag',   { params: { days } })
export const apiCacheMetrics= ()          => http.get('/metrics/cache')
export const apiDocMetrics  = ()          => http.get('/metrics/docs')
export const apiQPS         = ()          => http.get('/metrics/qps')
