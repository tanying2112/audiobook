<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { Icon } from '@iconify/vue'
import { useI18n } from './i18n'
import Sidebar from './components/Sidebar.vue'

const route = useRoute()
const { t } = useI18n()
const isSidebarOpen = ref(false)

const isPublicPage = computed(() =>
  route.matched.some((record) => record.meta.public)
)

function toggleSidebar() {
  isSidebarOpen.value = !isSidebarOpen.value
}

function closeSidebar() {
  isSidebarOpen.value = false
}
</script>

<template>
  <!-- Public pages (login, register) - no sidebar, full screen -->
  <div v-if="isPublicPage" class="app-public">
    <router-view />
  </div>

  <!-- Authenticated layout with responsive sidebar -->
  <div v-else class="app-layout">
    <!-- Mobile header with hamburger -->
    <header class="mobile-header" :aria-label="t('common.main_nav')">
      <button
        class="hamburger-btn touch-target"
        @click="toggleSidebar"
        :aria-expanded="isSidebarOpen"
        aria-controls="sidebar-drawer"
        :aria-label="t('common.open_menu')"
      >
        <Icon icon="mdi:menu" width="24" height="24" />
      </button>
      <div class="mobile-title">
        <Icon icon="mdi:microphone" width="24" height="24" />
        <span class="sidebar-title">{{ t('sidebar.title') }}</span>
      </div>
    </header>

    <!-- Sidebar drawer (mobile) / fixed sidebar (desktop) -->
    <aside
      id="sidebar-drawer"
      class="sidebar"
      :class="{ open: isSidebarOpen }"
      :aria-label="t('common.sidebar_nav')"
    >
      <Sidebar @close="closeSidebar" />
    </aside>

    <!-- Overlay for mobile sidebar -->
    <div
      v-show="isSidebarOpen"
      class="sidebar-overlay"
      @click="closeSidebar"
      aria-hidden="true"
    ></div>

    <!-- Main content -->
    <main class="main-content" @click="closeSidebar">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
/* Public pages (login/register) */
.app-public {
  min-height: 100vh;
}

/* Authenticated layout */
.app-layout {
  display: flex;
  min-height: 100vh;
  overflow: hidden;
}

/* Mobile header - hidden on desktop */
.mobile-header {
  display: none;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 56px;
  background: var(--color-card-bg);
  border-bottom: 1px solid var(--color-border);
  z-index: 30;
  padding: 0 16px;
  align-items: center;
  justify-content: space-between;
}

.mobile-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  font-size: 16px;
  color: var(--color-text);
}

.hamburger-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  padding: 8px;
  border-radius: var(--radius);
  cursor: pointer;
  color: var(--color-text);
  transition: background var(--transition-fast);
}
.hamburger-btn:hover {
  background: var(--color-bg-tertiary);
}

/* Sidebar - desktop: fixed width, mobile: drawer */
.sidebar {
  width: 220px;
  flex-shrink: 0;
  background: var(--color-sidebar-bg);
  color: #e2e8f0;
  display: flex;
  flex-direction: column;
  z-index: 50;
  transition: transform 0.25s ease, box-shadow 0.25s ease;
}

/* Desktop: sidebar always visible */
@media (min-width: 768px) {
  .sidebar {
    position: sticky;
    top: 0;
    height: 100vh;
    overflow-y: auto;
    box-shadow: var(--shadow-lg);
  }
}

/* Mobile: sidebar as drawer */
@media (max-width: 767px) {
  .mobile-header {
    display: flex;
  }

  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    height: 100vh;
    max-width: 280px;
    width: 85vw;
    transform: translateX(-100%);
    box-shadow: var(--shadow-xl);
    z-index: 50;
  }

  .sidebar.open {
    transform: translateX(0);
  }

  /* Adjust main content for mobile header */
  .main-content {
    padding-top: 72px; /* header height + spacing */
  }
}

/* Main content */
.main-content {
  flex: 1;
  overflow-y: auto;
  background: var(--color-bg);
  transition: margin-left 0.25s ease;
}

@media (min-width: 768px) {
  .main-content {
    padding: 24px 28px;
  }
}

@media (max-width: 767px) {
  .main-content {
    padding: 16px;
  }
}

/* Overlay */
.sidebar-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.5);
  z-index: 40;
  opacity: 0;
  visibility: hidden;
  transition: opacity 0.2s ease, visibility 0.2s ease;
}

@media (max-width: 767px) {
  .sidebar-overlay {
    display: block;
  }
  .sidebar-overlay.visible {
    opacity: 1;
    visibility: visible;
  }
}

/* Reduce motion */
@media (prefers-reduced-motion: reduce) {
  .sidebar,
  .sidebar-overlay,
  .main-content {
    transition: none !important;
  }
}
</style>