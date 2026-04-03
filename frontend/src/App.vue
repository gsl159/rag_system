<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-icon">🧠</span>
        <span class="brand-name">RAG System</span>
      </div>

      <nav class="nav">
        <router-link
          v-for="r in routes"
          :key="r.path"
          :to="r.path"
          class="nav-link"
          active-class="nav-link--active"
          exact-active-class="nav-link--active"
        >
          <span class="nav-icon">{{ r.meta.icon }}</span>
          <span>{{ r.meta.title }}</span>
        </router-link>
      </nav>

      <div class="sidebar-bottom">
        <div class="health-dot" :class="healthy ? 'ok' : 'err'" />
        <span style="font-size:11px;color:var(--text-3)">
          {{ healthy ? '服务正常' : '连接异常' }}
        </span>
      </div>
    </aside>

    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter }      from 'vue-router'
import { apiOverview }    from '@/api/index.js'

const router  = useRouter()
const routes  = router.options.routes
const healthy = ref(true)

onMounted(async () => {
  try { await apiOverview(); healthy.value = true }
  catch { healthy.value = false }
})
</script>

<style scoped>
.layout {
  display: flex; height: 100vh; overflow: hidden;
}

/* ── Sidebar ── */
.sidebar {
  width: 210px; min-width: 210px;
  background: var(--bg-card);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column;
}
.brand {
  display: flex; align-items: center; gap: 10px;
  padding: 20px 18px;
  border-bottom: 1px solid var(--border);
}
.brand-icon { font-size: 22px; }
.brand-name { font-size: 15px; font-weight: 700; color: var(--accent-2); }

.nav { flex: 1; padding: 12px 10px; display: flex; flex-direction: column; gap: 3px; }
.nav-link {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: var(--radius-md);
  color: var(--text-2); text-decoration: none;
  font-size: 14px; transition: all .18s;
}
.nav-link:hover           { background: var(--bg-hover); color: var(--text-1); }
.nav-link--active         { background: var(--bg-active); color: var(--accent-2); font-weight: 600; }
.nav-icon { font-size: 16px; }

.sidebar-bottom {
  padding: 14px 18px;
  border-top: 1px solid var(--border);
  display: flex; align-items: center; gap: 8px;
}
.health-dot {
  width: 8px; height: 8px; border-radius: 50%;
}
.health-dot.ok  { background: var(--green); box-shadow: 0 0 6px var(--green); }
.health-dot.err { background: var(--red);   box-shadow: 0 0 6px var(--red); }

/* ── Main ── */
.main-content { flex: 1; overflow: hidden; display: flex; flex-direction: column; }
</style>
