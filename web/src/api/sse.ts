/**
 * SSE 流式响应客户端
 *
 * 设计决策：对话式编辑是 POST（带 intent + history），而原生 EventSource 仅支持 GET。
 * 因此用 fetch + ReadableStream + TextDecoder 手动解析 SSE 协议（data: {...}\n\n），
 * 而非 EventSource。这样既能 POST body，又支持 AbortController 中途取消。
 *
 * 同时提供管线进度推送的轮询封装（蓝图策略 C 的降级兜底），
 * 后端 WebSocket 就绪后可替换实现而不改调用方回调接口。
 */

import type { ChatEditRequest, ChatEditStreamEvent, ChatSuggestion } from '../types/pipeline'
import { createPipelineWebSocketClient } from './websocket'

// ── 配置 ────────────────────────────────────────────────────────────────────

/**
 * API 基础地址。
 * - 开发环境：Vite proxy 已把 '/api' 转发到 localhost:8000，故用相对路径即可
 * - 生产环境：同源，相对路径同样有效
 * 可通过 VITE_API_BASE 覆盖（如 'http://localhost:8000'）
 */
const API_BASE = import.meta.env.VITE_API_BASE || ''

// ── A. 对话式编辑 SSE（POST + fetch streaming）──────────────────────────────

export interface ChatEditCallbacks {
  /** LLM 思考中（首个事件） */
  onThinking?: (messageId: string) => void
  /** 逐 token 文本（打字机追加） */
  onToken?: (content: string, messageId: string) => void
  /** 完整编辑建议 */
  onSuggestion?: (suggestion: ChatSuggestion, messageId: string) => void
  /** 流结束 */
  onDone?: (messageId: string) => void
  /** 错误 */
  onError?: (message: string, code?: string) => void
}

/**
 * 发起对话式编辑的 SSE 流式请求（POST）。
 *
 * 返回一个 AbortController —— 调用 `.abort()` 可中途"停止"（用户点停止按钮）。
 *
 * @example
 * const ctrl = streamChatEdit(req, {
 *   onToken: (t) => { streamingText.value += t },
 *   onSuggestion: (s) => { suggestion.value = s },
 *   onDone: () => { loading.value = false },
 * })
 * // 用户点击停止
 * ctrl.abort()
 */
export function streamChatEdit(
  req: ChatEditRequest,
  callbacks: ChatEditCallbacks,
  useMock = true,
): AbortController {
  const controller = new AbortController()
  const path = useMock ? '/api/mock/llm/chat-edit' : '/api/llm/chat-edit'
  const url = `${API_BASE}${path}`

  // fetch streaming 必须用 Promise + async，但这里不返回 Promise（用回调驱动）
  void _runSSEStream(url, req, callbacks, controller)
  return controller
}

/** 对话式标注 SSE（POST），接口与 streamChatEdit 一致 */
export function streamChatAnnotate(
  req: ChatEditRequest,
  callbacks: ChatEditCallbacks,
  useMock = true,
): AbortController {
  const controller = new AbortController()
  const path = useMock ? '/api/mock/llm/chat-annotate' : '/api/llm/chat-annotate'
  const url = `${API_BASE}${path}`
  void _runSSEStream(url, req, callbacks, controller)
  return controller
}

/**
 * SSE 流式核心：fetch + ReadableStream 解析。
 *
 * SSE 协议：事件以 `\n\n` 分隔，每条事件是 `data: <payload>\n`（可能多行）。
 * 后端 mock 在结尾发送 `data: [DONE]\n\n` 表示结束。
 */
async function _runSSEStream(
  url: string,
  body: unknown,
  callbacks: ChatEditCallbacks,
  controller: AbortController,
): Promise<void> {
  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    })

    if (!resp.ok) {
      callbacks.onError?.(`HTTP ${resp.status}: ${resp.statusText}`)
      return
    }
    if (!resp.body) {
      callbacks.onError?.('Response body is empty (streaming not supported)')
      return
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    // 逐 chunk 读取，按 SSE 帧边界（\n\n）切分
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // 按 \n\n 切分出完整事件，最后一个可能不完整留在 buffer
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''

      for (const frame of frames) {
        const evt = _parseSSEFrame(frame)
        if (evt === null) continue
        if (evt === '[DONE]') {
          // 流结束信号
          return
        }
        _dispatchEvent(evt, callbacks)
      }
    }

    // 处理 buffer 中残留的最后一段
    if (buffer.trim()) {
      const evt = _parseSSEFrame(buffer)
      if (evt !== null && evt !== '[DONE]') {
        _dispatchEvent(evt, callbacks)
      }
    }
  } catch (err: unknown) {
    // AbortError 是用户主动取消，不算错误
    if (err instanceof DOMException && err.name === 'AbortError') {
      return
    }
    const message = err instanceof Error ? err.message : String(err)
    callbacks.onError?.(message)
  }
}

/**
 * 解析单个 SSE 帧为事件对象。
 * 返回值：
 *   - 字符串 '[DONE]' → 流结束信号
 *   - 对象 → 正常事件
 *   - null → 无 data 行（如注释行或心跳）
 */
export function _parseSSEFrame(frame: string): ChatEditStreamEvent | '[DONE]' | null {
  // 一个帧可能含多行，合并所有 data: 行
  const dataLines: string[] = []
  for (const line of frame.split('\n')) {
    const trimmed = line.trim()
    if (trimmed.startsWith('data:')) {
      dataLines.push(trimmed.slice(5).trimStart())
    }
    // 忽略 event:/id:/retry:/注释(:) 行
  }
  if (dataLines.length === 0) return null

  const payload = dataLines.join('\n')

  if (payload === '[DONE]') return '[DONE]'

  try {
    return JSON.parse(payload) as ChatEditStreamEvent
  } catch {
    // 非 JSON（如纯文本注释），忽略
    return null
  }
}

/** 格式化 SSE 事件行（测试用导出） */
export function _sse(payload: unknown): string {
  const data = typeof payload === 'string' ? payload : JSON.stringify(payload, null, 0)
  return `data: ${data}\n\n`
}

/** 把事件分发到对应回调 */
function _dispatchEvent(evt: ChatEditStreamEvent, cb: ChatEditCallbacks): void {
  switch (evt.type) {
    case 'thinking':
      cb.onThinking?.(evt.message_id)
      break
    case 'token':
      cb.onToken?.(evt.content, evt.message_id)
      break
    case 'suggestion':
      cb.onSuggestion?.(evt.suggestion, evt.message_id)
      break
    case 'done':
      cb.onDone?.(evt.message_id)
      break
    case 'error':
      cb.onError?.(evt.message, evt.code)
      break
  }
}

// ── B. 管线进度推送（WebSocket 实时推送）──────────────────────────────────────

export interface PipelineEventCallbacks {
  onStageEnter?: (stage: string, chapterIndex: number) => void
  onStageProgress?: (stage: string, chapterIndex: number, progress: number) => void
  onStageExit?: (stage: string, chapterIndex: number) => void
  onChapterComplete?: (chapterId: number) => void
  onParagraphComplete?: (chapterId: number, paragraphIndex: number) => void
  onPipelineEnd?: (projectId: number) => void
  onError?: (message: string) => void
  onPaused?: () => void
  onResumed?: () => void
}

/**
 * 订阅管线进度事件（WebSocket 实时推送）。
 *
 * 通过 /ws/pipeline/{project_id} WebSocket 连接接收实时事件：
 * - stage_enter: 阶段开始
 * - stage_progress: 阶段进度更新
 * - stage_exit: 阶段结束
 * - chapter_complete: 章节完成
 * - completed: 管线完成
 * - paused/resumed: 暂停/恢复
 * - error: 错误
 *
 * 自动处理重连和心跳。
 *
 * @returns 取消订阅函数（组件 onUnmounted 时调用）
 *
 * @example
 * const unsubscribe = streamPipelineEvents(projectId, { onStageEnter: ... })
 * onUnmounted(unsubscribe)
 */
export function streamPipelineEvents(
  projectId: number,
  callbacks: PipelineEventCallbacks,
): () => void {
  const wsClient = createPipelineWebSocketClient({
    projectId,
    autoReconnect: true,
    callbacks: {
      onStageEnter: callbacks.onStageEnter,
      onStageProgress: callbacks.onStageProgress,
      onStageExit: callbacks.onStageExit,
      onChapterComplete: callbacks.onChapterComplete,
      onPipelineEnd: callbacks.onPipelineEnd,
      onError: callbacks.onError,
      onPaused: callbacks.onPaused,
      onResumed: callbacks.onResumed,
    },
  })

  wsClient.connect()

  return () => {
    wsClient.disconnect()
  }
}
