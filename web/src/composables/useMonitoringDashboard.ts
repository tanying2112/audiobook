import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { Chart, registerables } from 'chart.js'
import { useI18n } from '../i18n'
import { fetchProjectsWithMetrics, fetchProjectMetrics } from '../api'

Chart.register(...registerables)

export function useMonitoringDashboard() {
  const { t, getLocale } = useI18n()

  const selectedProjectId = ref<number>(1)
  const projects = ref<Array<{id: number, title: string}>>([])
  const metrics = ref<any>(null)
  const loading = ref(false)
  const costChart = ref<Chart | null>(null)
  const latencyChart = ref<Chart | null>(null)

  const fetchProjects = async () => {
    try {
      const res = await fetchProjectsWithMetrics()
      projects.value = (res.projects || []).map((p: any) => ({ id: p.project_id, title: p.title }))
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
      metrics.value = await fetchProjectMetrics(selectedProjectId.value)
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
                label: (ctx: any) => {
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
                label: (ctx: any) => `${ctx.label}: ${ctx.raw} ms`
              }
            }
          },
          scales: {
            x: { beginAtZero: true, title: { display: true, text: t('monitoring.latency_ms') } }
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
    return { labels, datasets: [{ data, backgroundColor: colors.slice(0, labels.length) }] }
  })

  const costTotal = computed(() => {
    return costChartData.value.datasets[0].data.reduce((a: number, b: number) => a + b, 0)
  })

  const latencyChartData = computed(() => {
    if (!metrics.value?.latency_profiles?.stage_wall_times_ms) {
      return { labels: [], datasets: [{ label: t('monitoring.latency_ms'), data: [], backgroundColor: [] }] }
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
    return { labels, datasets: [{ label: t('monitoring.latency_ms'), data, backgroundColor: colors }] }
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
      .filter((p: any) => p.call_count > 0 || p.cost_usd > 0)
      .sort((a: any, b: any) => b.cost_usd - a.cost_usd)
  })

  const formatDate = (iso: string) => {
    try { return new Date(iso).toLocaleString(getLocale()) } catch { return iso }
  }

  const refreshData = () => fetchMetrics()

  onMounted(async () => {
    await fetchProjects()
    if (selectedProjectId.value) {
      await fetchMetrics()
    }
  })

  watch(selectedProjectId, fetchMetrics)

  return {
    t,
    selectedProjectId,
    projects,
    metrics,
    loading,
    costChart,
    latencyChart,
    fetchProjects,
    fetchMetrics,
    refreshData,
    costChartData,
    costTotal,
    latencyChartData,
    sortedStages,
    resilience,
    latency,
    providerBreakdown,
    formatDate,
  }
}
