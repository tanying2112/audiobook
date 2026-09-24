<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
// Tree-shaken echarts with LAZY LOADING: 仅在访问 Dashboard 时加载 echarts(~1MB)
// 使用动态 import 实现代码分割
import { useI18n } from '../i18n'
import { fetchProjectMetrics, fetchMetricsHistory, fetchProjectsWithMetrics, type ProjectMetrics } from '../api'

// ECharts lazy loading - 仅在 DashboardView 挂载时加载
let echartsCore: any = null

async function loadECharts() {
  if (echartsCore) return // Already loaded
  
  // Dynamic imports for code splitting
  const [core, charts, components, renderers] = await Promise.all([
    import('echarts/core'),
    import('echarts/charts'),
    import('echarts/components'),
    import('echarts/renderers'),
  ])
  
  echartsCore = core
  
  // Register required components
  core.use([
    charts.PieChart,
    charts.BarChart,
    charts.LineChart,
    charts.GaugeChart,
    components.TitleComponent,
    components.TooltipComponent,
    components.LegendComponent,
    components.GridComponent,
    renderers.CanvasRenderer,
  ])
}

const route = useRoute()
const { t } = useI18n()

const projectId = Number(route.params.projectId) || 1
const chapterIndex = Number(route.query.chapter) || undefined

const metrics = ref<ProjectMetrics | null>(null)
const history = ref<any[]>([])
const projects = ref<any[]>([])
const selectedProjectId = ref(projectId)
const loading = ref(false)
const error = ref<string>('')

// ECharts instances
const costChart = ref<any>(null)
const latencyChart = ref<any>(null)
const providerCostChart = ref<any>(null)
const rtfChart = ref<any>(null)
const historyChart = ref<any>(null)
let refreshTimer: ReturnType<typeof setInterval> | null = null

const costChartRef = ref<HTMLElement | null>(null)
const latencyChartRef = ref<HTMLElement | null>(null)
const providerCostChartRef = ref<HTMLElement | null>(null)
const rtfChartRef = ref<HTMLElement | null>(null)
const historyChartRef = ref<HTMLElement | null>(null)

// Cost Pie Chart
function initCostChart(el: HTMLElement): void {
  costChart.value = echartsCore.init(el)
  costChart.value.setOption({
    title: { text: t('dashboard.cost_distribution'), left: 'center', top: 12, textStyle: { fontSize: 16, fontWeight: 500 } },
    tooltip: { trigger: 'item', formatter: '{a} <br/>{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', left: 'left', top: 'middle', data: [] },
    series: [{
      name: t('dashboard.cost_usd'), type: 'pie', radius: ['40%', '70%'], avoidLabelOverlap: false, data: [],
      emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.5)' } }
    }]
  })
  costChart.value.resize()
}

// Latency Horizontal Bar Chart
function initLatencyChart(el: HTMLElement): void {
  latencyChart.value = echartsCore.init(el)
  latencyChart.value.setOption({
    title: { text: t('dashboard.latency_leaderboard'), left: 'center', top: 12, textStyle: { fontSize: 16, fontWeight: 500 } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: '{b}: {c} ms' },
    grid: { left: '20%', right: '5%', top: 50, bottom: 20, containLabel: true },
    xAxis: { type: 'value', name: t('dashboard.latency_ms'), boundaryGap: [0, 0.1], axisLabel: { formatter: '{value} ms' } },
    yAxis: { type: 'category', data: [], axisLabel: { interval: 0 }, inverse: true },
    series: [{ name: t('dashboard.latency_ms'), type: 'bar', data: [], itemStyle: { color: (params: any) => params.data?.success ? '#4BC0C0' : '#FF6384' }, label: { show: true, position: 'right', formatter: (p: any) => `${p.value} ms` } }]
  })
  latencyChart.value.resize()
}

// Provider Cost Stacked Bar
function initProviderCostChart(el: HTMLElement): void {
  providerCostChart.value = echartsCore.init(el)
  providerCostChart.value.setOption({
    title: { text: t('dashboard.provider_cost_breakdown'), left: 'center', top: 12, textStyle: { fontSize: 16, fontWeight: 500 } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (params: any[]) => { let result = `${params[0].axisValue}<br/>`; params.forEach((p: any) => { result += `${p.seriesName}: $${p.value.toFixed(6)}<br/>` }); return result } },
    legend: { data: [], bottom: 0 },
    grid: { left: '8%', right: '5%', top: 50, bottom: 60, containLabel: true },
    xAxis: { type: 'value', name: t('dashboard.cost_usd') },
    yAxis: { type: 'category', data: [], axisLabel: { interval: 0 } },
    series: []
  })
  providerCostChart.value.resize()
}

// RTF Gauge Chart
function initRtfChart(el: HTMLElement): void {
  rtfChart.value = echartsCore.init(el)
  rtfChart.value.setOption({
    series: [{ type: 'gauge', startAngle: 225, endAngle: -45, min: 0, max: 2, splitNumber: 8, radius: '85%',
      axisLine: { lineStyle: { width: 22, color: [[0.5, '#22c55e'], [1.0, '#f59e0b'], [1.5, '#f97316'], [2.0, '#ef4444']] } },
      pointer: { show: true, length: '70%', width: 6 },
      detail: { valueAnimation: true, formatter: '{value}', fontSize: 24, fontWeight: 'bold', color: '#1f2937' },
      axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
      data: [{ value: 0, name: t('dashboard.rtf') }],
      progress: { show: true, width: 22, roundCap: true }
    }]
  })
  rtfChart.value.resize()
}

// History Line Chart
function initHistoryChart(el: HTMLElement): void {
  historyChart.value = echartsCore.init(el)
  historyChart.value.setOption({
    title: { text: t('dashboard.cost_history'), left: 'center', top: 12, textStyle: { fontSize: 16, fontWeight: 500 } },
    tooltip: { trigger: 'axis', formatter: (params: any[]) => { let result = `${params[0].axisValue}<br/>`; params.forEach(p => { result += `${p.seriesName}: $${p.value.toFixed(4)}<br/>` }); return result } },
    legend: { data: [], bottom: 0 },
    grid: { left: '8%', right: '5%', top: 50, bottom: 40, containLabel: true },
    xAxis: { type: 'category', data: [], axisLabel: { formatter: (v: string) => v.substring(5, 10) } },
    yAxis: { type: 'value', name: t('dashboard.cost_usd'), axisLabel: { formatter: '{value}' } },
    series: []
  })
  historyChart.value.resize()
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
  costChart.value?.dispose()
  latencyChart.value?.dispose()
  providerCostChart.value?.dispose()
  rtfChart.value?.dispose()
  historyChart.value?.dispose()
  costChart.value = latencyChart.value = providerCostChart.value = rtfChart.value = historyChart.value = null
}

const refresh = async (): Promise<void> => {
  await Promise.all([fetchMetrics(), fetchHistory()])
  updateCharts()
}

const updateCharts = (): void => {
  if (!metrics.value || !echartsCore) return

  const m = metrics.value
  const providers = m.cost_accounting?.providers || {}

  // Update cost pie chart
  if (costChart.value) {
    const costData = Object.entries(providers)
      .filter(([, p]) => p.cost_usd > 0)
      .map(([, p], i) => ({
        value: p.cost_usd,
        name: `${p.provider}:${p.model}`,
        itemStyle: { color: ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40', '#C9CBCF'][i % 7] }
      }))
    costChart.value.setOption({ series: [{ data: costData }], legend: { data: costData.map(d => d.name) } })
  }

  // Update latency bar chart
  if (latencyChart.value && m.latency_profiles?.stage_wall_times_ms) {
    const sorted = Object.entries(m.latency_profiles.stage_wall_times_ms)
      .map(([name, s]) => ({ name, duration: s.duration_ms, success: s.success }))
      .sort((a, b) => b.duration - a.duration)
      .slice(0, 10)
    latencyChart.value.setOption({
      yAxis: { data: sorted.map(s => s.name) },
      series: [{ data: sorted.map(s => ({ value: s.duration, success: s.success })) }]
    })
  }

  // Update provider cost stacked bar
  if (providerCostChart.value) {
    const providerNames = Object.entries(providers).map(([, p]) => `${p.provider}:${p.model}`)
    const providerCosts = Object.entries(providers).map(([, p]) => p.cost_usd)
    const series = providerNames.map((p, i) => ({
      name: p,
      type: 'bar',
      stack: 'total',
      emphasis: { focus: 'series' },
      data: [providerCosts[i]],
      itemStyle: { color: ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40', '#C9CBCF'][i % 7] },
    }))
    providerCostChart.value.setOption({ yAxis: { data: providerNames }, series })
  }

  // Update RTF gauge
  if (rtfChart.value && m.latency_profiles?.real_time_factor !== undefined) {
    rtfChart.value.setOption({ series: [{ data: [{ value: Math.min(m.latency_profiles.real_time_factor, 2), name: t('dashboard.rtf') }] }] })
  }
}

// Lifecycle
onMounted(async () => {
  await loadECharts()
  await fetchProjects()
  await refresh()
  
  // Initialize charts after DOM ready
  nextTick(() => {
    if (costChartRef.value) initCostChart(costChartRef.value)
    if (latencyChartRef.value) initLatencyChart(latencyChartRef.value)
    if (providerCostChartRef.value) initProviderCostChart(providerCostChartRef.value)
    if (rtfChartRef.value) initRtfChart(rtfChartRef.value)
    if (historyChartRef.value) initHistoryChart(historyChartRef.value)
  })

  // Auto-refresh every 30s
  refreshTimer = setInterval(refresh, 30000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  destroyCharts()
})

watch(selectedProjectId, () => {
  refresh()
}, { immediate: false })
</script>

<template>
  <div class="page-container dashboard-view">
    <header class="page-header">
      <div class="flex items-center gap-4">
        <h1>{{ t('dashboard.title') }}</h1>
        <span class="badge badge-muted">{{ t('dashboard.project') }} #{{ selectedProjectId }}</span>
        <span v-if="chapterIndex !== undefined" class="badge badge-info">{{ t('dashboard.chapter_filter') }} #{{ chapterIndex }}</span>
      </div>
    </header>

    <div v-if="loading" class="loading-state section">
      <div class="spinner"></div>
      <span>{{ t('dashboard.loading') }}</span>
    </div>

    <div v-else-if="error" class="alert alert-error section">{{ error }}</div>

    <template v-else>
      <!-- KPI Cards -->
      <section class="kpi-section section">
        <div class="card card-hover kpi-card">
          <div class="kpi-icon text-primary"><Icon icon="mdi:currency-usd" width="24" height="24" /></div>
          <div class="kpi-value font-bold" style="font-size: 24px;">${{ (metrics?.cost_accounting?.total_cost_usd || 0).toFixed(4) }}</div>
          <div class="kpi-label text-muted">{{ t('dashboard.total_cost') }}</div>
        </div>
        <div class="card card-hover kpi-card">
          <div class="kpi-icon text-success"><Icon icon="mdi:timer" width="24" height="24" /></div>
          <div class="kpi-value font-bold" style="font-size: 24px;">{{ (metrics?.latency_profiles?.real_time_factor || 0).toFixed(2) }}x</div>
          <div class="kpi-label text-muted">{{ t('dashboard.avg_rtf') }}</div>
        </div>
        <div class="card card-hover kpi-card">
          <div class="kpi-icon text-warning"><Icon icon="mdi:clock" width="24" height="24" /></div>
          <div class="kpi-value font-bold" style="font-size: 24px;">{{ Object.values(metrics?.latency_profiles?.stage_wall_times_ms || {}).reduce((sum, s) => sum + s.duration_ms, 0) }}ms</div>
          <div class="kpi-label text-muted">{{ t('dashboard.total_latency') }}</div>
        </div>
        <div class="card card-hover kpi-card">
          <div class="kpi-icon text-info"><Icon icon="mdi:chart-line" width="24" height="24" /></div>
          <div class="kpi-value font-bold" style="font-size: 24px;">{{ history.length }}</div>
          <div class="kpi-label text-muted">{{ t('dashboard.history_days') }}</div>
        </div>
      </section>

      <!-- Chart Row 1: Cost Distribution + Latency Leaderboard -->
      <div class="chart-row section">
        <div class="card card-hover" style="min-height: 320px;">
          <div ref="costChartRef" style="width: 100%; height: 100%; min-height: 300px;"></div>
        </div>
        <div class="card card-hover" style="min-height: 320px;">
          <div ref="latencyChartRef" style="width: 100%; height: 100%; min-height: 300px;"></div>
        </div>
      </div>

      <!-- Chart Row 2: Provider Cost Breakdown + RTF Gauge -->
      <div class="chart-row section">
        <div class="card card-hover" style="min-height: 320px;">
          <div ref="providerCostChartRef" style="width: 100%; height: 100%; min-height: 300px;"></div>
        </div>
        <div class="card card-hover" style="min-height: 320px;">
          <div ref="rtfChartRef" style="width: 100%; height: 100%; min-height: 300px;"></div>
        </div>
      </div>

      <!-- History Chart -->
      <section class="card card-hover section" style="min-height: 320px;">
        <div ref="historyChartRef" style="width: 100%; height: 100%; min-height: 300px;"></div>
      </section>

      <!-- Project Selector -->
      <section class="card card-hover section">
        <h2 class="card-title">{{ t('dashboard.select_project') }}</h2>
        <div class="flex items-center gap-4 flex-wrap">
          <div class="flex-1" style="min-width: 200px;">
            <select v-model="selectedProjectId" class="form-control" @change="refresh">
              <option v-for="p in projects" :key="p.project_id" :value="p.project_id">
                {{ p.title }} ({{ t('dashboard.total_cost') }}: ${{ p.total_cost_usd?.toFixed(4) || 0 }})
              </option>
            </select>
          </div>
          <div style="min-width: 200px;">
            <select v-model="chapterIndex" class="form-control" @change="refresh" style="min-width: 200px;">
              <option :value="null">{{ t('dashboard.latest_all_chapters') }}</option>
              <option v-for="i in 10" :key="i" :value="i">
                {{ t('dashboard.chapter', { num: i }) }}
              </option>
            </select>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.dashboard-view {
  max-width: 1400px;
}

.dashboard-grid { display: grid; gap: 24px; }
.chart-row { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 24px; }
.kpi-section { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
.metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }
.kpi-card { 
  min-height: 100px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-align: center;
  padding: 16px;
}
.kpi-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius);
  background: var(--color-primary-soft);
  color: var(--color-primary);
}
.kpi-value {
  line-height: 1.2;
}
.kpi-label {
  font-size: 13px;
}

/* Desktop only overrides */
@media (max-width: 1000px) { 
  .chart-row { grid-template-columns: 1fr; } 
  .kpi-section { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 600px) { 
  .kpi-section { grid-template-columns: 1fr; }
}
</style>