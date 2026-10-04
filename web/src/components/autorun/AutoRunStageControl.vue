<template>
  <div v-if="autoRunStatus || isPipelineRunning" class="card card-hover section">
    <h2 class="card-title">{{ t('auto_run.stage_control') }}</h2>

    <!-- Pipeline Stage Pipeline Visualization -->
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
        <!-- Stage connector line (except last) -->
        <div v-if="index < PIPELINE_STAGE_ORDER.length - 1" class="stage-connector"></div>

        <div class="stage-content">
          <!-- Stage icon/status indicator -->
          <div class="stage-indicator">
            <Icon 
              v-if="isStageCompleted(stage)" 
              icon="mdi:check-circle" 
              width="20" height="20" 
              class="text-success"
            />
            <Icon 
              v-else-if="isStageActive(stage)" 
              icon="mdi:spinner" 
              width="20" height="20" 
              class="text-primary spinner"
            />
            <Icon 
              v-else-if="isStageFailed(stage)" 
              icon="mdi:alert-circle" 
              width="20" height="20" 
              class="text-danger"
            />
            <span v-else class="stage-number">{{ index + 1 }}</span>
          </div>

          <!-- Stage label -->
          <div class="stage-label">
            <span class="stage-name">{{ getStageLabel(stage) }}</span>
            <span v-if="isStageActive(stage)" class="stage-progress-badge">
              {{ Math.round(getStageProgress(stage) * 100) }}%
            </span>
          </div>

          <!-- Stage actions (visible on hover or when active/completed) -->
          <div class="stage-actions" v-if="showStageActions(stage)">
            <button
              v-if="isStageActive(stage) && canPause"
              class="btn btn-sm btn-warning"
              @click="handlePauseStage(stage)"
              :title="t('auto_run.pause_after_stage')"
            >
              <Icon icon="mdi:pause" width="14" height="14" />
            </button>
            <button
              v-if="isStageCompleted(stage)"
              class="btn btn-sm btn-outline"
              @click="handleViewIntermediate(stage)"
              :title="t('auto_run.view_intermediate')"
            >
              <Icon icon="mdi:eye" width="14" height="14" />
            </button>
            <button
              v-if="isStageCompleted(stage) || isStageFailed(stage)"
              class="btn btn-sm btn-outline"
              @click="handleRerunStage(stage)"
              :title="t('auto_run.rerun_stage')"
            >
              <Icon icon="mdi:restart" width="14" height="14" />
            </button>
            <button
              v-if="isStagePending(stage) && isPreviousCompleted(stage)"
              class="btn btn-sm btn-primary"
              @click="handleRunFromStage(stage)"
              :title="t('auto_run.run_from_here')"
            >
              <Icon icon="mdi:play" width="14" height="14" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Stage Progress Detail (when a stage is active) -->
    <div v-if="currentStage" class="stage-progress-detail mt-4 p-3 rounded" style="background: var(--color-bg-tertiary);">
      <div class="flex items-center justify-between mb-2">
        <span class="font-medium">{{ getStageLabel(currentStage) }}</span>
        <span class="text-secondary text-sm">
          {{ t('auto_run.chapter') }} {{ currentChapterId || '—' }}
        </span>
      </div>
      <div class="w-full rounded-full h-2" style="background: var(--color-border); overflow: hidden;">
        <div
          class="h-full rounded-full transition-all duration-300"
          :style="{ width: stageProgress + '%' }"
          style="background: var(--color-primary);"
        ></div>
      </div>
      <p class="text-sm text-secondary mt-1">
        {{ t('auto_run.stage_progress', { progress: Math.round(stageProgress * 100) }) }}
      </p>
    </div>

    <!-- Completed Stages Summary -->
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

    <!-- Global Actions -->
    <div class="flex gap-2 flex-wrap mt-4 pt-4 border-t" style="border-color: var(--color-border);">
      <button
        v-if="isPipelineRunning && canPause"
        @click="handlePause"
        class="btn btn-warning"
      >
        <Icon icon="mdi:pause" width="18" height="18" class="gap-2" />
        {{ t('auto_run.pause_pipeline') }}
      </button>
      <button
        v-if="isPipelinePaused && canResume"
        @click="handleResume"
        class="btn btn-primary"
      >
        <Icon icon="mdi:play" width="18" height="18" class="gap-2" />
        {{ t('auto_run.resume_pipeline') }}
      </button>
      <button
        v-if="canCancel"
        @click="handleCancel"
        class="btn btn-danger"
      >
        <Icon icon="mdi:stop" width="18" height="18" class="gap-2" />
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

// 当前活跃阶段的进度（来自 WebSocket）
const stageProgress = computed(() => {
  return props.pipelineProgress?.stageProgress || 0
})

// 当前处理的章节 ID
const currentChapterId = computed(() => {
  return props.pipelineProgress?.currentChapterId || props.autoRunStatus?.current_chapter_id || null
})

// 当前阶段状态（来自 WebSocket）
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

// 检查前一阶段是否已完成
const isPreviousCompleted = (stage: PipelineStage): boolean => {
  const index = PIPELINE_STAGE_ORDER.indexOf(stage)
  if (index === 0) return true
  return props.completedStages.includes(PIPELINE_STAGE_ORDER[index - 1])
}

// 获取阶段进度
const getStageProgress = (stage: PipelineStage): number => {
  if (isStageActive(stage)) {
    return stageProgress.value
  }
  if (isStageCompleted(stage)) {
    return 1
  }
  return 0
}

// 显示阶段操作按钮
const showStageActions = (stage: PipelineStage): boolean => {
  return isStageActive(stage) || isStageCompleted(stage) || isStageFailed(stage) || 
         (isStagePending(stage) && isPreviousCompleted(stage))
}

// 获取阶段标签
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

// 阶段级操作
function handlePauseStage(stage: PipelineStage) {
  emit('pause-stage', stage)
}

function handleViewIntermediate(stage: PipelineStage) {
  emit('view-intermediate', stage)
}

function handleRerunStage(stage: PipelineStage) {
  emit('rerun-stage', stage)
}

function handleRunFromStage(stage: PipelineStage) {
  emit('run-from-stage', stage)
}
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
}

.stage-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  position: relative;
  min-width: 100px;
}

.stage-connector {
  position: absolute;
  top: 10px;
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
  background: var(--color-bg-secondary);
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
  border-radius: 8px;
  background: var(--color-primary-alpha);
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
.stage-node.failed .stage-actions {
  opacity: 1;
  transform: translateY(0);
}

@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 0 var(--color-primary-alpha); }
  50% { box-shadow: 0 0 0 8px transparent; }
}

.spinner {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.btn-sm {
  padding: 4px 8px;
  font-size: 12px;
}
</style>