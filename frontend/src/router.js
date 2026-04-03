import { createRouter, createWebHistory } from 'vue-router'
import Chat     from '@/pages/Chat.vue'
import Docs     from '@/pages/Docs.vue'
import Metrics  from '@/pages/Metrics.vue'
import Feedback from '@/pages/Feedback.vue'

const routes = [
  { path: '/',         component: Chat,     meta: { title: '智能问答',  icon: '💬' } },
  { path: '/docs',     component: Docs,     meta: { title: '文档管理',  icon: '📄' } },
  { path: '/metrics',  component: Metrics,  meta: { title: '监控大盘',  icon: '📊' } },
  { path: '/feedback', component: Feedback, meta: { title: '用户反馈',  icon: '👍' } },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
