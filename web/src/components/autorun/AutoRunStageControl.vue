<template>
  <div v-if="autoRunStatus || isPipelineRunning" class="card card-hover section">
    <h2 class="card-title">{{ t('auto_run.stage_control') }}</h2>
    <div class="pipeline-visualization">
      <div 
        v-for="(stage, index) in PIPELINE_STAGE_ORDER" 
        :key="stage"
        class="stage-node"
        :class="[
          'stage-' + stage,
          isStageCompleted(stage) ? 'completed' : '',
          isStageActive(stage) ? 'active' : '',
          isStageFailed(stage) ? 'failed' : '',
          isStagePending(stage) ? 'pending' : '',
        ]"
      >
        <div v-if="index < PIPELINE_STAGE_ORDER.length - 1" class="stage-connector"></div>

        <div class="stage-content">
          <div class="stage-indicator">
            <Icon v-if="isStageCompleted(stage)" icon="mdi:check-circle" width="20" height="20" class="text-success" />
            <Icon v-else-if="isStageActive(stage)" icon="mdi:spinner" width="20" height="20" class="text-primary spinner" />
            <Icon v-else-if="isStageFailed(stage)" icon="mdi:alert-circle" width="20" height="20" class="text-danger" />
            <span v-else class="stage-number">{{ index + 1 }}</span>
          </div>
          <div class="stage-label">
            <span class="stage-name">{{ getStageLabel(stage) }}</span>
            <span v-if="isStageActive(stage)" class="stage-progress-badge">
              {{ Math.round(getStageProgress(stage) * 100) }}%
            </span>
          </div>
          <div class="stage-actions" v-if="showStageActions(stage)">
            <button
              v-if="isStageActive(stage) && canPause"
              class="btn btn-sm btn-warning touch-target-sm"
              @click="handlePauseStage(stage)"
              :aria-label="t('auto_run.pause_after_stage')"
              :title="t('auto_run.pause_after_stage')"
            >
              <Icon icon="mdi:pause" width="14" height="14" />
            </button>
            <button
              v-if="isStageCompleted(stage)"
              class="btn btn-sm btn-outline touch-target-sm"
              @click="handleViewIntermediate(stage)"
              :aria-label="t('auto_run.view_intermediate')"
              :title="t('auto_run.view_intermediate')"
            >
              <Icon icon="mdi:eye" width="14" height="14" />
            </button>
            <button
              v-if="isStageCompleted(stage) || isStageFailed(stage)"
              class="btn btn-sm btn-outline touch-target-sm"
              @click="handleRerunStage(stage)"
              :aria-label="t('auto_run.rerun_stage')"
              :title="t('auto_run.rerun_stage')"
            >
              <Icon icon="mdi:restart" width="14" height="14" />
            </button>
            <button
              v-if="isStagePending(stage) && isPreviousCompleted(stage)"
              class="btn btn-sm btn-primary touch-target-sm"
              @click="handleRunFromStage(stage)"
              :aria-label="t('auto_run.run_from_here')"
              :title="t('auto_run.run_from_here')"
            >
              <Icon icon="mdi:play" width="14" height="14" />
            </button>
          </div>
        </div>
      </div>
    </div>
    <div v-if="currentStage" class="stage-progress-detail">
      <div class="flex items-center justify-between mb-2">
        <span class="font-medium">{{ getStageLabel(currentStage) }}</span>
        <span class="text-secondary text-sm">
          {{ t('auto_run.chapter') }} {{ currentChapterId || '—' }}
        </span>
      </div>
      <div class="stage-detail-track" role="progressbar" :aria-valuenow="Math.round(stageProgress * 100)" aria-valuemin="0" aria-valuemax="100">
        <div
          class="stage-detail-fill"
          :style="{ width: stageProgress * 100 + '%' }"
        ></div>
      </div>
      <p class="text-sm text-secondary mt-1">
        {{ t('auto_run.stage_progress', { progress: Math.round(stageProgress * 100) }) }}
      </p>
    </div>
    <div v-if="completedStages.length > 0" class="mt-4">
      <p class="text-secondary text-sm mb-2">{{ t('auto_run.completed_stages') }}</p>
      <div class="flex flex-wrap gap-2">
        <span
          v-for="stage in completedStages"
          :key="stage"
          class="badge badge-success"
        >
          {{ getStageLabel(stage) }}
        </span>
      </div>
    </div>
    <div class="global-actions">
      <button
        v-if="isPipelineRunning && canPause"
        @click="handlePause"
        class="btn btn-warning global-action-btn"
        aria-label="Pause pipeline"
      >
        <Icon icon="mdi:pause" width="18" height="18" />
        {{ t('auto_run.pause_pipeline') }}
      </button>
      <button
        v-if="isPipelinePaused && canResume"
        @click="handleResume"
        class="btn btn-primary global-action-btn"
        aria-label="Resume pipeline"
      >
        <Icon icon="mdi:play" width="18" height="18" />
        {{ t('auto_run.resume_pipeline') }}
      </button>
      <button
        v-if="canCancel"
        @click="handleCancel"
        class="btn btn-danger global-action-btn"
        aria-label="Cancel pipeline"
      >
        <Icon icon="mdi:stop" width="18" height="18" />
        {{ t('auto_run.cancel_pipeline') }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '../../i18n'
import { Icon } from '@iconify/vue'
import { PIPELINE_STAGE_ORDER, type PipelineStage } from '../../types/pipeline'

interface Props {
  autoRunStatus: any
  isPipelineRunning: boolean
  isPipelinePaused: boolean
  currentStage: PipelineStage | null
  completedStages: PipelineStage[]
  pipelineProgress: any
  canPause: boolean
  canResume: boolean
  canCancel: boolean
  progressPercent: number
  handlePause: () => Promise<void>
  handleResume: () => Promise<void>
  handleCancel: () => Promise<void>
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'view-intermediate': [stage: string]
  'rerun-stage': [stage: string]
  'run-from-stage': [stage: string]
  'pause-stage': [stage: string]
}>()

const { t } = useI18n()

const stageProgress = computed(() => {
  return props.pipelineProgress?.stageProgress || 0
})

const currentChapterId = computed(() => {
  return props.pipelineProgress?.currentChapterId || props.autoRunStatus?.current_chapter_id || null
})

const isStageActive = (stage: PipelineStage): boolean => {
  return props.currentStage === stage
}

const isStageCompleted = (stage: PipelineStage): boolean => {
  return props.completedStages.includes(stage)
}

const isStageFailed = (stage: PipelineStage): boolean => {
  return props.autoRunStatus?.status === 'failed' && props.autoRunStatus?.current_stage === stage
}

const isStagePending = (stage: PipelineStage): boolean => {
  return !isStageCompleted(stage) && !isStageActive(stage) && !isStageFailed(stage)
}

const isPreviousCompleted = (stage: PipelineStage): boolean => {
  const index = PIPELINE_STAGE_ORDER.indexOf(stage)
  if (index === 0) return true
  return props.completedStages.includes(PIPELINE_STAGE_ORDER[index - 1])
}

const getStageProgress = (stage: PipelineStage): number => {
  if (isStageActive(stage)) return stageProgress.value
  if (isStageCompleted(stage)) return 1
  return 0
}

const showStageActions = (stage: PipelineStage): boolean => {
  return isStageActive(stage) || isStageCompleted(stage) || isStageFailed(stage) || 
         (isStagePending(stage) && isPreviousCompleted(stage))
}

function getStageLabel(stage: string): string {
  const labels: Record<string, string> = {
    extract: t('pipeline.stages.extract'),
    analyze: t('pipeline.stages.analyze'),
    annotate: t('pipeline.stages.annotate'),
    edit: t('pipeline.stages.edit'),
    audio_postprocess: t('pipeline.stages.audio_postprocess'),
    synthesize: t('pipeline.stages.synthesize'),
    quality: t('pipeline.stages.quality'),
  }
  return labels[stage] || stage
}

function handlePauseStage(stage: PipelineStage) { emit('pause-stage', stage) }
function handleViewIntermediate(stage: PipelineStage) { emit('view-intermediate', stage) }
function handleRerunStage(stage: PipelineStage) { emit('rerun-stage', stage) }
function handleRunFromStage(stage: PipelineStage) { emit('run-from-stage', stage) }
</script>

<style scoped>
.section {
  margin-bottom: 20px;
}
.pipeline-visualization {
  display: flex;
  align-items: flex-start;
  position: relative;
  padding: 16px 8px;
  overflow-x: auto;
}

.stage-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  position: relative;
  min-width: 80px;
}

.stage-connector {
  position: absolute;
  top: 20px;
  left: 50%;
  right: -50%;
  height: 2px;
  background: var(--color-border);
  z-index: 0;
}

.stage-node.completed .stage-connector {
  background: var(--color-success);
}

.stage-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  position: relative;
  z-index: 1;
}

.stage-indicator {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-surface);
  border: 2px solid var(--color-border);
  transition: all 0.3s ease;
}

.stage-node.completed .stage-indicator {
  background: var(--color-success);
  border-color: var(--color-success);
}

.stage-node.active .stage-indicator {
  background: var(--color-primary);
  border-color: var(--color-primary);
  animation: pulse 1.5s infinite;
}

.stage-node.failed .stage-indicator {
  background: var(--color-danger);
  border-color: var(--color-danger);
}

.stage-number {
  font-weight: 600;
  font-size: 14px;
  color: var(--color-text-secondary);
}

.stage-label {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  text-align: center;
}

.stage-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text);
  white-space: nowrap;
}

.stage-progress-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: var(--radius-full);
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.stage-actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transform: translateY(8px);
  transition: all 0.2s ease;
}

.stage-node:hover .stage-actions,
.stage-node.active .stage-actions,
.stage-node.completed .stage-actions,
.stage-node.failed .stage-actions { opacity: 1; transform: translateY(0); }

@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 0 var(--color-primary-alpha); }
  50% { box-shadow: 0 0 0 8px transparent; }
}
.stage-progress-detail {
  margin-top: 16px;
  padding: 12px;
  border-radius: var(--radius);
  background: var(--color-bg-tertiary);
}
.stage-detail-track {
  width: 100%;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--color-primary-soft);
  overflow: hidden;
}
.stage-detail-fill {
  height: 100%;
  border-radius: var(--radius-full);
  background: var(--color-primary);
  transition: width 0.4s ease;
}
.global-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--color-border);
}
.global-action-btn {
  min-width: 140px;
}
@media (max-width: 767px) {
  .pipeline-visualization {
    padding: 12px 0;
  }
  .stage-node {
    min-width: 60px;
  }
  .stage-name {
    font-size: 11px;
  }
  .global-actions {
    flex-direction: column;
  }
  .global-action-btn {
    width: 100%;
    min-width: unset;
  }
}

/* btn-warning fallback + disabled clarity */
.btn-warning { background: var(--color-warning); color: #fff; border: 1px solid transparent; }
.btn-warning:hover:not(:disabled) { filter: brightness(0.85); box-shadow: var(--shadow-sm); }
.stage-actions .btn:disabled,
.global-actions .btn:disabled { opacity: 0.4; pointer-events: none; }
</style>
