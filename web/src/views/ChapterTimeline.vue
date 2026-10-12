<script setup lang="ts">
import './ChapterTimeline.css'
import { ref } from 'vue'
import type { Paragraph } from '../types'
import { updateParagraph, triggerRegeneration } from '../api'
import ParagraphEditor from '../components/ParagraphEditor.vue'
import { useChapterTimeline } from '../composables/useChapterTimeline'

const {
  t,
  chapterId,
  store,
  waveformContainer,
  selectedParaId,
  zoomLevel,
  isPlaying,
  currentTime,
  duration,
  wsError,
  playPause,
  skip,
  zoom,
  PIPELINE_STAGES,
  pipelineState,
  pipelineStageLabels,
  isStageCompleted,
  isStageActive,
  overallProgress,
  formatTime,
  selectParagraph,
  jumpToParagraph,
  goBack,
  hasAnnotations,
  projectId,
} = useChapterTimeline()

void waveformContainer

// ── 段落编辑(P0.1)────────────────────────────────────────────────────────
const editingParagraph = ref<Paragraph | null>(null)
const regeneratingId = ref<number | null>(null)

function openEditor(para: Paragraph) {
  editingParagraph.value = para
}

async function handleSave(paragraphId: number, payload: Partial<Paragraph>) {
  await updateParagraph(projectId, chapterId, paragraphId, payload)
  await store.loadParagraphs(projectId, chapterId)
  editingParagraph.value = null
}

async function regenerateAudio(para: Paragraph) {
  if (regeneratingId.value !== null) return
  regeneratingId.value = para.id
  try {
    await triggerRegeneration(para.id)
  } catch (err) {
    console.error('Regeneration failed:', err)
  } finally {
    regeneratingId.value = null
  }
}

/** Return the latest quality score for a paragraph, if loaded. */
function getQualityScore(para: Paragraph): number | null {
  const records = store.qualityResults.get(para.id)
  if (!records || records.length === 0) return null
  return records[records.length - 1].overall_score
}

function qualityClass(score: number): string {
  if (score >= 0.8) return 'quality-score quality-score-high'
  if (score >= 0.5) return 'quality-score quality-score-mid'
  return 'quality-score quality-score-low'
}
</script>


<template>
  <div class="page-container chapter-timeline">
    <header class="page-header">
      <button class="btn btn-ghost touch-target" @click="goBack" :aria-label="t('common.back')">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        <span class="hidden-mobile">{{ t('common.back') }}</span>
      </button>
      <h1>{{ store.currentChapter?.title || t('chapter_timeline.chapter_fallback', { id: chapterId }) }}</h1>
      <div class="header-meta" v-if="store.paragraphs.length">
        <span class="badge badge-muted">{{ store.paragraphs.length }} {{ t('chapter_timeline.paragraphs_count') }}</span>
      </div>
    </header>

    <!-- Pipeline Progress Bar -->
    <div class="card card-hover section pipeline-progress-section">
      <div class="pipeline-progress-header flex items-center justify-between flex-wrap gap-2 mb-4">
        <span class="badge" :class="pipelineState.isPaused ? 'badge-warning' : pipelineState.isRunning ? 'badge-info' : pipelineState.completedStages.length > 0 ? 'badge-success' : 'badge-muted'">
          {{ pipelineState.isPaused ? t('pipeline.paused') : pipelineState.isRunning ? t('pipeline.running') : pipelineState.completedStages.length > 0 ? t('pipeline.completed') : t('chapter_timeline.pipeline_idle') }}
        </span>
        <span v-if="pipelineState.currentStage" class="text-primary font-medium text-sm">
          {{ t(`pipeline.stages.${pipelineState.currentStage}`) || pipelineState.currentStage }}
          {{ pipelineState.currentChapterId !== null ? ` (${t('common.chapter')} #${pipelineState.currentChapterId})` : '' }}
        </span>
        <span class="font-medium" style="font-variant-numeric: tabular-nums;">{{ Math.round(overallProgress * 100) }}%</span>
      </div>
      <div class="progress-bar-track">
        <div
          class="progress-bar-fill"
          :style="{ width: `${overallProgress * 100}%` }"
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
        >
          <div class="stage-indicator">
            <span v-if="isStageCompleted(stage)" class="stage-icon">✓</span>
            <span v-else-if="isStageActive(stage)" class="stage-icon spinner">⟳</span>
            <span v-else class="stage-dot"></span>
          </div>
          <span class="stage-label">{{ t(`pipeline.stages.${stage}`) || pipelineStageLabels[stage] }}</span>
          <span v-if="isStageActive(stage)" class="stage-progress">
            {{ Math.round(pipelineState.stageProgress * 100) }}%
          </span>
        </div>
      </div>
      <div v-if="pipelineState.error" class="alert alert-error mt-4 pipeline-error">
        {{ pipelineState.error }}
      </div>
      <div v-else-if="!pipelineState.isRunning && pipelineState.completedStages.length === 0" class="text-center text-secondary text-sm mt-4 pipeline-idle-hint">
        {{ t('chapter_timeline.pipeline_not_started') }} — {{ t('auto_run.start') }} {{ t('auto_run.title') }} {{ t('common.or') }} {{ t('chapter_timeline.pipeline_flow') }}
      </div>
    </div>

    <!-- Waveform Player -->
    <div v-if="selectedParaId" class="card card-hover section waveform-section">
      <div class="waveform-toolbar">
        <button class="btn btn-ghost btn-sm touch-target" @click="skip(-5)" :aria-label="t('chapter_timeline.rewind_5s')">
          <Icon icon="mdi:skip-previous" width="18" height="18" />
        </button>
        <button class="btn btn-primary btn-lg touch-target waveform-play-btn" @click="playPause" :aria-label="isPlaying ? t('chapter_timeline.pause') : t('chapter_timeline.play')">
          <Icon :icon="isPlaying ? 'mdi:pause' : 'mdi:play'" width="20" height="20" />
        </button>
        <button class="btn btn-ghost btn-sm touch-target" @click="skip(5)" :aria-label="t('chapter_timeline.forward_5s')">
          <Icon icon="mdi:skip-next" width="18" height="18" />
        </button>
        <span class="time-display text-secondary">{{ formatTime(currentTime) }} / {{ formatTime(duration) }}</span>
        <div class="zoom-controls">
          <button class="btn btn-ghost btn-sm touch-target" @click="zoomLevel = Math.max(10, zoomLevel - 10); zoom(zoomLevel)" :aria-label="t('chapter_timeline.zoom_out')">
            <Icon icon="mdi:minus" width="18" height="18" />
          </button>
          <span class="zoom-label text-muted">{{ zoomLevel }}px/s</span>
          <button class="btn btn-ghost btn-sm touch-target" @click="zoomLevel = Math.min(200, zoomLevel + 10); zoom(zoomLevel)" :aria-label="t('chapter_timeline.zoom_in')">
            <Icon icon="mdi:plus" width="18" height="18" />
          </button>
        </div>
      </div>
      <div ref="waveformContainer" class="waveform-container"></div>
      <div v-if="wsError" class="alert alert-error mt-2">{{ wsError }}</div>
    </div>

    <!-- Paragraph Editor (P0.1) -->
    <ParagraphEditor
      v-if="editingParagraph"
      class="section"
      :paragraph="editingParagraph"
      :project-id="projectId"
      :chapter-id="chapterId"
      @save="handleSave"
      @close="editingParagraph = null"
    />

    <!-- Paragraph Selector Hint -->
    <div v-if="!editingParagraph && !selectedParaId && store.paragraphs.length" class="empty-state section">
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
        class="card card-hover paragraph-card"
        :class="{ selected: selectedParaId === para.id }"
        @click="selectParagraph(para.id)"
      >
        <div class="para-header">
          <span class="para-num">#{{ idx + 1 }}</span>
          <span class="para-role badge badge-muted">{{ para.speaker_canonical_name || t('chapter_timeline.narrator') }}</span>
          <span v-if="para.is_dialogue" class="badge badge-info para-type-badge">{{ t('chapter_timeline.dialogue') }}</span>
          <span v-else class="badge badge-muted para-type-badge">{{ t('chapter_timeline.narration') }}</span>
          <span class="status-dot" :class="para.status || 'pending'" />

          <!-- Quality score (if available) -->
          <span
            v-if="getQualityScore(para) !== null"
            :class="qualityClass(getQualityScore(para)!)"
            :title="'Quality: ' + Math.round(getQualityScore(para)! * 100) + '%'"
          >
            <Icon icon="mdi:star" width="10" height="10" />
            {{ Math.round(getQualityScore(para)! * 100) }}
          </span>

          <button
            class="btn btn-ghost btn-sm touch-target"
            :disabled="regeneratingId === para.id"
            :title="regeneratingId === para.id ? 'Regenerating…' : 'Regenerate audio'"
            :aria-label="regeneratingId === para.id ? 'Regenerating audio' : 'Regenerate audio'"
            @click.stop="regenerateAudio(para)"
          >
            <Icon :icon="regeneratingId === para.id ? 'mdi:loading' : 'mdi:refresh'" width="16" height="16" />
          </button>
          <button class="btn btn-ghost btn-sm touch-target" :aria-label="t('common.edit')" @click.stop="openEditor(para)">
            <Icon icon="mdi:pencil" width="16" height="16" />
          </button>
          <button class="btn btn-ghost btn-sm touch-target" :aria-label="t('chapter_timeline.waveform_jump')" @click.stop="jumpToParagraph(para.id)">
            <Icon icon="mdi:waveform" width="16" height="16" />
          </button>
        </div>

        <!-- Text content -->
        <div class="para-text-section">
          <div v-if="para.edited_text && para.edited_text !== para.text" class="edited-text-block">
            <span class="badge badge-success text-badge">{{ t('chapter_timeline.edited_badge') }}</span>
            <p class="para-text">{{ para.edited_text }}</p>
          </div>
          <div v-else class="original-text-block">
            <span class="badge badge-muted text-badge">{{ t('chapter_timeline.original_badge') }}</span>
            <p class="para-text">{{ para.text }}</p>
          </div>
        </div>

        <!-- Annotation chips row -->
        <div v-if="hasAnnotations(para)" class="annotation-chips">
          <span v-if="para.emotion" class="annotation-chip badge badge-info" :title="t('chapter_timeline.emotion') + ': ' + para.emotion">
            <Icon icon="mdi:emoticon" width="12" height="12" class="annotation-chip-icon" />
            {{ para.emotion }}{{ para.emotion_intensity ? ` (${para.emotion_intensity})` : '' }}
          </span>
          <span v-if="para.speech_rate && para.speech_rate !== 1" class="annotation-chip badge badge-warning" :title="t('chapter_timeline.speech_rate') + ': ' + para.speech_rate">
            <Icon icon="mdi:speedometer" width="12" height="12" class="annotation-chip-icon" />
            {{ para.speech_rate }}×
          </span>
          <span v-if="para.pitch_shift_semitones && para.pitch_shift_semitones !== 0" class="annotation-chip badge badge-primary" :title="t('chapter_timeline.pitch') + ': ' + para.pitch_shift_semitones">
            <Icon icon="mdi:music" width="12" height="12" class="annotation-chip-icon" />
            {{ para.pitch_shift_semitones > 0 ? '+' : '' }}{{ para.pitch_shift_semitones }}st
          </span>
          <span v-if="para.needs_sfx && para.sfx_tags && para.sfx_tags.length > 0" class="annotation-chip badge badge-secondary" :title="t('chapter_timeline.sfx') + ': ' + para.sfx_tags.join(', ')">
            <Icon icon="mdi:volume-high" width="12" height="12" class="annotation-chip-icon" />
            {{ t('chapter_timeline.sfx') }}: {{ para.sfx_tags.slice(0, 2).join(', ') }}{{ para.sfx_tags.length > 2 ? '...' : '' }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>
