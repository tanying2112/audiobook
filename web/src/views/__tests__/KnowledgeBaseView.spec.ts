import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import KnowledgeBaseView from '../KnowledgeBaseView.vue'

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
  listKnowledge: vi.fn().mockResolvedValue({
    project_id: 7,
    knowledge: [{ id: 'k1', topic: 'voice', knowledge: { style: 'narrator' }, source_agent: 'user' }],
  }),
  addKnowledge: vi.fn().mockResolvedValue({ id: 'k2', topic: 'voice', message: 'ok' }),
}))

vi.mock('../../api', () => ({
  listKnowledge: mocks.listKnowledge,
  addKnowledge: mocks.addKnowledge,
  default: {},
}))

describe('KnowledgeBaseView.vue — Agent 知识库页', () => {
  beforeEach(() => {
    mocks.listKnowledge.mockClear()
    mocks.addKnowledge.mockClear()
  })

  it('挂载后拉取知识条目', async () => {
    mount(KnowledgeBaseView as any, {
      global: {
        stubs: {
          'el-card': { template: '<div><slot name="header"/><slot /></div>' },
          'el-button': { template: '<button><slot /></button>' },
          'el-input': { template: '<input />' },
          'el-table': { template: '<div><slot /></div>' },
          'el-table-column': { template: '<div><slot /></div>' },
          'el-empty': { template: '<div><slot /></div>' },
          'el-dialog': { template: '<div><slot /><slot name="footer" /></div>' },
          'el-form': { template: '<div><slot /></div>' },
          'el-form-item': { template: '<div><slot /></div>' },
        },
      },
    })
    await flushPromises()

    expect(mocks.listKnowledge).toHaveBeenCalledWith(7, undefined)
  })
})
