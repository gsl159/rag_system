<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">文档管理</div>
      <div class="page-sub">上传 PDF / Word / HTML / TXT，自动解析入库</div>
    </div>
    <div class="page-body">

      <!-- Upload zone -->
      <div class="upload-zone card" :class="{dragging}" @click="$refs.fileInput.click()"
        @dragover.prevent="dragging=true" @dragleave.prevent="dragging=false" @drop.prevent="onDrop">
        <input ref="fileInput" type="file" style="display:none" multiple
          accept=".pdf,.docx,.doc,.html,.htm,.txt,.md" @change="onFileChange"/>
        <div class="upload-icon">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
        </div>
        <p class="upload-title">拖拽或点击上传文件</p>
        <p class="upload-hint">支持 .pdf .docx .html .txt .md · 单文件 ≤ 50MB</p>
      </div>

      <!-- Upload queue -->
      <div v-if="queue.length" class="card" style="margin-top:14px">
        <div class="section-hd">上传队列</div>
        <div v-for="(item,i) in queue" :key="i" class="queue-row">
          <div class="q-icon" :class="item.status">
            <span v-if="item.status==='uploading'" class="dots"><span/><span/><span/></span>
            <svg v-else-if="item.status==='ok'" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
            <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </div>
          <span class="q-name">{{ item.name }}</span>
          <span class="badge" :class="{'badge-blue':item.status==='uploading','badge-green':item.status==='ok','badge-red':item.status==='error'}">
            {{ {uploading:'上传中',ok:'已提交',error:'失败'}[item.status] }}
          </span>
          <span v-if="item.error" class="q-err">{{ item.error }}</span>
        </div>
      </div>

      <!-- Docs list -->
      <div class="card" style="margin-top:14px">
        <div class="list-header">
          <span class="section-hd" style="margin:0">文档列表 <span class="count-badge">{{ docs.length }}</span></span>
          <button class="btn btn-ghost btn-sm" @click="loadDocs">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>
            刷新
          </button>
        </div>

        <div v-if="docsLoading" class="empty-row"><span class="dots"><span/><span/><span/></span></div>
        <div v-else-if="!docs.length" class="empty-row" style="color:var(--text-3)">暂无文档，请上传</div>

        <table v-else class="data-table" style="margin-top:12px">
          <thead>
            <tr><th>文件名</th><th>类型</th><th>状态</th><th>质量分</th><th>分块数</th><th>大小</th><th>时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="doc in docs" :key="doc.id">
              <td class="doc-name" :title="doc.filename">{{ doc.filename }}</td>
              <td><span class="badge badge-gray">{{ doc.file_type }}</span></td>
              <td>
                <span class="badge" :class="statusBadge(doc.status)">{{ statusLabel(doc.status) }}</span>
                <span v-if="doc.status==='processing'" class="proc-dot"></span>
              </td>
              <td>
                <div class="score-wrap">
                  <div class="score-bar"><div class="score-fill" :style="{width:(doc.parse_score*100)+'%',background:scoreColor(doc.parse_score)}"/></div>
                  <span class="score-num">{{ (doc.parse_score*100).toFixed(0) }}%</span>
                </div>
              </td>
              <td>{{ doc.chunk_count }}</td>
              <td>{{ fmtSize(doc.file_size) }}</td>
              <td class="time-cell">{{ fmtDate(doc.created_at) }}</td>
              <td>
                <button class="btn btn-danger btn-sm" @click="remove(doc.id)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 失败详情 -->
      <div v-if="docs.some(d=>d.error_msg)" class="card err-card" style="margin-top:14px">
        <div class="section-hd" style="color:var(--red)">处理失败详情</div>
        <div v-for="doc in docs.filter(d=>d.error_msg)" :key="doc.id" class="err-row">
          <span class="err-name">{{ doc.filename }}</span>
          <span class="err-msg">{{ doc.error_msg }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { apiUpload, apiListDocs, apiDeleteDoc } from '@/api/index.js'

const docs        = ref([])
const queue       = ref([])
const dragging    = ref(false)
const docsLoading = ref(false)

onMounted(loadDocs)

async function loadDocs() {
  docsLoading.value = true
  try { docs.value = await apiListDocs() }
  catch (e) { console.error(e) }
  finally { docsLoading.value = false }
}

function onFileChange(e) { processFiles([...e.target.files]); e.target.value = '' }
function onDrop(e) { dragging.value = false; processFiles([...e.dataTransfer.files]) }

function processFiles(files) {
  files.forEach(file => {
    const item = reactive({ name: file.name, status: 'uploading', error: '' })
    queue.value.push(item)
    doUpload(file, item)
  })
}

async function doUpload(file, item) {
  const fd = new FormData(); fd.append('file', file)
  try {
    await apiUpload(fd)
    item.status = 'ok'
    setTimeout(loadDocs, 2000)
  } catch (e) {
    item.status = 'error'; item.error = typeof e === 'string' ? e : '上传失败'
  }
}

async function remove(id) {
  if (!confirm('确认删除该文档及所有相关向量数据？')) return
  try { await apiDeleteDoc(id); await loadDocs() }
  catch (e) { alert('删除失败: ' + e) }
}

const statusLabel = s => ({ pending:'等待中', processing:'处理中', done:'完成', failed:'失败' }[s] || s)
const statusBadge = s => ({ pending:'badge-gray', processing:'badge-blue', done:'badge-green', failed:'badge-red' }[s] || 'badge-gray')

function scoreColor(v) {
  if (v >= 0.8) return 'var(--green)'
  if (v >= 0.6) return 'var(--yellow)'
  return 'var(--red)'
}
function fmtSize(b) {
  if (!b) return '-'
  if (b < 1024) return b + 'B'
  if (b < 1048576) return (b/1024).toFixed(1) + 'KB'
  return (b/1048576).toFixed(1) + 'MB'
}
function fmtDate(s) {
  if (!s) return '-'
  return new Date(s).toLocaleString('zh-CN', { month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false })
}
</script>

<style scoped>
.upload-zone {
  border:2px dashed var(--border-md); text-align:center;
  padding:40px 20px; cursor:pointer; transition:all .2s;
  display:flex; flex-direction:column; align-items:center; gap:8px;
}
.upload-zone:hover, .upload-zone.dragging { border-color:var(--accent); background:var(--accent-bg); }
.upload-icon { color:var(--text-3); margin-bottom:4px; }
.upload-title { font-size:14px; font-weight:600; color:var(--text-2); }
.upload-hint  { font-size:12px; color:var(--text-3); }

.section-hd { font-size:12px; font-weight:600; color:var(--text-2); margin-bottom:10px; }
.count-badge { display:inline-block; padding:0 6px; border-radius:99px; background:var(--bg-hover); color:var(--text-3); font-size:11px; margin-left:6px; }
.list-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }

.queue-row { display:flex; align-items:center; gap:8px; padding:7px 0; border-bottom:1px solid rgba(255,255,255,.04); font-size:12px; }
.queue-row:last-child { border-bottom:none; }
.q-icon { width:18px; display:flex; align-items:center; justify-content:center; }
.q-name { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--text-2); }
.q-err  { color:var(--red); font-size:11px; }

.doc-name { max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--text-1); }
.score-wrap { display:flex; align-items:center; gap:5px; }
.score-bar  { width:48px; height:4px; background:var(--border); border-radius:2px; overflow:hidden; }
.score-fill { height:100%; border-radius:2px; transition:width .3s; }
.score-num  { font-size:11px; color:var(--text-3); }
.time-cell  { font-size:11px; color:var(--text-3); white-space:nowrap; }
.proc-dot   { display:inline-block; width:6px; height:6px; border-radius:50%; background:var(--accent); animation:pulse 1s infinite; margin-left:4px; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }

.empty-row { padding:30px; text-align:center; font-size:13px; }
.err-card  { border-color:rgba(248,113,113,.2); }
.err-row   { display:flex; gap:10px; padding:6px 0; font-size:12px; border-bottom:1px solid rgba(255,255,255,.04); }
.err-row:last-child { border-bottom:none; }
.err-name  { font-weight:500; color:var(--text-2); min-width:120px; }
.err-msg   { color:var(--red); }
</style>
