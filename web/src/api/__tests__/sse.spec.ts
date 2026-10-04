import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { streamChatEdit, streamChatAnnotate, _parseSSEFrame, _sse } from '../sse'

describe('api/sse.ts', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  describe('_sse', () => {
    it('should format object payload as SSE data line', () => {
      const payload = { type: 'token', content: 'hello' }
      const result = _sse(payload)
      expect(result).toBe('data: {"type":"token","content":"hello"}\n\n')
    })

    it('should format string payload as SSE data line', () => {
      const result = _sse('[DONE]')
      expect(result).toBe('data: [DONE]\n\n')
    })
  })

  describe('_parseSSEFrame', () => {
    it('should parse single data line', () => {
      const frame = 'data: {"type":"token","content":"hello"}\n\n'
      const result = _parseSSEFrame(frame)
      expect(result).toEqual({ type: 'token', content: 'hello' })
    })

    it('should parse multiple data lines merged', () => {
      const frame = 'data: {"type":"token"\n\n'
      // 无效 JSON，应该返回 null
      const result = _parseSSEFrame(frame)
      expect(result).toBeNull()
    })

    it('should return [DONE] string for done signal', () => {
      const frame = 'data: [DONE]\n\n'
      const result = _parseSSEFrame(frame)
      expect(result).toBe('[DONE]')
    })

    it('should ignore non-data lines (comments, event, id, retry)', () => {
      const frame = 'event: message\nid: 123\nretry: 1000\n: comment line\n\ndata: {"type":"done"}\n\n'
      const result = _parseSSEFrame(frame)
      expect(result).toEqual({ type: 'done' })
    })

    it('should return null for empty or comment-only frames', () => {
      expect(_parseSSEFrame(': heartbeat\n\n')).toBeNull()
      expect(_parseSSEFrame('\n\n')).toBeNull()
    })
  })

  describe('streamChatEdit', () => {
    it('should return AbortController', () => {
      const controller = streamChatEdit(
        {
          project_id: 1,
          chapter_index: 1,
          paragraph_index: 0,
          target_stage: 'edit',
          intent: '测试',
          conversation_history: [],
        },
        {},
        true,
      )

      expect(controller).toBeInstanceOf(AbortController)
      controller.abort() // 清理
    })

    it('should call onError when fetch fails', async () => {
      const onError = vi.fn()
      const originalFetch = global.fetch
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'))

      const controller = streamChatEdit(
        {
          project_id: 1,
          chapter_index: 1,
          paragraph_index: 0,
          target_stage: 'edit',
          intent: '测试',
          conversation_history: [],
        },
        { onError },
        true,
      )

      // 等待微任务
      await vi.runAllTimersAsync()

      expect(onError).toHaveBeenCalledWith(expect.stringContaining('Network error'))

      global.fetch = originalFetch
      controller.abort()
    })

    it('should not call onError for AbortError', async () => {
      const onError = vi.fn()
      const abortError = new DOMException('Aborted', 'AbortError')
      const originalFetch = global.fetch
      global.fetch = vi.fn().mockRejectedValue(abortError)

      const controller = streamChatEdit(
        {
          project_id: 1,
          chapter_index: 1,
          paragraph_index: 0,
          target_stage: 'edit',
          intent: '测试',
          conversation_history: [],
        },
        { onError },
        true,
      )

      controller.abort()
      await vi.runAllTimersAsync()

      expect(onError).not.toHaveBeenCalled()

      global.fetch = originalFetch
    })
  })

  describe('streamChatAnnotate', () => {
    it('should return AbortController', () => {
      const controller = streamChatAnnotate(
        {
          project_id: 1,
          chapter_index: 1,
          paragraph_index: 0,
          target_stage: 'annotate',
          intent: '标注测试',
          conversation_history: [],
        },
        {},
        true,
      )

      expect(controller).toBeInstanceOf(AbortController)
      controller.abort()
    })
  })
})
