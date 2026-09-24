<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import * as api from '../api'
import { useI18n } from '../i18n'

const router = useRouter()
const { t } = useI18n()

const form = ref({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
  full_name: '',
})
const error = ref<string | null>(null)
const loading = ref(false)
const showPassword = ref(false)
const showConfirmPassword = ref(false)

async function handleRegister() {
  error.value = null
  if (form.value.password !== form.value.confirmPassword) {
    error.value = t('auth.password_mismatch')
    return
  }
  loading.value = true
  try {
    await api.default.post('/api/auth/register', {
      username: form.value.username,
      email: form.value.email,
      password: form.value.password,
      full_name: form.value.full_name,
    })
    router.push('/login?registered=1')
  } catch (e: any) {
    error.value = e.response?.data?.detail || t('auth.register_failed')
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
      <p class="auth-subtitle">{{ t('auth.register_subtitle') }}</p>

      <form class="auth-form" @submit.prevent="handleRegister">
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
          <label for="email">{{ t('auth.email') }}</label>
          <input
            id="email"
            v-model.trim="form.email"
            type="email"
            required
            autocomplete="email"
            :placeholder="t('auth.email_placeholder')"
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
              autocomplete="new-password"
              :placeholder="t('auth.password_min')"
              minlength="8"
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
        <div class="form-group">
          <label for="confirmPassword">{{ t('auth.confirm_password') }}</label>
          <div class="password-field">
            <input
              id="confirmPassword"
              v-model="form.confirmPassword"
              :type="showConfirmPassword ? 'text' : 'password'"
              required
              autocomplete="new-password"
              :placeholder="t('auth.confirm_password_placeholder')"
              :disabled="loading"
            />
            <button
              type="button"
              class="password-toggle"
              :aria-label="showConfirmPassword ? t('auth.hide_password') : t('auth.show_password')"
              @click="showConfirmPassword = !showConfirmPassword"
            >
              <Icon :icon="showConfirmPassword ? 'mdi:eye-off-outline' : 'mdi:eye-outline'" width="18" height="18" />
            </button>
          </div>
        </div>
        <div class="form-group">
          <label for="full_name">{{ t('auth.full_name_optional') }}</label>
          <input
            id="full_name"
            v-model.trim="form.full_name"
            type="text"
            autocomplete="name"
            :placeholder="t('auth.full_name_placeholder')"
            :disabled="loading"
          />
        </div>

        <div v-if="error" class="alert alert-error">{{ error }}</div>

        <button type="submit" class="btn btn-primary btn-lg btn-block" :disabled="loading">
          <span v-if="loading" class="spinner" style="border-color: rgba(255,255,255,.35); border-top-color: #fff"></span>
          <span>{{ loading ? t('auth.register_in_progress') : t('auth.register') }}</span>
        </button>
      </form>

      <div class="auth-footer">
        <router-link to="/login">{{ t('auth.have_account') }}</router-link>
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
</style>