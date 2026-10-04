<template>
  <div class="messages-area">
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
          @click="$emit('send-message', prompt)"
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
            <button class="action-btn" @click="$emit('copy-message', msg.content)" :title="t('agentChat.copy')">
              <Icon icon="mdi:content-copy" width="16" height="16" />
            </button>
            <button class="action-btn" @click="$emit('regenerate', index)" :title="t('agentChat.regenerate')" v-if="index === messages.length - 1">
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
</template>

<script setup lang="ts">
import { useI18n } from '../../i18n'
import { Icon } from '@iconify/vue'

interface Props {
  messages: Array<{
    role: 'user' | 'assistant' | 'system'
    content: string
    timestamp: string
    metadata?: Record<string, any>
  }>
  loading: boolean
  settings: {
    autoScroll: boolean
    showTimestamps: boolean
  }
  suggestedPrompts: string[]
}

const props = defineProps<Props>()

defineEmits<{
  'send-message': [message: string]
  'copy-message': [content: string]
  regenerate: [index: number]
}>()

const { t } = useI18n()

const formatTime = (timestamp: string) => {
  if (!props.settings.showTimestamps) return ''
  const date = new Date(timestamp)
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

const formatMessage = (content: string) => {
  return content
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>')
}
</script>

<style scoped>
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
</style>
