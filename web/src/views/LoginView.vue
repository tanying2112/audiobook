<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import { useAuthStore } from '../stores/auth'
import { useI18n } from '../i18n'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const { t } = useI18n()

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
    error.value = e.response?.data?.detail || t('auth.login_failed')
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
      <p class="auth-subtitle">{{ t('auth.login_subtitle') }}</p>

      <div v-if="justRegistered" class="alert alert-success" style="margin-bottom: 16px">
        {{ t('auth.register_success') }}
      </div>

      <form class="auth-form" @submit.prevent="handleLogin">
        <div class="form-group">
          <label for="username">{{ t('auth.username') }}</label>
          <input
            id="username"
            v-model.trim="form.username"
            type="text"
            required
            autocomplete="username"
            :placeholder="t('auth.username_placeholder')"
            :disabled="loading"
          />
        </div>
        <div class="form-group">
          <label for="password">{{ t('auth.password') }}</label>
          <div class="password-field">
            <input
              id="password"
              v-model="form.password"
              :type="showPassword ? 'text' : 'password'"
              required
              autocomplete="current-password"
              :placeholder="t('auth.password_placeholder')"
              :disabled="loading"
            />
            <button
              type="button"
              class="password-toggle"
              :aria-label="showPassword ? t('auth.hide_password') : t('auth.show_password')"
              @click="showPassword = !showPassword"
            >
              <Icon :icon="showPassword ? 'mdi:eye-off-outline' : 'mdi:eye-outline'" width="18" height="18" />
            </button>
          </div>
        </div>

        <div v-if="error" class="alert alert-error">{{ error }}</div>

        <button type="submit" class="btn btn-primary btn-lg btn-block" :disabled="loading">
          <span v-if="loading" class="spinner" style="border-color: rgba(255,255,255,.35); border-top-color: #fff"></span>
          <span>{{ loading ? t('auth.login_in_progress') : t('auth.login') }}</span>
        </button>
      </form>

      <div class="auth-footer">
        <router-link to="/register">{{ t('auth.no_account') }}</router-link>
        <p class="bootstrap-hint">
          {{ t('auth.bootstrap_hint_before') }}<code>python scripts/bootstrap_admin.py</code>{{ t('auth.bootstrap_hint_after') }}
        </p>
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
  margin: 0 4px;
  border-radius: var(--radius-sm);
  font-size: 11px;
}
</style>