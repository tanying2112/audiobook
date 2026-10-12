<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h1>{{ t('sop.title') }}</h1>
      </div>
      <div class="header-actions">
        <span
          class="badge"
          :class="bgStatus.running ? 'badge-success' : 'badge-muted'"
        >
          {{ t('sop.background') }}: {{ bgStatus.running ? t('common.on') : t('common.off') }}
        </span>
        <button class="btn btn-outline btn-sm" @click="toggleBackground" :aria-label="bgStatus.running ? t('sop.stopBackground') : t('sop.startBackground')">
          {{ bgStatus.running ? t('sop.stopBackground') : t('sop.startBackground') }}
        </button>
      </div>
    </div>

    <div class="sop-layout">
      <!-- Genre sidebar -->
      <div class="card sop-sidebar">
        <div class="card-title">{{ t('sop.genres') }}</div>
        <nav class="genre-nav" role="listbox" :aria-label="t('sop.genres')">
          <button
            v-for="g in genres"
            :key="g"
            class="genre-item"
            :class="{ active: g === activeGenre }"
            role="option"
            :aria-selected="g === activeGenre"
            @click="onSelectGenre(g)"
          >
            {{ g }}
          </button>
        </nav>
        <div v-if="genres.length === 0" class="empty-state">
          {{ t('common.noData') }}
        </div>
      </div>

      <!-- Rules panel -->
      <div class="card sop-rules" v-loading="loadingRules">
        <div class="rules-header">
          <h2 class="card-title">{{ activeGenre || t('sop.selectGenre') }}</h2>
          <button
            v-if="activeGenre"
            class="btn btn-primary btn-sm"
            :disabled="reflecting"
            @click="onReflect"
          >
            <span v-if="reflecting" class="spinner"></span>
            {{ t('sop.reflectNow') }}
          </button>
        </div>

        <template v-if="rules">
          <div v-for="(val, key) in rules.rules" :key="key" class="rule-block">
            <h4>{{ key }}</h4>
            <pre class="rule-code">{{ JSON.stringify(val, null, 2) }}</pre>
          </div>
          <div v-if="Object.keys(rules.rules || {}).length === 0" class="empty-state">
            {{ t('sop.noRules') }}
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from '../i18n'
import {
  fetchSopGenres,
  fetchSopGenreRules,
  triggerSopReflection,
  fetchSopBackgroundStatus,
  startSopBackground,
  stopSopBackground,
  type SopGenreRules,
} from '../api/sop'

const { t } = useI18n()
const genres = ref<string[]>([])
const activeGenre = ref('')
const rules = ref<SopGenreRules | null>(null)
const loadingRules = ref(false)
const reflecting = ref(false)
const bgStatus = ref<{ running?: boolean }>({})

async function load() {
  try {
    const [g, st] = await Promise.all([
      fetchSopGenres().catch(() => ({ genres: [] as string[] })),
      fetchSopBackgroundStatus().catch(() => ({})),
    ])
    genres.value = g.genres ?? []
    bgStatus.value = st
    if (genres.value.length && !activeGenre.value) onSelectGenre(genres.value[0])
  } catch { /* degraded */ }
}

async function onSelectGenre(g: string) {
  activeGenre.value = g
  loadingRules.value = true
  try {
    rules.value = await fetchSopGenreRules(g)
  } catch {
    rules.value = null
  } finally {
    loadingRules.value = false
  }
}

async function onReflect() {
  if (!activeGenre.value) return
  reflecting.value = true
  try {
    await triggerSopReflection(activeGenre.value)
    ElMessage.success(t('sop.reflectTriggered'))
    await onSelectGenre(activeGenre.value)
  } finally {
    reflecting.value = false
  }
}

async function toggleBackground() {
  if (bgStatus.value.running) {
    await stopSopBackground()
  } else {
    await startSopBackground()
  }
  bgStatus.value = await fetchSopBackgroundStatus().catch(() => ({}))
}

onMounted(load)
</script>

<style scoped>
.sop-layout {
  display: grid;
  grid-template-columns: 240px 1fr;
  gap: 16px;
}

.sop-sidebar {
  padding: 0;
  overflow: hidden;
}

.genre-nav {
  display: flex;
  flex-direction: column;
  max-height: 500px;
  overflow-y: auto;
}

.genre-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 10px 16px;
  border: none;
  background: none;
  font-size: 14px;
  font-family: inherit;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
  border-left: 3px solid transparent;
}

.genre-item:hover {
  background: var(--color-primary-soft);
  color: var(--color-text);
}

.genre-item.active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-weight: 500;
  border-left-color: var(--color-primary);
}

.sop-rules {
  overflow: hidden;
}

.rules-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 8px;
}

.rules-header .card-title {
  margin: 0;
}

.rule-block {
  margin-bottom: 16px;
}

.rule-block h4 {
  margin: 0 0 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.rule-code {
  background: var(--color-bg-tertiary);
  padding: 12px;
  border-radius: var(--radius);
  overflow: auto;
  font-size: 13px;
  line-height: 1.5;
  font-family: var(--font-mono);
  color: var(--color-text-secondary);
  margin: 0;
}

@media (max-width: 767px) {
  .sop-layout {
    grid-template-columns: 1fr;
  }

  .genre-nav {
    flex-direction: row;
    max-height: none;
    overflow-x: auto;
    overflow-y: hidden;
    gap: 4px;
    padding: 8px;
  }

  .genre-item {
    white-space: nowrap;
    border-left: none;
    border-bottom: 2px solid transparent;
    padding: 6px 12px;
  }

  .genre-item.active {
    border-left-color: transparent;
    border-bottom-color: var(--color-primary);
  }
}
</style>
