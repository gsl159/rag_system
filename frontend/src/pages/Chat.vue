<template>
  <div class="page chat-page">
    <!-- Header -->
    <div class="page-header" style="border-bottom:1px solid var(--border);padding-bottom:16px">
      <div class="page-title">💬 智能问答</div>
      <div class="page-sub">基于知识库的 RAG 问答 · 支持流式输出</div>
    </div>

    <!-- Messages -->
    <div class="messages" ref="msgBox">
      <div v-if="!messages.length" class="empty" style="margin:auto">
        <div class="empty-icon">🧠</div>
        <p>先在「文档管理」上传知识库，再来提问</p>
        <p style="font-size:12px;margin-top:6px;color:var(--text-3)">
          支持 PDF / Word / HTML / TXT / Markdown
        </p>
      </div>

      <template v-for="(msg, i) in messages" :key="i">
        <!-- User bubble -->
        <div v-if="msg.role === 'user'" class="row row-user">
          <div class="bubble bubble-user">{{ msg.content }}</div>
          <div class="avatar">👤</div>
        </div>

        <!-- Assistant bubble -->
        <div v-else class="row row-bot">
          <div class="avatar">🤖</div>
          <div class="bubble-wrap">
            <div class="bubble bubble-bot" v-html="renderMd(msg.content)" />

            <!-- Meta bar -->
            <div class="meta-bar" v-if="msg.done">
              <span v-if="msg.latency_ms" class="meta-item">⏱ {{ msg.latency_ms }}ms</span>
              <span v-if="msg.cache_hit"  class="meta-item cache">⚡ 已缓存</span>
              <span v-if="msg.rewritten_query && msg.rewritten_query !== msg.query"
                    class="meta-item rewrite" :title="'改写为：' + msg.rewritten_query">✏️ 已改写</span>
              <div class="spacer" />
              <button class="thumb-btn" @click="doFeedback(msg, 'like')">👍</button>
              <button class="thumb-btn" @click="doFeedback(msg, 'dislike')">👎</button>
            </div>

            <!-- Sources -->
            <div v-if="msg.sources && msg.sources.length" class="sources">
              <div class="sources-title">📎 参考片段</div>
              <div v-for="(s,si) in msg.sources" :key="si" class="source-item">
                <span class="src-score">{{ (s.score*2).toFixed(1) }}</span>
                {{ s.text.slice(0,100) }}…
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- Typing indicator -->
      <div v-if="loading" class="row row-bot">
        <div class="avatar">🤖</div>
        <div class="bubble bubble-bot dots">
          <span /><span /><span />
        </div>
      </div>
    </div>

    <!-- Input -->
    <div class="input-bar">
      <div class="mode-toggle">
        <label class="toggle-label">
          <input type="checkbox" v-model="streamMode" />
          <span>流式输出</span>
        </label>
      </div>
      <textarea
        v-model="input"
        placeholder="输入问题… Ctrl+Enter 发送"
        @keydown.ctrl.enter.prevent="send"
        rows="3"
        :disabled="loading"
      />
      <button class="btn btn-primary send-btn" @click="send" :disabled="loading || !input.trim()">
        {{ loading ? '生成中…' : '发送' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'
import { apiChat, apiFeedback, streamUrl } from '@/api/index.js'

const messages  = ref([])
const input     = ref('')
const loading   = ref(false)
const msgBox    = ref(null)
const streamMode= ref(true)

function renderMd(text) {
  // 最简 markdown：换行、加粗、inline code
  return (text || '')
    .replace(/\n/g, '<br/>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code style="background:#1e2535;padding:1px 4px;border-radius:4px">$1</code>')
}

async function scrollBottom() {
  await nextTick()
  if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight
}

async function send() {
  const q = input.value.trim()
  if (!q || loading.value) return

  messages.value.push({ role: 'user', content: q })
  input.value = ''
  loading.value = true
  await scrollBottom()

  if (streamMode.value) {
    await sendStream(q)
  } else {
    await sendSync(q)
  }
}

async function sendSync(q) {
  try {
    const data = await apiChat(q)
    messages.value.push({
      role:            'assistant',
      content:         data.answer,
      sources:         data.sources || [],
      latency_ms:      data.latency_ms,
      cache_hit:       data.cache_hit,
      rewritten_query: data.rewritten_query,
      query:           q,
      log_id:          data.log_id,
      done:            true,
    })
  } catch (e) {
    messages.value.push({ role: 'assistant', content: `⚠️ 请求失败：${e}`, done: true })
  } finally {
    loading.value = false
    await scrollBottom()
  }
}

async function sendStream(q) {
  const idx = messages.value.length
  messages.value.push({ role: 'assistant', content: '', done: false })

  try {
    const evtSrc = new EventSource(streamUrl(q))
    evtSrc.onmessage = async (e) => {
      if (e.data === '[DONE]') {
        evtSrc.close()
        messages.value[idx].done = true
        loading.value = false
        return
      }
      if (e.data.startsWith('[ERROR]')) {
        messages.value[idx].content = `⚠️ ${e.data}`
        messages.value[idx].done = true
        evtSrc.close()
        loading.value = false
        return
      }
      messages.value[idx].content += e.data
      await scrollBottom()
    }
    evtSrc.onerror = () => {
      evtSrc.close()
      messages.value[idx].done = true
      loading.value = false
    }
  } catch (e) {
    messages.value[idx].content = `⚠️ 流式请求失败：${e}`
    messages.value[idx].done = true
    loading.value = false
  }
  await scrollBottom()
}

async function doFeedback(msg, type) {
  try {
    await apiFeedback({
      query:    msg.query || '',
      answer:   msg.content,
      feedback: type,
      log_id:   msg.log_id,
    })
    alert(type === 'like' ? '✅ 感谢好评！' : '📝 感谢反馈，我们会持续改进！')
  } catch { alert('反馈提交失败') }
}
</script>

<style scoped>
.chat-page { display: flex; flex-direction: column; height: 100%; }

.messages {
  flex: 1; overflow-y: auto;
  padding: 20px 24px;
  display: flex; flex-direction: column; gap: 18px;
}

.row { display: flex; gap: 12px; align-items: flex-start; }
.row-user { flex-direction: row-reverse; }
.avatar   { font-size: 24px; flex-shrink: 0; margin-top: 4px; }

.bubble {
  padding: 12px 16px; border-radius: 12px;
  font-size: 14px; line-height: 1.7;
  max-width: 72%;
}
.bubble-user { background: var(--bg-active); color: var(--text-1); }
.bubble-bot  { background: var(--bg-card);   color: var(--text-1); border: 1px solid var(--border); }

.bubble-wrap { display: flex; flex-direction: column; gap: 6px; max-width: 78%; }

.meta-bar {
  display: flex; align-items: center; gap: 8px;
  font-size: 11px; color: var(--text-3);
  padding: 4px 2px;
}
.meta-item        { display: flex; align-items: center; gap: 3px; }
.meta-item.cache  { color: var(--yellow); }
.meta-item.rewrite{ color: var(--blue); cursor: default; }
.spacer           { flex: 1; }
.thumb-btn {
  background: none; border: none; cursor: pointer;
  font-size: 15px; padding: 2px 4px; border-radius: 4px;
  transition: background .15s;
}
.thumb-btn:hover  { background: var(--bg-hover); }

.sources       { font-size: 12px; }
.sources-title { color: var(--accent-2); font-weight: 600; margin-bottom: 5px; }
.source-item   {
  background: var(--bg-base); border: 1px solid var(--border);
  border-radius: 6px; padding: 5px 8px; margin-bottom: 4px;
  color: var(--text-2); display: flex; gap: 6px; align-items: baseline;
}
.src-score {
  background: var(--accent); color: #fff;
  border-radius: 4px; padding: 0 5px; font-size: 10px; flex-shrink: 0;
}

/* Input bar */
.input-bar {
  padding: 14px 24px;
  border-top: 1px solid var(--border);
  display: flex; gap: 10px; align-items: flex-end;
  flex-shrink: 0; background: var(--bg-card);
}
.mode-toggle {
  display: flex; flex-direction: column;
  justify-content: flex-end; padding-bottom: 2px;
}
.toggle-label {
  display: flex; align-items: center; gap: 5px;
  font-size: 12px; color: var(--text-3); cursor: pointer; white-space: nowrap;
}
textarea {
  flex: 1; background: var(--bg-base);
  border: 1px solid var(--border); border-radius: var(--radius-md);
  color: var(--text-1); padding: 10px 14px;
  font-size: 14px; resize: none; font-family: inherit;
  outline: none; line-height: 1.5; transition: border-color .18s;
}
textarea:focus     { border-color: var(--accent); }
textarea:disabled  { opacity: .5; }
.send-btn { height: 44px; padding: 0 24px; }
</style>
