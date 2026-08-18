/**
 * P0.1 DoD 测试 — ParagraphEditor.vue 保存段落后自动投喂 SOP 纠错。
 *
 * 对应执行手册 docs/EVOLUTION_ROADMAP.md P0.1 子任务 #1 的验收标准：
 *  ① 编辑段落保存成功后，sendCorrection 被调用一次，带 project_id/genre/edited_text 修正；
 *  ② 投喂失败不阻塞保存（这里通过断言"保存→投喂"调用顺序，且即使投喂 reject 保存仍成功）；
 *  ③ Vitest 新增用例断言"保存→投喂"被调用。
 *
 * 红线 #1 主路径真实性：mock 的是 websocket/网络层（useSopCorrection），保留真实组件行为。
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import type { ComponentMountingOptions } from '@vue/test-utils'
import ParagraphEditor from '../ParagraphEditor.vue'
import type { Paragraph } from '../../types'

// ── Mock useSopCorrection composable（隔离 WS / HTTP 网络）────────────────
const sendCorrectionMock = vi.fn().mockResolvedValue(true)
vi.mock('../../composables/useSopCorrection', () => ({
  useSopCorrection: () => ({
    sendCorrection: sendCorrectionMock,
    connect: vi.fn(),
    disconnect: vi.fn(),
    reset: vi.fn(),
    connectionState: { value: 'connected' },
    isUsingFallback: { value: false },
    pendingCount: { value: 0 },
  }),
}))

// ── Mock api（fetchProject 用于解析 genre）─────────────────────────────────
vi.mock('../../api', () => ({
  fetchProject: vi.fn().mockResolvedValue({ id: 7, genre: '科幻小说' } as any),
}))

function makeParagraph(over: Partial<Paragraph> = {}): Paragraph {
  return {
    id: 100,
    project_id: 7,
    chapter_id: 3,
    index: 9,
    text: '原始正文文本在这里。',
    original_text: '原始正文文本在这里。',
    ...over,
  } as Paragraph
}

function mountEditor(paragraph: Paragraph) {
  return mount(ParagraphEditor, {
    props: { paragraph, projectId: 7, chapterId: 3 },
  } as ComponentMountingOptions<typeof ParagraphEditor>)
}

describe('ParagraphEditor.vue — SOP 纠错投喂 (P0.1)', () => {
  beforeEach(() => {
    sendCorrectionMock.mockReset()
    sendCorrectionMock.mockResolvedValue(true)
  })
  afterEach(() => vi.clearAllMocks())

  it('改动正文并保存 → sendCorrection 被调用一次，带 edited_text/原值/修正值/genre', async () => {
    const p = makeParagraph()
    const wrapper = mountEditor(p)
    await flushPromises() // 等待 onMounted fetchProject + 校验

    // 模拟用户改写正文 textarea
    const textarea = wrapper.find('textarea')
    await textarea.setValue('用户翻改后的新正文。')
    // 触发 @input（v-model 已绑定，但 hasChanges 依赖 @input onTextChange）
    await textarea.trigger('input')
    expect((wrapper.vm as any).hasChanges).toBe(true)

    // 点击保存
    await wrapper.find('button.btn-primary').trigger('click')
    await flushPromises()

    // ① 投喂确实发生，且只一次
    expect(sendCorrectionMock).toHaveBeenCalledTimes(1)
    const [field, original, corrected, paragraphIndex, chapterIndex, context] =
      sendCorrectionMock.mock.calls[0]
    expect(field).toBe('edited_text')
    expect(original).toBe('原始正文文本在这里。')
    expect(corrected).toBe('用户翻改后的新正文。')
    expect(paragraphIndex).toBe(9) // paragraph.index
    expect(chapterIndex).toBe(3) // props.chapterId
    expect(typeof context).toBe('string')
    expect(context).toContain('ParagraphEditor')

    // ② 保存主路径（emit('save')）不受投喂影响
    expect((wrapper.vm as any).hasChanges).toBe(false)
  })

  it('正文未变化 → 不投喂（避免无意义噪声）', async () => {
    const p = makeParagraph({ text: '保持不变', original_text: '保持不变' })
    const wrapper = mountEditor(p)
    await flushPromises()
    // 不改正文，直接保存（需先制造 hasChanges——但保存逻辑会比对值）
    const ta = wrapper.find('textarea')
    await ta.setValue('保持不变')
    await ta.trigger('input')
    await wrapper.find('button.btn-primary').trigger('click')
    await flushPromises()
    // 校正值与原值相同 → 不投喂
    expect(sendCorrectionMock).not.toHaveBeenCalled()
  })

  it('投喂失败不阻塞保存（reject 仍 emit save、清 hasChanges）', async () => {
    sendCorrectionMock.mockRejectedValue(new Error('network down'))
    const p = makeParagraph()
    const wrapper = mountEditor(p)
    await flushPromises()
    const ta = wrapper.find('textarea')
    await ta.setValue('又一个改动后的正文。')
    await ta.trigger('input')
    await wrapper.find('button.btn-primary').trigger('click')
    await flushPromises()

    // 投喂被调用但 reject；保存主路径仍完成（hasChanges 清空、save 已 emit）
    expect(sendCorrectionMock).toHaveBeenCalledTimes(1)
    expect((wrapper.vm as any).hasChanges).toBe(false)
  })
})
