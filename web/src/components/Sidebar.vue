<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import { useI18n } from '../i18n'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const navItems = [
  { label: 'nav.projects', icon: 'mdi:bookshelf', route: '/' },
  { label: 'nav.project_management', icon: 'mdi:book-open-variant', route: '/projects', pattern: '/projects/' },
  { label: 'nav.feedback_entry', icon: 'mdi:comment-edit-outline', route: '/feedback' },
  { label: 'nav.harness_console', icon: 'mdi:tune-variant', route: '/harness' },
]

function isActive(path: string): boolean {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar-header">
      <Icon icon="mdi:microphone" width="28" height="28" />
      <span class="sidebar-title">{{ t('sidebar.title') }}</span>
    </div>
    <nav class="sidebar-nav">
      <button
        v-for="item in navItems"
        :key="item.label"
        :class="['nav-btn', { active: isActive(item.route || item.pattern || '') }]"
        @click="router.push(item.route || '/')"
      >
        <Icon :icon="item.icon" width="20" height="20" />
        <span>{{ t(item.label) }}</span>
      </button>
    </nav>
    <div class="sidebar-footer">
      <Icon icon="mdi:cog-outline" width="20" height="20" />
      <span>{{ t('sidebar.settings') }}</span>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 220px;
  background: var(--color-sidebar-bg, #1e293b);
  color: #e2e8f0;
  display: flex;
  flex-direction: column;
  padding: 16px 0;
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
  padding: 10px 12px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #cbd5e1;
  font-size: 14px;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
}
.nav-btn:hover {
  background: #334155;
  color: #f1f5f9;
}
.nav-btn.active {
  background: #3b82f6;
  color: #fff;
}
.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 16px 0;
  border-top: 1px solid #334155;
  margin-top: 12px;
  font-size: 14px;
  color: #94a3b8;
}
</style>
