<template>
  <div class="login-shell">
    <div class="login-card">
      <div class="login-logo">
        <div class="logo-box">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
        </div>
        <span class="logo-text">RAG 知识库</span>
      </div>
      <p class="login-sub">企业级智能问答平台</p>

      <form @submit.prevent="doLogin" class="login-form">
        <div class="field">
          <label class="field-label">用户名</label>
          <input v-model="username" class="input-base field-input" placeholder="请输入用户名" autocomplete="username" :disabled="loading" />
        </div>
        <div class="field">
          <label class="field-label">密码</label>
          <input v-model="password" type="password" class="input-base field-input" placeholder="请输入密码" autocomplete="current-password" :disabled="loading" />
        </div>
        <div v-if="error" class="err-tip">{{ error }}</div>
        <button class="btn btn-primary login-btn" type="submit" :disabled="loading || !username || !password">
          <span v-if="loading" class="dots"><span/><span/><span/></span>
          <span v-else>登录</span>
        </button>
      </form>

      <div class="login-hint">默认账号：admin / admin123</div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiLogin } from '@/api/index.js'

const router   = useRouter()
const username = ref('')
const password = ref('')
const loading  = ref(false)
const error    = ref('')

async function doLogin() {
  error.value   = ''
  loading.value = true
  try {
    const data = await apiLogin(username.value, password.value)
    localStorage.setItem('rag_token', data.token)
    localStorage.setItem('rag_user',  JSON.stringify(data.user))
    router.push('/')
  } catch (e) {
    error.value = typeof e === 'string' ? e : '登录失败，请检查用户名和密码'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-shell {
  height: 100vh; display: flex; align-items: center; justify-content: center;
  background: var(--bg);
}
.login-card {
  width: 380px; background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--r-lg); padding: 40px 36px;
}
.login-logo {
  display: flex; align-items: center; gap: 10px; margin-bottom: 6px;
}
.logo-box {
  width: 36px; height: 36px; background: var(--accent); border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
}
.logo-text { font-size: 18px; font-weight: 700; color: var(--text-1); }
.login-sub { font-size: 12px; color: var(--text-3); margin-bottom: 28px; }
.login-form { display: flex; flex-direction: column; gap: 16px; }
.field { display: flex; flex-direction: column; gap: 6px; }
.field-label { font-size: 12px; color: var(--text-2); font-weight: 500; }
.field-input { width: 100%; }
.err-tip {
  padding: 8px 12px; background: var(--red-bg); border: 1px solid rgba(248,113,113,.2);
  border-radius: var(--r-sm); font-size: 12px; color: var(--red);
}
.login-btn { width: 100%; justify-content: center; height: 40px; margin-top: 4px; }
.login-hint { margin-top: 20px; text-align: center; font-size: 11px; color: var(--text-3); }
</style>
