<script setup lang="ts">
import { ref, onMounted, nextTick, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useChapterStore } from '../stores/chapters'
import { useWaveSurfer } from '../composables/useWaveSurfer'
import { usePipelineProgress } from '../composables/usePipelineProgress'
import { useI18n } from '../i18n'
import type { PipelineStage } from '../types/pipeline'

const route = useRoute()
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

const pipelineStageLabels: Record<PipelineStage, string> = {
  extract: '文本提取',
  analyze: '结构分析',
  annotate: '段落标注',
  edit: '文本编辑',
  audio_postprocess: '音频后处理',
  synthesize: '语音合成',
  quality: '质量检查',
}

const {
  state: pipelineState,
  getOverallProgress,
  isStageCompleted,
  isStageActive,
} = usePipelineProgress({
  projectId,
  autoConnect: true,
})

onMounted(async () => {
  await store.loadChapter(projectId, chapterId)
  await store.loadParagraphs(projectId, chapterId)
})

function getAudioUrl(paragraphId: number): string {
  return `/api/paragraphs/${paragraphId}/audio`
}

function selectParagraph(paraId: number) {
  cleanup()
  selectedParaId.value = paraId

  const para = store.paragraphs.find((p) => p.id === paraId)
  if (!para) return

  // Load audio segments if available, otherwise try direct audio URL
  store.loadAudioSegments(paraId)
  store.loadQuality(paraId)

  // Load waveform
  nextTick(() => {
    loadWave(getAudioUrl(paraId))
  })
}

function jumpToParagraph(paraId: number) {
  selectParagraph(paraId)
  // Scroll the paragraph card into view
  const el = document.getElementById(`para-${paraId}`)
  el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function formatTime(seconds: number): string {
  if (!seconds || !isFinite(seconds)) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

const overallProgress = computed(() => getOverallProgress())
</script>

<template>
  <div class="chapter-timeline">
    <div class="page-header">
      <button class="btn btn-ghost" @click="$router.push(`/projects/${projectId}`)">
        {{ t('common.back') }}
      </button>
      <h1>{{ store.currentChapter?.title || t('chapter_timeline.chapter_fallback', { id: chapterId }) }}</h1>
      <div class="header-meta" v-if="store.paragraphs.length">
        <span class="badge">{{ store.paragraphs.length }} {{ t('chapter_timeline.paragraphs_count') }}</span>
      </div>
    </div>

    <!-- Pipeline Progress Bar -->
    <div v-if="pipelineState.isRunning || pipelineState.completedStages.length > 0" class="pipeline-progress-section">
      <div class="pipeline-progress-header">
        <span class="pipeline-status" :class="{ paused: pipelineState.isPaused }">
          {{ pipelineState.isPaused ? t('pipeline.paused') : t('pipeline.running') }}
        </span>
        <span v-if="pipelineState.currentStage" class="pipeline-current-stage">
          {{ t(`pipeline.stages.${pipelineState.currentStage}`) || pipelineState.currentStage }}
          {{ pipelineState.currentChapterId !== null ? ` (章节 #${pipelineState.currentChapterId})` : '' }}
        </span>
        <span class="pipeline-overall-progress">{{ Math.round(overallProgress * 100) }}%</span>
      </div>
      <div class="pipeline-progress-bar">
        <div
          class="pipeline-progress-fill"
          :style="{ width: `${overallProgress * 100}%` }"
        ></div>
      </div>
      <div class="pipeline-stages">
        <div
          v-for="stage in PIPELINE_STAGES"
          :key="stage"
          class="pipeline-stage"
          :class="{
            completed: isStageCompleted(stage),
            active: isStageActive(stage),
            pending: !isStageCompleted(stage) && !isStageActive(stage),
          }"
        >
          <div class="stage-indicator">
            <span v-if="isStageCompleted(stage)" class="stage-icon">✓</span>
            <span v-else-if="isStageActive(stage)" class="stage-icon spinner">⟳</span>
            <span v-else class="stage-dot"></span>
          </div>
          <span class="stage-label">{{ pipelineStageLabels[stage] }}</span>
          <span
            v-if="isStageActive(stage)"
            class="stage-progress"
          >
            {{ Math.round(pipelineState.stageProgress * 100) }}%
          </span>
        </div>
      </div>
      <div v-if="pipelineState.error" class="pipeline-error">
        {{ pipelineState.error }}
      </div>
    </div>

    <!-- Waveform Player -->
    <div class="waveform-section" v-if="selectedParaId">
      <div class="waveform-toolbar">
        <button class="btn-icon" @click="skip(-5)" :title="t('chapter_timeline.rewind_5s')">
          ⟪
        </button>
        <button class="btn-play" @click="playPause" :title="isPlaying ? t('chapter_timeline.pause') : t('chapter_timeline.play')">
          {{ isPlaying ? '⏸' : '▶' }}
        </button>
        <button class="btn-icon" @click="skip(5)" :title="t('chapter_timeline.forward_5s')">
          ⟫
        </button>
        <span class="time-display">{{ formatTime(currentTime) }} / {{ formatTime(duration) }}</span>
        <div class="zoom-controls">
          <button class="btn-icon" @click="zoomLevel = Math.max(10, zoomLevel - 10); zoom(zoomLevel)" :title="t('chapter_timeline.zoom_out')">
            －
          </button>
          <span class="zoom-label">{{ zoomLevel }}px/s</span>
          <button class="btn-icon" @click="zoomLevel = Math.min(200, zoomLevel + 10); zoom(zoomLevel)" :title="t('chapter_timeline.zoom_in')">
            ＋
          </button>
        </div>
      </div>
      <div ref="waveformContainer" class="waveform-container"></div>
      <div v-if="wsError" class="waveform-error">{{ wsError }}</div>
    </div>

    <!-- Paragraph Selector Hint -->
    <div v-if="!selectedParaId && store.paragraphs.length" class="select-hint">
      {{ t('chapter_timeline.select_hint') }}
    </div>

    <!-- Loading -->
    <div v-if="store.loading" class="loading">{{ t('chapter_timeline.loading') }}</div>

    <!-- Paragraph List -->
    <div v-else class="paragraph-list">
      <div
        v-for="(para, idx) in store.paragraphs"
        :key="para.id"
        :id="`para-${para.id}`"
        :class="['paragraph-card', { selected: selectedParaId === para.id }]"
        @click="selectParagraph(para.id)"
      >
        <div class="para-header">
          <span class="para-num">#{{ idx + 1 }}</span>
          <span class="para-role">{{ para.speaker_canonical_name || t('chapter_timeline.narrator') }}</span>
          <span :class="['status-dot', para.status || 'pending']" />
          <button class="btn-icon btn-jump" @click.stop="jumpToParagraph(para.id)" :title="t('chapter_timeline.waveform_jump')">
            ~
          </button>
        </div>
        <p class="para-text">{{ para.text }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chapter-timeline { max-width: 900px; margin: 0 auto; }

/* Header */
.page-header { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; }
.page-header h1 { margin: 0; font-size: 22px; flex: 1; }
.badge { font-size: 11px; padding: 2px 10px; border-radius: 99px; background: #dbeafe; color: #1d4ed8; }

/* Waveform */
.waveform-section {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 20px;
}
.waveform-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.btn-play { background: none; border: none; cursor: pointer; color: #3b82f6; padding: 0; line-height: 1; }
.btn-play:hover { color: #2563eb; }
.time-display { font-size: 13px; color: #64748b; font-variant-numeric: tabular-nums; min-width: 90px; }
.zoom-controls { margin-left: auto; display: flex; align-items: center; gap: 4px; }
.zoom-label { font-size: 11px; color: #94a3b8; min-width: 40px; text-align: center; }
.waveform-container { min-height: 80px; }
.waveform-error { color: #ef4444; font-size: 13px; margin-top: 8px; }

/* Select hint */
.select-hint { text-align: center; padding: 12px; color: #94a3b8; font-size: 13px; }

/* Paragraphs */
.paragraph-list {}
.paragraph-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 18px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.paragraph-card:hover { border-color: #93c5fd; }
.paragraph-card.selected { border-color: #3b82f6; box-shadow: 0 0 0 2px rgba(59,130,246,0.15); }
.para-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.para-num { font-weight: 600; color: #3b82f6; font-size: 12px; min-width: 28px; }
.para-role { font-size: 12px; color: #64748b; background: #f1f5f9; padding: 1px 8px; border-radius: 4px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; }
.status-dot.completed { background: #22c55e; }
.status-dot.pending { background: #facc15; }
.status-dot.error { background: #ef4444; }
.btn-jump { margin-left: auto; color: #94a3b8; }
.btn-jump:hover { color: #3b82f6; }
.para-text { margin: 0; font-size: 14px; line-height: 1.7; color: #1e293b; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }

/* Pipeline Progress */
.pipeline-progress-section {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 20px;
}
.pipeline-progress-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.pipeline-status {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: 99px;
  background: #dbeafe;
  color: #1d4ed8;
  text-transform: uppercase;
}
.pipeline-status.paused {
  background: #fef3c7;
  color: #b45309;
}
.pipeline-current-stage {
  font-size: 13px;
  color: #3b82f6;
  font-weight: 500;
}
.pipeline-overall-progress {
  margin-left: auto;
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  font-variant-numeric: tabular-nums;
}
.pipeline-progress-bar {
  height: 8px;
  background: #f1f5f9;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 16px;
}
.pipeline-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #22c55e);
  border-radius: 4px;
  transition: width 0.3s ease;
}
.pipeline-stages {
  display: flex;
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 8px;
}
.pipeline-stage {
  flex: 1;
  min-width: 100px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  position: relative;
}
.pipeline-stage:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 14px;
  right: -6px;
  width: 12px;
  height: 2px;
  background: #e2e8f0;
}
.pipeline-stage.completed::after {
  background: #22c55e;
}
.pipeline-stage.active::after {
  background: #3b82f6;
}
.stage-indicator {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  background: #e2e8f0;
  transition: all 0.2s ease;
}
.pipeline-stage.completed .stage-indicator {
  background: #22c55e;
}
.pipeline-stage.active .stage-indicator {
  background: #3b82f6;
  animation: pulse 1.5s infinite;
}
.pipeline-stage.active .stage-icon.spinner {
  animation: spin 1s linear infinite;
}
@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.4); }
  50% { box-shadow: 0 0 0 8px rgba(59, 130, 246, 0); }
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.stage-label {
  font-size: 10px;
  color: #64748b;
  text-align: center;
  white-space: nowrap;
}
.pipeline-stage.completed .stage-label,
.pipeline-stage.active .stage-label {
  color: #1e293b;
  font-weight: 500;
}
.stage-progress {
  font-size: 10px;
  color: #3b82f6;
  font-weight: 600;
}
.pipeline-error {
  margin-top: 12px;
  padding: 8px 12px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: #dc2626;
  font-size: 13px;
}

/* Utilities */
.btn-icon { background: none; border: none; cursor: pointer; color: #64748b; padding: 4px; border-radius: 6px; line-height: 1; display: inline-flex; align-items: center; }
.btn-icon:hover { background: #f1f5f9; color: #1e293b; }
.loading { text-align: center; padding: 60px; color: #64748b; }
</style>
