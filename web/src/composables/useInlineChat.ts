/**
 * useInlineChat — Cursor 风格内联小窗对话 composable
 *
 * 核心场景：用户在文本编辑 / 人物音频参数等阶段，选中内容或聚焦某参数控件，
 * 在选区旁边跳出一个小窗口与 LLM 针对所选内容对话。
 *
 * 与右侧固定面板（P0-AI-1）的区别：
 *   - 内联小窗锚定在具体选区/控件旁，上下文极强，空间感自然
 *   - 右侧面板适合长段落连续编辑；内联小窗适合"就地微调"
 *   - 两者复用同一套 SSE 流式协议与 ChatSuggestion 结构
 *
 * 设计要点：
 *   1. 与 context store 联动：open() 时把锚点写入全局 store（供 Teleport 定位层渲染）
 *   2. 流式接收复用 api/sse.ts 的 streamChatEdit
 *   3. 多轮上下文：messages 数组累积，每次发送带 history
 *   4. 采纳/拒绝：accept() 把 suggestion 写回目标（业务层 hook），reject() 记负反馈
 */

import { ref, shallowRef, computed } from 'vue'
import { useContextStore } from '../stores/context'
import { streamChatEdit, type ChatEditCallbacks } from '../api/sse'
import type {
  ChatMessage,
  ChatSuggestion,
  InlineChatAnchor,
  ChatEditTargetStage,
} from '../types/pipeline'

/** 生成简易 ID（非安全用途，仅用于消息标识） */
function _uid(): string {
  return `msg_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

/** useInlineChat 配置 */
export interface UseInlineChatOptions {
  /** 项目 ID（默认从 context store 读取） */
  projectId?: () => number | null
  /** 章节索引（默认从 context store 读取） */
  chapterIndex?: () => number | null
  /** 目标阶段 */
  targetStage?: ChatEditTargetStage
  /** 是否使用 mock 端点（默认 true，基建阶段验证用） */
  useMock?: boolean
  /** 采纳 suggestion 时的业务回调（由调用方实现落盘逻辑） */
  onAccept?: (suggestion: ChatSuggestion) => void | Promise<void>
  /** 拒绝 suggestion 时的业务回调（记负反馈等） */
  onReject?: (suggestion: ChatSuggestion) => void | Promise<void>
}

export function useInlineChat(options: UseInlineChatOptions = {}) {
  const ctx = useContextStore()
  const targetStage = options.targetStage ?? 'edit'
  const useMock = options.useMock ?? true

  // ── 响应式状态 ───────────────────────────────────────────────────────
  const messages = ref<ChatMessage[]>([])
  const streamingText = ref<string>('')
  const loading = ref<boolean>(false)
  const error = ref<string | null>(null)
  const currentSuggestion = ref<ChatSuggestion | null>(null)
  const inputText = ref<string>('')

  /**
   * 锚点元素引用（定位的真实来源）。
   * open() 时存入，定位 composable 据此实时 getBoundingClientRect()，
   * 页面滚动/缩放/翻转判定全部基于此元素，杜绝一次性 rect 快照导致的飘移。
   */
  const anchorEl = ref<HTMLElement | null>(null)

  /** 当前 AbortController（用于中途停止） */
  const abortController = shallowRef<AbortController | null>(null)

  // ── 派生 ─────────────────────────────────────────────────────────────
  const active = computed(() => ctx.isInlineChatActive)
  const anchor = computed(() => ctx.activeAnchor)
  const canStop = computed(() => loading.value && abortController.value !== null)
  const canSend = computed(() => inputText.value.trim().length > 0 && !loading.value)

  // ── 打开 / 关闭 ──────────────────────────────────────────────────────

  /**
   * 打开内联小窗，锚定到某元素（选区或控件）。
   *
   * 关键：保留元素引用而非只存 rect 快照，使定位 composable 能在滚动/resize 时
   * 实时重算位置（防飘移）。rect 仍写入 store 供需要初始坐标的逻辑使用。
   *
   * @param triggerEl 触发元素（定位锚点，必须真实存在于 DOM）
   * @param anchorInfo 锚点语义信息（选区文本 / 参数字段等）
   */
  function open(
    triggerEl: HTMLElement,
    anchorInfo: Omit<InlineChatAnchor, 'rect'>,
  ): void {
    anchorEl.value = triggerEl
    const rect = triggerEl.getBoundingClientRect()
    ctx.openInlineChat({ ...anchorInfo, rect })
    // 重置对话状态（新锚点 = 新对话）
    resetConversation()
  }

  /** 关闭内联小窗 */
  function close(): void {
    stop()
    ctx.closeInlineChat()
    anchorEl.value = null
    resetConversation()
  }

  function resetConversation(): void {
    messages.value = []
    streamingText.value = ''
    currentSuggestion.value = null
    error.value = null
    inputText.value = ''
  }

  // ── 发送对话（SSE 流式）──────────────────────────────────────────────

  /**
   * 发送一条用户消息并触发 LLM 流式响应。
   * 复用 api/sse.ts 的 streamChatEdit。
   */
  async function send(): Promise<void> {
    const intent = inputText.value.trim()
    if (!intent || loading.value) return

    const projectId = options.projectId?.() ?? ctx.projectId
    const chapterIndex = options.chapterIndex?.() ?? ctx.chapterIndex
    const anchorData = ctx.activeAnchor

    if (projectId == null || chapterIndex == null) {
      error.value = '缺少项目/章节上下文，无法发起对话'
      return
    }

    // 追加用户消息
    const userMsg: ChatMessage = {
      id: _uid(),
      role: 'user',
      content: intent,
      timestamp: new Date().toISOString(),
    }
    messages.value.push(userMsg)
    inputText.value = ''

    // 重置流式状态
    streamingText.value = ''
    currentSuggestion.value = null
    error.value = null
    loading.value = true

    // 构造请求（注入锚点上下文，让 LLM 知道针对的是什么）
    const paragraphIndex = anchorData?.paragraph_id ?? 0
    const annotationContext = anchorData
      ? {
          selected_text: anchorData.selected_text,
          param_field: anchorData.param_field,
          param_value: anchorData.param_value,
        }
      : undefined

    const callbacks: ChatEditCallbacks = {
      onThinking: () => {
        // 可在此触发"思考中"动画；打字机在首个 token 到来前显示占位
      },
      onToken: (content) => {
        streamingText.value += content
      },
      onSuggestion: (suggestion) => {
        currentSuggestion.value = suggestion
        // 把流式文本固化为一条 assistant 消息
        messages.value.push({
          id: _uid(),
          role: 'assistant',
          content: streamingText.value || suggestion.rationale,
          timestamp: new Date().toISOString(),
          suggestion,
          adoption: 'pending',
        })
        streamingText.value = ''
      },
      onDone: () => {
        // 若无 suggestion（纯对话），把流式文本固化为普通消息
        if (streamingText.value && !currentSuggestion.value) {
          messages.value.push({
            id: _uid(),
            role: 'assistant',
            content: streamingText.value,
            timestamp: new Date().toISOString(),
          })
          streamingText.value = ''
        }
        loading.value = false
        abortController.value = null
      },
      onError: (message) => {
        error.value = message
        loading.value = false
        abortController.value = null
      },
    }

    abortController.value = streamChatEdit(
      {
        project_id: projectId,
        chapter_index: chapterIndex,
        paragraph_index: paragraphIndex,
        target_stage: targetStage,
        intent,
        conversation_history: messages.value.slice(0, -1), // 不含刚追加的 userMsg
        annotation_context: annotationContext,
      },
      callbacks,
      useMock,
    )
  }

  /** 中途停止流式接收 */
  function stop(): void {
    abortController.value?.abort()
    abortController.value = null
    loading.value = false
    // 保留已接收的部分文本
    if (streamingText.value) {
      messages.value.push({
        id: _uid(),
        role: 'assistant',
        content: streamingText.value + ' [已停止]',
        timestamp: new Date().toISOString(),
      })
      streamingText.value = ''
    }
  }

  // ── 采纳 / 拒绝 suggestion ───────────────────────────────────────────

  /** 采纳当前 suggestion：调用业务回调落盘，更新消息状态 */
  async function accept(): Promise<void> {
    const suggestion = currentSuggestion.value
    if (!suggestion) return
    // 更新对应 assistant 消息的 adoption
    const lastAssistant = [...messages.value].reverse().find((m) => m.suggestion === suggestion)
    if (lastAssistant) lastAssistant.adoption = 'accepted'
    try {
      await options.onAccept?.(suggestion)
    } finally {
      currentSuggestion.value = null
    }
  }

  /** 拒绝当前 suggestion：记负反馈 */
  async function reject(): Promise<void> {
    const suggestion = currentSuggestion.value
    if (!suggestion) return
    const lastAssistant = [...messages.value].reverse().find((m) => m.suggestion === suggestion)
    if (lastAssistant) lastAssistant.adoption = 'rejected'
    try {
      await options.onReject?.(suggestion)
    } finally {
      currentSuggestion.value = null
    }
  }

  return {
    // 状态
    messages,
    streamingText,
    loading,
    error,
    currentSuggestion,
    inputText,
    active,
    anchor,
    /** 锚点元素 ref（传给 useInlineChatPosition 做实时跟随定位） */
    anchorEl,
    canStop,
    canSend,
    // 操作
    open,
    close,
    send,
    stop,
    accept,
    reject,
    resetConversation,
  }
}
