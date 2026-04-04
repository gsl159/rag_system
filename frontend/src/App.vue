<template>
  <!-- 登录页不显示侧边栏 -->
  <div v-if="$route.path === '/login'" class="login-layout">
    <router-view/>
  </div>

  <!-- 主布局 -->
  <div v-else class="shell">
    <aside class="sidebar">
      <!-- Logo -->
      <div class="brand">
        <div class="brand-icon">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
        </div>
        <span class="brand-name">RAG 知识库</span>
      </div>

      <!-- Nav -->
      <nav class="nav">
        <div class="nav-group-label">主功能</div>
        <router-link to="/"        class="nav-link" active-class="nav-link--active" exact-active-class="nav-link--active">
          <IconChat class="nav-icon"/> 智能问答
        </router-link>
        <router-link to="/docs"    class="nav-link" active-class="nav-link--active">
          <IconDocs class="nav-icon"/> 文档管理
        </router-link>

        <div class="nav-group-label" style="margin-top:12px">运营</div>
        <router-link to="/metrics"  class="nav-link" active-class="nav-link--active">
          <IconMetrics class="nav-icon"/> 监控大盘
        </router-link>
        <router-link to="/feedback" class="nav-link" active-class="nav-link--active">
          <IconFeedback class="nav-icon"/> 用户反馈
        </router-link>

        <div class="nav-group-label" style="margin-top:12px">系统</div>
        <router-link to="/audit" class="nav-link" active-class="nav-link--active">
          <IconAudit class="nav-icon"/> 审计日志
        </router-link>
      </nav>

      <!-- User -->
      <div class="sidebar-footer">
        <div class="user-row">
          <div class="user-avatar">{{ userInitial }}</div>
          <div class="user-info">
            <div class="user-name">{{ userName }}</div>
            <div class="user-role">{{ userRole }}</div>
          </div>
          <button class="logout-btn" @click="logout" title="退出登录">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
          </button>
        </div>
        <div class="health-row">
          <span class="health-dot" :class="healthy?'ok':'err'"></span>
          <span class="health-label">{{ healthy ? '服务正常' : '连接异常' }}</span>
        </div>
      </div>
    </aside>

    <main class="main-content">
      <router-view/>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { apiHealth, apiLogout } from '@/api/index.js'

const router  = useRouter()
const healthy = ref(true)

// 读取本地存储的用户信息
const userInfo = computed(() => {
  try { return JSON.parse(localStorage.getItem('rag_user') || '{}') }
  catch { return {} }
})
const userName    = computed(() => userInfo.value.username || '用户')
const userInitial = computed(() => (userInfo.value.username || 'U').charAt(0).toUpperCase())
const userRole    = computed(() => ({ super_admin:'超级管理员', admin:'管理员', user:'普通用户' }[userInfo.value.role] || '用户'))

onMounted(async () => {
  try { await apiHealth(); healthy.value = true }
  catch { healthy.value = false }
  setInterval(async () => {
    try { await apiHealth(); healthy.value = true }
    catch { healthy.value = false }
  }, 30000)
})

async function logout() {
  try { await apiLogout() } catch {}
  localStorage.removeItem('rag_token')
  localStorage.removeItem('rag_user')
  router.push('/login')
}

// 内联 SVG 图标组件
const IconChat     = { template: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2 3h12M2 7h8M2 11h6"/></svg>` }
const IconDocs     = { template: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="1" width="12" height="14" rx="1.5"/><path d="M5 5h6M5 8h4"/></svg>` }
const IconMetrics  = { template: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2 13V9l3-3 3 3 4-4v8"/></svg>` }
const IconFeedback = { template: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M8 1l1.9 3.8L14 5.6l-3 2.9.7 4.1L8 10.4l-3.7 2.2.7-4.1L2 5.6l4.1-.8z"/></svg>` }
const IconAudit    = { template: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="2" width="12" height="12" rx="2"/><path d="M5 8h6M5 5h3M5 11h4"/></svg>` }
</script>

<style>
html, body, #app { height: 100%; }
</style>

<style scoped>
.login-layout { height: 100%; }

.shell {
  display: flex; height: 100vh; overflow: hidden;
  background: var(--bg);
}

/* ── Sidebar ── */
.sidebar {
  width: 200px; min-width: 200px;
  background: var(--bg-card);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column;
}
.brand {
  display: flex; align-items: center; gap: 9px;
  padding: 18px 16px;
  border-bottom: 1px solid var(--border);
}
.brand-icon {
  width: 28px; height: 28px; background: var(--accent);
  border-radius: 7px; display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.brand-name { font-size: 14px; font-weight: 700; color: var(--text-1); }

.nav { flex: 1; padding: 10px 8px; display: flex; flex-direction: column; gap: 1px; overflow-y: auto; }
.nav-group-label {
  font-size: 10px; font-weight: 600; color: var(--text-3);
  letter-spacing: .06em; padding: 6px 8px 4px;
  text-transform: uppercase;
}
.nav-link {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 10px; border-radius: var(--r-sm);
  color: var(--text-2); text-decoration: none;
  font-size: 13px; transition: all .15s;
}
.nav-link:hover           { background: var(--bg-hover); color: var(--text-1); }
.nav-link--active         { background: var(--accent-bg); color: var(--accent); font-weight: 500; }
.nav-icon { width: 15px; height: 15px; flex-shrink: 0; opacity: .7; }
.nav-link--active .nav-icon { opacity: 1; }

.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--border);
  display: flex; flex-direction: column; gap: 8px;
}
.user-row {
  display: flex; align-items: center; gap: 8px;
}
.user-avatar {
  width: 28px; height: 28px; border-radius: 50%;
  background: var(--accent); color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; flex-shrink: 0;
}
.user-info { flex: 1; min-width: 0; }
.user-name { font-size: 12px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.user-role { font-size: 10px; color: var(--text-3); }
.logout-btn {
  background: none; border: none; cursor: pointer;
  color: var(--text-3); padding: 3px; border-radius: 4px;
  display: flex; transition: color .15s;
}
.logout-btn:hover { color: var(--red); }
.health-row { display: flex; align-items: center; gap: 6px; }
.health-dot { width: 6px; height: 6px; border-radius: 50%; }
.health-dot.ok  { background: var(--green); box-shadow: 0 0 4px var(--green); }
.health-dot.err { background: var(--red); }
.health-label { font-size: 11px; color: var(--text-3); }

/* ── Main ── */
.main-content { flex: 1; overflow: hidden; display: flex; flex-direction: column; }
</style>
