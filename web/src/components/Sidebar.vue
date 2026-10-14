<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import { useI18n, getLocale } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { useContextStore } from '../stores/context'
import LocaleSwitcher from './LocaleSwitcher.vue'
import { useTheme } from '../composables/useTheme'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()
const contextStore = useContextStore()
const { themeMode, isDark, cycleTheme, getThemeLabel } = useTheme()

onMounted(() => {
  if (authStore.isAuthenticated() && !authStore.user) {
    authStore.fetchUser()
  }
})

const emit = defineEmits<{
  close: []
}>()

// ── All navigation items (13+ entries) ──────────────────────────
const navItems = computed(() => [
  { label: 'nav.projects', icon: 'mdi:bookshelf', route: '/', group: 'workspace' },
  { label: 'nav.project_management', icon: 'mdi:book-open-variant', route: '/projects', group: 'workspace', pattern: '/projects/' },
  { label: 'nav.feedback_entry', icon: 'mdi:comment-edit-outline', route: '/feedback', group: 'workspace' },
  { label: 'nav.harness_console', icon: 'mdi:tune-variant', route: '/harness', group: 'system' },
  { label: 'nav.promotions', icon: 'mdi:rocket-launch-outline', route: '/evolution/promotions', group: 'evolution' },
  { label: 'nav.golden_data', icon: 'mdi:database-star-outline', route: '/evolution/golden', group: 'evolution' },
  { label: 'nav.sop_rules', icon: 'mdi:book-cog-outline', route: '/evolution/sop', group: 'evolution' },
  { label: 'nav.feedback_insights', icon: 'mdi:comment-quote-outline', route: '/evolution/feedback', group: 'evolution' },
  { label: 'nav.admin_panel', icon: 'mdi:shield-account-outline', route: '/admin', group: 'system' },
  { label: 'nav.monitoring', icon: 'mdi:chart-line', route: '/monitoring', group: 'system' },
  { label: 'nav.provider_management', icon: 'mdi:server', route: '/providers', group: 'system' },
  { label: 'nav.model_market', icon: 'mdi:puzzle', route: '/model-market', group: 'system' },
  { label: 'nav.waveform_demo', icon: 'mdi:waveform', route: '/waveform-demo', group: 'system' },
  {
    label: 'nav.dashboard',
    icon: 'mdi:chart-pie',
    route: contextStore.projectId ? `/projects/${contextStore.projectId}/dashboard` : '',
    group: 'project',
  },
])

// ── Grouped navigation items ──────────────────────────────────────
interface NavGroup {
  id: string
  label: string
  items: typeof navItems.value
}

const groups = computed<NavGroup[]>(() => {
  const items = navItems.value
  const groupOrder = ['workspace', 'project', 'evolution', 'system']
  const isZh = getLocale().startsWith('zh')
  const groupLabels: Record<string, string> = isZh
    ? { workspace: '工作区', project: '当前项目', evolution: '进化中心', system: '系统' }
    : { workspace: 'Workspace', project: 'Current Project', evolution: 'Evolution Center', system: 'System' }
  return groupOrder
    .map((id) => ({
      id,
      label: groupLabels[id] || id,
      items: items.filter((item) => item.group === id),
    }))
    .filter((g) => g.items.length > 0)
})

function isActive(path: string): boolean {
  if (!path) return false
  if (path === '/') return route.path === '/'
  if (path === '/projects') return route.path === '/projects'
  return route.path.startsWith(path)
}

function handleNavClick(itemRoute: string) {
  if (!itemRoute) return
  router.push(itemRoute)
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

    <nav class="sidebar-nav" :aria-label="t('common.main_nav')">
      <template v-for="(group, gi) in groups" :key="group.id">
        <div v-if="gi > 0" class="nav-divider" aria-hidden="true"></div>
        <span class="nav-group-label">{{ group.label }}</span>
        <button
          v-for="item in group.items"
          :key="item.label"
          :class="['nav-item', { active: isActive(item.route || ''), disabled: !item.route }]"
          :disabled="!item.route"
          :aria-label="t(item.label)"
          @click="handleNavClick(item.route)"
        >
          <Icon :icon="item.icon" width="20" height="20" />
          <span>{{ t(item.label) }}</span>
        </button>
      </template>
    </nav>

    <div class="sidebar-footer">
      <LocaleSwitcher />
      <button class="theme-btn" :title="getThemeLabel(themeMode, t)" @click="cycleTheme" :aria-label="getThemeLabel(themeMode, t)">
        <Icon :icon="isDark ? 'mdi:weather-night' : (themeMode === 'auto' ? 'mdi:monitor-shimmer' : 'mdi:weather-sunny')" width="18" height="18" />
      </button>
      <div class="user-info" :title="authStore.user?.email">
        <div class="user-avatar">
          {{ (authStore.user?.full_name || authStore.user?.username || '?').charAt(0).toUpperCase() }}
        </div>
        <div class="user-meta">
          <span class="user-name">{{ authStore.user?.full_name || authStore.user?.username || '—' }}</span>
          <span v-if="authStore.user?.is_superuser" class="user-role">{{ t('common.admin') }}</span>
        </div>
      </div>
      <button class="logout-btn" :title="t('auth.logout')" :aria-label="t('auth.logout')" @click="handleLogout">
        <Icon icon="mdi:logout" width="18" height="18" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.sidebar {
  width: 100%;
  background: var(--color-sidebar);
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
  border-bottom: 1px solid rgba(255, 255, 255, 0.12);
  margin-bottom: 12px;
}

.sidebar-title {
  font-weight: 600;
  font-size: 16px;
}

/* ── Navigation ──────────────────────────────────────── */

.sidebar-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 8px;
}

/* Group label (section header) */
.nav-group-label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: rgba(255, 255, 255, 0.35);
  padding: 12px 14px 4px;
  user-select: none;
}

/* Divider line between groups */
.nav-divider {
  height: 1px;
  background: rgba(255, 255, 255, 0.1);
  margin: 6px 14px;
}

/* Individual nav item button */
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border: none;
  border-left: 3px solid transparent;
  border-radius: 0 var(--radius) var(--radius) 0;
  background: transparent;
  color: #cbd5e1;
  font-size: 14px;
  cursor: pointer;
  text-align: left;
  transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast);
  min-height: 40px;
  width: 100%;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #f1f5f9;
}

.nav-item.active {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
  border-left-color: var(--color-primary);
}

.nav-item.disabled,
.nav-item:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.nav-item.disabled:hover,
.nav-item:disabled:hover {
  background: transparent;
  color: #cbd5e1;
  border-left-color: transparent;
}

/* ── Footer (locale / theme / user / logout) ──────────── */

.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.12);
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
  border-radius: var(--radius-full);
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
  border-radius: var(--radius);
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
  flex-shrink: 0;
}

.logout-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #f87171;
}

.theme-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: var(--radius);
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
  flex-shrink: 0;
}

.theme-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: var(--color-primary);
}
</style>
