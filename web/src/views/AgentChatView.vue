<template>
  <div class="agent-chat" :class="{ 'fsm-mode': fsmMode }">
    <!-- FSM Mode Header -->
    <header v-if="fsmMode" class="fsm-header">
      <div class="header-left">
        <button class="btn btn-ghost" @click="goBack">
          <Icon icon="mdi:arrow-left" width="18" height="18" />
          <span>{{ t('common.back') }}</span>
        </button>
        <h1>{{ t('agentChat.fsm.title') }}</h1>
        <el-tag :type="getFsmStatusType(fsmStatus)" size="small">
          {{ getFsmStatusLabel(fsmStatus) }}
        </el-tag>
      </div>
      <div class="header-right">
        <el-button type="default" @click="refreshFsmStatus" :loading="fsmLoading" size="small">
          <Refresh /><span>{{ t('agentChat.fsm.refresh') }}</span>
        </el-button>
        <el-button type="danger" @click="stopPipeline" :disabled="!fsmIsRunning" size="small">
          <Stopwatch /><span>{{ t('agentChat.fsm.stop') }}</span>
        </el-button>
      </div>
    </header>

    <!-- Chat Mode Header -->
    <header v-else class="chat-header">
      <ChatHeader
        :connection-status="connectionStatus"
        :closable="closable"
        @history="showHistory = true"
        @settings="showSettings = true"
        @close="handleClose"
      />
    </header>

    <!-- FSM Mode Layout -->
    <div v-if="fsmMode" class="fsm-layout">
      <ChapterListPanel
        ref="chapterListRef"
        :fsm-chapters="fsmChapters"
        :current-chapter="currentFsmChapter"
        :fsm-loading="fsmLoading"
        :fsm-mode="true"
        @chapter-select="handleChapterSelect"
        @refresh="refreshFsmStatus"
      />

      <div class="fsm-main">
        <ChapterDetailPanel
          :current-chapter="currentFsmChapter"
          :chapter-detail="fsmChapterDetail"
          :fsm-mode="true"
          @annotation-click="handleAnnotationClick"
        />

        <FSMActionBar
          :fsm-can-confirm="fsmCanConfirm"
          :fsm-is-paused="fsmIsPaused"
          :fsm-is-running="fsmIsRunning"
          :fsm-action-loading="fsmActionLoading"
          :fsm-status="fsmStatus"
          :pending-chapter="pendingChapter"
          @approve="approveChapter"
          @reject="rejectChapter"
          @request-rerun="requestRerun"
          @edit="editChapter"
          @resume="handleResume"
          @start-pipeline="handleStartPipeline"
        />
      </div>
    </div>

    <!-- Chat Mode Layout -->
    <div v-else class="chat-layout">
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
    </div>

    <!-- Shared Panels -->
    <ChatHistoryPanel
      v-if="!fsmMode"
      :show="showHistory"
      :sessions="sessions"
      :current-session-id="currentSessionId"
      @close="showHistory = false"
      @load-session="loadSession"
      @delete-session="deleteSession"
      @new-session="newSession"
    />

    <ChatSettingsModal
      v-if="!fsmMode"
      :show="showSettings"
      :settings="settings"
      @close="showSettings = false"
      @clear-history="clearAllHistory"
    />

    <ConnectionStatus v-if="!fsmMode" :connection-status="connectionStatus" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '../i18n'
import { useAgentChat } from '../composables/useAgentChat'
import { ElButton, ElTag } from 'element-plus'
import { Refresh, Stopwatch } from '@element-plus/icons-vue'
import { Icon } from '@iconify/vue'
import type { PipelineStatusResponse } from '../api'

// Chat components
import ChatHeader from '../components/chat/ChatHeader.vue'
import ChatMessages from '../components/chat/ChatMessages.vue'
import ChatInput from '../components/chat/ChatInput.vue'
import ChatHistoryPanel from '../components/chat/ChatHistoryPanel.vue'
import ChatSettingsModal from '../components/chat/ChatSettingsModal.vue'
import ConnectionStatus from '../components/chat/ConnectionStatus.vue'

// FSM components (Phase 2)
import ChapterListPanel from '../components/agent/ChapterListPanel.vue'
import ChapterDetailPanel from '../components/agent/ChapterDetailPanel.vue'
import FSMActionBar from '../components/agent/FSMActionBar.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const projectId = Number(route.params.projectId)
const fsmMode = ref<boolean>(route.query.fsm === 'true')
const closable = ref(false)

const chat = useAgentChat({
  projectId,
  closable: false,
  initialMessage: '',
  fsmMode: fsmMode.value,
  onClose: () => {
    router.push('/projects/' + projectId)
  },
  onChapterChange: (chapter) => {
    console.log('Chapter changed:', chapter)
  },
  onFsmStateChange: (state) => {
    console.log('FSM state changed:', state)
  },
})

const {
  // Chat
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

  // FSM
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
} = chat

const getFsmStatusType = (status: PipelineStatusResponse | null) => {
  if (!status) return 'info'
  const state = status.current_state || status.status
  switch (state) {
    case 'running':
    case 'synthesizing':
    case 'quality_check':
    case 'exporting':
    case 'extracting':
    case 'analyzing':
    case 'annotating':
    case 'audio_postprocessing':
      return 'primary'
    case 'paused':
    case 'pending_human_confirm':
      return 'warning'
    case 'completed':
      return 'success'
    case 'failed':
      return 'danger'
    default: return 'info'
  }
}

const getFsmStatusLabel = (status: PipelineStatusResponse | null) => {
  if (!status) return '空闲'
  const state = status.current_state || status.status
  const labels: Record<string, string> = {
    running: '运行中',
    paused: '暂停',
    completed: '完成',
    failed: '失败',
    idle: '空闲',
    extracting: '提取中',
    analyzing: '分析中',
    annotating: '标注中',
    pending_human_confirm: '待人工确认',
    audio_postprocessing: '音频后处理',
    synthesizing: '合成中',
    quality_check: '质检中',
    exporting: '导出中',
  }
  return labels[state] || state
}

const handleChapterSelect = (chapter: { id: number; index: number; title: string; status: string; current_stage?: string; progress: number }) => {
  loadChapterDetail(chapter as any)
}

const handleAnnotationClick = (annotation: { id: string; type: string; label: string; value: string }) => {
  console.log('Annotation clicked:', annotation)
}

const refreshFsmStatus = async () => {
  try {
    const { fetchPipelineStatus } = await import('../api')
    const status = await fetchPipelineStatus(projectId)
    chat.fsmStatus.value = status
    if (status.chapters) {
      chat.fsmChapters.value = status.chapters as any
    }
  } catch (e) {
    console.error('Failed to refresh FSM status:', e)
  }
}

const stopPipeline = async () => {
  try {
    // Use WebSocket to send stop command
    if (chat.ws?.readyState === WebSocket.OPEN) {
      chat.ws.send(JSON.stringify({ type: 'stop', project_id: projectId }))
    }
    await refreshFsmStatus()
  } catch (e) {
    console.error('Failed to stop pipeline:', e)
  }
}

const handleStartPipeline = async () => {
  try {
    // Use WebSocket to send start command
    if (chat.ws?.readyState === WebSocket.OPEN) {
      chat.ws.send(JSON.stringify({ type: 'start', project_id: projectId }))
    }
    await refreshFsmStatus()
  } catch (e) {
    console.error('Failed to start pipeline:', e)
  }
}

const handleResume = async () => {
  try {
    // Use WebSocket to send resume command
    if (chat.ws?.readyState === WebSocket.OPEN) {
      chat.ws.send(JSON.stringify({ type: 'resume', project_id: projectId }))
    }
    await refreshFsmStatus()
  } catch (e) {
    console.error('Failed to resume pipeline:', e)
  }
}

const goBack = () => {
  router.push('/projects/' + projectId)
}
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

/* FSM Mode */
.fsm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color, #e8e8e8);
  background: var(--bg-secondary, #fafafa);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-left h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary, #333);
}
.header-right {
  display: flex;
  gap: 8px;
}

.fsm-layout {
  display: flex;
  flex: 1;
  overflow: hidden;
  min-height: 0;
}

.fsm-main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.fsm-main :deep(.chapter-detail-panel) {
  flex: 1;
  min-height: 0;
}

.fsm-main :deep(.fsm-action-bar) {
  flex-shrink: 0;
}

/* Chat Mode */
.chat-header {
  /* ChatHeader handles its own styling */
}

.chat-layout {
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow: hidden;
}
.chat-layout :deep(.chat-messages) {
  flex: 1;
  overflow-y: auto;
}
</style>