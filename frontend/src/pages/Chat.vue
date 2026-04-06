<template>
  <div class="page chat-page">
    <!-- Topbar -->
    <div class="chat-topbar">
      <div class="topbar-left">
        <span class="page-title">智能问答</span>
        <span class="intent-badge" :class="lastIntent ? `i-${lastIntent.toLowerCase()}` : ''">
          {{ lastIntent || '就绪' }}
        </span>
      </div>
      <div class="topbar-right">
        <span v-if="lastTrace" class="trace-pill">{{ lastTrace }}</span>
        <span class="status-dot" :class="healthy ? 'ok' : 'err'" :title="healthy ? '服务正常' : '服务异常'"></span>
      </div>
    </div>

    <!-- Messages -->
    <div class="messages" ref="msgBox">
      <div v-if="!messages.length" class="empty-state">
        <div class="empty-icon">
          <svg width="48" height="48" viewBox="0 0 48 48" fill="none"><circle cx="24" cy="24" r="23" stroke="var(--border-md)" stroke-width="1.5"/><path d="M16 24h16M16 18h10M16 30h8" stroke="var(--text-3)" stroke-width="1.5" stroke-linecap="round"/></svg>
        </div>
        <p class="empty-title">开始提问</p>
        <p class="empty-sub">先在「文档管理」上传知识库，再来提问</p>
        <div class="quick-questions">
          <button v-for="q in quickQuestions" :key="q" class="quick-btn" @click="sendQuick(q)">{{ q }}</button>
        </div>
      </div>

      <template v-for="(msg, i) in messages" :key="i">
        <!-- 用户消息 -->
        <div v-if="msg.role === 'user'" class="msg-row msg-user">
          <div class="bubble bubble-user">{{ msg.content }}</div>
          <div class="msg-avatar user-av">我</div>
        </div>

        <!-- AI消息 -->
        <div v-else class="msg-row msg-ai">
          <div class="msg-avatar ai-av">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
          </div>
          <div class="bubble-wrap">
            <div class="bubble bubble-ai" v-html="renderMd(msg.content)"></div>

            <!-- Meta bar -->
            <div class="meta-bar" v-if="msg.done">
              <span class="intent-tag" :class="`i-${(msg.intent||'c2').toLowerCase()}`">
                {{ {C0:'FAQ缓存',C1:'轻量',C2:'完整'}[msg.intent] || msg.intent }}
              </span>
              <span v-if="msg.degrade_level && msg.degrade_level !== 'C2'" class="degrade-tag">
                降级{{ msg.degrade_level }}
                <span v-if="msg.degrade_reason" class="degrade-reason">·{{ msg.degrade_reason }}</span>
              </span>
              <span v-if="msg.latency_ms" class="meta-item">{{ msg.latency_ms }}ms</span>
              <span v-if="msg.cache_hit" class="cache-tag">缓存命中</span>
              <div v-if="msg.confidence != null" class="conf-wrap">
                <div class="conf-bar"><div class="conf-fill" :style="{width: (msg.confidence*100)+'%', background: confColor(msg.confidence)}"></div></div>
                <span class="conf-val">{{ (msg.confidence*100).toFixed(0) }}%</span>
              </div>
              <div class="spacer"/>
              <button class="fb-btn" @click="doFeedback(msg,'like')" :class="{active: msg.fb==='like'}">👍</button>
              <button class="fb-btn" @click="doFeedback(msg,'dislike')" :class="{active: msg.fb==='dislike'}">👎</button>
            </div>

            <!-- Sources -->
            <div v-if="msg.sources && msg.sources.length" class="sources-block">
              <div class="sources-title">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7z"/><path d="M14 2v5h5"/></svg>
                参考来源
              </div>
              <div v-for="(s,si) in msg.sources" :key="si" class="source-item">
                <span class="score-pill">{{ (s.score*100).toFixed(0) }}</span>
                <span class="source-text">{{ s.text.slice(0,90) }}…</span>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- Typing -->
      <div v-if="loading" class="msg-row msg-ai">
        <div class="msg-avatar ai-av"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg></div>
        <div class="bubble bubble-ai dots"><span/><span/><span/></div>
      </div>
    </div>

    <!-- Input -->
    <div class="input-area">
      <div class="input-options">
        <label class="opt-label">
          <input type="checkbox" v-model="streamMode"> 流式
        </label>
        <label class="opt-label">
          意图
          <select v-model="forceIntent" class="intent-sel">
            <option value="">自动</option>
            <option value="C0">C0 FAQ</option>
            <option value="C1">C1 轻量</option>
            <option value="C2">C2 完整</option>
          </select>
        </label>
        <button v-if="messages.length" class="btn btn-ghost btn-sm clear-btn" @click="messages=[]">清空</button>
      </div>
      <div class="input-row">
        <div class="textarea-wrap">
          <textarea
            v-model="input"
            class="chat-textarea"
            placeholder="输入问题… Ctrl+Enter 发送"
            @keydown.ctrl.enter.prevent="send"
            rows="3"
            :disabled="loading"
          />
        </div>
        <button class="send-btn" @click="send" :disabled="loading || !input.trim()">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from 'vue'
import { apiChat, apiFeedback, streamUrl, apiHealth } from '@/api/index.js'

const messages     = ref([])
const input        = ref('')
const loading      = ref(false)
const msgBox       = ref(null)
const streamMode   = ref(true)
const forceIntent  = ref('')
const lastTrace    = ref('')
const lastIntent   = ref('')
const healthy      = ref(true)

const quickQuestions = [
  '公司报销流程是什么？',
  '年假政策如何申请？',
  '如何提交绩效评估？',
]

onMounted(async () => {
  try { await apiHealth(); healthy.value = true }
  catch { healthy.value = false }
})

function renderMd(text) {
  return (text || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\n/g, '<br/>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
    .replace(/【来源：(.*?)】/g, '<span class="cite-tag">$1</span>')
}

function confColor(v) {
  if (v >= 0.75) return 'var(--green)'
  if (v >= 0.5)  return 'var(--yellow)'
  return 'var(--red)'
}

async function scrollBottom() {
  await nextTick()
  if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight
}

function sendQuick(q) { input.value = q; send() }

async function send() {
  const q = input.value.trim()
  if (!q || loading.value) return
  messages.value.push({ role: 'user', content: q })
  input.value = ''
  loading.value = true
  await scrollBottom()
  streamMode.value ? await sendStream(q) : await sendSync(q)
}

async function sendSync(q) {
  try {
    const data = await apiChat(q)
    lastTrace.value  = data.trace_id || ''
    lastIntent.value = data.intent || 'C2'
    messages.value.push({
      role: 'assistant', content: data.answer,
      sources: data.sources || [], latency_ms: data.latency_ms,
      cache_hit: data.cache_hit, intent: data.intent,
      confidence: data.confidence, degrade_level: data.degrade_level,
      degrade_reason: data.degrade_reason,
      log_id: data.log_id, query: q, done: true,
    })
  } catch (e) {
    messages.value.push({ role: 'assistant', content: `请求失败：${e}`, done: true })
  } finally {
    loading.value = false
    await scrollBottom()
  }
}

async function sendStream(q) {
  const idx = messages.value.length
  messages.value.push({ role: 'assistant', content: '', done: false, query: q })
  try {
    const es = new EventSource(streamUrl(q))
    es.onmessage = async (e) => {
      if (e.data === '[DONE]') {
        es.close(); messages.value[idx].done = true; loading.value = false; return
      }
      if (e.data.startsWith('[ERROR]')) {
        messages.value[idx].content = `错误：${e.data.slice(7)}`
        messages.value[idx].done = true; es.close(); loading.value = false; return
      }
      messages.value[idx].content += e.data + '\n'
      await scrollBottom()
    }
    es.onerror = () => { es.close(); messages.value[idx].done = true; loading.value = false }
  } catch (e) {
    messages.value[idx].content = `流式请求失败：${e}`
    messages.value[idx].done = true; loading.value = false
  }
  await scrollBottom()
}

async function doFeedback(msg, type) {
  if (msg.fb) return
  msg.fb = type
  try {
    await apiFeedback({ query: msg.query||'', answer: msg.content, feedback: type, log_id: msg.log_id })
  } catch {}
}
</script>

<style scoped>
.chat-page { display:flex; flex-direction:column; height:100%; }

.chat-topbar {
  height:48px; border-bottom:1px solid var(--border);
  display:flex; align-items:center; padding:0 20px; gap:10px; flex-shrink:0;
}
.topbar-left { display:flex; align-items:center; gap:8px; }
.topbar-right { margin-left:auto; display:flex; align-items:center; gap:8px; }
.trace-pill { font-size:11px; color:var(--text-3); font-family:monospace; padding:2px 7px; border:1px solid var(--border); border-radius:4px; }
.status-dot { width:8px; height:8px; border-radius:50%; }
.status-dot.ok  { background:var(--green); box-shadow:0 0 5px var(--green); }
.status-dot.err { background:var(--red); }

.intent-badge { font-size:11px; font-weight:600; padding:2px 7px; border-radius:4px; }
.i-c0 { background:var(--green-bg); color:var(--green); }
.i-c1 { background:var(--yellow-bg); color:var(--yellow); }
.i-c2 { background:var(--blue-bg); color:var(--accent); }

.messages {
  flex:1; overflow-y:auto; padding:20px;
  display:flex; flex-direction:column; gap:18px;
}
.empty-state { margin:auto; text-align:center; padding:40px 20px; }
.empty-icon  { margin:0 auto 14px; opacity:.4; }
.empty-title { font-size:15px; font-weight:600; color:var(--text-2); margin-bottom:6px; }
.empty-sub   { font-size:13px; color:var(--text-3); margin-bottom:18px; }
.quick-questions { display:flex; flex-wrap:wrap; gap:8px; justify-content:center; }
.quick-btn {
  padding:6px 14px; border-radius:99px; border:1px solid var(--border-md);
  background:var(--bg-card); color:var(--text-2); font-size:12px; cursor:pointer;
  transition:all .15s;
}
.quick-btn:hover { border-color:var(--accent); color:var(--accent); }

.msg-row { display:flex; gap:10px; align-items:flex-start; }
.msg-user { flex-direction:row-reverse; }
.msg-avatar { width:28px; height:28px; border-radius:50%; flex-shrink:0; display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:600; }
.user-av { background:var(--bg-hover); color:var(--text-2); border:1px solid var(--border-md); }
.ai-av   { background:var(--accent); color:#fff; }

.bubble { padding:11px 15px; border-radius:12px; font-size:13px; line-height:1.7; max-width:74%; }
.bubble-user { background:var(--accent-bg); border:1px solid rgba(79,126,248,.25); color:var(--text-1); }
.bubble-ai   { background:var(--bg-card); border:1px solid var(--border); color:var(--text-1); }
.bubble-wrap { display:flex; flex-direction:column; gap:6px; max-width:80%; }

.meta-bar { display:flex; align-items:center; gap:6px; flex-wrap:wrap; font-size:11px; color:var(--text-3); padding:0 2px; }
.intent-tag { padding:1px 6px; border-radius:3px; font-weight:600; }
.degrade-tag { padding:1px 6px; border-radius:3px; background:var(--yellow-bg); color:var(--yellow); font-size:10px; }
.degrade-reason { opacity:.7; }
.meta-item { }
.cache-tag { padding:1px 6px; border-radius:3px; background:var(--green-bg); color:var(--green); font-weight:600; }
.conf-wrap { display:flex; align-items:center; gap:4px; }
.conf-bar  { width:40px; height:3px; background:var(--border-md); border-radius:2px; overflow:hidden; }
.conf-fill { height:100%; border-radius:2px; transition:width .3s; }
.conf-val  { font-size:11px; }
.spacer { flex:1; }
.fb-btn { background:none; border:none; cursor:pointer; padding:2px 5px; border-radius:4px; font-size:14px; transition:background .1s; }
.fb-btn:hover, .fb-btn.active { background:var(--bg-hover); }

.sources-block { border:1px solid var(--border); border-radius:8px; overflow:hidden; }
.sources-title { padding:6px 10px; font-size:11px; font-weight:600; color:var(--text-2); background:var(--bg-hover); display:flex; align-items:center; gap:5px; }
.source-item { display:flex; align-items:baseline; gap:7px; padding:6px 10px; border-top:1px solid rgba(255,255,255,.04); font-size:11px; }
.score-pill { padding:1px 5px; border-radius:3px; background:var(--accent-bg); color:var(--accent); font-weight:700; flex-shrink:0; }
.source-text { color:var(--text-2); }

:deep(.inline-code) { background:var(--bg-hover); padding:1px 5px; border-radius:3px; font-family:monospace; font-size:12px; }
:deep(.cite-tag) { padding:0 4px; border-radius:3px; background:var(--green-bg); color:var(--green); font-size:11px; }

.input-area { border-top:1px solid var(--border); padding:12px 16px; flex-shrink:0; background:var(--bg-card); }
.input-options { display:flex; align-items:center; gap:12px; margin-bottom:8px; font-size:12px; color:var(--text-3); }
.opt-label { display:flex; align-items:center; gap:4px; cursor:pointer; }
.intent-sel { background:var(--bg); border:1px solid var(--border); color:var(--text-2); border-radius:4px; padding:2px 6px; font-size:11px; outline:none; }
.clear-btn  { margin-left:auto; }
.input-row  { display:flex; gap:8px; align-items:flex-end; }
.textarea-wrap { flex:1; }
.chat-textarea {
  width:100%; background:var(--bg); border:1px solid var(--border-md);
  border-radius:10px; color:var(--text-1); padding:10px 14px;
  font-size:13px; resize:none; font-family:inherit; outline:none;
  line-height:1.5; transition:border-color .15s;
}
.chat-textarea:focus { border-color:var(--accent); }
.chat-textarea:disabled { opacity:.5; }
.chat-textarea::placeholder { color:var(--text-3); }
.send-btn {
  width:42px; height:42px; border-radius:10px; background:var(--accent);
  border:none; cursor:pointer; display:flex; align-items:center; justify-content:center;
  flex-shrink:0; color:#fff; transition:background .15s;
}
.send-btn:hover:not(:disabled) { background:var(--accent-h); }
.send-btn:disabled { opacity:.4; cursor:not-allowed; }
</style>
