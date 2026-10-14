<template>
  <div class="page-container feedback-insights">
    <div class="page-header">
      <h1>{{ t('feedbackInsights.title') }}</h1>
      <button :class="['btn btn-outline touch-target', loading ? 'btn-loading' : '']" @click="load" :aria-label="t('common.refresh')">
        {{ t('common.refresh') }}
      </button>
    </div>

    <div class="grid grid-2">
      <!-- Funnel -->
      <section class="card">
        <h2 class="card-title">{{ t('feedbackInsights.funnel') }}</h2>
        <div v-if="funnel" class="funnel">
          <div
            v-for="step in funnelSteps"
            :key="step.key"
            class="funnel-step"
          >
            <span class="funnel-label">{{ t(step.label) }}</span>
            <div class="funnel-bar-wrapper">
              <div
                class="funnel-bar"
                :style="{ width: funnelPct(step.value) }"
              />
            </div>
            <span class="funnel-value">{{ step.value }}</span>
          </div>
        </div>
        <div v-else-if="!loading" class="empty-state">{{ t('common.noData') }}</div>
      </section>

      <!-- Patterns -->
      <section class="card">
        <h2 class="card-title">{{ t('feedbackInsights.patterns') }}</h2>
        <div v-if="heatmap?.top_patterns?.length" class="top-patterns">
          <span v-for="p in heatmap.top_patterns" :key="p" class="badge badge-muted">{{ p }}</span>
        </div>
        <div v-if="heatmap?.patterns?.length" class="pattern-table table-responsive">
          <table class="table">
            <thead>
              <tr>
                <th scope="col">{{ t('feedbackInsights.pattern') }}</th>
                <th scope="col">{{ t('feedbackInsights.stage') }}</th>
                <th scope="col">{{ t('feedbackInsights.count') }}</th>
                <th scope="col">{{ t('feedbackInsights.severity') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in heatmap.patterns.slice(0, 20)" :key="row.tag">
                <td>{{ row.tag }}</td>
                <td>{{ row.stage }}</td>
                <td>{{ row.count }}</td>
                <td>
                  <span :class="severityBadgeClass(row?.severity)">{{ row?.severity || '—' }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else-if="!loading" class="empty-state">{{ t('common.noData') }}</div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from '../i18n'
import { fetchFeedbackFunnel, fetchPatternHeatmap, type FeedbackFunnel, type PatternHeatmapResponse } from '../api'

const { t } = useI18n()
const funnel = ref<FeedbackFunnel | null>(null)
const heatmap = ref<PatternHeatmapResponse | null>(null)
const loading = ref(false)

const funnelSteps = computed(() => {
  if (!funnel.value) return []
  const f = funnel.value
  return [
    { key: 'total', label: 'feedbackInsights.totalFeedback', value: f.total_feedback },
    { key: 'analyzed', label: 'feedbackInsights.analyzed', value: f.analyzed_count },
    { key: 'triggered', label: 'feedbackInsights.triggered', value: f.triggered_upgrade_count },
    { key: 'promoted', label: 'feedbackInsights.promoted', value: f.promotion_passed_count },
    { key: 'published', label: 'feedbackInsights.published', value: f.published_count },
  ]
})

function funnelPct(value: number): string {
  const total = funnel.value?.total_feedback || 0
  if (total <= 0) return '0%'
  return `${Math.round((value / total) * 100)}%`
}

function severityBadgeClass(severity?: string | null): string {
  if (severity === 'high') return 'badge badge-danger'
  if (severity === 'medium' || severity === 'warning') return 'badge badge-warning'
  return 'badge badge-info'
}

async function load() {
  loading.value = true
  try {
    const [f, h] = await Promise.all([
      fetchFeedbackFunnel().catch(() => null),
      fetchPatternHeatmap().catch(() => null),
    ])
    funnel.value = f
    heatmap.value = h
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.feedback-insights {
  max-width: 1200px;
}

.funnel-step {
  display: grid;
  grid-template-columns: 130px 1fr 60px;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.funnel-bar-wrapper {
  background: var(--color-bg-tertiary);
  border-radius: 4px;
  height: 18px;
  overflow: hidden;
}
.funnel-bar {
  height: 100%;
  background: var(--color-primary);
  border-radius: 4px;
  min-width: 2px;
}
.funnel-value {
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  font-size: 14px;
}

.top-patterns {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}

/* Responsive */
@media (max-width: 767px) {
  .funnel-step {
    grid-template-columns: 1fr;
    gap: 4px;
  }
  .funnel-label {
    text-align: left;
  }
}
</style>
