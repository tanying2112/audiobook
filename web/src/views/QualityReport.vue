<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChapterStore } from '../stores/chapters'
import { useI18n } from '../i18n'
import { Icon } from '@iconify/vue'

const route = useRoute()
const router = useRouter()
const store = useChapterStore()
const { t } = useI18n()

const projectId = Number(route.params.projectId)
const filterStatus = ref<string>('all')

onMounted(async () => {
  await store.loadChapters(projectId)
})

const filteredChapters = computed(() => {
  if (filterStatus.value === 'all') return store.chapters
  return store.chapters.filter((ch) => (ch.status || 'pending') === filterStatus.value)
})

const stats = computed(() => {
  const total = store.chapters.length
  const completed = store.chapters.filter((ch) => ch.status === 'completed').length
  const error = store.chapters.filter((ch) => ch.status === 'error').length
  const pending = total - completed - error
  const completionRate = total > 0 ? Math.round((completed / total) * 100) : 0
  return { total, completed, error, pending, completionRate }
})

function goBack() {
  router.push(`/projects/${projectId}`)
}

function getStatusBadgeClass(status: string): string {
  const map: Record<string, string> = {
    completed: 'badge-success',
    pending: 'badge-warning',
    error: 'badge-danger',
  }
  return map[status?.toLowerCase()] || 'badge-muted'
}

function formatStatus(status: string): string {
  return t(`quality_report.${status || 'pending'}`)
}
</script>

<template>
  <div class="page-container quality-report">
    <header class="page-header">
      <button class="btn btn-ghost touch-target" @click="goBack">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        <span class="hidden-mobile">{{ t('common.back') }}</span>
      </button>
      <h1>{{ t('quality_report.title') }}</h1>
    </header>

    <section class="summary-cards grid grid-auto-fill gap-4 section">
      <div class="card card-hover" style="border-color: var(--color-primary); background: var(--color-primary-soft);">
        <span class="summary-value font-bold" style="font-size: 28px; color: var(--color-primary);">{{ stats.total }}</span>
        <span class="summary-label text-muted">{{ t('quality_report.total_chapters') }}</span>
      </div>
      <div class="card card-hover">
        <span class="summary-value font-bold text-success" style="font-size: 28px;">{{ stats.completed }}</span>
        <span class="summary-label text-muted">{{ t('quality_report.completed') }}</span>
      </div>
      <div class="card card-hover">
        <span class="summary-value font-bold text-warning" style="font-size: 28px;">{{ stats.pending }}</span>
        <span class="summary-label text-muted">{{ t('quality_report.pending') }}</span>
      </div>
      <div class="card card-hover">
        <span class="summary-value font-bold text-danger" style="font-size: 28px;">{{ stats.error }}</span>
        <span class="summary-label text-muted">{{ t('quality_report.error') }}</span>
      </div>
    </section>

    <section class="completion-bar-section card card-hover section">
      <div class="completion-header flex justify-between mb-4">
        <span class="font-medium">{{ t('quality_report.overall_completion') }}</span>
        <span class="completion-pct text-primary font-bold" style="font-variant-numeric: tabular-nums;">{{ stats.completionRate }}%</span>
      </div>
      <div class="completion-track" style="height: 8px; background: var(--color-border); border-radius: 99px; overflow: hidden;">
        <div class="completion-fill" :style="{ width: stats.completionRate + '%' }" style="height: 100%; background: linear-gradient(90deg, var(--color-primary), var(--color-success)); border-radius: 99px; transition: width 0.3s;"></div>
      </div>
    </section>

    <section class="filter-bar section">
      <div class="flex gap-2 flex-wrap">
        <button
          v-for="opt in [['all', 'common.all'], ['completed', 'quality_report.completed'], ['pending', 'quality_report.pending'], ['error', 'quality_report.error']]"
          :key="opt[0]"
          class="btn btn-outline btn-sm"
          :class="{ 'btn-primary': filterStatus === opt[0] }"
          @click="filterStatus = opt[0]"
        >{{ t(opt[1]) }}</button>
      </div>
    </section>

    <section class="chapter-quality-list">
      <div v-if="filteredChapters.length === 0" class="empty-state">
        <Icon icon="mdi:file-chart-outline" width="48" height="48" style="opacity: 0.4" />
        <p>{{ t('common.no_data') }}</p>
      </div>
      <div v-else class="grid gap-3">
        <div
          v-for="ch in filteredChapters"
          :key="ch.id"
          class="card card-hover quality-row flex items-center justify-between"
        >
          <div class="quality-row-info flex items-center gap-3">
            <Icon
              :icon="ch.status === 'completed' ? 'mdi:check-circle' : ch.status === 'error' ? 'mdi:alert-circle' : 'mdi:clock-outline'"
              :class="['status-icon', ch.status || 'pending', { 'text-success': ch.status === 'completed', 'text-danger': ch.status === 'error', 'text-warning': ch.status === 'pending' }]"
              width="20"
              height="20"
            />
            <span class="quality-row-title font-medium">{{ ch.title || t('chapter_timeline.chapter_fallback', { id: ch.chapter_number || ch.id }) }}</span>
          </div>
          <div class="quality-row-meta flex items-center gap-2">
            <span :class="getStatusBadgeClass(ch.status || 'pending')">{{ formatStatus(ch.status || 'pending') }}</span>
            <button
              class="btn btn-ghost btn-sm touch-target"
              @click="router.push(`/projects/${projectId}/chapters/${ch.id}`)"
            >
              {{ t('quality_report.view_details') }}
            </button>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.quality-report {
  max-width: 960px;
}

.summary-value {
  display: block;
  line-height: 1.2;
}
.summary-label {
  display: block;
  margin-top: 4px;
}

.status-icon.completed { color: var(--color-success); }
.status-icon.error { color: var(--color-danger); }
.status-icon.pending { color: var(--color-warning); }

.quality-row {
  padding: 12px 16px;
}

@media (max-width: 767px) {
  .grid-auto-fill {
    grid-template-columns: 1fr;
  }
  .filter-bar .btn {
    flex: 1;
    justify-content: center;
  }
}
</style>