import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import RunsView from '../RunsView.vue'

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { projectId: '7' } }),
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('../../i18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))

vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn(), warning: vi.fn(), success: vi.fn() },
}))

const mocks = vi.hoisted(() => ({
  fetchIntermediateProduct: vi.fn().mockResolvedValue({ stage: 'extract', raw_text: 'hello' }),
  runPipelineStage: vi.fn().mockResolvedValue({ stage: 'extract', status: 'completed', message: 'ok', progress: 1 }),
}))

vi.mock('../../api', () => ({
  fetchIntermediateProduct: mocks.fetchIntermediateProduct,
  runPipelineStage: mocks.runPipelineStage,
  default: {},
}))

describe('RunsView.vue — 运行记录/中间产物页', () => {
  beforeEach(() => {
    mocks.fetchIntermediateProduct.mockClear()
    mocks.runPipelineStage.mockClear()
  })

  it('挂载后拉取中间产物，可触发手动单阶段运行', async () => {
    const wrapper = mount(RunsView as any, {
      global: {
        stubs: {
          'el-card': { template: '<div><slot name="header"/><slot /></div>' },
          'el-form': { template: '<div><slot /></div>' },
          'el-form-item': { template: '<div><slot /></div>' },
          'el-select': { template: '<select><slot /></select>' },
          'el-option': { template: '<option><slot /></option>' },
          'el-input-number': { template: '<input />' },
          'el-button': { template: "<button @click=\"$emit('click')\"><slot /></button>" },
          'el-alert': { template: '<div><slot /></div>' },
          'el-empty': { template: '<div><slot /></div>' },
        },
      },
    })
    await flushPromises()

    expect(mocks.fetchIntermediateProduct).toHaveBeenCalledWith(7, 'extract', undefined)

    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(mocks.runPipelineStage).toHaveBeenCalledWith(7, { stage: 'extract' })
  })
})
