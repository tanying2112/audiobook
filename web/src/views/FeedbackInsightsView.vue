<template>
  <div class="feedback-insights">
    <div class="header">
      <h1>{{ t('feedbackInsights.title') }}</h1>
      <el-button :loading="loading" @click="load">{{ t('common.refresh') }}</el-button>
    </div>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card class="section" v-loading="loading">
          <template #header>{{ t('feedbackInsights.funnel') }}</template>
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
          <el-empty v-else-if="!loading" :description="t('common.noData')" />
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card class="section" v-loading="loading">
          <template #header>{{ t('feedbackInsights.patterns') }}</template>
          <div v-if="heatmap?.top_patterns?.length" class="top-patterns">
            <el-tag v-for="p in heatmap.top_patterns" :key="p" class="pattern-tag" size="small">{{ p }}</el-tag>
          </div>
          <el-table
            v-if="heatmap?.patterns?.length"
            :data="heatmap.patterns.slice(0, 20)"
            size="small"
          >
            <el-table-column prop="tag" :label="t('feedbackInsights.pattern')" min-width="160" />
            <el-table-column prop="stage" :label="t('feedbackInsights.stage')" width="120" />
            <el-table-column prop="count" :label="t('feedbackInsights.count')" width="90" />
            <el-table-column :label="t('feedbackInsights.severity')" width="110">
              <template #default="{ row }">
                <el-tag :type="severityType(row?.severity)" size="small">{{ row?.severity || '—' }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else-if="!loading" :description="t('common.noData')" />
        </el-card>
      </el-col>
    </el-row>
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

function severityType(severity?: string | null): 'danger' | 'warning' | 'info' {
  if (severity === 'high') return 'danger'
  if (severity === 'medium' || severity === 'warning') return 'warning'
  return 'info'
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
.feedback-insights { padding: 24px; max-width: 1200px; margin: 0 auto; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.section { margin-bottom: 16px; }
.funnel-step { display: grid; grid-template-columns: 130px 1fr 60px; align-items: center; gap: 10px; margin-bottom: 12px; }
.funnel-bar-wrapper { background: var(--el-fill-color-light); border-radius: 4px; height: 18px; overflow: hidden; }
.funnel-bar { height: 100%; background: var(--el-color-primary); border-radius: 4px; min-width: 2px; }
.funnel-value { text-align: right; font-variant-numeric: tabular-nums; }
.top-patterns { margin-bottom: 12px; }
.pattern-tag { margin-right: 6px; margin-bottom: 6px; }
</style>
