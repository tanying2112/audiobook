<template>
  <div class="fsm-action-bar" v-if="fsmCanConfirm || fsmIsPaused || fsmIsRunning">
    <div class="action-group primary-actions">
      <el-button
        v-if="fsmCanConfirm"
        type="primary"
        size="large"
        :loading="fsmActionLoading === 'approve'"
        @click="handleApprove"
        class="approve-btn"
      >
        <Check /><span>{{ t('agentChat.fsm.approve') }}</span>
      </el-button>
      <el-button
        v-if="fsmCanConfirm"
        type="danger"
        size="large"
        :loading="fsmActionLoading === 'reject'"
        @click="handleReject"
        class="reject-btn"
      >
        <Close /><span>{{ t('agentChat.fsm.reject') }}</span>
      </el-button>
    </div>

    <div class="action-group secondary-actions">
      <el-button
        v-if="fsmCanConfirm"
        type="warning"
        size="default"
        :loading="fsmActionLoading === 'request_rerun'"
        @click="handleRequestRerun"
      >
        <Refresh /><span>{{ t('agentChat.fsm.request_rerun') }}</span>
      </el-button>
      <el-button
        v-if="fsmCanConfirm"
        type="info"
        size="default"
        :loading="fsmActionLoading === 'edit'"
        @click="handleEdit"
      >
        <Edit /><span>{{ t('agentChat.fsm.edit') }}</span>
      </el-button>
      <el-button
        v-if="fsmIsPaused && !fsmCanConfirm"
        type="primary"
        size="default"
        @click="handleResume"
      >
        <VideoPlay /><span>{{ t('agentChat.fsm.resume') }}</span>
      </el-button>
    </div>

    <div class="action-group status-info">
      <el-tag v-if="fsmIsRunning" type="primary" effect="plain">
        <Loading class="spin" />{{ t('agentChat.fsm.running') }}
      </el-tag>
      <el-tag v-else-if="fsmIsPaused && fsmCanConfirm" type="warning" effect="plain">
        <Warning />{{ t('agentChat.fsm.awaiting_action') }}
      </el-tag>
      <el-tag v-else-if="fsmIsPaused" type="info" effect="plain">
        <VideoPause /><span>{{ t('agentChat.fsm.paused') }}</span>
      </el-tag>
      <el-tag v-else-if="fsmStatus?.status === 'completed'" type="success" effect="plain">
        <CircleCheck />{{ t('agentChat.fsm.completed') }}
      </el-tag>
      <el-tag v-else-if="fsmStatus?.status === 'failed'" type="danger" effect="plain">
        <CircleClose />{{ t('agentChat.fsm.failed') }}
      </el-tag>
    </div>

    <div class="action-group chapter-info" v-if="pendingChapter">
      <span class="chapter-badge">
        <Document />
        {{ t('agentChat.fsm.chapter') }} {{ pendingChapter.index }}
        <el-tag type="warning" size="small" style="margin-left: 8px;">{{ t('agentChat.fsm.awaiting_confirm') }}</el-tag>
      </span>
    </div>
  </div>

  <div class="fsm-action-bar" v-else>
    <el-tag type="info" effect="plain">
      <Document />{{ t('agentChat.fsm.no_active_pipeline') }}
    </el-tag>
    <el-button type="primary" @click="$emit('start-pipeline')">
      <VideoPlay /><span>{{ t('agentChat.fsm.start_pipeline') }}</span>
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from '@/i18n'
import { ElButton, ElTag } from 'element-plus'
import {
  Check, Close, Refresh, Edit, VideoPlay, VideoPause, Warning, Loading,
  CircleCheck, CircleClose, Document
} from '@element-plus/icons-vue'

const props = defineProps<{
  fsmCanConfirm: boolean
  fsmIsPaused: boolean
  fsmIsRunning: boolean
  fsmActionLoading: string | null
  fsmStatus: {
    status: string
    current_state?: string
  } | null
  pendingChapter: {
    id: number
    index: number
    title: string
  } | null
}>()

const emit = defineEmits<{
  'approve': [edits?: Record<string, unknown>]
  'reject': []
  'request-rerun': []
  'edit': []
  'resume': []
  'start-pipeline': []
}>()

const { t } = useI18n()

const handleApprove = () => {
  emit('approve')
}

const handleReject = () => {
  emit('reject')
}

const handleRequestRerun = () => {
  emit('request-rerun')
}

const handleEdit = () => {
  // 这里可以打开编辑弹窗，暂时直接发出事件
  emit('edit')
}

const handleResume = () => {
  emit('resume')
}
</script>

<style scoped>
.fsm-action-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 12px 16px;
  background: var(--bg-secondary, #fafafa);
  border-top: 1px solid var(--border-color, #e8e8e8);
  border-radius: 0 0 8px 8px;
}

.action-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.primary-actions {
  flex: 1;
  justify-content: flex-end;
  display: flex;
  gap: 12px;
}

.approve-btn, .reject-btn {
  min-width: 120px;
  height: 44px;
  font-size: 14px;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.secondary-actions {
  display: flex;
  gap: 8px;
}

.secondary-actions .el-button {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-info {
  display: flex;
  align-items: center;
}

.status-info .el-tag {
  font-size: 13px;
  height: 28px;
}

.chapter-info {
  display: flex;
  align-items: center;
}

.chapter-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  background: var(--color-warning-light, #fdf6ec);
  border-radius: 20px;
  font-size: 13px;
  color: var(--color-warning, #e6a23c);
}

.chapter-badge .el-tag {
  vertical-align: middle;
}

.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 响应式调整 */
@media (max-width: 768px) {
  .fsm-action-bar {
    flex-direction: column;
    align-items: stretch;
  }
  .primary-actions {
    justify-content: stretch;
  }
  .approve-btn, .reject-btn {
    flex: 1;
  }
  .secondary-actions {
    justify-content: center;
  }
  .status-info {
    justify-content: center;
  }
  .chapter-info {
    justify-content: center;
  }
}
</style>