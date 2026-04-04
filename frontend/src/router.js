import { createRouter, createWebHistory } from 'vue-router'
import Login    from '@/pages/Login.vue'
import Chat     from '@/pages/Chat.vue'
import Docs     from '@/pages/Docs.vue'
import Metrics  from '@/pages/Metrics.vue'
import Feedback from '@/pages/Feedback.vue'
import Audit    from '@/pages/Audit.vue'

const routes = [
  { path: '/login', component: Login, meta: { public: true } },
  { path: '/',         component: Chat,     meta: { title:'智能问答', icon:'chat' } },
  { path: '/docs',     component: Docs,     meta: { title:'文档管理', icon:'docs' } },
  { path: '/metrics',  component: Metrics,  meta: { title:'监控大盘', icon:'metrics' } },
  { path: '/feedback', component: Feedback, meta: { title:'用户反馈', icon:'feedback' } },
  { path: '/audit',    component: Audit,    meta: { title:'审计日志', icon:'audit' } },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const token = localStorage.getItem('rag_token')
  if (!to.meta.public && !token) return '/login'
})

export default router
