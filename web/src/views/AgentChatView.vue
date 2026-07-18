<template>
  <div class="agent-chat" ref="chatContainer">
    <!-- Header -->
    <div class="chat-header">
      <div class="header-left">
        <div class="avatar" :class="statusClass">
          <Icon icon="mdi:robot" width="24" height="24" />
        </div>
        <div class="header-info">
          <h3>{{ t('agentChat.title') }}</h3>
          <span class="status-badge" :class="statusClass">
            {{ statusText }}
          </span>
        </div>
      </div>
      <div class="header-actions">
        <button class="icon-btn" @click="toggleHistory" :title="t('agentChat.history')">
          <Icon icon="mdi:history" width="20" height="20" />
        </button>
        <button class="icon-btn" @click="showSettings = true" :title="t('agentChat.settings')">
          <Icon icon="mdi:cog" width="20" height="20" />
        </button>
        <button class="icon-btn" @click="$emit('close')" v-if="closable" :title="t('common.close')">
          <Icon icon="mdi:close" width="20" height="20" />
        </button>
      </div>
    </div>

    <!-- Messages Area -->
    <div class="messages-area" ref="messagesArea">
      <!-- Welcome Message -->
      <div class="welcome-message" v-if="messages.length === 0 && !loading">
        <div class="welcome-avatar">
          <Icon icon="mdi:star" width="32" height="32" />
        </div>
        <h4>{{ t('agentChat.welcomeTitle') }}</h4>
        <p>{{ t('agentChat.welcomeText') }}</p>
        <div class="suggested-prompts">
          <button
            v-for="prompt in suggestedPrompts"
            :key="prompt"
            class="suggested-prompt"
            @click="sendMessage(prompt)"
          >
            {{ prompt }}
          </button>
        </div>
      </div>

      <!-- Messages List -->
      <div class="messages-list" v-else>
        <div
          v-for="(msg, index) in messages"
          :key="index"
          class="message"
          :class="msg.role"
        >
          <div class="message-avatar">
            <Icon :icon="msg.role === 'user' ? 'mdi:account' : 'mdi:robot'" width="20" height="20" />
          </div>
          <div class="message-content">
            <div class="message-header">
              <span class="message-role">
                {{ msg.role === 'user' ? t('agentChat.you') : t('agentChat.assistant') }}
              </span>
              <span class="message-time">{{ formatTime(msg.timestamp) }}</span>
            </div>
            <div class="message-text" v-html="formatMessage(msg.content)"></div>
            <div class="message-actions" v-if="msg.role === 'assistant'">
              <button class="action-btn" @click="copyMessage(msg.content)" :title="t('agentChat.copy')">
                <Icon icon="mdi:content-copy" width="16" height="16" />
              </button>
              <button class="action-btn" @click="regenerateResponse(index)" :title="t('agentChat.regenerate')" v-if="index === messages.length - 1">
                <Icon icon="mdi:refresh" width="16" height="16" />
              </button>
            </div>
          </div>
        </div>

        <!-- Typing Indicator -->
        <div class="typing-indicator" v-if="loading">
          <div class="typing-avatar">
            <Icon icon="mdi:robot" width="24" height="24" />
          </div>
          <div class="typing-bubble">
            <span></span><span></span><span></span>
          </div>
        </div>
      </div>
    </div>

    <!-- Input Area -->
    <div class="input-area">
      <div class="input-wrapper">
        <textarea
          ref="messageInput"
          v-model="inputMessage"
          :placeholder="t('agentChat.placeholder')"
          @keydown.enter.exact="sendMessage"
          @keydown.enter.shift="addNewline"
          rows="1"
          class="message-input"
        ></textarea>
        <div class="input-actions">
          <button class="icon-btn" @click="attachFile" :title="t('agentChat.attachFile')">
            <Icon icon="mdi:paperclip" width="20" height="20" />
          </button>
          <button
            class="icon-btn send-btn"
            @click="sendMessage"
            :disabled="!inputMessage.trim() || loading"
            :title="t('agentChat.send')"
          >
            <Icon icon="mdi:send" width="20" height="20" />
          </button>
        </div>
      </div>
      <div class="input-hints">
        <span>{{ t('agentChat.enterToSend') }}</span>
        <span>{{ t('agentChat.shiftEnterForNewline') }}</span>
      </div>
    </div>

    <!-- History Panel -->
    <div class="history-panel" v-if="showHistory" @click.self="toggleHistory">
      <div class="history-panel-content">
        <div class="history-header">
          <h4>{{ t('agentChat.chatHistory') }}</h4>
          <button class="icon-btn" @click="toggleHistory" :title="t('common.close')">
            <Icon icon="mdi:close" width="20" height="20" />
          </button>
        </div>
        <div class="history-list">
          <div
            v-for="session in sessions"
            :key="session.session_id"
            class="history-item"
            :class="{ active: session.session_id === currentSessionId }"
            @click="loadSession(session.session_id)"
          >
            <div class="history-item-info">
              <div class="history-item-title">
                {{ session.message_count > 0 ? session.messages[0]?.content?.substring(0, 30) + '...' : t('agentChat.emptyChat') }}
              </div>
              <div class="history-item-meta">
                <span>{{ formatDate(session.last_active) }}</span>
                <span>{{ session.message_count }} {{ t('agentChat.messages') }}</span>
              </div>
            </div>
            <button class="icon-btn danger" @click.stop="deleteSession(session.session_id)" :title="t('agentChat.delete')">
              <Icon icon="mdi:trash-can" width="16" height="16" />
            </button>
          </div>
          <button class="new-chat-btn" @click="newSession">
            <Icon icon="mdi:plus" width="20" height="20" />
            {{ t('agentChat.newChat') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Settings Modal -->
    <div class="modal-overlay" v-if="showSettings" @click.self="showSettings = false">
      <div class="modal settings-modal">
        <div class="modal-header">
          <h4>{{ t('agentChat.settings') }}</h4>
          <button class="icon-btn" @click="showSettings = false">
            <Icon icon="mdi:close" width="20" height="20" />
          </button>
        </div>
        <div class="modal-body">
          <div class="setting-group">
            <label>{{ t('agentChat.agentPersonality') }}</label>
            <select v-model="settings.personality" class="setting-select">
              <option value="general">{{ t('agentChat.personality.general') }}</option>
              <option value="expert">{{ t('agentChat.personality.expert') }}</option>
              <option value="creative">{{ t('agentChat.personality.creative') }}</option>
              <option value="concise">{{ t('agentChat.personality.concise') }}</option>
            </select>
          </div>
          <div class="setting-group">
            <label>{{ t('agentChat.responseLength') }}</label>
            <select v-model="settings.responseLength" class="setting-select">
              <option value="short">{{ t('agentChat.length.short') }}</option>
              <option value="medium">{{ t('agentChat.length.medium') }}</option>
              <option value="long">{{ t('agentChat.length.long') }}</option>
            </select>
          </div>
          <div class="setting-group">
            <label class="checkbox-label">
              <input type="checkbox" v-model="settings.autoScroll" />
              <span>{{ t('agentChat.autoScroll') }}</span>
            </label>
          </div>
          <div class="setting-group">
            <label class="checkbox-label">
              <input type="checkbox" v-model="settings.showTimestamps" />
              <span>{{ t('agentChat.showTimestamps') }}</span>
            </label>
          </div>
          <div class="setting-group danger-zone">
            <h5>{{ t('agentChat.dangerZone') }}</h5>
            <button class="btn danger" @click="clearAllHistory">
              {{ t('agentChat.clearAllHistory') }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Connection Status -->
    <div class="connection-status" :class="connectionStatus">
      <Icon :icon="connectionStatus === 'connected' ? 'mdi:wifi' : 'mdi:wifi-off'" width="14" height="14" />
      <span>{{ connectionStatusText }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useI18n } from '../i18n'
import { Icon } from '@iconify/vue'

interface Message {
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  metadata?: Record<string, any>
}

interface Session {
  session_id: string
  project_id: number
  messages: Message[]
  created_at: string
  last_active: string
  message_count: number
}

interface Settings {
  personality: 'general' | 'expert' | 'creative' | 'concise'
  responseLength: 'short' | 'medium' | 'long'
  autoScroll: boolean
  showTimestamps: boolean
}

interface Props {
  projectId: number
  closable?: boolean
  initialMessage?: string
}

const props = withDefaults(defineProps<Props>(), {
  closable: false,
  initialMessage: '',
})

const emit = defineEmits<{
  close: []
  messageSent: [message: string]
  messageReceived: [message: string]
}>()

const { t } = useI18n()

// State
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

// Computed
const statusClass = computed(() => {
  if (connectionStatus.value === 'connected') return 'online'
  if (connectionStatus.value === 'connecting') return 'connecting'
  return 'offline'
})

const statusText = computed(() => {
  if (connectionStatus.value === 'connected') return '在线'
  if (connectionStatus.value === 'connecting') return '连接中...'
  return '离线'
})

const connectionStatusText = computed(() => {
  if (connectionStatus.value === 'connected') return 'WebSocket 已连接'
  if (connectionStatus.value === 'connecting') return '正在连接 WebSocket...'
  return 'WebSocket 未连接，使用 HTTP 轮询模式'
})

const suggestedPrompts = computed(() => [
  t('agentChat.suggestions.progress'),
  t('agentChat.suggestions.chapters'),
  t('agentChat.suggestions.tts'),
  t('agentChat.suggestions.quality'),
  t('agentChat.suggestions.export'),
  t('agentChat.suggestions.help'),
])

// Methods
const connectWebSocket = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = import.meta.env.VITE_API_BASE
    ? new URL(import.meta.env.VITE_API_BASE, window.location.origin).host
    : window.location.host
  const wsUrl = `${protocol}//${host}/api/agent/chat/${props.projectId}`

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
        emit('messageReceived', data.message)
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
      // Show error message
      messages.value.push({
        role: 'assistant',
        content: `❌ ${data.message}`,
        timestamp: data.timestamp,
        metadata: { error: true },
      })
      break
    case 'keepalive':
      // Connection alive
      break
    default:
      console.log('Unknown message type:', data.type)
  }
}

const sendWebSocketMessage = (type: string, payload: any) => {
  if (ws.value?.readyState === WebSocket.OPEN) {
    ws.value.send(JSON.stringify({ type, ...payload }))
    return true
  }
  return false
}

const sendMessage = (content?: string | Event) => {
  // Handle both direct string call and event from button click
  const message = typeof content === 'string' ? content : inputMessage.value.trim()
  if (!message || loading.value) return

  // Add user message immediately
  messages.value.push({
    role: 'user',
    content: message,
    timestamp: new Date().toISOString(),
  })
  inputMessage.value = ''
  loading.value = true
  scrollToBottom()

  emit('messageSent', message)

  // Try WebSocket first
  const sent = sendWebSocketMessage('message', {
    session_id: currentSessionId.value,
    content: message,
    context: { personality: settings.value.personality, length: settings.value.responseLength },
  })

  // Fallback to HTTP if WebSocket not connected
  if (!sent) {
    sendHttpMessage(message)
  }
}

const sendHttpMessage = async (message: string) => {
  try {
    const response = await fetch(`/api/agent/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_id: props.projectId,
        message,
        session_id: currentSessionId.value,
        context: { personality: settings.value.personality, length: settings.value.responseLength },
      }),
    })

    const data = await response.json()
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
      emit('messageReceived', data.message)
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
    const response = await fetch(`/api/agent/chat/${props.projectId}/sessions`)
    const data = await response.json()
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
    const response = await fetch(`/api/agent/chat/${props.projectId}/history?session_id=${sessionId}`)
    const data = await response.json()
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
    await fetch(`/api/agent/chat/${props.projectId}/sessions/${sessionId}`, {
      method: 'DELETE',
    })
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
      await fetch(`/api/agent/chat/${props.projectId}/sessions/${session.session_id}`, {
        method: 'DELETE',
      })
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
  // Could show toast notification here
}

const attachFile = () => {
  // TODO: Implement file attachment for sending files to agent
  // Could open a file picker and upload the file
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
  // Simple markdown-like formatting
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

// Lifecycle
onMounted(() => {
  connectWebSocket()
  if (props.initialMessage) {
    sendMessage(props.initialMessage)
  }
  // Auto-resize textarea
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
})

// Watch for input height adjustment
watch(inputMessage, () => {
  nextTick(() => {
    if (messageInput.value) {
      messageInput.value.style.height = 'auto'
      messageInput.value.style.height = `${Math.min(messageInput.value.scrollHeight, 150)}px`
    }
  })
})
</script>

<style scoped>
.agent-chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 500px;
  max-height: 800px;
  background: var(--bg-primary, #ffffff);
  border-radius: 12px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  position: relative;
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  background: var(--bg-secondary, #f8f9fa);
  border-bottom: 1px solid var(--border-color, #e9ecef);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  font-size: 18px;

  &.online {
    box-shadow: 0 0 0 2px #22c55e;
  }
  &.connecting {
    box-shadow: 0 0 0 2px #f59e0b;
  }
  &.offline {
    box-shadow: 0 0 0 2px #9ca3af;
  }
}

.header-info h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
}

.status-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 500;

  &.online {
    background: #dcfce7;
    color: #166534;
  }
  &.connecting {
    background: #fef3c7;
    color: #92400e;
  }
  &.offline {
    background: #f3f4f6;
    color: #6b7280;
  }
}

.header-actions {
  display: flex;
  gap: 8px;
}

.icon-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary, #6b7280);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;

  &:hover {
    background: var(--bg-tertiary, #e9ecef);
    color: var(--text-primary, #1f2937);
  }

  &.danger:hover {
    background: #fee2e2;
    color: #dc2626;
  }
}

.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.welcome-message {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 40px 20px;
  color: var(--text-secondary, #6b7280);

  .welcome-avatar {
    width: 64px;
    height: 64px;
    border-radius: 50%;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: 24px;
    margin-bottom: 16px;
  }

  h4 {
    margin: 0 0 8px;
    font-size: 20px;
    color: var(--text-primary, #1f2937);
  }

  p {
    margin: 0 0 24px;
    max-width: 400px;
    line-height: 1.6;
  }
}

.suggested-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  max-width: 500px;
}

.suggested-prompt {
  padding: 8px 16px;
  border: 1px solid var(--border-color, #e9ecef);
  border-radius: 20px;
  background: var(--bg-primary, #ffffff);
  color: var(--text-secondary, #6b7280);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;

  &:hover {
    border-color: #667eea;
    color: #667eea;
    background: #f0f4ff;
  }
}

.messages-list {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
}

.message {
  display: flex;
  gap: 10px;
  animation: fadeIn 0.3s ease;

  &.user {
    flex-direction: row-reverse;
    .message-content {
      text-align: right;
    }
  }
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.message-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 14px;

  .user & {
    background: #e0e7ff;
    color: #3730a3;
  }
  .assistant & {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
  }
  .system & {
    background: #fef3c7;
    color: #92400e;
  }
}

.message-content {
  flex: 1;
  min-width: 0;
}

.message-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
  font-size: 12px;

  .user & {
    flex-direction: row-reverse;
  }
}

.message-role {
  font-weight: 600;
  color: var(--text-secondary, #6b7280);
}

.message-time {
  color: var(--text-tertiary, #9ca3af);
  font-size: 11px;
}

.message-text {
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-primary, #1f2937);
  white-space: pre-wrap;
  word-wrap: break-word;

  code {
    background: var(--bg-tertiary, #f3f4f6);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 13px;
    font-family: 'Monaco', 'Menlo', monospace;
  }

  strong {
    font-weight: 600;
  }

  em {
    font-style: italic;
  }
}

.message-actions {
  display: flex;
  gap: 4px;
  margin-top: 8px;
  justify-content: flex-end;

  .user & {
    justify-content: flex-start;
  }
}

.action-btn {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-tertiary, #9ca3af);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  transition: all 0.2s;

  &:hover {
    background: var(--bg-tertiary, #f3f4f6);
    color: var(--text-primary, #1f2937);
  }
}

.typing-indicator {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  padding-bottom: 8px;

  .typing-avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: 14px;
    flex-shrink: 0;
  }

  .typing-bubble {
    display: flex;
    gap: 3px;
    padding: 12px 16px;
    background: var(--bg-secondary, #f8f9fa);
    border-radius: 18px;
    border-bottom-left-radius: 4px;

    span {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--text-tertiary, #9ca3af);
      animation: typing 1.4s infinite ease-in-out;

      &:nth-child(2) { animation-delay: 0.2s; }
      &:nth-child(3) { animation-delay: 0.4s; }
    }
  }
}

@keyframes typing {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-6px); opacity: 1; }
}

.input-area {
  padding: 16px 20px;
  background: var(--bg-secondary, #f8f9fa);
  border-top: 1px solid var(--border-color, #e9ecef);
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  background: var(--bg-primary, #ffffff);
  border: 1px solid var(--border-color, #e9ecef);
  border-radius: 12px;
  padding: 8px 12px;
  transition: border-color 0.2s;

  &:focus-within {
    border-color: #667eea;
    box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
  }
}

.message-input {
  flex: 1;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  font-size: 14px;
  line-height: 1.5;
  font-family: inherit;
  color: var(--text-primary, #1f2937);
  min-height: 24px;
  max-height: 150px;
  padding: 4px 0;

  &::placeholder {
    color: var(--text-tertiary, #9ca3af);
  }
}

.input-actions {
  display: flex;
  gap: 4px;
  align-items: center;
}

.send-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s, opacity 0.2s;

  &:hover:not(:disabled) {
    transform: scale(1.05);
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
}

.input-hints {
  display: flex;
  gap: 16px;
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-tertiary, #9ca3af);
}

.history-panel {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 320px;
  max-width: 100%;
  background: var(--bg-primary, #ffffff);
  box-shadow: -4px 0 20px rgba(0, 0, 0, 0.1);
  z-index: 10;
  animation: slideIn 0.3s ease;

  @media (max-width: 600px) {
    width: 100%;
  }
}

@keyframes slideIn {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

.history-panel-content {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color, #e9ecef);

  h4 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }
}

.history-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;

  &:hover {
    background: var(--bg-secondary, #f8f9fa);
  }

  &.active {
    background: #f0f4ff;
    border-left: 3px solid #667eea;
  }
}

.history-item-info {
  flex: 1;
  min-width: 0;
}

.history-item-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary, #1f2937);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}

.history-item-meta {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--text-tertiary, #9ca3af);
}

.new-chat-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 12px;
  margin: 8px;
  border: 1px dashed var(--border-color, #e9ecef);
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary, #6b7280);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;

  &:hover {
    border-color: #667eea;
    color: #667eea;
    background: #f0f4ff;
  }
}

.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 20px;
}

.settings-modal {
  width: 100%;
  max-width: 400px;
  background: var(--bg-primary, #ffffff);
  border-radius: 16px;
  overflow: hidden;
  animation: scaleIn 0.2s ease;
}

@keyframes scaleIn {
  from { transform: scale(0.95); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color, #e9ecef);

  h4 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }
}

.modal-body {
  padding: 20px;
}

.setting-group {
  margin-bottom: 20px;

  label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary, #1f2937);
    margin-bottom: 8px;
  }
}

.setting-select {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border-color, #e9ecef);
  border-radius: 8px;
  background: var(--bg-primary, #ffffff);
  font-size: 13px;
  color: var(--text-primary, #1f2937);
  cursor: pointer;

  &:focus {
    outline: none;
    border-color: #667eea;
    box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
  }
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-primary, #1f2937);

  input {
    width: 18px;
    height: 18px;
    accent-color: #667eea;
  }
}

.danger-zone {
  padding-top: 20px;
  border-top: 1px solid var(--border-color, #e9ecef);

  h5 {
    margin: 0 0 12px;
    font-size: 13px;
    font-weight: 600;
    color: #dc2626;
  }
}

.btn {
  padding: 10px 16px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;

  &.danger {
    background: #fee2e2;
    color: #dc2626;
    width: 100%;

    &:hover {
      background: #fecaca;
    }
  }
}

.connection-status {
  position: absolute;
  bottom: 12px;
  left: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 11px;
  z-index: 5;
  background: var(--bg-primary, #ffffff);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);

  &.connected {
    color: #166534;
    background: #dcfce7;

    svg { color: #22c55e; }
  }
  &.connecting {
    color: #92400e;
    background: #fef3c7;

    svg { color: #f59e0b; }
  }
  &.disconnected {
    color: #6b7280;
    background: #f3f4f6;

    svg { color: #9ca3af; }
  }
}
</style>