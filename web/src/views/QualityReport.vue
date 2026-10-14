<template>
  <div class="page-container quality-report">
    <header class="page-header">
      <button class="btn btn-ghost touch-target" @click="goBack" aria-label="Back">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        <span class="hidden-mobile">{{ t('common.back') }}</span>
      </button>
      <h1>{{ t('quality_report.title') }}</h1>
    </header>

    <!-- Summary Cards using stat-value -->
    <section class="summary-grid section">
      <div class="card summary-card summary-card-primary">
        <span class="stat-value">{{ stats.total }}</span>
        <span class="summary-label text-muted">{{ t('quality_report.total_chapters') }}</span>
      </div>
      <div class="card summary-card">
        <span class="stat-value text-success">{{ stats.completed }}</span>
        <span class="summary-label text-muted">{{ t('quality_report.completed') }}</span>
      </div>
      <div class="card summary-card">
        <span class="stat-value text-warning">{{ stats.pending }}</span>
        <span class="summary-label text-muted">{{ t('quality_report.pending') }}</span>
      </div>
      <div class="card summary-card">
        <span class="stat-value text-danger">{{ stats.error }}</span>
        <span class="summary-label text-muted">{{ t('quality_report.error') }}</span>
      </div>
    </section>

    <!-- Completion Progress Bar -->
    <section class="card section">
      <div class="completion-header">
        <span class="font-medium">{{ t('quality_report.overall_completion') }}</span>
        <span class="completion-pct text-primary font-bold">{{ stats.completionRate }}%</span>
      </div>
      <div class="completion-track">
        <div class="completion-fill" :style="{ width: stats.completionRate + '%' }"></div>
      </div>
    </section>

    <!-- Filter using el-select -->
    <section class="filter-bar section">
      <el-select
        v-model="filterStatus"
        size="default"
        class="filter-select"
        aria-label="Filter by status"
      >
        <el-option value="all" :label="t('common.all')" />
        <el-option value="completed" :label="t('quality_report.completed')" />
        <el-option value="pending" :label="t('quality_report.pending')" />
        <el-option value="error" :label="t('quality_report.error')" />
      </el-select>
    </section>

    <!-- Chapter Quality List -->
    <section class="chapter-quality-list">
      <div v-if="filteredChapters.length === 0" class="empty-state">
        <Icon icon="mdi:file-chart-outline" width="48" height="48" class="empty-icon" />
        <p>{{ t('common.no_data') }}</p>
      </div>
      <div v-else class="quality-list">
        <div
          v-for="ch in filteredChapters"
          :key="ch.id"
          class="card quality-row"
        >
          <div class="quality-row-info">
            <Icon
              :icon="statusIcon(ch.status || 'pending')"
              :class="['status-icon', ch.status || 'pending']"
              width="20"
              height="20"
              aria-hidden="true"
            />
            <span class="quality-row-title font-medium">
              {{ ch.title || t('chapter_timeline.chapter_fallback', { id: ch.chapter_number || ch.id }) }}
            </span>
          </div>
          <div class="quality-row-actions">
            <span class="status-badge" :class="badgeClass(ch.status || 'pending')">
              {{ formatStatus(ch.status || 'pending') }}
            </span>
            <button
              class="btn btn-ghost btn-sm touch-target"
              :aria-label="t('quality_report.view_details')"
              @click="router.push(`/projects/${projectId}/chapters/${ch.id}`)"
            >
              <Icon icon="mdi:chevron-right" width="16" height="16" />
            </button>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

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

function statusIcon(status: string): string {
  const map: Record<string, string> = {
    completed: 'mdi:check-circle',
    error: 'mdi:alert-circle',
    pending: 'mdi:clock-outline',
  }
  return map[status?.toLowerCase()] || 'mdi:clock-outline'
}

function badgeClass(status: string): string {
  const map: Record<string, string> = {
    completed: 'status-badge-success',
    pending: 'status-badge-warning',
    error: 'status-badge-danger',
  }
  return map[status?.toLowerCase()] || 'status-badge-muted'
}

function formatStatus(status: string): string {
  return t(`quality_report.${status || 'pending'}`)
}
</script>

<style scoped>
.quality-report {
  max-width: 960px;
}

/* Summary grid */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
}
.summary-card {
  text-align: center;
  padding: 20px 16px;
}
.summary-card-primary {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
}
.summary-label {
  display: block;
  margin-top: 6px;
  font-size: 0.88rem;
}

/* Completion bar */
.completion-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.completion-pct {
  font-variant-numeric: tabular-nums;
}
.completion-track {
  height: 8px;
  background: var(--color-border);
  border-radius: var(--radius-full);
  overflow: hidden;
}
.completion-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary), var(--color-success));
  border-radius: var(--radius-full);
  transition: width 0.3s;
}

/* Filter */
.filter-select {
  width: 200px;
}

/* Empty state */
.empty-icon {
  opacity: 0.4;
  color: var(--color-text-muted);
}

/* Quality list */
.quality-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.quality-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  transition: border-color var(--transition);
}
.quality-row:hover {
  border-color: var(--color-border-strong);
}
.quality-row-info {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
}
.quality-row-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.quality-row-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* Status icons */
.status-icon.completed { color: var(--color-success); }
.status-icon.error { color: var(--color-danger); }
.status-icon.pending { color: var(--color-warning); }

/* Status badges (scoped to this component) */
.status-badge-success {
  background: var(--color-success-soft);
  color: var(--color-success);
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-size: 0.78rem;
  font-weight: 600;
}
.status-badge-warning {
  background: var(--color-warning-soft);
  color: var(--color-warning);
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-size: 0.78rem;
  font-weight: 600;
}
.status-badge-danger {
  background: var(--color-danger-soft);
  color: var(--color-danger);
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-size: 0.78rem;
  font-weight: 600;
}
.status-badge-muted {
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-size: 0.78rem;
  font-weight: 600;
}

/* Mobile */
@media (max-width: 767px) {
  .summary-grid {
    grid-template-columns: 1fr 1fr;
  }
  .filter-select {
    width: 100%;
  }
  .quality-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }
  .quality-row-actions {
    width: 100%;
    justify-content: space-between;
  }
}
</style>
