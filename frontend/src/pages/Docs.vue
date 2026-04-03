<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">📄 文档管理</div>
      <div class="page-sub">上传 PDF / Word / HTML / TXT，自动解析入库</div>
    </div>

    <div class="page-body">
      <!-- Upload zone -->
      <div
        class="upload-zone card"
        :class="{ dragging }"
        @click="$refs.fileInput.click()"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <input
          ref="fileInput" type="file" style="display:none"
          multiple accept=".pdf,.docx,.doc,.html,.htm,.txt,.md"
          @change="onFileChange"
        />
        <div style="font-size:42px;margin-bottom:10px">📥</div>
        <p style="font-weight:600">拖拽文件到此处，或点击选择</p>
        <p style="font-size:12px;color:var(--text-3);margin-top:4px">
          支持 .pdf .docx .html .txt .md · 单文件 ≤ 50MB
        </p>
      </div>

      <!-- Upload queue -->
      <div v-if="queue.length" class="card" style="margin-top:16px">
        <div class="section-title">上传队列</div>
        <div v-for="(item,i) in queue" :key="i" class="queue-row">
          <span class="q-filename">📎 {{ item.name }}</span>
          <span :class="['badge', qBadge(item.status)]">{{ item.label }}</span>
          <span v-if="item.error" class="q-error">{{ item.error }}</span>
        </div>
      </div>

      <!-- Doc list -->
      <div class="card" style="margin-top:16px">
        <div class="list-header">
          <span class="section-title" style="margin-bottom:0">文档列表</span>
          <div style="display:flex;gap:8px">
            <button class="btn btn-ghost btn-sm" @click="loadDocs">🔄 刷新</button>
          </div>
        </div>

        <div v-if="docsLoading" class="empty"><div class="empty-icon">⏳</div><p>加载中…</p></div>
        <div v-else-if="!docs.length" class="empty"><div class="empty-icon">📭</div><p>暂无文档，请上传</p></div>

        <table v-else class="data-table" style="margin-top:12px">
          <thead>
            <tr>
              <th>文件名</th>
              <th>类型</th>
              <th>状态</th>
              <th>质量分</th>
              <th>分块数</th>
              <th>大小</th>
              <th>上传时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="doc in docs" :key="doc.id">
              <td class="doc-name" :title="doc.filename">{{ doc.filename }}</td>
              <td><span class="badge badge-gray">{{ doc.file_type || '-' }}</span></td>
              <td><span :class="['badge', statusBadge(doc.status)]">{{ statusLabel(doc.status) }}</span></td>
              <td>
                <div class="score-wrap">
                  <div class="score-bar">
                    <div
                      class="score-fill"
                      :style="{
                        width:      (doc.parse_score * 100) + '%',
                        background: scoreColor(doc.parse_score)
                      }"
                    />
                  </div>
                  <span>{{ (doc.parse_score * 100).toFixed(0) }}%</span>
                </div>
              </td>
              <td>{{ doc.chunk_count }}</td>
              <td>{{ fmtSize(doc.file_size) }}</td>
              <td>{{ fmtDate(doc.created_at) }}</td>
              <td>
                <button class="btn btn-danger btn-sm" @click="remove(doc.id)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Error detail -->
      <div v-if="docs.some(d => d.error_msg)" class="card" style="margin-top:16px">
        <div class="section-title">⚠️ 处理失败详情</div>
        <div v-for="doc in docs.filter(d => d.error_msg)" :key="doc.id" class="error-row">
          <span class="err-name">{{ doc.filename }}</span>
          <span class="err-msg">{{ doc.error_msg }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { apiUpload, apiListDocs, apiDeleteDoc } from '@/api/index.js'

const docs        = ref([])
const queue       = ref([])
const dragging    = ref(false)
const docsLoading = ref(false)
const fileInput   = ref(null)

onMounted(loadDocs)

async function loadDocs() {
  docsLoading.value = true
  try { docs.value = await apiListDocs() }
  catch (e) { console.error(e) }
  finally { docsLoading.value = false }
}

function onFileChange(e) { processFiles([...e.target.files]); e.target.value = '' }
function onDrop(e)       { dragging.value = false; processFiles([...e.dataTransfer.files]) }

function processFiles(files) {
  files.forEach(file => {
    const item = reactive({ name: file.name, status: 'uploading', label: '上传中…', error: '' })
    queue.value.push(item)
    doUpload(file, item)
  })
}

import { reactive } from 'vue'
async function doUpload(file, item) {
  const fd = new FormData()
  fd.append('file', file)
  try {
    await apiUpload(fd)
    item.status = 'ok'; item.label = '已提交'
    setTimeout(loadDocs, 2000)
  } catch (e) {
    item.status = 'error'; item.label = '失败'
    item.error  = typeof e === 'string' ? e : '上传失败'
  }
}

async function remove(id) {
  if (!confirm('确认删除该文档及其向量数据？')) return
  try {
    await apiDeleteDoc(id)
    await loadDocs()
  } catch (e) { alert('删除失败: ' + e) }
}

const statusLabel = s => ({ pending:'等待中', processing:'处理中', done:'完成', failed:'失败' }[s] || s)
const statusBadge = s => ({ pending:'badge-gray', processing:'badge-blue', done:'badge-green', failed:'badge-red' }[s] || 'badge-gray')
const qBadge      = s => ({ uploading:'badge-blue', ok:'badge-green', error:'badge-red' }[s] || 'badge-gray')

function scoreColor(v) {
  if (v >= 0.8) return 'var(--green)'
  if (v >= 0.6) return 'var(--yellow)'
  return 'var(--red)'
}
function fmtSize(b) {
  if (!b) return '-'
  if (b < 1024)    return b + ' B'
  if (b < 1048576) return (b/1024).toFixed(1) + ' KB'
  return (b/1048576).toFixed(1) + ' MB'
}
function fmtDate(s) {
  if (!s) return '-'
  return new Date(s).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.upload-zone {
  border: 2px dashed var(--border); text-align: center;
  padding: 44px 20px; cursor: pointer; transition: all .2s;
}
.upload-zone:hover, .upload-zone.dragging {
  border-color: var(--accent); background: var(--bg-hover);
}
.list-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.queue-row {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 0; border-bottom: 1px solid var(--border-dim); font-size: 13px;
}
.q-filename { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.q-error    { color: var(--red); font-size: 11px; }
.doc-name   { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.score-wrap { display: flex; align-items: center; gap: 6px; }
.score-bar  { width: 54px; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }
.score-fill { height: 100%; border-radius: 3px; transition: width .3s; }
.error-row  { display: flex; gap: 10px; padding: 6px 0; font-size: 12px; border-bottom: 1px solid var(--border-dim); }
.err-name   { font-weight: 500; color: var(--text-2); min-width: 120px; }
.err-msg    { color: var(--red); }
</style>
