<script setup lang="ts">
import { ref, onMounted, nextTick, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChapterStore } from '../stores/chapters'
import { useWaveSurfer } from '../composables/useWaveSurfer'
import { usePipelineProgress } from '../composables/usePipelineProgress'
import { useI18n } from '../i18n'
import { Icon } from '@iconify/vue'
import type { PipelineStage } from '../types/pipeline'
import { normalizeChapterPipeline } from '../utils/normalize'

const route = useRoute()
const router = useRouter()
const store = useChapterStore()
const { t } = useI18n()

const projectId = Number(route.params.projectId)
const chapterId = Number(route.params.chapterId)

const waveformContainer = ref<HTMLElement | null>(null)
const selectedParaId = ref<number | null>(null)
const zoomLevel = ref(50)

const {
  isPlaying, currentTime, duration, error: wsError,
  load: loadWave, playPause, skip, zoom, cleanup,
} = useWaveSurfer(waveformContainer)

const PIPELINE_STAGES: PipelineStage[] = [
  'extract', 'analyze', 'annotate', 'edit',
  'audio_postprocess', 'synthesize', 'quality'
]

const {
  state: pipelineState,
  getOverallProgress,
  isStageCompleted,
  isStageActive,
} = usePipelineProgress({
  projectId,
  autoConnect: true,
})

const pipelineStageLabels: Record<PipelineStage, string> = {
  extract: t('pipeline.stages.extract'),
  analyze: t('pipeline.stages.analyze'),
  annotate: t('pipeline.stages.annotate'),
  edit: t('pipeline.stages.edit'),
  audio_postprocess: t('pipeline.stages.audio_postprocess'),
  synthesize: t('pipeline.stages.synthesize'),
  quality: t('pipeline.stages.quality'),
}

// Sync persisted chapter per-stage status into pipeline progress on load
function syncPersistedPipelineStatus() {
  const chapter = store.currentChapter
  if (!chapter) return
  const normalized = normalizeChapterPipeline(chapter, store.paragraphs)
  const completed: PipelineStage[] = []
  let current: PipelineStage | null = null
  let stageProgress = 0

  for (const ns of normalized) {
    if (ns.status === 'completed') {
      completed.push(ns.stage)
    } else if (ns.status === 'running') {
      current = ns.stage
      stageProgress = 0.5
    }
  }

  // Only override if we have meaningful persisted data and pipeline isn't already running
  if (completed.length > 0 && !pipelineState.value.isRunning) {
    pipelineState.value.completedStages = completed
    if (current) {
      pipelineState.value.currentStage = current
      pipelineState.value.stageProgress = stageProgress
    }
  }
}

onMounted(async () => {
  await store.loadChapter(projectId, chapterId)
  await store.loadParagraphs(projectId, chapterId)
  syncPersistedPipelineStatus()
})

// Re-sync when chapters/paragraphs load finishes (race-safe)
watch(() => store.currentChapter, syncPersistedPipelineStatus, { immediate: false })
watch(() => store.paragraphs.length, syncPersistedPipelineStatus, { immediate: false })

function getAudioUrl(paragraphId: number): string {
  return `/api/paragraphs/${paragraphId}/audio`
}

function selectParagraph(paraId: number) {
  cleanup()
  selectedParaId.value = paraId

  const para = store.paragraphs.find((p) => p.id === paraId)
  if (!para) return

  store.loadAudioSegments(paraId)
  store.loadQuality(paraId)

  nextTick(() => {
    loadWave(getAudioUrl(paraId))
  })
}

function jumpToParagraph(paraId: number) {
  selectParagraph(paraId)
  const el = document.getElementById(`para-${paraId}`)
  el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function formatTime(seconds: number): string {
  if (!seconds || !isFinite(seconds)) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function goBack() {
  router.push(`/projects/${projectId}`)
}

const overallProgress = computed(() => getOverallProgress())

// Check if paragraph has any annotations to display
function hasAnnotations(para: any): boolean {
  return !!(
    para.emotion ||
    (para.speech_rate && para.speech_rate !== 1) ||
    (para.pitch_shift_semitones && para.pitch_shift_semitones !== 0) ||
    (para.needs_sfx && para.sfx_tags && para.sfx_tags.length > 0)
  )
}
</script>

<template>
  <div class="page-container chapter-timeline">
    <header class="page-header">
      <button class="btn btn-ghost touch-target" @click="goBack">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        <span class="hidden-mobile">{{ t('common.back') }}</span>
      </button>
      <h1>{{ store.currentChapter?.title || t('chapter_timeline.chapter_fallback', { id: chapterId }) }}</h1>
      <div class="header-meta" v-if="store.paragraphs.length">
        <span class="badge badge-muted">{{ store.paragraphs.length }} {{ t('chapter_timeline.paragraphs_count') }}</span>
      </div>
    </header>

    <!-- Pipeline Progress Bar (Always Visible) -->
    <div class="card card-hover section pipeline-progress-section">
      <div class="pipeline-progress-header flex items-center justify-between flex-wrap gap-2 mb-4">
        <span class="badge" :class="pipelineState.isPaused ? 'badge-warning' : pipelineState.isRunning ? 'badge-info' : pipelineState.completedStages.length > 0 ? 'badge-success' : 'badge-muted'">
          {{ pipelineState.isPaused ? t('pipeline.paused') : pipelineState.isRunning ? t('pipeline.running') : pipelineState.completedStages.length > 0 ? t('pipeline.completed') : t('chapter_timeline.pipeline_idle') }}
        </span>
        <span v-if="pipelineState.currentStage" class="pipeline-current-stage text-primary font-medium text-sm">
          {{ t(`pipeline.stages.${pipelineState.currentStage}`) || pipelineState.currentStage }}
          {{ pipelineState.currentChapterId !== null ? ` (${t('common.chapter')} #${pipelineState.currentChapterId})` : '' }}
        </span>
        <span class="pipeline-overall-progress font-medium" style="font-variant-numeric: tabular-nums;">{{ Math.round(overallProgress * 100) }}%</span>
      </div>
      <div class="pipeline-progress-bar" style="height: 8px; background: var(--color-border); border-radius: 4px; overflow: hidden; margin-bottom: 16px;">
        <div
          class="pipeline-progress-fill"
          :style="{ width: `${overallProgress * 100}%` }"
          style="height: 100%; background: linear-gradient(90deg, var(--color-primary), var(--color-success)); border-radius: 4px; transition: width 0.3s ease;"
        ></div>
      </div>
      <div class="pipeline-stages flex gap-4 overflow-x-auto pb-2">
        <div
          v-for="stage in PIPELINE_STAGES"
          :key="stage"
          class="pipeline-stage flex flex-col items-center gap-2"
          :class="{
            completed: isStageCompleted(stage),
            active: isStageActive(stage),
            pending: !isStageCompleted(stage) && !isStageActive(stage),
          }"
          style="flex: 1; min-width: 100px; position: relative;"
        >
          <div class="stage-indicator" style="width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; color: #fff; background: var(--color-border); transition: all 0.2s ease;">
            <span v-if="isStageCompleted(stage)" class="stage-icon">✓</span>
            <span v-else-if="isStageActive(stage)" class="stage-icon spinner">⟳</span>
            <span v-else class="stage-dot"></span>
          </div>
          <span class="stage-label" style="font-size: 10px; color: var(--color-text-secondary); text-align: center; white-space: nowrap;">{{ t(`pipeline.stages.${stage}`) || pipelineStageLabels[stage] }}</span>
          <span
            v-if="isStageActive(stage)"
            class="stage-progress"
            style="font-size: 10px; color: var(--color-primary); font-weight: 600;"
          >
            {{ Math.round(pipelineState.stageProgress * 100) }}%
          </span>
        </div>
      </div>
      <div v-if="pipelineState.error" class="alert alert-error mt-4" style="font-size: 13px;">
        {{ pipelineState.error }}
      </div>
      <div v-else-if="!pipelineState.isRunning && pipelineState.completedStages.length === 0" class="text-center text-secondary text-sm mt-4" style="color: var(--color-text-muted);">
        {{ t('chapter_timeline.pipeline_not_started') }} — {{ t('auto_run.start') }} {{ t('auto_run.title') }} {{ t('common.or') }} {{ t('chapter_timeline.pipeline_flow') }}
      </div>
    </div>

    <!-- Waveform Player -->
    <div v-if="selectedParaId" class="card card-hover section waveform-section">
      <div class="waveform-toolbar flex items-center gap-2 mb-4">
        <button class="btn btn-ghost btn-sm touch-target" @click="skip(-5)" :title="t('chapter_timeline.rewind_5s')" :aria-label="t('chapter_timeline.rewind_5s')">
          <Icon icon="mdi:skip-previous" width="18" height="18" />
        </button>
        <button class="btn btn-primary btn-lg touch-target" @click="playPause" :title="isPlaying ? t('chapter_timeline.pause') : t('chapter_timeline.play')" :aria-label="isPlaying ? t('chapter_timeline.pause') : t('chapter_timeline.play')" style="width: 44px; height: 44px;">
          <Icon :icon="isPlaying ? 'mdi:pause' : 'mdi:play'" width="20" height="20" />
        </button>
        <button class="btn btn-ghost btn-sm touch-target" @click="skip(5)" :title="t('chapter_timeline.forward_5s')" :aria-label="t('chapter_timeline.forward_5s')">
          <Icon icon="mdi:skip-next" width="18" height="18" />
        </button>
        <span class="time-display text-secondary" style="font-size: 13px; font-variant-numeric: tabular-nums; min-width: 90px;">{{ formatTime(currentTime) }} / {{ formatTime(duration) }}</span>
        <div class="zoom-controls flex items-center gap-2" style="margin-left: auto;">
          <button class="btn btn-ghost btn-sm touch-target" @click="zoomLevel = Math.max(10, zoomLevel - 10); zoom(zoomLevel)" :title="t('chapter_timeline.zoom_out')" :aria-label="t('chapter_timeline.zoom_out')">
            <Icon icon="mdi:minus" width="18" height="18" />
          </button>
          <span class="zoom-label text-muted" style="font-size: 11px; min-width: 50px; text-align: center;">{{ zoomLevel }}px/s</span>
          <button class="btn btn-ghost btn-sm touch-target" @click="zoomLevel = Math.min(200, zoomLevel + 10); zoom(zoomLevel)" :title="t('chapter_timeline.zoom_in')" :aria-label="t('chapter_timeline.zoom_in')">
            <Icon icon="mdi:plus" width="18" height="18" />
          </button>
        </div>
      </div>
      <div ref="waveformContainer" class="waveform-container" style="min-height: 80px;"></div>
      <div v-if="wsError" class="alert alert-error mt-2">{{ wsError }}</div>
    </div>

    <!-- Paragraph Selector Hint -->
    <div v-if="!selectedParaId && store.paragraphs.length" class="empty-state section">
      <Icon icon="mdi:hand-pointing-right" width="32" height="32" style="opacity: 0.4" />
      <p>{{ t('chapter_timeline.select_hint') }}</p>
    </div>

    <!-- Loading -->
    <div v-else-if="store.loading" class="loading-state section">
      <div class="spinner"></div>
      <span>{{ t('chapter_timeline.loading') }}</span>
    </div>

    <!-- Paragraph List -->
    <div v-else class="paragraph-list grid gap-3">
      <div
        v-for="(para, idx) in store.paragraphs"
        :key="para.id"
        :id="`para-${para.id}`"
        class="card card-hover grid-auto-fill paragraph-card"
        @click="selectParagraph(para.id)"
        :class="{ selected: selectedParaId === para.id }"
        style="cursor: pointer;"
      >
        <div class="para-header flex items-center gap-2 mb-2 flex-wrap">
          <span class="para-num font-medium text-primary" style="font-size: 12px; min-width: 28px;">#{{ idx + 1 }}</span>
          <span class="para-role badge badge-muted" style="font-size: 11px;">{{ para.speaker_canonical_name || t('chapter_timeline.narrator') }}</span>
          <span v-if="para.is_dialogue" class="badge badge-info" style="font-size: 10px;">{{ t('chapter_timeline.dialogue') }}</span>
          <span v-else class="badge badge-muted" style="font-size: 10px;">{{ t('chapter_timeline.narration') }}</span>
          <span :class="['status-dot', para.status || 'pending']" style="width: 8px; height: 8px; border-radius: 50%;" :style="{ background: para.status === 'completed' ? 'var(--color-success)' : para.status === 'error' ? 'var(--color-danger)' : 'var(--color-warning)' }" />
          <button class="btn btn-ghost btn-sm touch-target" @click.stop="jumpToParagraph(para.id)" :title="t('chapter_timeline.waveform_jump')" :aria-label="t('chapter_timeline.waveform_jump')">
            <Icon icon="mdi:waveform" width="18" height="18" />
          </button>
        </div>

        <!-- Text content: show edited_text with badge if exists, else original text -->
        <div class="para-text-section">
          <div v-if="para.edited_text && para.edited_text !== para.text" class="edited-text-block">
            <span class="badge badge-success" style="font-size: 10px; margin-bottom: 6px;">{{ t('chapter_timeline.edited_badge') }}</span>
            <p style="margin: 0; font-size: 14px; line-height: 1.7; color: var(--color-text);">{{ para.edited_text }}</p>
          </div>
          <div v-else class="original-text-block">
            <span class="badge badge-muted" style="font-size: 10px; margin-bottom: 6px;">{{ t('chapter_timeline.original_badge') }}</span>
            <p style="margin: 0; font-size: 14px; line-height: 1.7; color: var(--color-text); display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;">{{ para.text }}</p>
          </div>
        </div>

        <!-- Annotation chips row -->
        <div v-if="hasAnnotations(para)" class="annotation-chips flex flex-wrap gap-2 mt-2">
          <span v-if="para.emotion" class="annotation-chip badge badge-info" :title="t('chapter_timeline.emotion') + ': ' + para.emotion">
            <Icon icon="mdi:emoticon" width="12" height="12" class="gap-1" />
            {{ para.emotion }}{{ para.emotion_intensity ? ` (${para.emotion_intensity})` : '' }}
          </span>
          <span v-if="para.speech_rate && para.speech_rate !== 1" class="annotation-chip badge badge-warning" :title="t('chapter_timeline.speech_rate') + ': ' + para.speech_rate">
            <Icon icon="mdi:speedometer" width="12" height="12" class="gap-1" />
            {{ para.speech_rate }}×
          </span>
          <span v-if="para.pitch_shift_semitones && para.pitch_shift_semitones !== 0" class="annotation-chip badge badge-primary" :title="t('chapter_timeline.pitch') + ': ' + para.pitch_shift_semitones">
            <Icon icon="mdi:music" width="12" height="12" class="gap-1" />
            {{ para.pitch_shift_semitones > 0 ? '+' : '' }}{{ para.pitch_shift_semitones }}st
          </span>
          <span v-if="para.needs_sfx && para.sfx_tags && para.sfx_tags.length > 0" class="annotation-chip badge badge-secondary" :title="t('chapter_timeline.sfx') + ': ' + para.sfx_tags.join(', ')">
            <Icon icon="mdi:volume-high" width="12" height="12" class="gap-1" />
            {{ t('chapter_timeline.sfx') }}: {{ para.sfx_tags.slice(0, 2).join(', ') }}{{ para.sfx_tags.length > 2 ? '...' : '' }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chapter-timeline {
  max-width: 960px;
}

.pipeline-stage {
  position: relative;
}
.pipeline-stage:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 14px;
  right: -6px;
  width: 12px;
  height: 2px;
  background: var(--color-border);
}
.pipeline-stage.completed::after {
  background: var(--color-success);
}
.pipeline-stage.active::after {
  background: var(--color-primary);
}

.stage-indicator {
  transition: all 0.2s ease;
}
.pipeline-stage.completed .stage-indicator {
  background: var(--color-success);
}
.pipeline-stage.active .stage-indicator {
  background: var(--color-primary);
  animation: pulse 1.5s infinite;
}
.pipeline-stage.active .stage-icon.spinner {
  animation: spin 1s linear infinite;
}

@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(79, 70, 229, 0.4); }
  50% { box-shadow: 0 0 0 8px rgba(79, 70, 229, 0); }
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.pipeline-stage.completed .stage-label,
.pipeline-stage.active .stage-label {
  color: var(--color-text);
  font-weight: 500;
}

.paragraph-card.selected {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px var(--color-primary-alpha);
}

.status-dot.completed { background: var(--color-success); }
.status-dot.pending { background: var(--color-warning); }
.status-dot.error { background: var(--color-danger); }

/* WaveSurfer container */
.waveform-container {
  min-height: 80px;
}

/* Responsive */
@media (max-width: 767px) {
  .pipeline-stages {
    gap: 8px;
  }
  .pipeline-stage {
    min-width: 80px;
  }
  .stage-label {
    font-size: 9px;
  }
}

/* Annotation chips */
.annotation-chip {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 99px;
  white-space: nowrap;
}

.para-text-section {
  margin-bottom: 4px;
}

.edited-text-block p {
  background: #f0fdf4;
  padding: 8px 10px;
  border-radius: 6px;
  border-left: 3px solid var(--color-success);
}

.original-text-block p {
  /* keeps existing clamp styling */
}
</style>