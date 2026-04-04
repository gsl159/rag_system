<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">审计日志</div>
      <div class="page-sub">操作记录 · 登录追踪 · 安全审计</div>
    </div>
    <div class="page-body">
      <div class="card">
        <!-- 过滤栏 -->
        <div class="filter-row">
          <select v-model="filterAction" class="input-base filter-sel" @change="load">
            <option value="">全部操作</option>
            <option value="login">登录</option>
            <option value="login_fail">登录失败</option>
            <option value="query">查询</option>
            <option value="upload">上传</option>
            <option value="delete_doc">删除文档</option>
          </select>
          <button class="btn btn-ghost btn-sm" @click="load">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>
            刷新
          </button>
          <span class="total-info" v-if="total">共 {{ total }} 条</span>
        </div>

        <div v-if="loading" class="empty-row"><span class="dots"><span/><span/><span/></span></div>
        <div v-else-if="!items.length" class="empty-row">暂无日志</div>
        <table v-else class="data-table" style="margin-top:12px">
          <thead>
            <tr><th>时间</th><th>用户</th><th>操作</th><th>资源</th><th>IP</th><th>Trace ID</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.id">
              <td class="time-col">{{ fmtDate(item.created_at) }}</td>
              <td>{{ item.username || item.user_id || '-' }}</td>
              <td><span class="action-tag" :class="actionClass(item.action)">{{ actionLabel(item.action) }}</span></td>
              <td class="resource-col" :title="item.resource">{{ (item.resource||'-').slice(0,30) }}</td>
              <td class="mono-col">{{ item.ip || '-' }}</td>
              <td class="trace-col">{{ item.trace_id || '-' }}</td>
            </tr>
          </tbody>
        </table>

        <!-- 分页 -->
        <div class="pager" v-if="total > limit">
          <button class="btn btn-ghost btn-sm" :disabled="page<=1" @click="page--;load()">上一页</button>
          <span class="page-info">第 {{ page }} / {{ Math.ceil(total/limit) }} 页</span>
          <button class="btn btn-ghost btn-sm" :disabled="page>=Math.ceil(total/limit)" @click="page++;load()">下一页</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { apiAuditLogs } from '@/api/index.js'

const items        = ref([])
const total        = ref(0)
const loading      = ref(false)
const page         = ref(1)
const limit        = ref(20)
const filterAction = ref('')

async function load() {
  loading.value = true
  try {
    const data = await apiAuditLogs(page.value, limit.value, filterAction.value)
    items.value = data.items || []
    total.value = data.total || 0
  } catch {} finally { loading.value = false }
}

onMounted(load)

const actionLabel = a => ({ login:'登录', login_fail:'登录失败', query:'查询', upload:'上传', delete_doc:'删除文档' }[a] || a)
const actionClass = a => ({ login:'tag-green', login_fail:'tag-red', query:'tag-blue', upload:'tag-yellow', delete_doc:'tag-red' }[a] || 'tag-gray')

function fmtDate(s) {
  if (!s) return '-'
  return new Date(s).toLocaleString('zh-CN', { month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false })
}
</script>

<style scoped>
.filter-row { display:flex; align-items:center; gap:10px; margin-bottom:4px; }
.filter-sel { width:140px; }
.total-info { margin-left:auto; font-size:12px; color:var(--text-3); }
.empty-row  { padding:40px; text-align:center; color:var(--text-3); font-size:13px; }
.time-col     { font-size:11px; color:var(--text-3); white-space:nowrap; }
.resource-col { max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.mono-col   { font-family:monospace; font-size:11px; color:var(--text-3); }
.trace-col  { font-family:monospace; font-size:11px; color:var(--text-3); }
.action-tag { display:inline-flex; align-items:center; padding:2px 7px; border-radius:4px; font-size:11px; font-weight:600; }
.tag-green  { background:var(--green-bg); color:var(--green); }
.tag-red    { background:var(--red-bg); color:var(--red); }
.tag-blue   { background:var(--blue-bg); color:var(--accent); }
.tag-yellow { background:var(--yellow-bg); color:var(--yellow); }
.tag-gray   { background:var(--bg-hover); color:var(--text-2); }
.pager { display:flex; align-items:center; gap:10px; justify-content:center; padding-top:16px; border-top:1px solid var(--border); margin-top:12px; }
.page-info { font-size:12px; color:var(--text-3); }
</style>
