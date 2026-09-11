<template>
  <div class="agent-chat">
    <ChatHeader
      :connection-status="connectionStatus"
      :closable="closable"
      @history="showHistory = true"
      @settings="showSettings = true"
      @close="handleClose"
    />

    <ChatMessages
      :messages="messages"
      :loading="loading"
      :settings="settings"
      :suggested-prompts="suggestedPrompts"
      @send-message="sendMessage"
      @copy-message="copyMessage"
      @regenerate="regenerateResponse"
    />

    <ChatInput
      v-model="inputMessage"
      :loading="loading"
      :placeholder="t('agentChat.placeholder')"
      @send="sendMessage"
      @attach="attachFile"
      @newline="addNewline"
    />

    <ChatHistoryPanel
      :show="showHistory"
      :sessions="sessions"
      :current-session-id="currentSessionId"
      @close="showHistory = false"
      @load-session="loadSession"
      @delete-session="deleteSession"
      @new-session="newSession"
    />

    <ChatSettingsModal
      :show="showSettings"
      :settings="settings"
      @close="showSettings = false"
      @clear-history="clearAllHistory"
    />

    <ConnectionStatus :connection-status="connectionStatus" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '../i18n'
import { useAgentChat } from '../composables/useAgentChat'
import ChatHeader from '../components/chat/ChatHeader.vue'
import ChatMessages from '../components/chat/ChatMessages.vue'
import ChatInput from '../components/chat/ChatInput.vue'
import ChatHistoryPanel from '../components/chat/ChatHistoryPanel.vue'
import ChatSettingsModal from '../components/chat/ChatSettingsModal.vue'
import ConnectionStatus from '../components/chat/ConnectionStatus.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const projectId = Number(route.params.projectId)
const closable = ref(false)

const chat = useAgentChat({
  projectId,
  closable: false,
  initialMessage: '',
  onClose: () => {
    router.push('/projects/' + projectId)
  },
})

const {
  messages,
  inputMessage,
  loading,
  showHistory,
  showSettings,
  currentSessionId,
  sessions,
  connectionStatus,
  settings,
  suggestedPrompts,
  sendMessage,
  loadSession,
  newSession,
  deleteSession,
  clearAllHistory,
  regenerateResponse,
  copyMessage,
  attachFile,
  addNewline,
  handleClose,
} = chat
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
</style>
