<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { useI18n } from '../i18n'
import { fetchProjectMetrics, fetchMetricsHistory, fetchProjectsWithMetrics, type ProjectMetrics } from '../api'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const projectId = Number(route.params.projectId) || 1
const chapterIndex = Number(route.query.chapter) || undefined

const metrics = ref<ProjectMetrics | null>(null)
const history = ref<any[]>([])
const projects = ref<any[]>([])
const selectedProjectId = ref(projectId)
const loading = ref(false)
const error = ref<string>('')

let costChart: echarts.ECharts | null = null
let latencyChart: echarts.ECharts | null = null
let providerCostChart: echarts.ECharts | null = null
let rtfChart: echarts.ECharts | null = null
let historyChart: echarts.ECharts | null = null
let refreshTimer: ReturnType<typeof setInterval> | null = null

const costChartRef = ref<HTMLElement | null>(null)
const latencyChartRef = ref<HTMLElement | null>(null)
const providerCostChartRef = ref<HTMLElement | null>(null)
const rtfChartRef = ref<HTMLElement | null>(null)
const historyChartRef = ref<HTMLElement | null>(null)

// Cost Pie Chart
function initCostChart(el: HTMLElement): void {
  costChart = echarts.init(el)
  costChart.setOption({
    title: { text: t('dashboard.cost_distribution'), left: 'center', top: 12, textStyle: { fontSize: 16, fontWeight: 500 } },
    tooltip: { trigger: 'item', formatter: '{a} <br/>{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', left: 'left', top: 'middle', data: [] },
    series: [{
      name: t('dashboard.cost_usd'), type: 'pie', radius: ['40%', '70%'], avoidLabelOverlap: false, data: [],
      emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.5)' } }
    }]
  })
  costChart.resize()
}

// Latency Horizontal Bar Chart
function initLatencyChart(el: HTMLElement): void {
  latencyChart = echarts.init(el)
  latencyChart.setOption({
    title: { text: t('dashboard.latency_leaderboard'), left: 'center', top: 12, textStyle: { fontSize: 16, fontWeight: 500 } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: '{b}: {c} ms' },
    grid: { left: '20%', right: '5%', top: 50, bottom: 20, containLabel: true },
    xAxis: { type: 'value', name: t('dashboard.latency_ms'), boundaryGap: [0, 0.1], axisLabel: { formatter: '{value} ms' } },
    yAxis: { type: 'category', data: [], axisLabel: { interval: 0 }, inverse: true },
    series: [{ name: t('dashboard.latency_ms'), type: 'bar', data: [], itemStyle: { color: (params: any) => params.data?.success ? '#4BC0C0' : '#FF6384' }, label: { show: true, position: 'right', formatter: (p: any) => `${p.value} ms` } }]
  })
  latencyChart.resize()
}

// Provider Cost Stacked Bar
function initProviderCostChart(el: HTMLElement): void {
  providerCostChart = echarts.init(el)
  providerCostChart.setOption({
    title: { text: t('dashboard.provider_cost_breakdown'), left: 'center', top: 12, textStyle: { fontSize: 16, fontWeight: 500 } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (params: any[]) => { let result = `${params[0].axisValue}<br/>`; params.forEach((p: any) => { result += `${p.seriesName}: $${p.value.toFixed(6)}<br/>` }); return result } },
    legend: { data: [], bottom: 0 },
    grid: { left: '8%', right: '5%', top: 50, bottom: 60, containLabel: true },
    xAxis: { type: 'value', name: t('dashboard.cost_usd') },
    yAxis: { type: 'category', data: [], axisLabel: { interval: 0 } },
    series: []
  })
  providerCostChart.resize()
}

// RTF Gauge Chart
function initRtfChart(el: HTMLElement): void {
  rtfChart = echarts.init(el)
  rtfChart.setOption({
    series: [{ type: 'gauge', startAngle: 225, endAngle: -45, min: 0, max: 2, splitNumber: 8, radius: '85%',
      axisLine: { lineStyle: { width: 22, color: [[0.5, '#22c55e'], [1.0, '#f59e0b'], [1.5, '#f97316'], [2.0, '#ef4444']] } },
      pointer: { show: true, length: '70%', width: 6 },
      detail: { valueAnimation: true, formatter: '{value}', fontSize: 24, fontWeight: 'bold', color: '#1f2937' },
      axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
      data: [{ value: 0, name: t('dashboard.rtf') }],
      progress: { show: true, width: 22, roundCap: true }
    }]
  })
  rtfChart.resize()
}

// History Line Chart
function initHistoryChart(el: HTMLElement): void {
  historyChart = echarts.init(el)
  historyChart.setOption({
    title: { text: t('dashboard.cost_history'), left: 'center', top: 12, textStyle: { fontSize: 16, fontWeight: 500 } },
    tooltip: { trigger: 'axis', formatter: (params: any[]) => { let result = `${params[0].axisValue}<br/>`; params.forEach(p => { result += `${p.seriesName}: $${p.value.toFixed(4)}<br/>` }); return result } },
    legend: { data: [], bottom: 0 },
    grid: { left: '8%', right: '5%', top: 50, bottom: 40, containLabel: true },
    xAxis: { type: 'category', data: [], axisLabel: { formatter: (v: string) => v.substring(5, 10) } },
    yAxis: { type: 'value', name: t('dashboard.cost_usd'), axisLabel: { formatter: '{value}' } },
    series: []
  })
  historyChart.resize()
}

// Data Fetching
const fetchMetrics = async (): Promise<void> => {
  loading.value = true
  error.value = ''
  try {
    const res = await fetchProjectMetrics(selectedProjectId.value, chapterIndex)
    metrics.value = res
  } catch (e: any) {
    error.value = e.response?.data?.detail || e.message || 'Failed to load metrics'
    console.error('Failed to fetch metrics:', e)
  } finally {
    loading.value = false
  }
}

const fetchHistory = async (): Promise<void> => {
  try {
    const res = await fetchMetricsHistory(selectedProjectId.value, 30)
    history.value = res.history || []
  } catch (e) { console.error('Failed to fetch history:', e) }
}

const fetchProjects = async (): Promise<void> => {
  try {
    const res = await fetchProjectsWithMetrics()
    projects.value = res.projects || []
    if (!projects.value.find((p: any) => p.project_id === selectedProjectId.value) && projects.value.length > 0) {
      selectedProjectId.value = projects.value[0].project_id
    }
  } catch (e) { console.error('Failed to fetch projects:', e) }
}

function destroyCharts(): void {
  costChart?.dispose()
  latencyChart?.dispose()
  providerCostChart?.dispose()
  rtfChart?.dispose()
  historyChart?.dispose()
  costChart = latencyChart = providerCostChart = rtfChart = historyChart = null
}

function updateCharts(): void {
  if (!metrics.value) return
  const m = metrics.value
  nextTick(() => {
    const providers = m.cost_accounting?.providers || {}
    const costData = Object.entries(providers)
      .filter(([, p]: [string, any]) => p.cost_usd > 0 || p.total_tokens > 0)
      .map(([, p]: [string, any], i: number) => ({
        name: `${p.provider}:${p.model}`,
        value: p.cost_usd,
        itemStyle: { color: ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40', '#C9CBCF'][i % 7] }
      }))
    costChart?.setOption({ legend: { data: costData.map(d => d.name) }, series: [{ data: costData }] })

    const providerNames = costData.map(d => d.name)
    const providerCosts = costData.map(d => d.value)
    providerCostChart?.setOption({
      legend: { data: providerNames },
      yAxis: { data: providerNames },
      series: [{ name: t('dashboard.cost_usd'), type: 'bar', stack: 'total', data: providerCosts, itemStyle: { color: (params: any) => costData[params.dataIndex]?.itemStyle?.color } }]
    })

    const stages = m.latency_profiles?.stage_wall_times_ms || {}
    const latencyEntries = Object.entries(stages)
      .map(([name, s]: [string, any]) => ({ name, duration: s.duration_ms, success: s.success }))
      .sort((a, b) => b.duration - a.duration)
    latencyChart?.setOption({ yAxis: { data: latencyEntries.map(e => e.name) }, series: [{ data: latencyEntries.map(e => ({ value: e.duration, success: e.success })) }] })

    const rtf = m.latency_profiles?.real_time_factor || 0
    rtfChart?.setOption({ series: [{ data: [{ value: rtf, name: t('dashboard.rtf') }] }] })

    if (history.value.length > 0) {
      const dates = history.value.map((h: any) => h.timestamp?.substring(5, 10) || '')
      const costs = history.value.map((h: any) => h.total_cost_usd || 0)
      historyChart?.setOption({ legend: { data: [t('dashboard.cost_usd')] }, xAxis: { data: dates }, series: [{ name: t('dashboard.cost_usd'), type: 'line', data: costs, smooth: true }] })
    }
  })
}

const costTotal = computed(() => {
  if (!metrics.value?.cost_accounting?.providers) return 0
  return Object.values(metrics.value.cost_accounting.providers).reduce((sum: number, p: any) => sum + (p.cost_usd || 0), 0)
})

const totalTokens = computed(() => {
  if (!metrics.value?.cost_accounting?.providers) return 0
  return Object.values(metrics.value.cost_accounting.providers).reduce((sum: number, p: any) => sum + (p.prompt_tokens || 0) + (p.completion_tokens || 0), 0)
})

const providerBreakdown = computed(() => {
  if (!metrics.value?.cost_accounting?.providers) return []
  return Object.entries(metrics.value.cost_accounting.providers)
    .map(([key, p]: [string, any]) => ({ key, ...p }))
    .filter(p => p.call_count > 0 || p.cost_usd > 0)
    .sort((a, b) => b.cost_usd - a.cost_usd)
})

const latencyStages = computed(() => {
  if (!metrics.value?.latency_profiles?.stage_wall_times_ms) return []
  return Object.entries(metrics.value.latency_profiles.stage_wall_times_ms)
    .map(([name, s]: [string, any]) => ({ name, duration: s.duration_ms, success: s.success }))
    .sort((a, b) => b.duration - a.duration)
})

const rtfValue = computed(() => metrics.value?.latency_profiles?.real_time_factor || 0)
const synthesisRate = computed(() => metrics.value?.latency_profiles?.synthesis_rate_ratio || 0)
const totalAudioSec = computed(() => (metrics.value?.latency_profiles?.total_audio_duration_ms || 0) / 1000)

const resilience = computed(() => metrics.value?.resilience_metrics || { llm: { total_calls: 0, total_retries: 0, total_fallbacks: 0 }, tts: { total_segments: 0, successful_segments: 0, failed_segments: 0 } })

const ttsSuccessRate = computed(() => {
  const tts = resilience.value.tts
  if (tts.total_segments === 0) return '0'
  return (tts.successful_segments / tts.total_segments * 100).toFixed(1)
})

const llmStats = computed(() => resilience.value.llm)

onMounted(async () => {
  await fetchProjects()
  await fetchMetrics()
  await fetchHistory()

  costChartRef.value && initCostChart(costChartRef.value)
  latencyChartRef.value && initLatencyChart(latencyChartRef.value)
  providerCostChartRef.value && initProviderCostChart(providerCostChartRef.value)
  rtfChartRef.value && initRtfChart(rtfChartRef.value)
  historyChartRef.value && initHistoryChart(historyChartRef.value)

  updateCharts()

  refreshTimer = setInterval(fetchMetrics, 30000)
})

onUnmounted(() => {
  destroyCharts()
  if (refreshTimer) clearInterval(refreshTimer)
})

watch(metrics, updateCharts, { deep: true })

function handleProjectChange(): void {
  fetchMetrics()
  fetchHistory()
  router.push({ path: `/projects/${selectedProjectId.value}/dashboard`, query: chapterIndex ? { chapter: chapterIndex } : {} })
}

function formatNumber(n: number): string { return n.toLocaleString() }
function formatCost(n: number): string { return `$${n.toFixed(4)}` }
function formatRmb(n: number): string { return `¥${(n * 7.2).toFixed(2)}` }

function refetch(): void { fetchMetrics(); fetchHistory() }
</script>

<template>
  <div class="dashboard-container">
    <header class="dashboard-header">
      <h1>{{ t('dashboard.title') }}</h1>
      <div class="header-controls">
        <select v-model="selectedProjectId" @change="handleProjectChange" class="project-select">
          <option v-for="p in projects" :key="p.project_id" :value="p.project_id">
            {{ p.title }} (ID: {{ p.project_id }})
          </option>
        </select>
        <button @click="refetch" :disabled="loading" class="btn btn-primary">
          {{ loading ? t('dashboard.refreshing') : t('dashboard.refresh') }}
        </button>
      </div>
    </header>

    <div v-if="error" class="error-banner">{{ error }}</div>

    <div v-else-if="loading && !metrics" class="loading-state">
      <div class="spinner"></div>
      <p>{{ t('dashboard.loading') }}</p>
    </div>

    <div v-else class="dashboard-grid">
      <section class="kpi-section" v-if="metrics">
        <div class="kpi-card">
          <span class="kpi-label">{{ t('dashboard.total_cost_usd') }}</span>
          <span class="kpi-value">{{ formatCost(costTotal) }}</span>
          <span class="kpi-sub">{{ formatRmb(costTotal) }}</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">{{ t('dashboard.total_tokens') }}</span>
          <span class="kpi-value">{{ formatNumber(totalTokens) }}</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">{{ t('dashboard.total_audio') }}</span>
          <span class="kpi-value">{{ totalAudioSec.toFixed(1) }}s</span>
        </div>
        <div class="kpi-card success">
          <span class="kpi-label">{{ t('dashboard.rtf') }}</span>
          <span class="kpi-value">{{ rtfValue.toFixed(2) }}</span>
          <span class="kpi-sub">{{ rtfValue < 1 ? '⚡ 实时' : rtfValue < 1.5 ? '⚠️ 接近实时' : '🐢 慢' }}</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">{{ t('dashboard.synthesis_rate') }}</span>
          <span class="kpi-value">{{ (synthesisRate * 100).toFixed(1) }}%</span>
        </div>
        <div class="kpi-card success">
          <span class="kpi-label">{{ t('dashboard.tts_success_rate') }}</span>
          <span class="kpi-value">{{ ttsSuccessRate }}%</span>
        </div>
      </section>

      <section class="chart-row">
        <div class="chart-card" ref="costChartRef" style="height: 360px;"></div>
        <div class="chart-card" ref="latencyChartRef" style="height: 360px;"></div>
      </section>

      <section class="chart-row">
        <div class="chart-card" ref="providerCostChartRef" style="height: 360px;"></div>
        <div class="chart-card" ref="rtfChartRef" style="height: 360px;"></div>
      </section>

      <section class="table-section" v-if="providerBreakdown.length > 0">
        <h2>{{ t('dashboard.provider_cost_detail') }}</h2>
        <div class="table-responsive">
          <table>
            <thead>
              <tr>
                <th>{{ t('dashboard.provider') }}</th>
                <th>{{ t('dashboard.model') }}</th>
                <th>{{ t('dashboard.prompt_tokens') }}</th>
                <th>{{ t('dashboard.completion_tokens') }}</th>
                <th>{{ t('dashboard.cost_usd') }}</th>
                <th>{{ t('dashboard.cost_rmb') }}</th>
                <th>{{ t('dashboard.calls') }}</th>
                <th>{{ t('dashboard.avg_latency') }}</th>
                <th>{{ t('dashboard.success_rate') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in providerBreakdown" :key="p.key">
                <td>{{ p.provider }}</td>
                <td>{{ p.model }}</td>
                <td>{{ formatNumber(p.prompt_tokens) }}</td>
                <td>{{ formatNumber(p.completion_tokens) }}</td>
                <td class="cost">{{ formatCost(p.cost_usd) }}</td>
                <td class="cost">{{ formatRmb(p.cost_usd) }}</td>
                <td>{{ p.call_count }}</td>
                <td>{{ p.avg_latency_ms.toFixed(0) }}ms</td>
                <td :class="p.success_rate >= 0.95 ? 'success' : (p.success_rate >= 0.8 ? 'warn' : 'danger')">
                  {{ (p.success_rate * 100).toFixed(1) }}%
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="table-section" v-if="latencyStages.length > 0">
        <h2>{{ t('dashboard.stage_latency_detail') }}</h2>
        <div class="table-responsive">
          <table>
            <thead>
              <tr>
                <th>{{ t('dashboard.rank') }}</th>
                <th>{{ t('dashboard.stage') }}</th>
                <th>{{ t('dashboard.duration_ms') }}</th>
                <th>{{ t('dashboard.status') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(stage, i) in latencyStages" :key="stage.name" :class="stage.success ? 'success' : 'failed'">
                <td class="rank">{{ i + 1 }}</td>
                <td class="stage-name">{{ stage.name }}</td>
                <td class="duration">{{ stage.duration }} ms</td>
                <td class="status">{{ stage.success ? '✅' : '❌' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="metrics-section" v-if="metrics">
        <h2>{{ t('dashboard.resilience_metrics') }}</h2>
        <div class="metrics-grid">
          <div class="metric-box">
            <span class="metric-label">{{ t('dashboard.llm_total_calls') }}</span>
            <span class="metric-value">{{ llmStats.total_calls || 0 }}</span>
          </div>
          <div class="metric-box warn">
            <span class="metric-label">{{ t('dashboard.llm_retries') }}</span>
            <span class="metric-value">{{ llmStats.total_retries || 0 }}</span>
          </div>
          <div class="metric-box danger">
            <span class="metric-label">{{ t('dashboard.llm_fallbacks') }}</span>
            <span class="metric-value">{{ llmStats.total_fallbacks || 0 }}</span>
          </div>
          <div class="metric-box">
            <span class="metric-label">{{ t('dashboard.tts_segments') }}</span>
            <span class="metric-value">{{ resilience.tts?.total_segments || 0 }}</span>
          </div>
          <div class="metric-box success">
            <span class="metric-label">{{ t('dashboard.tts_success') }}</span>
            <span class="metric-value">{{ resilience.tts?.successful_segments || 0 }}</span>
          </div>
          <div class="metric-box danger">
            <span class="metric-label">{{ t('dashboard.tts_failed') }}</span>
            <span class="metric-value">{{ resilience.tts?.failed_segments || 0 }}</span>
          </div>
        </div>
      </section>

      <section class="chart-section" v-if="history.length > 0">
        <h2>{{ t('dashboard.cost_history') }}</h2>
        <div ref="historyChartRef" class="chart-card" style="height: 300px;"></div>
      </section>
    </div>

    <div v-if="metrics?.latency_profiles" class="chapter-selector">
      <label>{{ t('dashboard.select_chapter') }}: </label>
      <select v-model="chapterIndex" @change="handleProjectChange">
        <option :value="null">{{ t('dashboard.latest_all_chapters') }}</option>
        <option v-for="i in 10" :key="i" :value="i">
          {{ t('dashboard.chapter', { num: i }) }}
        </option>
      </select>
    </div>
  </div>
</template>

<style scoped>
.dashboard-container { max-width: 1600px; margin: 0 auto; padding: 24px; font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }
.dashboard-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--vp-c-divider, #e8e8e8); flex-wrap: wrap; gap: 12px; }
.dashboard-header h1 { margin: 0; font-size: 1.75rem; font-weight: 600; }
.header-controls { display: flex; gap: 12px; align-items: center; }
.project-select { padding: 8px 12px; border: 1px solid var(--vp-c-divider, #e8e8e8); border-radius: 6px; background: var(--vp-c-bg, #fff); font-size: 0.9rem; min-width: 280px; }
.btn { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 0.9rem; font-weight: 500; transition: opacity 0.2s; }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-primary { background: var(--vp-c-brand, #42b883); color: white; }
.btn-primary:hover:not(:disabled) { opacity: 0.9; }
.error-banner { padding: 12px 16px; background: #fef2f2; color: #dc2626; border-radius: 8px; margin-bottom: 16px; }
.loading-state { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 60px; text-align: center; }
.spinner { width: 40px; height: 40px; border: 3px solid var(--vp-c-divider, #e8e8e8); border-top-color: var(--vp-c-brand, #42b883); border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.dashboard-grid { display: grid; gap: 24px; }
.kpi-section { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
.kpi-card { background: var(--vp-c-bg-soft, #fafafa); border: 1px solid var(--vp-c-divider, #e8e8e8); border-radius: 12px; padding: 20px; display: flex; flex-direction: column; gap: 4px; }
.kpi-card.success { border-color: #22c55e; background: #f0fdf4; }
.kpi-label { font-size: 0.8rem; color: var(--vp-c-text-2, #787878); text-transform: uppercase; letter-spacing: 0.05em; }
.kpi-value { font-size: 1.75rem; font-weight: 700; color: var(--vp-c-text-1, #333); }
.kpi-sub { font-size: 0.75rem; color: var(--vp-c-text-2, #787878); }

.chart-row { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 24px; }
@media (max-width: 1000px) { .chart-row { grid-template-columns: 1fr; } }
.chart-card { background: var(--vp-c-bg-soft, #fafafa); border: 1px solid var(--vp-c-divider, #e8e8e8); border-radius: 12px; overflow: hidden; }

.table-section, .metrics-section, .chart-section { margin-bottom: 32px; }
.table-section h2, .metrics-section h2, .chart-section h2 { margin: 0 0 16px; font-size: 1.1rem; font-weight: 600; color: var(--vp-c-text-1, #333); }
.table-responsive { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--vp-c-divider, #e8e8e8); }
th { background: var(--vp-c-bg, #fff); font-weight: 600; color: var(--vp-c-text-2, #787878); }
td.cost { color: var(--vp-c-brand, #42b883); font-weight: 600; }
td.success { color: #22c55e; }
td.warn { color: #f59e0b; }
td.danger { color: #ef4444; }
.rank { font-weight: 700; color: var(--vp-c-brand, #42b883); width: 50px; }
.stage-name { font-family: monospace; }
.duration { font-variant-numeric: tabular-nums; }

.metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }
.metric-box { background: var(--vp-c-bg, #fff); border: 1px solid var(--vp-c-divider, #e8e8e8); border-radius: 8px; padding: 16px; display: flex; flex-direction: column; gap: 4px; }
.metric-label { font-size: 0.8rem; color: var(--vp-c-text-2, #787878); }
.metric-value { font-size: 1.5rem; font-weight: 700; color: var(--vp-c-text-1, #333); }
.metric-box.warn .metric-value { color: #f59e0b; }
.metric-box.danger .metric-value { color: #ef4444; }
.metric-box.success .metric-value { color: #22c55e; }

.chapter-selector { margin-top: 24px; padding: 16px; background: var(--vp-c-bg-soft, #fafafa); border-radius: 8px; display: flex; align-items: center; gap: 12px; }
.chapter-selector label { font-weight: 500; }
.chapter-selector select { padding: 6px 12px; border: 1px solid var(--vp-c-divider, #e8e8e8); border-radius: 6px; background: var(--vp-c-bg, #fff); font-size: 0.9rem; }
</style>