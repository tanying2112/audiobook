<template>
  <div class="monitoring-dashboard">
    <header class="dashboard-header">
      <h1>📊 监控仪表盘</h1>
      <div class="header-controls">
        <select v-model="selectedProjectId" @change="fetchMetrics" class="project-select">
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.title }} (ID: {{ p.id }})</option>
        </select>
        <button @click="refreshData" :disabled="loading" class="btn btn-primary">
          {{ loading ? '刷新中...' : '刷新数据' }}
        </button>
      </div>
    </header>

    <div v-if="loading" class="loading-overlay">
      <div class="spinner"></div>
      <p>正在加载遥测数据...</p>
    </div>

    <div v-else-if="!metrics" class="empty-state">
      <p>暂无遥测数据。请运行流水线生成 metrics_summary.json</p>
    </div>

    <div v-else class="dashboard-grid">
      <!-- Cost Analysis Pie Chart -->
      <section class="chart-card">
        <h2>💰 成本分析饼图</h2>
        <div class="chart-container">
          <canvas ref="costChart"></canvas>
        </div>
        <div class="chart-legend" v-if="costChartData.labels.length > 0">
          <div v-for="(label, i) in costChartData.labels" :key="label" class="legend-item">
            <span class="legend-color" :style="{ backgroundColor: costChartData.datasets[0].backgroundColor[i] }"></span>
            <span class="legend-label">{{ label }}</span>
            <span class="legend-value">${{ costChartData.datasets[0].data[i].toFixed(4) }}</span>
            <span class="legend-pct">({{ ((costChartData.datasets[0].data[i] / costTotal) * 100).toFixed(1) }}%)</span>
          </div>
          <div class="legend-total">
            <strong>总计: ${{ costTotal.toFixed(4) }}</strong>
          </div>
        </div>
        <div v-if="costChartData.labels.length === 0" class="no-data">暂无成本数据</div>
      </section>

      <!-- Stage Latency Leaderboard -->
      <section class="chart-card">
        <h2>⏱️ 阶段延迟排行榜</h2>
        <div class="chart-container">
          <canvas ref="latencyChart"></canvas>
        </div>
        <div class="leaderboard-table" v-if="latencyChartData.labels.length > 0">
          <table>
            <thead>
              <tr>
                <th>排名</th>
                <th>阶段</th>
                <th>延迟 (ms)</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(stage, i) in sortedStages" :key="stage.name" :class="stage.success ? 'success' : 'failed'">
                <td class="rank">{{ i + 1 }}</td>
                <td class="stage-name">{{ stage.name }}</td>
                <td class="latency">{{ stage.duration.toFixed(0) }} ms</td>
                <td class="status">{{ stage.success ? '✅ 成功' : '❌ 失败' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="latencyChartData.labels.length === 0" class="no-data">暂无阶段延迟数据</div>
      </section>

      <!-- Resilience Metrics -->
      <section class="metrics-card">
        <h2>🛡️ 复原力指标</h2>
        <div class="metrics-grid">
          <div class="metric-box">
            <span class="metric-label">LLM 总调用</span>
            <span class="metric-value">{{ resilience.llm.total_calls }}</span>
          </div>
          <div class="metric-box">
            <span class="metric-label">LLM 重试次数</span>
            <span class="metric-value warn">{{ resilience.llm.total_retries }}</span>
          </div>
          <div class="metric-box">
            <span class="metric-label">LLM 回退次数</span>
            <span class="metric-value danger">{{ resilience.llm.total_fallbacks }}</span>
          </div>
          <div class="metric-box">
            <span class="metric-label">TTS 总片段</span>
            <span class="metric-value">{{ resilience.tts.total_segments }}</span>
          </div>
          <div class="metric-box">
            <span class="metric-label">TTS 成功率</span>
            <span class="metric-value success">{{ (resilience.tts.total_segments > 0 ? (resilience.tts.successful_segments / resilience.tts.total_segments * 100).toFixed(1) : 0) }}%</span>
          </div>
          <div class="metric-box">
            <span class="metric-label">合成率比</span>
            <span class="metric-value">{{ latency.synthesis_rate_ratio.toFixed(2) }}</span>
          </div>
          <div class="metric-box">
            <span class="metric-label">实时因子</span>
            <span class="metric-value">{{ latency.real_time_factor.toFixed(2) }}</span>
          </div>
          <div class="metric-box">
            <span class="metric-label">总音频时长</span>
            <span class="metric-value">{{ (latency.total_audio_duration_ms / 1000).toFixed(1) }} 秒</span>
          </div>
        </div>
      </section>

      <!-- Provider Cost Breakdown -->
      <section class="metrics-card">
        <h2>📦 Provider 成本明细</h2>
        <div class="provider-table" v-if="providerBreakdown.length > 0">
          <table>
            <thead>
              <tr>
                <th>Provider</th>
                <th>Model</th>
                <th>Prompt Tokens</th>
                <th>Completion Tokens</th>
                <th>成本 ($)</th>
                <th>调用次数</th>
                <th>平均延迟</th>
                <th>成功率</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in providerBreakdown" :key="p.key">
                <td>{{ p.provider }}</td>
                <td>{{ p.model }}</td>
                <td>{{ p.prompt_tokens.toLocaleString() }}</td>
                <td>{{ p.completion_tokens.toLocaleString() }}</td>
                <td class="cost">${{ p.cost_usd.toFixed(6) }}</td>
                <td>{{ p.call_count }}</td>
                <td>{{ p.avg_latency_ms.toFixed(0) }} ms</td>
                <td :class="p.success_rate >= 0.95 ? 'success' : (p.success_rate >= 0.8 ? 'warn' : 'danger')">
                  {{ (p.success_rate * 100).toFixed(1) }}%
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="no-data">暂无 Provider 数据</div>
      </section>
    </div>

    <!-- Pipeline Metadata -->
    <section class="metadata-section" v-if="metrics?.metadata">
      <h2>📋 流水线元数据</h2>
      <div class="metadata-grid">
        <div><strong>Project ID:</strong> {{ metrics.metadata.project_id }}</div>
        <div><strong>Pipeline ID:</strong> {{ metrics.metadata.pipeline_id }}</div>
        <div><strong>开始时间:</strong> {{ formatDate(metrics.metadata.started_at) }}</div>
        <div><strong>结束时间:</strong> {{ metrics.metadata.ended_at ? formatDate(metrics.metadata.ended_at) : '进行中' }}</div>
        <div><strong>总耗时:</strong> {{ metrics.metadata.duration_ms.toFixed(0) }} ms</div>
        <div><strong>状态:</strong> <span :class="metrics.metadata.success ? 'success' : 'danger'">{{ metrics.metadata.success ? '✅ 成功' : '❌ 失败' }}</span></div>
        <div v-if="metrics.metadata.error"><strong>错误:</strong> {{ metrics.metadata.error }}</div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, computed, nextTick } from 'vue'
import { Chart, registerables } from 'chart.js'
import axios from 'axios'

Chart.register(...registerables)

const selectedProjectId = ref<number>(1)
const projects = ref<Array<{id: number, title: string}>>([])
const metrics = ref<any>(null)
const loading = ref(false)
const costChart = ref<Chart | null>(null)
const latencyChart = ref<Chart | null>(null)

const fetchProjects = async () => {
  try {
    const res = await axios.get('/api/monitoring/projects')
    projects.value = res.data.projects || res.data
    if (projects.value.length > 0) {
      selectedProjectId.value = projects.value[0].id
    }
  } catch (e) {
    console.error('Failed to fetch projects:', e)
  }
}

const fetchMetrics = async () => {
  loading.value = true
  try {
    const res = await axios.get(`/api/monitoring/projects/${selectedProjectId.value}/metrics`)
    metrics.value = res.data
    destroyCharts()
    await nextTick()
    initCharts()
  } catch (e: any) {
    console.error('Failed to fetch metrics:', e)
    metrics.value = null
  } finally {
    loading.value = false
  }
}

const initCharts = () => {
  if (!metrics.value) return

  // Cost Analysis Pie Chart
  const costCtx = (document.querySelector('.chart-card canvas') as HTMLCanvasElement)?.getContext('2d')
  if (costCtx && costChartData.value.labels.length > 0) {
    costChart.value = new Chart(costCtx, {
      type: 'pie',
      data: costChartData.value,
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const value = ctx.raw as number
                const total = costChartData.value.datasets[0].data.reduce((a: number, b: number) => a + b, 0)
                return `${ctx.label}: $${value.toFixed(4)} (${((value / total) * 100).toFixed(1)}%)`
              }
            }
          }
        }
      }
    })
  }

  // Latency Horizontal Bar Chart
  const latencyCtx = (document.querySelectorAll('.chart-card canvas')[1] as HTMLCanvasElement)?.getContext('2d')
  if (latencyCtx && latencyChartData.value.labels.length > 0) {
    latencyChart.value = new Chart(latencyCtx, {
      type: 'bar',
      data: latencyChartData.value,
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.label}: ${ctx.raw} ms`
            }
          }
        },
        scales: {
          x: { beginAtZero: true, title: { display: true, text: '延迟 (ms)' } }
        }
      }
    })
  }
}

const destroyCharts = () => {
  costChart.value?.destroy()
  latencyChart.value?.destroy()
  costChart.value = null
  latencyChart.value = null
}

const costChartData = computed(() => {
  if (!metrics.value?.cost_accounting?.providers) {
    return { labels: [], datasets: [{ data: [], backgroundColor: [] }] }
  }
  const providers = metrics.value.cost_accounting.providers
  const labels: string[] = []
  const data: number[] = []
  const colors = ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40', '#C9CBCF']

  Object.entries(providers).forEach(([_key, p]: [string, any], _i) => {
    if (p.cost_usd > 0 || p.total_tokens > 0) {
      labels.push(`${p.provider}:${p.model}`)
      data.push(p.cost_usd)
    }
  })

  return {
    labels,
    datasets: [{ data, backgroundColor: colors.slice(0, labels.length) }]
  }
})

const costTotal = computed(() => {
  return costChartData.value.datasets[0].data.reduce((a: number, b: number) => a + b, 0)
})

const latencyChartData = computed(() => {
  if (!metrics.value?.latency_profiles?.stage_wall_times_ms) {
    return { labels: [], datasets: [{ label: '延迟 (ms)', data: [], backgroundColor: [] }] }
  }
  const stages = metrics.value.latency_profiles.stage_wall_times_ms
  const labels: string[] = []
  const data: number[] = []
  const colors: string[] = []

  Object.entries(stages).forEach(([name, s]: [string, any]) => {
    labels.push(name)
    data.push(s.duration_ms)
    colors.push(s.success ? '#4BC0C0' : '#FF6384')
  })

  return {
    labels,
    datasets: [{ label: '延迟 (ms)', data, backgroundColor: colors }]
  }
})

const sortedStages = computed(() => {
  if (!metrics.value?.latency_profiles?.stage_wall_times_ms) return []
  return Object.entries(metrics.value.latency_profiles.stage_wall_times_ms)
    .map(([name, s]: [string, any]) => ({ name, duration: s.duration_ms, success: s.success }))
    .sort((a, b) => b.duration - a.duration)
})

const resilience = computed(() => metrics.value?.resilience_metrics || { llm: {}, tts: {} })
const latency = computed(() => metrics.value?.latency_profiles || {})

const providerBreakdown = computed(() => {
  if (!metrics.value?.cost_accounting?.providers) return []
  return Object.entries(metrics.value.cost_accounting.providers)
    .map(([key, p]: [string, any]) => ({ key, ...p }))
    .filter(p => p.call_count > 0 || p.cost_usd > 0)
    .sort((a, b) => b.cost_usd - a.cost_usd)
})

const formatDate = (iso: string) => {
  try { return new Date(iso).toLocaleString('zh-CN') } catch { return iso }
}

const refreshData = () => fetchMetrics()

onMounted(async () => {
  await fetchProjects()
  if (selectedProjectId.value) {
    await fetchMetrics()
  }
})

watch(selectedProjectId, fetchMetrics)
</script>

<style scoped>
.monitoring-dashboard {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}

.dashboard-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--vp-c-divider, #e8e8e8);
}

.dashboard-header h1 {
  margin: 0;
  font-size: 1.75rem;
}

.header-controls {
  display: flex;
  gap: 12px;
  align-items: center;
}

.project-select {
  padding: 8px 12px;
  border: 1px solid var(--vp-c-divider, #e8e8e8);
  border-radius: 6px;
  background: var(--vp-c-bg, #fff);
  font-size: 0.9rem;
}

.btn {
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.9rem;
  font-weight: 500;
  transition: opacity 0.2s;
}
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-primary { background: var(--vp-c-brand, #42b883); color: white; }
.btn-primary:hover:not(:disabled) { opacity: 0.9; }

.loading-overlay {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px;
  text-align: center;
}
.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--vp-c-divider, #e8e8e8);
  border-top-color: var(--vp-c-brand, #42b883);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.empty-state {
  text-align: center;
  padding: 60px;
  color: var(--vp-c-text-2, #787878);
}

.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
  gap: 24px;
}

.chart-card {
  background: var(--vp-c-bg-soft, #fafafa);
  border: 1px solid var(--vp-c-divider, #e8e8e8);
  border-radius: 12px;
  padding: 20px;
}
.chart-card h2 {
  margin: 0 0 16px;
  font-size: 1.1rem;
  color: var(--vp-c-text-1, #333);
}

.chart-container {
  height: 300px;
  position: relative;
}

.chart-legend {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 16px;
  font-size: 0.85rem;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.legend-color {
  width: 12px;
  height: 12px;
  border-radius: 3px;
}
.legend-label { flex: 1; }
.legend-value { font-weight: 600; color: var(--vp-c-brand, #42b883); }
.legend-pct { color: var(--vp-c-text-2, #787878); font-size: 0.8rem; }
.legend-total { padding-top: 8px; border-top: 1px solid var(--vp-c-divider, #e8e8e8); }

.leaderboard-table {
  margin-top: 16px;
  overflow-x: auto;
}
.leaderboard-table table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}
.leaderboard-table th,
.leaderboard-table td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid var(--vp-c-divider, #e8e8e8);
}
.leaderboard-table th {
  background: var(--vp-c-bg, #fff);
  font-weight: 600;
  color: var(--vp-c-text-2, #787878);
}
.leaderboard-table tr.success td { background: rgba(75, 192, 192, 0.05); }
.leaderboard-table tr.failed td { background: rgba(255, 99, 132, 0.05); }
.rank { font-weight: 700; color: var(--vp-c-brand, #42b883); width: 50px; }
.stage-name { font-family: monospace; }
.latency { font-variant-numeric: tabular-nums; }
.status { white-space: nowrap; }

.metrics-card {
  background: var(--vp-c-bg-soft, #fafafa);
  border: 1px solid var(--vp-c-divider, #e8e8e8);
  border-radius: 12px;
  padding: 20px;
  grid-column: 1 / -1;
}
.metrics-card h2 {
  margin: 0 0 16px;
  font-size: 1.1rem;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
}
.metric-box {
  background: var(--vp-c-bg, #fff);
  border: 1px solid var(--vp-c-divider, #e8e8e8);
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.metric-label {
  font-size: 0.8rem;
  color: var(--vp-c-text-2, #787878);
}
.metric-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--vp-c-text-1, #333);
}
.metric-value.warn { color: #f59e0b; }
.metric-value.danger { color: #ef4444; }
.metric-value.success { color: #22c55e; }

.provider-table {
  overflow-x: auto;
}
.provider-table table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.provider-table th,
.provider-table td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid var(--vp-c-divider, #e8e8e8);
}
.provider-table th {
  background: var(--vp-c-bg, #fff);
  font-weight: 600;
  color: var(--vp-c-text-2, #787878);
}
.provider-table td.cost { color: var(--vp-c-brand, #42b883); font-weight: 600; }
.provider-table td.success { color: #22c55e; }
.provider-table td.warn { color: #f59e0b; }
.provider-table td.danger { color: #ef4444; }

.metadata-section {
  margin-top: 32px;
  padding: 20px;
  background: var(--vp-c-bg-soft, #fafafa);
  border: 1px solid var(--vp-c-divider, #e8e8e8);
  border-radius: 12px;
}
.metadata-section h2 {
  margin: 0 0 16px;
  font-size: 1.1rem;
}
.metadata-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 12px;
  font-size: 0.9rem;
}
.metadata-grid div.success { color: #22c55e; }
.metadata-grid div.danger { color: #ef4444; }

.no-data {
  text-align: center;
  padding: 40px;
  color: var(--vp-c-text-2, #787878);
}
</style>