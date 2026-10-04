import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '../i18n'
import {
  fetchHarnessDashboard,
  triggerIteration,
  type HarnessDashboardResponse,
} from '../api'

export function useHarnessDashboard() {
  const router = useRouter()
  const { t } = useI18n()

  // State
  const dashboard = ref<HarnessDashboardResponse | null>(null)
  const loading = ref(true)
  const error = ref('')
  const triggering = ref(false)
  const triggerMessage = ref('')
  const triggerError = ref(false)
  const lastRefresh = ref<string>('')
  let refreshTimer: ReturnType<typeof setInterval> | null = null

  async function loadDashboard() {
    try {
      loading.value = true
      error.value = ''
      dashboard.value = await fetchHarnessDashboard()
      lastRefresh.value = new Date().toLocaleTimeString()
    } catch (e: any) {
      error.value = t('harness_dashboard.load_failed', { error: e.response?.data?.detail || e.message })
    } finally {
      loading.value = false
    }
  }

  async function handleTrigger() {
    try {
      triggering.value = true
      triggerMessage.value = ''
      triggerError.value = false
      const result = await triggerIteration()
      triggerMessage.value = result.message
      await loadDashboard()
    } catch (e: any) {
      triggerError.value = true
      triggerMessage.value = t('harness_dashboard.trigger_failed', { error: e.response?.data?.detail || e.message })
    } finally {
      triggering.value = false
    }
  }

  function statusColor(status: string): string {
    switch (status) {
      case 'running': return '#22c55e'
      case 'paused': return 'var(--color-warning)'
      case 'completed': return 'var(--color-primary)'
      case 'failed': return '#ef4444'
      case 'rolled_back': return '#9333ea'
      default: return '#94a3b8'
    }
  }

  function gateBarWidth(rate: number, threshold: number): string {
    const pct = Math.min((rate / threshold) * 100, 100)
    return `${pct}%`
  }

  function gateBarColor(rate: number, threshold: number): string {
    return rate >= threshold ? '#22c55e' : '#ef4444'
  }

  function verdictColor(verdict: string): string {
    switch (verdict) {
      case 'accept': return '#22c55e'
      case 'reject': return '#ef4444'
      case 'needs_revision': return 'var(--color-warning)'
      default: return '#94a3b8'
    }
  }

  function patternBarWidth(count: number, maxCount: number): string {
    if (maxCount === 0) return '0%'
    return `${(count / maxCount) * 100}%`
  }

  onMounted(async () => {
    await loadDashboard()
    refreshTimer = setInterval(loadDashboard, 30000)
  })

  onUnmounted(() => {
    if (refreshTimer) clearInterval(refreshTimer)
  })

  return {
    t,
    router,
    dashboard,
    loading,
    error,
    triggering,
    triggerMessage,
    triggerError,
    lastRefresh,
    loadDashboard,
    handleTrigger,
    statusColor,
    gateBarWidth,
    gateBarColor,
    verdictColor,
    patternBarWidth,
  }
}
