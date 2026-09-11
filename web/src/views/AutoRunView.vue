<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { useI18n } from '../i18n'
import { useAutoRun } from '../composables/useAutoRun'
import AutoRunConfigForm from '../components/autorun/AutoRunConfigForm.vue'
import AutoRunStatusPanel from '../components/autorun/AutoRunStatusPanel.vue'
import AutoRunStageControl from '../components/autorun/AutoRunStageControl.vue'
import AutopilotPreviewModal from '../components/autopilot/AutopilotPreviewModal.vue'

const { t } = useI18n()
const {
  loading,
  starting,
  autopilotStarting,
  ttsStatus,
  ttsVoices,
  autoRunStatus,
  showAutopilotPreview,
  autopilotPreview,
  previewLoading,
  config,
  selectedEngine,
  selectedVoice,
  availableEngines,
  availableVoices,
  canStart,
  progressPercent,
  // WebSocket 实时状态
  isPipelineRunning,
  isPipelinePaused,
  currentStage,
  completedStages,
  pipelineProgress,
  handleStartAutoRun,
  handlePause,
  handleResume,
  handleCancel,
  handleAutopilotPreview,
  handleStartAutopilot,
  loadAutoRunStatus,
  goBack,
} = useAutoRun()
</script>

<template>
  <div class="page-container auto-run-view">
    <header class="page-header">
      <button class="btn btn-ghost touch-target" @click="goBack">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        <span class="hidden-mobile">{{ t('common.back') }}</span>
      </button>
      <div class="flex-1">
        <h1>{{ t('auto_run.title') }}</h1>
        <p class="page-subtitle">{{ t('auto_run.subtitle') }}</p>
      </div>
    </header>

    <AutoRunConfigForm
      :tts-status="ttsStatus"
      :tts-voices="ttsVoices"
      :config="config"
      :selected-engine="selectedEngine"
      :selected-voice="selectedVoice"
      :available-engines="availableEngines"
      :available-voices="availableVoices"
      :loading="loading"
      @update:config="config = $event"
      @update:selectedEngine="selectedEngine = $event"
      @update:selectedVoice="selectedVoice = $event"
    />

    <AutoRunStatusPanel
      :auto-run-status="autoRunStatus"
      :progress-percent="progressPercent"
      :can-start="canStart"
      :starting="starting"
      :autopilot-starting="autopilotStarting"
      :preview-loading="previewLoading"
      @start="handleStartAutoRun"
      @pause="handlePause"
      @resume="handleResume"
      @cancel="handleCancel"
      @refresh="loadAutoRunStatus"
      @autopilot-preview="handleAutopilotPreview"
    />

    <AutoRunStageControl
      :auto-run-status="autoRunStatus"
      :is-pipeline-running="isPipelineRunning"
      :is-pipeline-paused="isPipelinePaused"
      :current-stage="currentStage"
      :completed-stages="completedStages"
      :pipeline-progress="pipelineProgress"
      :can-pause="autoRunStatus?.can_pause ?? false"
      :can-resume="autoRunStatus?.can_resume ?? false"
      :can-cancel="autoRunStatus?.can_cancel ?? false"
      :progress-percent="progressPercent"
      :handle-pause="handlePause"
      :handle-resume="handleResume"
      :handle-cancel="handleCancel"
    />

    <AutopilotPreviewModal
      :show="showAutopilotPreview"
      :loading="previewLoading"
      :starting="autopilotStarting"
      :preview="autopilotPreview"
      @close="showAutopilotPreview = false"
      @confirm="handleStartAutopilot"
    />
  </div>
</template>

<style scoped>
.auto-run-view {
  max-width: 960px;
}

.page-header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.page-header h1 {
  margin: 0;
  font-size: 22px;
  flex: 1;
}

.page-subtitle {
  margin: 4px 0 0;
  color: var(--color-text-muted);
  font-size: 13px;
}

.flex-1 { flex: 1 1 0%; }
</style>
