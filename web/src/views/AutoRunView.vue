<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { useRouter } from 'vue-router'
import { useI18n } from '../i18n'
import { useAutoRun } from '../composables/useAutoRun'
import AutoRunConfigForm from '../components/autorun/AutoRunConfigForm.vue'
import AutoRunStatusPanel from '../components/autorun/AutoRunStatusPanel.vue'
import AutoRunStageControl from '../components/autorun/AutoRunStageControl.vue'
import AutopilotPreviewModal from '../components/autopilot/AutopilotPreviewModal.vue'

const { t } = useI18n()
const router = useRouter()
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
  mode,
  selectedEngine,
  selectedVoice,
  availableEngines,
  availableVoices,
  canStart,
  progressPercent,
  isPipelineRunning,
  isPipelinePaused,
  isAwaitingReview,
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
  goToReviewGate,
  projectId,
} = useAutoRun()

function handleViewIntermediate(stage: string) {
  router.push({ path: `/projects/${projectId}/runs`, query: { stage } })
}
function handleRerunStage(stage: string) {
  router.push({ path: `/projects/${projectId}/runs`, query: { stage } })
}
function handleRunFromStage(stage: string) {
  router.push({ path: `/projects/${projectId}/runs`, query: { stage } })
}
</script>

<template>
  <div class="page-container auto-run-view">
    <header class="page-header">
      <button class="btn btn-ghost touch-target" @click="goBack" aria-label="Back">
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
      :mode="mode"
      :selected-engine="selectedEngine"
      :selected-voice="selectedVoice"
      :available-engines="availableEngines"
      :available-voices="availableVoices"
      :loading="loading"
      @update:config="config = $event"
      @update:mode="mode = $event"
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
      :is-awaiting-review="isAwaitingReview"
      @start="handleStartAutoRun"
      @pause="handlePause"
      @resume="handleResume"
      @cancel="handleCancel"
      @refresh="loadAutoRunStatus"
      @go-review="goToReviewGate"
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
      @view-intermediate="handleViewIntermediate"
      @rerun-stage="handleRerunStage"
      @run-from-stage="handleRunFromStage"
      @pause-stage="handlePause"
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

.flex-1 {
  flex: 1 1 0%;
}
</style>
