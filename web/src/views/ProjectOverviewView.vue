<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import { useI18n } from '../i18n'
import {
  fetchProject,
  fetchChapters,
  fetchCharacters,
  getAutoRunStatus,
  type AutoRunStatusResponse,
} from '../api'
import type { Project, Chapter, Character } from '../types'
import PipelineStages from '../components/overview/PipelineStages.vue'
import ChapterList from '../components/overview/ChapterList.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const projectId = Number(route.params.id)
const project = ref<Project | null>(null)
const chapters = ref<Chapter[]>([])
const characters = ref<Character[]>([])
const autoRun = ref<AutoRunStatusResponse | null>(null)
const loading = ref(false)

// ── Pipeline status tag ──────────────────────────────────────────
const pipelineStatus = computed(() => {
  const s = autoRun.value?.status
  if (s === 'running') return { label: t('common.running'), color: 'var(--color-primary)', bg: 'var(--color-primary-soft)' }
  if (s === 'completed') return { label: t('common.completed'), color: 'var(--color-success)', bg: 'var(--color-success-soft)' }
  if (s === 'failed') return { label: t('common.failed'), color: 'var(--color-danger)', bg: 'var(--color-danger-soft)' }
  return { label: t('overview.notStarted'), color: 'var(--color-text-muted)', bg: 'var(--color-bg-tertiary)' }
})

// ── Quick actions ────────────────────────────────────────────────
interface QuickAction {
  icon: string
  label: string
  target: string
  color: string
}

const quickActions = computed<QuickAction[]>(() => [
  { icon: 'mdi:play-circle-outline', label: t('overview.runPipeline'), target: 'auto-run', color: 'var(--color-primary)' },
  { icon: 'mdi:download-outline', label: t('overview.export'), target: 'export', color: 'var(--color-success)' },
  { icon: 'mdi:account-group-outline', label: t('overview.links.characters'), target: 'characters', color: 'var(--color-info)' },
  { icon: 'mdi:chart-line', label: t('overview.links.dashboard'), target: 'dashboard', color: 'var(--color-warning)' },
  { icon: 'mdi:microphone-settings', label: t('overview.links.voiceClone'), target: 'voice-clone', color: 'var(--color-primary)' },
  { icon: 'mdi:translate', label: t('overview.links.translation'), target: 'translation', color: 'var(--color-success)' },
])

// ── Meta info fields ────────────────────────────────────────────
const metaFields = computed(() => {
  if (!project.value) return []
  return [
    { key: 'author', icon: 'mdi:account-outline', value: project.value.author },
    { key: 'genre', icon: 'mdi:book-open-page-variant-outline', value: project.value.genre },
    { key: 'language', icon: 'mdi:translate', value: project.value.language },
    { key: 'difficulty', icon: 'mdi:signal-cellular-3', value: project.value.difficulty },
  ].filter((f) => !!f.value)
})

function go(target: string) {
  const map: Record<string, string> = {
    'auto-run': `/projects/${projectId}/auto-run`,
    export: `/projects/${projectId}/export`,
    publish: `/projects/${projectId}/publish`,
    characters: `/projects/${projectId}/characters`,
    chapters: `/projects/${projectId}/chapters/${chapters.value[0]?.id ?? 1}`,
    quality: `/projects/${projectId}/quality`,
    translation: `/projects/${projectId}/translation`,
    'voice-clone': `/projects/${projectId}/voice-clone`,
    dashboard: `/projects/${projectId}/dashboard`,
    'audio-segments': `/projects/${projectId}/audio-segments`,
    runs: `/projects/${projectId}/runs`,
    knowledge: `/projects/${projectId}/knowledge`,
  }
  if (map[target]) router.push(map[target])
}

async function load() {
  loading.value = true
  try {
    const [p, ch, chars, ar] = await Promise.all([
      fetchProject(projectId).catch(() => null),
      fetchChapters(projectId).catch(() => [] as Chapter[]),
      fetchCharacters(projectId).catch(() => [] as Character[]),
      getAutoRunStatus(projectId).catch(() => null),
    ])
    project.value = p
    chapters.value = ch
    characters.value = chars
    autoRun.value = ar
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="overview-view" v-loading="loading">
    <template v-if="project">
      <!-- ── Header ─────────────────────────────────────────── -->
      <div class="ov-header">
        <div class="ov-title-block">
          <h1 class="ov-title">{{ project.title }}</h1>
          <div class="ov-meta" v-if="metaFields.length">
            <span v-for="field in metaFields" :key="field.key" class="meta-pill">
              <Icon :icon="field.icon" width="14" height="14" />
              {{ field.value }}
            </span>
          </div>
        </div>
        <span class="pipeline-badge" :style="{ color: pipelineStatus.color, background: pipelineStatus.bg }">
          {{ pipelineStatus.label }}
        </span>
      </div>

      <!-- ── Pipeline stages ────────────────────────────────── -->
      <div class="card section-card">
        <div class="section-head">
          <Icon icon="mdi:road-variant" width="20" height="20" class="text-primary" />
          <span class="section-title">{{ t('overview.stageProgress') }}</span>
        </div>
        <PipelineStages :auto-run="autoRun" />
      </div>

      <!-- ── Quick actions ──────────────────────────────────── -->
      <div class="card section-card">
        <div class="section-head">
          <Icon icon="mdi:lightning-bolt-outline" width="20" height="20" class="text-primary" />
          <span class="section-title">{{ t('overview.quickLinks') }}</span>
        </div>
        <div class="action-grid">
          <button
            v-for="action in quickActions"
            :key="action.target"
            class="action-btn"
            @click="go(action.target)"
            :aria-label="action.label"
          >
            <div class="action-icon" :style="{ color: action.color, background: action.color + '14' }">
              <Icon :icon="action.icon" width="22" height="22" />
            </div>
            <span class="action-label">{{ action.label }}</span>
          </button>
        </div>
      </div>

      <!-- ── Recent chapters ────────────────────────────────── -->
      <div class="card section-card" v-if="chapters.length > 0">
        <div class="section-head">
          <Icon icon="mdi:format-list-numbered" width="20" height="20" class="text-primary" />
          <span class="section-title">{{ t('overview.chapters') }}</span>
          <span class="section-count">{{ chapters.length }}</span>
        </div>
        <ChapterList :chapters="chapters" :project-id="projectId" @navigate="(p) => router.push(p)" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.overview-view {
  padding: 24px;
  max-width: 960px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* ── Header ──────────────────────────────────────────────── */

.ov-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.ov-title-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ov-title {
  font-size: 22px;
  font-weight: 600;
  color: var(--color-text);
  margin: 0;
}

.ov-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.meta-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-secondary);
  background: var(--color-bg-tertiary);
  padding: 3px 10px;
  border-radius: var(--radius-full);
}

.pipeline-badge {
  font-size: 12px;
  font-weight: 600;
  padding: 4px 12px;
  border-radius: var(--radius-full);
  white-space: nowrap;
  flex-shrink: 0;
  align-self: center;
}

/* ── Section card ─────────────────────────────────────────── */

.section-card {
  padding: 20px;
}

.section-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.section-count {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-muted);
  background: var(--color-bg-tertiary);
  padding: 1px 8px;
  border-radius: var(--radius-full);
  margin-left: auto;
}

.text-primary {
  color: var(--color-primary);
}

/* ── Quick action grid ───────────────────────────────────── */

.action-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 12px;
}

.action-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 14px 8px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-surface);
  cursor: pointer;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.action-btn:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-sm);
}

.action-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.action-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius);
  display: flex;
  align-items: center;
  justify-content: center;
}

.action-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text);
  text-align: center;
  line-height: 1.3;
}

/* ── Responsive ───────────────────────────────────────────── */

@media (max-width: 600px) {
  .overview-view {
    padding: 16px;
    gap: 16px;
  }

  .ov-header {
    flex-direction: column;
    gap: 12px;
  }

  .action-grid {
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
  }

  .section-card {
    padding: 16px;
  }
}
</style>
