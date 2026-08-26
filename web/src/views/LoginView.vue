<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const form = ref({ username: '', password: '' })
const error = ref<string | null>(null)
const loading = ref(false)
const showPassword = ref(false)
const justRegistered = ref(route.query.registered === '1')

async function handleLogin() {
  error.value = null
  loading.value = true
  try {
    await authStore.login(form.value)
    await authStore.fetchUser()
    router.push('/')
  } catch (e: any) {
    error.value = e.response?.data?.detail || '登录失败，请检查用户名和密码'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="auth-brand">
        <Icon icon="mdi:microphone" width="30" height="30" />
        <h1>Audiobook Studio</h1>
      </div>
      <p class="auth-subtitle">登录以继续您的工作</p>

      <div v-if="justRegistered" class="alert alert-success" style="margin-bottom: 16px">
        注册成功，请使用新账号登录
      </div>

      <form class="auth-form" @submit.prevent="handleLogin">
        <div class="form-group">
          <label for="username">用户名</label>
          <input
            id="username"
            v-model.trim="form.username"
            type="text"
            required
            autocomplete="username"
            placeholder="请输入用户名"
            :disabled="loading"
          />
        </div>
        <div class="form-group">
          <label for="password">密码</label>
          <div class="password-field">
            <input
              id="password"
              v-model="form.password"
              :type="showPassword ? 'text' : 'password'"
              required
              autocomplete="current-password"
              placeholder="请输入密码"
              :disabled="loading"
            />
            <button
              type="button"
              class="password-toggle"
              :aria-label="showPassword ? '隐藏密码' : '显示密码'"
              @click="showPassword = !showPassword"
            >
              <Icon :icon="showPassword ? 'mdi:eye-off-outline' : 'mdi:eye-outline'" width="18" height="18" />
            </button>
          </div>
        </div>

        <div v-if="error" class="alert alert-error">{{ error }}</div>

        <button type="submit" class="btn btn-primary btn-lg btn-block" :disabled="loading">
          <span v-if="loading" class="spinner" style="border-color: rgba(255,255,255,.35); border-top-color: #fff"></span>
          <span>{{ loading ? '登录中…' : '登录' }}</span>
        </button>
      </form>

      <div class="auth-footer">
        <router-link to="/register">没有账号？注册新用户</router-link>
        <p class="bootstrap-hint">首次部署请运行 <code>python scripts/bootstrap_admin.py</code> 创建管理员账号</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.password-field {
  position: relative;
}
.password-field input {
  width: 100%;
  padding-right: 40px;
}
.password-toggle {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 4px;
  display: flex;
  border-radius: var(--radius-sm);
}
.password-toggle:hover {
  color: var(--color-text);
  background: var(--color-bg-tertiary);
}
.bootstrap-hint {
  margin: 12px 0 0;
  font-size: 12px;
}
.bootstrap-hint code {
  background: var(--color-bg-tertiary);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-size: 11px;
}
</style>