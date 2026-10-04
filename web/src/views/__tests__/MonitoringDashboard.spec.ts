import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import MonitoringDashboard from '../MonitoringDashboard.vue'

vi.mock('chart.js', () => ({
  Chart: Object.assign(vi.fn(() => ({ destroy: vi.fn() })), { register: vi.fn() }),
  registerables: [],
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/monitoring' }),
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('../../i18n', () => ({
  useI18n: () => ({ t: (k: string) => k, getLocale: () => 'en-US' }),
}))

const mocks = vi.hoisted(() => ({
  fetchProjectsWithMetrics: vi.fn().mockResolvedValue({
    projects: [{ project_id: 7, title: 'Demo Book', latest_metrics: '', last_updated: '' }],
  }),
  fetchProjectMetrics: vi.fn().mockResolvedValue({
    metadata: { project_id: 7, success: true, started_at: '', ended_at: '', duration_ms: 0 },
    cost_accounting: { providers: {} },
    latency_profiles: { stage_wall_times_ms: {}, synthesis_rate_ratio: 1, real_time_factor: 1, total_audio_duration_ms: 0 },
    resilience_metrics: { llm: { total_calls: 0, total_retries: 0, total_fallbacks: 0 }, tts: { total_segments: 0, successful_segments: 0 } },
  }),
}))

vi.mock('../../api', () => ({
  fetchProjectsWithMetrics: mocks.fetchProjectsWithMetrics,
  fetchProjectMetrics: mocks.fetchProjectMetrics,
  default: {},
}))

describe('MonitoringDashboard.vue — 统一 api 客户端数据层', () => {
  beforeEach(() => {
    mocks.fetchProjectsWithMetrics.mockClear()
    mocks.fetchProjectMetrics.mockClear()
  })

  it('挂载后通过统一 api 获取项目列表与指标', async () => {
    mount(MonitoringDashboard as any)
    await flushPromises()

    expect(mocks.fetchProjectsWithMetrics).toHaveBeenCalledTimes(1)
    expect(mocks.fetchProjectMetrics).toHaveBeenCalledWith(7)
  })
})
