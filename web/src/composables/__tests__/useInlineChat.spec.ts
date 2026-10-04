import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useInlineChat } from '../useInlineChat'
import { useContextStore } from '../../stores/context'

// Mock sse module
vi.mock('../../api/sse', () => ({
  streamChatEdit: vi.fn(() => {
    const controller = new AbortController()
    return controller
  }),
  streamChatAnnotate: vi.fn(),
}))

import { streamChatEdit } from '../../api/sse'

/** 构造符合 DOMRect 完整接口的 mock（含 bottom/left/right/top/toJSON） */
function mockDomRect(overrides: Partial<DOMRect> = {}): DOMRect {
  return {
    x: 10, y: 20, width: 100, height: 30,
    top: 20, bottom: 50, left: 10, right: 110,
    toJSON: () => ({}),
    ...overrides,
  } as DOMRect
}

describe('useInlineChat composable', () => {
  let ctxStore: ReturnType<typeof useContextStore>

  beforeEach(() => {
    setActivePinia(createPinia())
    ctxStore = useContextStore()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  describe('初始状态', () => {
    it('应该有正确的初始状态', () => {
      const { messages, loading, error, currentSuggestion, inputText, active, anchor, canSend, canStop } = useInlineChat()

      expect(messages.value).toEqual([])
      expect(loading.value).toBe(false)
      expect(error.value).toBeNull()
      expect(currentSuggestion.value).toBeNull()
      expect(inputText.value).toBe('')
      expect(active.value).toBe(false)
      expect(anchor.value).toBeNull()
      expect(canSend.value).toBe(false)
      expect(canStop.value).toBe(false)
    })
  })

  describe('open / close', () => {
    it('open 应该设置 context store 的 activeAnchor', () => {
      const { open, active, anchor } = useInlineChat()
      const mockEl = document.createElement('div')
      mockEl.getBoundingClientRect = () => mockDomRect()

      open(mockEl, {
        kind: 'text_selection',
        paragraph_id: 1,
        selected_text: '测试文本',
        selection_start: 0,
        selection_end: 4,
      })

      expect(active.value).toBe(true)
      expect(anchor.value).toBeDefined()
      expect(anchor.value?.kind).toBe('text_selection')
      expect(anchor.value?.selected_text).toBe('测试文本')
      expect(ctxStore.activeAnchor).toEqual(anchor.value)
    })

    it('close 应该清空 anchor 和重置对话', () => {
      const { open, close, active, anchor, messages } = useInlineChat()
      const mockEl = document.createElement('div')
      mockEl.getBoundingClientRect = () => mockDomRect()

      open(mockEl, {
        kind: 'text_selection',
        paragraph_id: 1,
        selected_text: '测试',
        selection_start: 0,
        selection_end: 2,
      })

      // 添加一些消息
      messages.value.push({ id: '1', role: 'user', content: '测试', timestamp: '' })

      close()

      expect(active.value).toBe(false)
      expect(anchor.value).toBeNull()
      expect(messages.value).toEqual([])
      expect(ctxStore.activeAnchor).toBeNull()
    })
  })

  describe('send', () => {
    it('输入为空时不发送', async () => {
      const { send, inputText, loading } = useInlineChat()
      inputText.value = ''

      await send()

      expect(loading.value).toBe(false)
      expect(streamChatEdit).not.toHaveBeenCalled()
    })

    it('加载中时不发送', async () => {
      const { send, inputText, loading } = useInlineChat()
      inputText.value = '测试'
      loading.value = true

      await send()

      expect(streamChatEdit).not.toHaveBeenCalled()
    })

    it('缺少 projectId/chapterIndex 时设置错误', async () => {
      const { send, inputText, error } = useInlineChat({
        projectId: () => null,
        chapterIndex: () => null,
      })
      inputText.value = '测试'

      await send()

      expect(error.value).toBe('缺少项目/章节上下文，无法发起对话')
      expect(streamChatEdit).not.toHaveBeenCalled()
    })

    it('正常发送时调用 streamChatEdit', async () => {
      const { send, inputText, loading, messages } = useInlineChat({
        projectId: () => 1,
        chapterIndex: () => 1,
        useMock: true,
      })
      inputText.value = '口语化'

      const mockController = new AbortController()
      vi.mocked(streamChatEdit).mockReturnValue(mockController)

      await send()

      expect(streamChatEdit).toHaveBeenCalled()
      expect(loading.value).toBe(true)
      expect(messages.value.length).toBe(1)
      expect(messages.value[0].role).toBe('user')
      expect(messages.value[0].content).toBe('口语化')
    })
  })

  describe('stop', () => {
    it('应该中止流式请求并保留已接收文本', async () => {
      const { send, stop, streamingText, messages, loading, inputText } = useInlineChat({
        projectId: () => 1,
        chapterIndex: () => 1,
      })

      // 先发送一个请求，建立 controller
      inputText.value = '测试意图'
      const mockController = { abort: vi.fn() }
      vi.mocked(streamChatEdit).mockReturnValue(mockController as any)
      await send()

      // 现在模拟流式接收中 - send() 已经添加了 1 条 user 消息
      streamingText.value = '已接收的部分文本'
      loading.value = true

      stop()

      expect(mockController.abort).toHaveBeenCalled()
      expect(loading.value).toBe(false)
      // send() 添加了 user 消息，stop() 追加了 assistant 消息，共 2 条
      expect(messages.value.length).toBe(2)
      expect(messages.value[1].content).toContain('已接收的部分文本')
    })
  })

  describe('accept / reject', () => {
    it('accept 应该调用 onAccept 回调', async () => {
      const onAccept = vi.fn()
      const { accept, currentSuggestion, messages } = useInlineChat({
        onAccept,
      })

      const mockSuggestion = {
        kind: 'text_edit' as const,
        paragraph_id: '1_ch1_p0',
        before: { text: '原文' },
        after: { text: '新文本' },
        changes_made: ['口语化'],
        confidence: 0.9,
        rationale: '更自然',
      }
      currentSuggestion.value = mockSuggestion
      messages.value.push({
        id: '1',
        role: 'assistant',
        content: '建议',
        timestamp: '',
        suggestion: mockSuggestion,
        adoption: 'pending',
      })

      await accept()

      expect(onAccept).toHaveBeenCalledWith(mockSuggestion)
      expect(currentSuggestion.value).toBeNull()
      expect(messages.value[0].adoption).toBe('accepted')
    })

    it('reject 应该调用 onReject 回调', async () => {
      const onReject = vi.fn()
      const { reject, currentSuggestion, messages } = useInlineChat({
        onReject,
      })

      const mockSuggestion = {
        kind: 'text_edit' as const,
        paragraph_id: '1_ch1_p0',
        before: { text: '原文' },
        after: { text: '新文本' },
        changes_made: ['口语化'],
        confidence: 0.9,
        rationale: '更自然',
      }
      currentSuggestion.value = mockSuggestion
      messages.value.push({
        id: '1',
        role: 'assistant',
        content: '建议',
        timestamp: '',
        suggestion: mockSuggestion,
        adoption: 'pending',
      })

      await reject()

      expect(onReject).toHaveBeenCalledWith(mockSuggestion)
      expect(currentSuggestion.value).toBeNull()
      expect(messages.value[0].adoption).toBe('rejected')
    })

    it('无 suggestion 时不执行任何操作', async () => {
      const onAccept = vi.fn()
      const { accept, currentSuggestion } = useInlineChat({ onAccept })

      currentSuggestion.value = null
      await accept()

      expect(onAccept).not.toHaveBeenCalled()
    })
  })

  describe('canSend / canStop 计算属性', () => {
    it('canSend: 有输入且未加载时为 true', () => {
      const { inputText, loading, canSend } = useInlineChat()
      inputText.value = '测试'
      loading.value = false
      expect(canSend.value).toBe(true)
    })

    it('canSend: 输入为空时为 false', () => {
      const { inputText, loading, canSend } = useInlineChat()
      inputText.value = ''
      loading.value = false
      expect(canSend.value).toBe(false)
    })

    it('canSend: 加载中时为 false', () => {
      const { inputText, loading, canSend } = useInlineChat()
      inputText.value = '测试'
      loading.value = true
      expect(canSend.value).toBe(false)
    })
  })
})
