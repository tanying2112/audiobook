import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import FeedbackInsightsView from '../FeedbackInsightsView.vue'

vi.mock('../../i18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))

const mocks = vi.hoisted(() => ({
  fetchFeedbackFunnel: vi.fn().mockResolvedValue({
    total_feedback: 10,
    analyzed_count: 8,
    triggered_upgrade_count: 5,
    promotion_passed_count: 3,
    published_count: 2,
    conversion_rates: {},
  }),
  fetchPatternHeatmap: vi.fn().mockResolvedValue({
    patterns: [{ tag: 'fake-pattern', count: 4, stage: 'edit', severity: 'high' }],
    by_stage: {},
    top_patterns: ['fake-pattern'],
  }),
}))

vi.mock('../../api', () => ({
  fetchFeedbackFunnel: mocks.fetchFeedbackFunnel,
  fetchPatternHeatmap: mocks.fetchPatternHeatmap,
  default: {},
}))

describe('FeedbackInsightsView.vue — 反馈洞察页', () => {
  beforeEach(() => {
    mocks.fetchFeedbackFunnel.mockClear()
    mocks.fetchPatternHeatmap.mockClear()
  })

  it('挂载后通过统一 api 拉取反馈漏斗与模式热力图', async () => {
    mount(FeedbackInsightsView as any, {
      global: {
        stubs: {
          'el-card': { template: '<div><slot name="header"/><slot /></div>' },
          'el-button': { template: '<button><slot /></button>' },
          'el-row': { template: '<div><slot /></div>' },
          'el-col': { template: '<div><slot /></div>' },
          'el-table': { template: '<div><slot /></div>' },
          'el-table-column': { template: '<div><slot /></div>' },
          'el-tag': { template: '<span><slot /></span>' },
          'el-empty': { template: '<div><slot /></div>' },
        },
      },
    })
    await flushPromises()

    expect(mocks.fetchFeedbackFunnel).toHaveBeenCalledTimes(1)
    expect(mocks.fetchPatternHeatmap).toHaveBeenCalledTimes(1)
  })
})
