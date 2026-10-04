<template>
  <div class="history-panel" v-if="show" @click.self="$emit('close')">
    <div class="history-panel-content">
      <div class="history-header">
        <h4>{{ t('agentChat.chatHistory') }}</h4>
        <button class="icon-btn" @click="$emit('close')" :title="t('common.close')">
          <Icon icon="mdi:close" width="20" height="20" />
        </button>
      </div>
      <div class="history-list">
        <div
          v-for="session in sessions"
          :key="session.session_id"
          class="history-item"
          :class="{ active: session.session_id === currentSessionId }"
          @click="$emit('load-session', session.session_id)"
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
          <button class="icon-btn danger" @click.stop="$emit('delete-session', session.session_id)" :title="t('agentChat.delete')">
            <Icon icon="mdi:trash-can" width="16" height="16" />
          </button>
        </div>
        <button class="new-chat-btn" @click="$emit('new-session')">
          <Icon icon="mdi:plus" width="20" height="20" />
          {{ t('agentChat.newChat') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from '../../i18n'
import { Icon } from '@iconify/vue'

interface Session {
  session_id: string
  project_id: number
  messages: Array<{
    role: string
    content: string
    timestamp: string
  }>
  created_at: string
  last_active: string
  message_count: number
}

interface Props {
  show: boolean
  sessions: Session[]
  currentSessionId: string | null
}

const props = defineProps<Props>()

defineEmits<{
  close: []
  'load-session': [sessionId: string]
  'delete-session': [sessionId: string]
  'new-session': []
}>()

const { t } = useI18n()

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
</script>

<style scoped>
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
</style>
