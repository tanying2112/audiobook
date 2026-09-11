<template>
  <div v-if="autoRunStatus">
    <!-- Status Display -->
    <div class="card card-hover section">
      <div class="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h2 class="card-title">{{ t('auto_run.status') }}</h2>
        <span
          class="badge"
          :class="[
            autoRunStatus.status === 'running' && 'badge-info',
            autoRunStatus.status === 'paused' && 'badge-warning',
            autoRunStatus.status === 'completed' && 'badge-success',
            autoRunStatus.status === 'failed' && 'badge-danger',
            autoRunStatus.status === 'cancelled' && 'badge-muted',
            (autoRunStatus.status === 'not_started' || autoRunStatus.status === 'pending') && 'badge-muted',
          ]"
        >
          {{ t('auto_run.status_' + autoRunStatus.status) }}
        </span>
      </div>

      <!-- Progress Bar -->
      <div class="mb-4">
        <div class="flex justify-between text-sm mb-1">
          <span class="text-secondary">{{ t('auto_run.progress') }}</span>
          <span class="font-medium">{{ progressPercent }}%</span>
        </div>
        <div class="w-full rounded-full h-2" style="background: var(--color-border); overflow: hidden;">
          <div
            class="h-full rounded-full transition-all duration-300"
            :style="{ width: progressPercent + '%' }"
            style="background: var(--color-primary);"
          ></div>
        </div>
      </div>

      <!-- Current Stage -->
      <div v-if="autoRunStatus.current_stage" class="mb-4 p-3 rounded" style="background: var(--color-bg-tertiary);">
        <p class="text-secondary text-sm">{{ t('auto_run.current_stage') }}</p>
        <p class="font-medium">{{ getStageLabel(autoRunStatus.current_stage) }}</p>
      </div>

      <!-- Completed Stages -->
      <div v-if="autoRunStatus.completed_stages && autoRunStatus.completed_stages.length > 0" class="mb-4">
        <p class="text-secondary text-sm mb-2">{{ t('auto_run.completed_stages') }}</p>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="stage in autoRunStatus.completed_stages"
            :key="stage"
            class="badge badge-success"
          >
            {{ getStageLabel(stage) }}
          </span>
        </div>
      </div>

      <!-- Error Message -->
      <div v-if="autoRunStatus.error_message" class="alert alert-error mb-4" style="font-size: 13px;">
        {{ autoRunStatus.error_message }}
      </div>

      <!-- Cost Info -->
      <div v-if="autoRunStatus.cost_usd > 0" class="alert alert-info mb-4" style="font-size: 13px;">
        {{ t('auto_run.current_cost', { cost: autoRunStatus.cost_usd.toFixed(4) }) }}
      </div>
    </div>

    <!-- Action Buttons -->
    <div class="flex gap-2 flex-wrap section">
      <button
        v-if="canStart"
        @click="$emit('start')"
        :disabled="starting"
        class="btn btn-primary btn-lg flex-1 min-w-[140px]"
      >
        <Icon v-if="starting" icon="mdi:loading" width="18" height="18" class="spinner" style="border-color: rgba(255,255,255,.35); border-top-color: #fff" />
        {{ starting ? t('auto_run.starting') : t('auto_run.start') }}
      </button>

      <button
        v-if="canStart"
        @click="$emit('autopilot-preview')"
        :disabled="starting || autopilotStarting || previewLoading"
        class="btn btn-outline btn-lg"
        :title="t('auto_run.autopilot_tooltip')"
      >
        <Icon v-if="autopilotStarting || previewLoading" icon="mdi:loading" width="18" height="18" class="spinner" style="border-color: var(--color-primary-alpha); border-top-color: var(--color-primary)" />
        <Icon icon="mdi:robot-outline" width="18" height="18" class="gap-2" />
        {{ t('auto_run.autopilot') }}
      </button>

      <button
        v-else-if="autoRunStatus.status === 'running' && autoRunStatus.can_pause"
        @click="$emit('pause')"
        class="btn btn-warning btn-lg"
      >
        <Icon icon="mdi:pause" width="18" height="18" class="gap-2" />
        {{ t('auto_run.pause') }}
      </button>

      <button
        v-else-if="autoRunStatus.status === 'paused' && autoRunStatus.can_resume"
        @click="$emit('resume')"
        class="btn btn-primary btn-lg"
      >
        <Icon icon="mdi:play" width="18" height="18" class="gap-2" />
        {{ t('auto_run.resume') }}
      </button>

      <button
        v-if="autoRunStatus.can_cancel"
        @click="$emit('cancel')"
        class="btn btn-danger btn-lg"
      >
        <Icon icon="mdi:stop" width="18" height="18" class="gap-2" />
        {{ t('auto_run.cancel') }}
      </button>

      <button
        v-if="autoRunStatus.status === 'completed' || autoRunStatus.status === 'failed' || autoRunStatus.status === 'cancelled'"
        @click="$emit('refresh')"
        class="btn btn-outline btn-lg"
      >
        <Icon icon="mdi:refresh" width="18" height="18" class="gap-2" />
        {{ t('auto_run.refresh') }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from '../../i18n'
import { Icon } from '@iconify/vue'
import type { AutoRunStatusResponse } from '../../api'

interface Props {
  autoRunStatus: AutoRunStatusResponse | null
  progressPercent: number
  canStart: boolean
  starting: boolean
  autopilotStarting: boolean
  previewLoading: boolean
}

defineProps<Props>()

defineEmits<{
  start: []
  pause: []
  resume: []
  cancel: []
  refresh: []
  'autopilot-preview': []
}>()

const { t } = useI18n()

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
</script>

<style scoped>
.section {
  margin-bottom: 20px;
}
.flex { display: flex; }
.items-center { align-items: center; }
.justify-between { justify-content: space-between; }
.flex-wrap { flex-wrap: wrap; }
.gap-2 { gap: 8px; }
</style>
