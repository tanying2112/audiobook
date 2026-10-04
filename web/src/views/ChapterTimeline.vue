<script setup lang="ts">
import './ChapterTimeline.css'
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
} = useChapterTimeline()

void waveformContainer
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
