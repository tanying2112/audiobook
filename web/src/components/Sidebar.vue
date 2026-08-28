<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import { useI18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { useContextStore } from '../stores/context'
import LocaleSwitcher from './LocaleSwitcher.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()
const contextStore = useContextStore()

onMounted(() => {
  if (authStore.isAuthenticated() && !authStore.user) {
    authStore.fetchUser()
  }
})

const emit = defineEmits<{
  close: []
}>()

const navItems = computed(() => [
  { label: 'nav.projects', icon: 'mdi:bookshelf', route: '/' },
  { label: 'nav.project_management', icon: 'mdi:book-open-variant', route: '/projects', pattern: '/projects/' },
  { label: 'nav.feedback_entry', icon: 'mdi:comment-edit-outline', route: '/feedback' },
  { label: 'nav.harness_console', icon: 'mdi:tune-variant', route: '/harness' },
  { label: 'nav.monitoring', icon: 'mdi:chart-line', route: '/monitoring' },
  { label: 'nav.provider_management', icon: 'mdi:server', route: '/providers' },
  { label: 'nav.model_market', icon: 'mdi:puzzle', route: '/model-market' },
  // Dashboard route dynamically generated with actual projectId from context store
  { label: 'nav.dashboard', icon: 'mdi:chart-pie', route: contextStore.projectId ? `/projects/${contextStore.projectId}/dashboard` : '' },
])

function isActive(path: string): boolean {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

function handleNavClick(itemRoute: string) {
  router.push(itemRoute || '/')
  emit('close')
}

function handleLogout() {
  authStore.logout()
  router.push('/login')
}
</script>

<template>
  <div class="sidebar">
    <div class="sidebar-header">
      <Icon icon="mdi:microphone" width="28" height="28" />
      <span class="sidebar-title">{{ t('sidebar.title') }}</span>
    </div>
    <nav class="sidebar-nav" aria-label="主导航">
      <button
        v-for="item in navItems"
        :key="item.label"
        :class="['nav-btn', { active: isActive(item.route || item.pattern || '') }]"
        @click="handleNavClick(item.route || '/')"
      >
        <Icon :icon="item.icon" width="20" height="20" />
        <span>{{ t(item.label) }}</span>
      </button>
    </nav>
    <div class="sidebar-footer">
      <LocaleSwitcher />
      <div class="user-info" :title="authStore.user?.email">
        <div class="user-avatar">
          {{ (authStore.user?.full_name || authStore.user?.username || '?').charAt(0).toUpperCase() }}
        </div>
        <div class="user-meta">
          <span class="user-name">{{ authStore.user?.full_name || authStore.user?.username || '—' }}</span>
          <span v-if="authStore.user?.is_superuser" class="user-role">管理员</span>
        </div>
      </div>
      <button class="logout-btn" :title="t('auth.logout')" aria-label="登出" @click="handleLogout">
        <Icon icon="mdi:logout" width="18" height="18" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.sidebar {
  width: 100%;
  background: var(--color-sidebar-bg, #0f172a);
  color: #e2e8f0;
  display: flex;
  flex-direction: column;
  padding: 16px 0;
  height: 100%;
  overflow-y: auto;
}
.sidebar-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px 20px;
  border-bottom: 1px solid #334155;
  margin-bottom: 12px;
}
.sidebar-title {
  font-weight: 600;
  font-size: 16px;
}
.sidebar-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 8px;
}
.nav-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #cbd5e1;
  font-size: 14px;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s, color 0.15s;
  min-height: 44px; /* touch-friendly */
}
.nav-btn:hover {
  background: #334155;
  color: #f1f5f9;
}
.nav-btn.active {
  background: var(--color-primary);
  color: #fff;
}
.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px 0;
  border-top: 1px solid #334155;
  margin-top: 12px;
}
.user-info {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}
.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--color-primary);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}
.user-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.user-name {
  font-size: 13px;
  color: #e2e8f0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.user-role {
  font-size: 11px;
  color: #94a3b8;
}
.logout-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
  flex-shrink: 0;
}
.logout-btn:hover {
  background: #334155;
  color: #f87171;
}
</style>
