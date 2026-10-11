import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useI18n } from '../i18n'
import {
  sendAgentChatMessage,
  fetchAgentSessions,
  fetchAgentSessionHistory,
  deleteAgentSession,
  confirmPipelineAction,
  fetchPipelineStatus,
  type PipelineConfirmRequest,
  type PipelineStatusResponse,
} from '../api'
import type { FsmChapterItem, FsmChapterDetail, FsmConfirmRequest } from '../types/pipeline'

export interface Message {
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  metadata?: Record<string, any>
}

export interface Session {
  session_id: string
  project_id: number
  messages: Message[]
  created_at: string
  last_active: string
  message_count: number
}

export interface Settings {
  personality: 'general' | 'expert' | 'creative' | 'concise'
  responseLength: 'short' | 'medium' | 'long'
  autoScroll: boolean
  showTimestamps: boolean
}

export interface UseAgentChatOptions {
  projectId: number
  closable?: boolean
  initialMessage?: string
  onClose?: () => void
  onMessageSent?: (message: string) => void
  onMessageReceived?: (message: string) => void
  /** 是否启用 FSM 交互模式 */
  fsmMode?: boolean
  /** FSM 章节变更回调 */
  onChapterChange?: (chapter: FsmChapterItem) => void
  /** FSM 状态变更回调 */
  onFsmStateChange?: (state: any) => void
}

export function useAgentChat(options: UseAgentChatOptions) {
  const { t } = useI18n()

  const {
    projectId,
    initialMessage = '',
    onClose,
    onMessageSent,
    onMessageReceived,
    fsmMode = false,
    onChapterChange,
    onFsmStateChange,
  } = options

  // ─────────────────────────────────────────────────────────────────────────
  // 基础聊天状态
  // ─────────────────────────────────────────────────────────────────────────
  const messages = ref<Message[]>([])
  const inputMessage = ref('')
  const loading = ref(false)
  const showHistory = ref(false)
  const showSettings = ref(false)
  const currentSessionId = ref<string | null>(null)
  const sessions = ref<Session[]>([])
  const connectionStatus = ref<'connected' | 'connecting' | 'disconnected'>('connecting')
  const ws = ref<WebSocket | null>(null)
  const reconnectAttempts = ref(0)
  const maxReconnectAttempts = 10
  const reconnectInterval = 3000

  const messagesArea = ref<HTMLElement>()
  const messageInput = ref<HTMLTextAreaElement>()

  const settings = ref<Settings>({
    personality: 'general',
    responseLength: 'medium',
    autoScroll: true,
    showTimestamps: true,
  })

  // ─────────────────────────────────────────────────────────────────────────
  // FSM 交互模式状态（Phase 2）
  // ─────────────────────────────────────────────────────────────────────────
  const fsmChapters = ref<FsmChapterItem[]>([])
  const currentFsmChapter = ref<FsmChapterItem | null>(null)
  const fsmChapterDetail = ref<FsmChapterDetail | null>(null)
  const fsmStatus = ref<PipelineStatusResponse | null>(null)
  const fsmLoading = ref(false)
  const fsmActionLoading = ref<string | null>(null)

  // FSM WebSocket 连接
  const fsmWs = ref<WebSocket | null>(null)
  const fsmReconnectAttempts = ref(0)
  const fsmMaxReconnectAttempts = 10
  const fsmReconnectInterval = 3000

  // ─────────────────────────────────────────────────────────────────────────
  // Computed
  // ─────────────────────────────────────────────────────────────────────────
  const statusClass = computed(() => {
    if (connectionStatus.value === 'connected') return 'online'
    if (connectionStatus.value === 'connecting') return 'connecting'
    return 'offline'
  })

  const statusText = computed(() => {
    if (connectionStatus.value === 'connected') return t('status.online')
    if (connectionStatus.value === 'connecting') return t('status.connecting')
    return t('status.offline')
  })

  const connectionStatusText = computed(() => {
    if (connectionStatus.value === 'connected') return t('agentChat.wsConnected')
    if (connectionStatus.value === 'connecting') return t('agentChat.wsConnecting')
    return t('agentChat.wsDisconnected')
  })

  const suggestedPrompts = computed(() => [
    t('agentChat.suggestions.progress'),
    t('agentChat.suggestions.chapters'),
    t('agentChat.suggestions.tts'),
    t('agentChat.suggestions.quality'),
    t('agentChat.suggestions.export'),
    t('agentChat.suggestions.help'),
  ])

  // FSM 计算属性
  const fsmIsRunning = computed(() => {
    return !!fsmStatus.value && ['running', 'paused'].includes(fsmStatus.value.status)
  })

  const fsmIsPaused = computed(() => {
    return !!fsmStatus.value && fsmStatus.value.status === 'paused'
  })

  const fsmCanConfirm = computed(() => {
    return !!fsmStatus.value && fsmStatus.value.status === 'paused' && fsmStatus.value.current_state === 'pending_human_confirm'
  })

  const pendingChapter = computed(() => {
    if (!fsmStatus.value || !fsmCanConfirm.value) return null
    return fsmChapters.value.find(c => c.status === 'awaiting_confirm') || null
  })

  // ─────────────────────────────────────────────────────────────────────────
  // 基础聊天 WebSocket
  // ─────────────────────────────────────────────────────────────────────────
  const connectWebSocket = () => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = import.meta.env.VITE_API_BASE
      ? new URL(import.meta.env.VITE_API_BASE, window.location.origin).host
      : window.location.host
    const wsUrl = `${protocol}//${host}/api/agent/chat/${projectId}`

    try {
      ws.value = new WebSocket(wsUrl)
      connectionStatus.value = 'connecting'

      ws.value.onopen = () => {
        connectionStatus.value = 'connected'
        reconnectAttempts.value = 0
        console.log('Agent chat WebSocket connected')
      }

      ws.value.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          handleWebSocketMessage(data)
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e)
        }
      }

      ws.value.onclose = () => {
        connectionStatus.value = 'disconnected'
        scheduleReconnect()
      }

      ws.value.onerror = (error) => {
        console.error('WebSocket error:', error)
        connectionStatus.value = 'disconnected'
      }
    } catch (error) {
      console.error('Failed to create WebSocket:', error)
      connectionStatus.value = 'disconnected'
    }
  }

  const scheduleReconnect = () => {
    if (reconnectAttempts.value >= maxReconnectAttempts) {
      console.log('Max reconnect attempts reached')
      return
    }
    reconnectAttempts.value++
    setTimeout(() => {
      connectWebSocket()
    }, reconnectInterval)
  }

  const handleWebSocketMessage = (data: any) => {
    switch (data.type) {
      case 'connected':
        currentSessionId.value = data.session_id
        loadSessions()
        break
      case 'response':
        loading.value = false
        if (data.message) {
          messages.value.push({
            role: 'assistant',
            content: data.message,
            timestamp: data.timestamp,
            metadata: { agent_type: data.agent_type },
          })
          scrollToBottom()
          onMessageReceived?.(data.message)
        }
        break
      case 'history':
        if (data.session_id === currentSessionId.value) {
          messages.value = data.messages || []
        }
        break
      case 'error':
        loading.value = false
        console.error('Agent error:', data.message)
        messages.value.push({
          role: 'assistant',
          content: `❌ ${data.message}`,
          timestamp: data.timestamp,
          metadata: { error: true },
        })
        break
      case 'keepalive':
        break
      default:
        console.log('Unknown message type:', data.type)
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // FSM WebSocket 连接（复用 usePipelineProgress 的模式，专用 subprotocol）
  // ─────────────────────────────────────────────────────────────────────────
  const connectFsmWebSocket = () => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = import.meta.env.VITE_API_BASE
      ? new URL(import.meta.env.VITE_API_BASE, window.location.origin).host
      : window.location.host
    // 使用 FSM 专用 subprotocol
    const wsUrl = `${protocol}//${host}/api/agent/chat/${projectId}?fsm=true`

    try {
      fsmWs.value = new WebSocket(wsUrl, 'v1.audiobook.fsm')
      fsmWs.value.onopen = () => {
        console.log('FSM WebSocket connected')
        fsmReconnectAttempts.value = 0
        // 请求初始状态
        sendFsmMessage('status', {})
      }

      fsmWs.value.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          handleFsmWebSocketMessage(data)
        } catch (e) {
          console.error('Failed to parse FSM WebSocket message:', e)
        }
      }

      fsmWs.value.onclose = () => {
        scheduleFsmReconnect()
      }

      fsmWs.value.onerror = (error) => {
        console.error('FSM WebSocket error:', error)
      }
    } catch (error) {
      console.error('Failed to create FSM WebSocket:', error)
    }
  }

  const scheduleFsmReconnect = () => {
    if (fsmReconnectAttempts.value >= fsmMaxReconnectAttempts) {
      console.log('FSM max reconnect attempts reached')
      return
    }
    fsmReconnectAttempts.value++
    setTimeout(() => {
      connectFsmWebSocket()
    }, fsmReconnectInterval)
  }

  const sendFsmMessage = (type: string, payload: any): boolean => {
    if (fsmWs.value?.readyState === WebSocket.OPEN) {
      fsmWs.value.send(JSON.stringify({ type, ...payload }))
      return true
    }
    return false
  }

  const handleFsmWebSocketMessage = (data: any) => {
    switch (data.type) {
      case 'fsm.state_changed':
        // 章节状态变更
        updateFsmChaptersFromEvent(data)
        onFsmStateChange?.(data)
        break
      case 'fsm.awaiting_confirmation':
        // 等待人工确认
        handleAwaitingConfirmation(data)
        break
      case 'fsm.chapter_completed':
        // 章节完成
        handleChapterCompleted(data)
        break
      case 'fsm.pipeline_completed':
        // 流水线完成
        handlePipelineCompleted(data)
        break
      case 'fsm.error':
        console.error('FSM error:', data.message)
        break
      case 'status':
        // 完整状态响应
        updateFsmStatus(data)
        break
      case 'keepalive':
        break
      default:
        console.log('Unknown FSM message type:', data.type)
    }
  }

  const updateFsmChaptersFromEvent = (data: any) => {
    if (data.chapters) {
      fsmChapters.value = data.chapters.map((c: any) => ({
        id: c.id,
        index: c.index,
        title: c.title,
        status: c.status,
        current_stage: c.current_stage,
        progress: c.progress || 0,
      }))
    }
  }

  const updateFsmStatus = (data: PipelineStatusResponse) => {
    fsmStatus.value = data
    // 同步章节列表
    if (data.chapters) {
      fsmChapters.value = data.chapters as unknown as FsmChapterItem[]
    }
  }

  const handleAwaitingConfirmation = (data: any) => {
    const chapterId = data.chapter_id
    const chapter = fsmChapters.value.find(c => c.id === chapterId)
    if (chapter) {
      chapter.status = 'awaiting_confirm'
      chapter.current_stage = data.current_state
      chapter.progress = data.progress || 0
    }
    // 更新当前章节详情
    if (chapter) {
      loadChapterDetail(chapter)
    }
    fsmStatus.value = data
  }

  const handleChapterCompleted = (data: any) => {
    const chapterId = data.chapter_id
    const chapter = fsmChapters.value.find(c => c.id === chapterId)
    if (chapter) {
      chapter.status = 'completed'
      chapter.progress = 1
    }
    fsmStatus.value = data
    onChapterChange?.(chapter!)
    // 自动加载下一章节详情
    const nextChapter = fsmChapters.value.find(c => c.status === 'pending' || c.status === 'current')
    if (nextChapter) {
      loadChapterDetail(nextChapter)
    }
  }

  const handlePipelineCompleted = (data: any) => {
    fsmStatus.value = data
    // 标记所有章节完成
    fsmChapters.value.forEach(c => {
      if (c.status !== 'failed') c.status = 'completed'
    })
  }

  // ─────────────────────────────────────────────────────────────────────────
  // FSM 章节详情加载
  // ─────────────────────────────────────────────────────────────────────────
  const loadChapterDetail = async (chapter: FsmChapterItem) => {
    currentFsmChapter.value = chapter
    try {
      // 从后端获取章节详情（原文、编辑文本、标注、路由决策）
      const response = await fetch(`/api/projects/${projectId}/chapters/${chapter.id}/detail`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
      })
      if (response.ok) {
        const detail = await response.json()
        fsmChapterDetail.value = {
          chapter,
          original_text: detail.original_text || '',
          edited_text: detail.edited_text || '',
          annotations: detail.annotations || [],
          routing_decision: detail.routing_decision,
        }
      }
    } catch (error) {
      console.error('Failed to load chapter detail:', error)
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // FSM 动作：批准、驳回、重标注、跳过
  // ─────────────────────────────────────────────────────────────────────────
  const confirmFsmAction = async (action: FsmConfirmRequest['action'], edits?: Record<string, unknown>) => {
    if (!pendingChapter.value) return
    fsmActionLoading.value = action

    try {
      const payload: PipelineConfirmRequest = {
        project_id: projectId,
        chapter_id: pendingChapter.value.id,
        action,
        edits,
      }
      const response = await confirmPipelineAction(payload)
      fsmStatus.value = {
        project_id: projectId,
        mode: response.mode || 'interactive',
        current_state: response.current_state,
        chapter_index: response.chapter_index || 0,
        chapter_id: response.chapter_id || null,
        paused_at: null,
        user_confirmed: action === 'approve' || action === 'edit',
        error: null,
        completed_stages: [],
        status: 'running',
      }
      // 发送 WebSocket 确认
      sendFsmMessage('confirm', payload)
    } catch (error) {
      console.error('FSM confirm action failed:', error)
    } finally {
      fsmActionLoading.value = null
    }
  }

  const approveChapter = (edits?: Record<string, unknown>) => confirmFsmAction('approve', edits)
  const rejectChapter = () => confirmFsmAction('reject')
  const requestRerun = () => confirmFsmAction('request_rerun')
  const editChapter = (edits?: Record<string, unknown>) => confirmFsmAction('edit', edits)

  // ─────────────────────────────────────────────────────────────────────────
  // 基础聊天方法
  // ─────────────────────────────────────────────────────────────────────────
  const sendWebSocketMessage = (type: string, payload: any): boolean => {
    if (ws.value?.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify({ type, ...payload }))
      return true
    }
    return false
  }

  const sendMessage = (content?: string | Event) => {
    const message = typeof content === 'string' ? content : inputMessage.value.trim()
    if (!message || loading.value) return

    messages.value.push({
      role: 'user',
      content: message,
      timestamp: new Date().toISOString(),
    })
    inputMessage.value = ''
    loading.value = true
    scrollToBottom()

    onMessageSent?.(message)

    const sent = sendWebSocketMessage('message', {
      session_id: currentSessionId.value,
      content: message,
      context: { personality: settings.value.personality, length: settings.value.responseLength },
    })

    if (!sent) {
      sendHttpMessage(message)
    }
  }

  const sendHttpMessage = async (message: string) => {
    try {
      const data = await sendAgentChatMessage(projectId, {
        message,
        session_id: currentSessionId.value,
        context: { personality: settings.value.personality, length: settings.value.responseLength },
      })
      loading.value = false

      if (data.message) {
        messages.value.push({
          role: 'assistant',
          content: data.message,
          timestamp: data.timestamp,
          metadata: { agent_type: data.agent_type },
        })
        currentSessionId.value = data.session_id
        scrollToBottom()
        onMessageReceived?.(data.message)
      }
    } catch (error) {
      loading.value = false
      console.error('HTTP request failed:', error)
      messages.value.push({
        role: 'assistant',
        content: `❌ ${t('agentChat.error.network')}`,
        timestamp: new Date().toISOString(),
        metadata: { error: true },
      })
    }
  }

  const loadSessions = async () => {
    try {
      const data = await fetchAgentSessions(projectId)
      sessions.value = data.sessions || []
      if (sessions.value.length > 0 && !currentSessionId.value) {
        currentSessionId.value = sessions.value[0].session_id
        loadSession(currentSessionId.value)
      }
    } catch (error) {
      console.error('Failed to load sessions:', error)
    }
  }

  const loadSession = async (sessionId: string) => {
    try {
      const data = await fetchAgentSessionHistory(projectId, sessionId)
      messages.value = data.messages || []
      currentSessionId.value = data.session_id
      showHistory.value = false
      scrollToBottom()
    } catch (error) {
      console.error('Failed to load session:', error)
    }
  }

  const newSession = () => {
    messages.value = []
    currentSessionId.value = null
    loading.value = false
    showHistory.value = false
    sendWebSocketMessage('message', {
      content: '',
      session_id: null,
    })
  }

  const deleteSession = async (sessionId: string) => {
    try {
      await deleteAgentSession(projectId, sessionId)
      sessions.value = sessions.value.filter((s) => s.session_id !== sessionId)
      if (currentSessionId.value === sessionId) {
        newSession()
      }
    } catch (error) {
      console.error('Failed to delete session:', error)
    }
  }

  const clearAllHistory = async () => {
    if (!confirm(t('agentChat.confirmClearHistory'))) return

    try {
      for (const session of sessions.value) {
        await deleteAgentSession(projectId, session.session_id)
      }
      sessions.value = []
      newSession()
      showSettings.value = false
    } catch (error) {
      console.error('Failed to clear history:', error)
    }
  }

  const regenerateResponse = (index: number) => {
    if (index > 0 && messages.value[index - 1].role === 'user') {
      const userMessage = messages.value[index - 1].content
      messages.value.splice(index)
      sendMessage(userMessage)
    }
  }

  const copyMessage = (content: string) => {
    navigator.clipboard.writeText(content)
  }

  const attachFile = () => {
    console.log('Attach file clicked')
  }

  const addNewline = () => {
    inputMessage.value += '\n'
  }

  const scrollToBottom = () => {
    if (!settings.value.autoScroll) return
    nextTick(() => {
      if (messagesArea.value) {
        messagesArea.value.scrollTop = messagesArea.value.scrollHeight
      }
    })
  }

  const formatTime = (timestamp: string) => {
    if (!settings.value.showTimestamps) return ''
    const date = new Date(timestamp)
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  const formatDate = (timestamp: string) => {
    const date = new Date(timestamp)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const days = Math.floor(diff / (1000 * 60 * 60 * 24))

    if (days === 0) return t('agentChat.today')
    if (days === 1) return t('agentChat.yesterday')
    if (days < 7) return `${days}${t('agentChat.daysAgo')}`
    return date.toLocaleDateString()
  }

  const formatMessage = (content: string) => {
    return content
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/`(.+?)`/g, '<code>$1</code>')
      .replace(/\n/g, '<br>')
  }

  const toggleHistory = () => {
    showHistory.value = !showHistory.value
    if (showHistory.value) {
      loadSessions()
    }
  }

  const handleClose = () => {
    onClose?.()
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Lifecycle
  // ─────────────────────────────────────────────────────────────────────────
  onMounted(() => {
    connectWebSocket()
    if (fsmMode) {
      connectFsmWebSocket()
      // 初始加载状态
      fetchPipelineStatus(projectId).then(status => {
        fsmStatus.value = status
        if (status.chapters) {
          fsmChapters.value = status.chapters as unknown as FsmChapterItem[]
        }
      }).catch(console.error)
    }
    if (initialMessage) {
      sendMessage(initialMessage)
    }
    if (messageInput.value) {
      messageInput.value.style.height = 'auto'
      messageInput.value.style.height = `${messageInput.value.scrollHeight}px`
    }
  })

  onUnmounted(() => {
    if (ws.value) {
      ws.value.close()
      ws.value = null
    }
    if (fsmWs.value) {
      fsmWs.value.close()
      fsmWs.value = null
    }
  })

  watch(inputMessage, () => {
    nextTick(() => {
      if (messageInput.value) {
        messageInput.value.style.height = 'auto'
        messageInput.value.style.height = `${Math.min(messageInput.value.scrollHeight, 150)}px`
      }
    })
  })

  return {
    // 基础聊天
    messages,
    inputMessage,
    loading,
    showHistory,
    showSettings,
    currentSessionId,
    sessions,
    connectionStatus,
    messagesArea,
    messageInput,
    settings,
    statusClass,
    statusText,
    connectionStatusText,
    suggestedPrompts,
    sendMessage,
    loadSessions,
    loadSession,
    newSession,
    deleteSession,
    clearAllHistory,
    regenerateResponse,
    copyMessage,
    attachFile,
    addNewline,
    scrollToBottom,
    formatTime,
    formatDate,
    formatMessage,
    toggleHistory,
    handleClose,
    ws: ws.value,

    // FSM 交互模式
    fsmMode,
    fsmChapters,
    currentFsmChapter,
    fsmChapterDetail,
    fsmStatus,
    fsmLoading,
    fsmActionLoading,
    fsmIsRunning,
    fsmIsPaused,
    fsmCanConfirm,
    pendingChapter,
    loadChapterDetail,
    approveChapter,
    rejectChapter,
    requestRerun,
    editChapter,
    confirmFsmAction,
  }
}
