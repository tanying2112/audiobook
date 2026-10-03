<template>
  <div v-if="autoRunStatus">
    <!-- Status Display -->
    <div class="card card-hover section">
      <div class="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h2 class="card-title">{{ t('auto_run.status') }}</h2>
        <span
          class="badge"
          :class="statusBadgeClass"
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
        <div class="progress-track" role="progressbar" :aria-valuenow="progressPercent" aria-valuemin="0" aria-valuemax="100">
          <div
            class="progress-fill"
            :class="progressFillClass"
            :style="{ width: progressPercent + '%' }"
          ></div>
        </div>
      </div>

      <!-- Elapsed / Remaining Time -->
      <div v-if="elapsedText || remainingText" class="time-info">
        <div v-if="elapsedText" class="time-item">
          <Icon icon="mdi:clock-outline" width="16" height="16" class="text-muted" />
          <span class="text-secondary text-sm">Elapsed: {{ elapsedText }}</span>
        </div>
        <div v-if="remainingText" class="time-item">
          <Icon icon="mdi:timer-sand" width="16" height="16" class="text-muted" />
          <span class="text-secondary text-sm">Remaining: {{ remainingText }}</span>
        </div>
      </div>

      <!-- Current Stage -->
      <div v-if="autoRunStatus.current_stage" class="current-stage-box">
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
      <div v-if="autoRunStatus.error_message" class="alert alert-error mb-4 small-text">
        {{ autoRunStatus.error_message }}
      </div>

      <!-- Cost Info -->
      <div v-if="autoRunStatus.cost_usd > 0" class="alert alert-info mb-4 small-text">
        {{ t('auto_run.current_cost', { cost: autoRunStatus.cost_usd.toFixed(4) }) }}
      </div>
    </div>

    <!-- Action Buttons -->
    <div class="action-bar section">
      <!-- 人工终审门激活 → 进入终审工作台编辑并放行 -->
      <button
        v-if="isAwaitingReview"
        @click="$emit('go-review')"
        class="btn btn-primary btn-lg action-btn action-btn--primary"
        :aria-label="t('auto_run.go_to_review')"
      >
        <Icon icon="mdi:clipboard-check-search-outline" width="18" height="18" />
        {{ t('auto_run.go_to_review') }}
      </button>

      <button
        v-if="canStart"
        @click="$emit('start')"
        :disabled="starting"
        class="btn btn-primary btn-lg action-btn action-btn--primary"
        :aria-label="starting ? t('auto_run.starting') : t('auto_run.start')"
      >
        <Icon v-if="starting" icon="mdi:loading" width="18" height="18" class="spinner" />
        <Icon v-else icon="mdi:play" width="18" height="18" />
        {{ starting ? t('auto_run.starting') : t('auto_run.start') }}
      </button>

      <button
        v-if="canStart"
        @click="$emit('autopilot-preview')"
        :disabled="starting || autopilotStarting || previewLoading"
        class="btn btn-outline btn-lg action-btn"
        :title="t('auto_run.autopilot_tooltip')"
        aria-label="Autopilot"
      >
        <Icon v-if="autopilotStarting || previewLoading" icon="mdi:loading" width="18" height="18" class="spinner" />
        <Icon icon="mdi:robot-outline" width="18" height="18" />
        {{ t('auto_run.autopilot') }}
      </button>

      <button
        v-else-if="autoRunStatus.status === 'running' && autoRunStatus.can_pause"
        @click="$emit('pause')"
        class="btn btn-lg action-btn action-btn--warning"
        aria-label="Pause pipeline"
      >
        <Icon icon="mdi:pause" width="18" height="18" />
        {{ t('auto_run.pause') }}
      </button>

      <button
        v-else-if="autoRunStatus.status === 'paused' && autoRunStatus.can_resume"
        @click="$emit('resume')"
        class="btn btn-primary btn-lg action-btn action-btn--primary"
        aria-label="Resume pipeline"
      >
        <Icon icon="mdi:play" width="18" height="18" />
        {{ t('auto_run.resume') }}
      </button>

      <button
        v-if="autoRunStatus.can_cancel"
        @click="$emit('cancel')"
        class="btn btn-danger btn-lg action-btn action-btn--danger"
        aria-label="Cancel pipeline"
      >
        <Icon icon="mdi:stop" width="18" height="18" />
        {{ t('auto_run.cancel') }}
      </button>

      <button
        v-if="autoRunStatus.status === 'completed' || autoRunStatus.status === 'failed' || autoRunStatus.status === 'cancelled'"
        @click="$emit('refresh')"
        class="btn btn-outline btn-lg action-btn"
        :aria-label="t('auto_run.refresh')"
      >
        <Icon icon="mdi:refresh" width="18" height="18" />
        {{ t('auto_run.refresh') }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
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
  /** 终审门激活（REST awaiting_review/can_review 或 WS awaiting_review 事件） */
  isAwaitingReview?: boolean
}

const props = defineProps<Props>()

defineEmits<{
  start: []
  pause: []
  resume: []
  cancel: []
  refresh: []
  'go-review': []
  'autopilot-preview': []
}>()

const { t } = useI18n()

// ── Elapsed / Estimated Remaining Time ──────────────────────
const now = ref(Date.now())
let timerHandle: ReturnType<typeof setInterval> | null = null

function startTimer() {
  if (timerHandle) return
  now.value = Date.now()
  timerHandle = setInterval(() => { now.value = Date.now() }, 1000)
}
function stopTimer() {
  if (timerHandle) { clearInterval(timerHandle); timerHandle = null }
}

const elapsedMs = computed(() => {
  const s = props.autoRunStatus
  if (!s?.started_at) return 0
  const end = s.completed_at ? new Date(s.completed_at).getTime() : now.value
  return Math.max(0, end - new Date(s.started_at).getTime())
})

function formatDuration(ms: number): string {
  const totalSec = Math.floor(ms / 1000)
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const sec = totalSec % 60
  if (h > 0) return `${h}h ${m}m ${sec}s`
  if (m > 0) return `${m}m ${sec}s`
  return `${sec}s`
}

const elapsedText = computed(() => {
  const s = props.autoRunStatus
  if (!s?.started_at) return ''
  return formatDuration(elapsedMs.value)
})

const remainingText = computed(() => {
  const s = props.autoRunStatus
  if (!s?.started_at) return ''
  if (s.status !== 'running') return ''
  const progress = props.progressPercent / 100
  if (progress <= 0) return ''
  const estimated = elapsedMs.value / progress - elapsedMs.value
  if (estimated < 1000) return ''
  return formatDuration(estimated)
})

// Start/stop timer based on pipeline state（终审门内运行仍在计时）
watch(
  () => props.autoRunStatus?.status,
  (status) => {
    if (status === 'running' || status === 'awaiting_review') startTimer()
    else stopTimer()
  },
  { immediate: true }
)

onMounted(() => {
  if (props.autoRunStatus?.status === 'running' || props.autoRunStatus?.status === 'awaiting_review') startTimer()
})
onUnmounted(stopTimer)

// ── Status badge class ──────────────────────────────────────
const statusBadgeClass = computed(() => {
  const s = props.autoRunStatus?.status
  return [
    s === 'running' && 'badge-info',
    s === 'paused' && 'badge-warning',
    s === 'awaiting_review' && 'badge-warning',
    s === 'completed' && 'badge-success',
    s === 'failed' && 'badge-danger',
    s === 'cancelled' && 'badge-danger',
    (!s || s === 'not_started' || s === 'pending') && 'badge-muted',
  ].filter(Boolean)
})

// ── Progress fill color ─────────────────────────────────────
const progressFillClass = computed(() => {
  const s = props.autoRunStatus?.status
  if (s === 'cancelled') return 'progress-fill--danger'
  if (s === 'paused') return 'progress-fill--warning'
  if (s === 'awaiting_review') return 'progress-fill--warning'
  if (s === 'failed') return 'progress-fill--danger'
  return 'progress-fill--primary'
})

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
.small-text {
  font-size: 13px;
}
.current-stage-box {
  margin-bottom: 16px;
  padding: 12px;
  border-radius: var(--radius);
  background: var(--color-bg-tertiary);
}

/* ── Progress bar ─────────────────────────────────────────── */
.progress-track {
  width: 100%;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--color-primary-soft);
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width 0.4s ease;
}
.progress-fill--primary {
  background: var(--color-primary);
}
.progress-fill--warning {
  background: var(--color-warning);
}
.progress-fill--danger {
  background: var(--color-danger);
}

/* ── Time info ────────────────────────────────────────────── */
.time-info {
  display: flex;
  gap: 20px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.time-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* ── Action bar ───────────────────────────────────────────── */
.action-bar {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.action-btn {
  min-width: 140px;
}
.action-btn--primary {
  /* primary btn already styled by .btn-primary */
}
.action-btn--warning {
  background: var(--color-warning);
  color: #fff;
  border: 1px solid transparent;
}
.action-btn--warning:hover:not(:disabled) {
  background: var(--color-warning);
  filter: brightness(0.85);
  box-shadow: var(--shadow-sm);
}
.action-btn--danger {
  /* btn-danger already styled */
}

@media (max-width: 767px) {
  .action-bar {
    flex-direction: column;
  }
  .action-btn {
    width: 100%;
    min-width: unset;
  }
}
</style>
