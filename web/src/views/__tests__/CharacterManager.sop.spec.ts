/**
 * P0.1 DoD 测试 — CharacterManager.vue 角色改名/重绑声音后投喂 SOP 纠错。
 *
 * 对应执行手册 docs/EVOLUTION_ROADMAP.md P0.1 子任务 #2 的验收标准：
 *  ① saveCharacter 内成功后投喂 speaker_canonical_name(改名) / suggested_voice_id(重绑) 型纠错；
 *  ② 投喂失败不影响保存。
 *
 * 红线 #1 主路径真实性：mock 的是 api / composable 网络层，保留真实组件保存→投喂逻辑。
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { ComponentMountingOptions } from '@vue/test-utils'
import { mount, flushPromises } from '@vue/test-utils'
import CharacterManager from '../CharacterManager.vue'

// ── Mock vue-router───────────────────────────────────────────────────────
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { projectId: '7' } }),
  useRouter: () => ({ push: vi.fn() }),
}))

// vi.mock 工厂被提升到文件顶部，故用 vi.hoisted 在工厂作用域可见地定义 mock 函数。
const mocks = vi.hoisted(() => {
  return {
    fetchCharacters: vi.fn().mockResolvedValue([
      { id: 1, canonical_name: '林冲', suggested_voice_id: 'voice-A' },
    ]),
    fetchProject: vi.fn().mockResolvedValue({ id: 7, genre: '武侠小说' }),
    updateCharacter: vi.fn().mockImplementation(async (_pid: number, _id: number, payload: any) => ({
      id: 1,
      canonical_name: payload.canonical_name,
      suggested_voice_id: payload.suggested_voice_id,
    })),
    createCharacter: vi.fn(),
    sendCorrection: vi.fn().mockResolvedValue(true),
  }
})

// ── Mock api（注意：从 __tests__/ 出发真实路径是 ../../api）────────────────
vi.mock('../../api', () => ({
  fetchCharacters: mocks.fetchCharacters,
  fetchProject: mocks.fetchProject,
  updateCharacter: mocks.updateCharacter,
  createCharacter: mocks.createCharacter,
  default: {
    fetchCharacters: mocks.fetchCharacters,
    fetchProject: mocks.fetchProject,
    updateCharacter: mocks.updateCharacter,
    createCharacter: mocks.createCharacter,
  },
}))

// ── Mock useSopCorrection composable（隔离 WS / HTTP 网络）────────────────
vi.mock('../../composables/useSopCorrection', () => ({
  useSopCorrection: () => ({
    sendCorrection: mocks.sendCorrection,
    connect: vi.fn(),
    disconnect: vi.fn(),
    reset: vi.fn(),
    connectionState: { value: 'connected' },
    isUsingFallback: { value: false },
    pendingCount: { value: 0 },
  }),
}))

// ── Mock i18n（组件依赖 useI18n────────────────────────────────────────────
vi.mock('../../i18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))

const fetchCharactersMock = mocks.fetchCharacters
const fetchProjectMock = mocks.fetchProject
const updateCharacterMock = mocks.updateCharacter
const sendCorrectionMock = mocks.sendCorrection

// ── 避免 confirm/alert 污染测试 ────────────────────────────────────────────
;(window as any).confirm = vi.fn(() => true)
;(window as any).alert = vi.fn()

function mountManager() {
  return mount(CharacterManager as any, {} as ComponentMountingOptions<any>)
}

describe('CharacterManager.vue — SOP 纠错投喂 (P0.1)', () => {
  beforeEach(() => {
    sendCorrectionMock.mockReset()
    sendCorrectionMock.mockResolvedValue(true)
    updateCharacterMock.mockClear()
    fetchCharactersMock.mockClear()
    fetchProjectMock.mockClear()
  })
  afterEach(() => vi.clearAllMocks())

  it('角色改名 → 投喂 speaker_canonical_name 一次，带原值/新值/genre', async () => {
    const wrapper = mountManager()
    await flushPromises() // onMounted: fetchCharacters + fetchProject + 初始化 SOP composable
    expect(fetchProjectMock).toHaveBeenCalled()

    // 打开编辑现有角色（林冲 → voice-A）
    ;(wrapper.findAll('button').find((b) => b.text().includes('character_manager.edit')) as any)?.trigger('click')
    await flushPromises()

    // 改名
    const nameInput = wrapper.find('input[type="text"]')
    await nameInput.setValue('林教头')
    // 点击保存
    ;(wrapper.findAll('button').find((b) => b.text().includes('common.save')) as any)?.trigger('click')
    await flushPromises()

    // updateCharacter 被调用（主路径）：voice 未改 → 携带原 voice-A
    expect(updateCharacterMock).toHaveBeenCalledWith(7, 1, {
      canonical_name: '林教头',
      suggested_voice_id: 'voice-A',
    } as any)

    // ① 投喂：改名 → speaker_canonical_name（声音未变 → 不投喂 suggested_voice_id）
    expect(sendCorrectionMock).toHaveBeenCalledTimes(1)
    const [field, original, corrected, pIndex, cIndex, context] = sendCorrectionMock.mock.calls[0]
    expect(field).toBe('speaker_canonical_name')
    expect(original).toBe('林冲')
    expect(corrected).toBe('林教头')
    expect(pIndex).toBe(0)
    expect(cIndex).toBe(0)
    expect(
      typeof context === 'string' && context.includes('CharacterManager') && context.includes('改名'),
    ).toBe(true)
  })

  it('重绑声音（同名）→ 投喂 suggested_voice_id', async () => {
    const wrapper = mountManager()
    await flushPromises()
    ;(wrapper.findAll('button').find((b) => b.text().includes('character_manager.edit')) as any)?.trigger('click')
    await flushPromises()
    const voiceInput = wrapper.findAll('input[type="text"]')[1]
    await voiceInput.setValue('voice-B')
    ;(wrapper.findAll('button').find((b) => b.text().includes('common.save')) as any)?.trigger('click')
    await flushPromises()

    expect(updateCharacterMock).toHaveBeenCalled()
    expect(sendCorrectionMock).toHaveBeenCalledTimes(1)
    const [field, original, corrected] = sendCorrectionMock.mock.calls[0]
    expect(field).toBe('suggested_voice_id')
    expect(original).toBe('voice-A')
    expect(corrected).toBe('voice-B')
  })

  it('投喂失败不阻塞保存（reject 仍 updateCharacter 成功、无 alert）', async () => {
    sendCorrectionMock.mockRejectedValue(new Error('net down'))
    const wrapper = mountManager()
    await flushPromises()
    ;(wrapper.findAll('button').find((b) => b.text().includes('character_manager.edit')) as any)?.trigger('click')
    await flushPromises()
    const nameInput = wrapper.find('input[type="text"]')
    await nameInput.setValue('新名字')
    ;(wrapper.findAll('button').find((b) => b.text().includes('common.save')) as any)?.trigger('click')
    await flushPromises()

    expect(updateCharacterMock).toHaveBeenCalled() // 保存主路径完成
    expect(sendCorrectionMock).toHaveBeenCalled()
    expect((window as any).alert).not.toHaveBeenCalled()
  })
})
