<template>
  <div class="page-container">
    <header class="page-header">
      <div>
        <button class="btn btn-ghost touch-target" @click="router.back()">
          <Icon icon="mdi:arrow-left" width="18" height="18" />
          <span class="hidden-mobile">{{ t('common.back') }}</span>
        </button>
        <h1 class="mt-4 mb-0">{{ t('translation.title') }}</h1>
        <p class="text-secondary">{{ t('translation.subtitle') }}</p>
      </div>
    </header>

    <!-- Step 1: Configure -->
    <section class="card section" v-if="step === 1">
      <h2>{{ t('translation.config_title') }}</h2>

      <div class="form-group">
        <label class="form-label">{{ t('translation.project_label') }}</label>
        <div class="form-control project-display">
          <Icon icon="mdi:book-open-variant" width="20" height="20" />
          <span>{{ projectTitle || t('translation.loading_project') }}</span>
        </div>
      </div>

      <div class="form-group">
        <label class="form-label">{{ t('translation.target_language_label') }}</label>
        <select v-model="targetLanguage" class="form-control">
          <option value="" disabled>{{ t('translation.select_language') }}</option>
          <option
            v-for="lang in languages"
            :key="lang.code"
            :value="lang.code"
          >
            {{ lang.native_name }} ({{ lang.name }})
          </option>
        </select>
      </div>

      <div class="form-group">
        <label class="form-label">{{ t('translation.chapter_range_label') }}</label>
        <div class="flex flex-wrap gap-4 chapter-range">
          <label class="radio-label touch-target">
            <input type="radio" v-model="chapterMode" value="all" class="touch-target-sm" />
            {{ t('translation.all_chapters') }}
          </label>
          <label class="radio-label touch-target">
            <input type="radio" v-model="chapterMode" value="selected" class="touch-target-sm" />
            {{ t('translation.selected_chapters') }}
          </label>
        </div>
        <div v-if="chapterMode === 'selected'" class="grid grid-auto-fill chapter-checkboxes">
          <label
            v-for="ch in chapters"
            :key="ch.id"
            class="checkbox-label touch-target"
          >
            <input
              type="checkbox"
              :value="ch.chapter_number || ch.id"
              v-model="selectedChapters"
              class="touch-target-sm"
            />
            {{ ch.title || t('project_detail.chapter_fallback', { number: ch.chapter_number || ch.id }) }}
          </label>
        </div>
      </div>

      <div class="actions flex gap-2 flex-wrap justify-end mt-4">
        <button
          class="btn btn-primary touch-target"
          @click="startTranslate"
          :disabled="!targetLanguage || translating"
        >
          {{ translating ? t('translation.starting') : t('translation.start_btn') }}
        </button>
      </div>
    </section>

    <!-- Step 2: Progress -->
    <section class="card section" v-if="step === 2">
      <h2>{{ t('translation.progress_title') }}</h2>

      <div class="progress-header">
        <div class="progress-bar-container w-full">
          <div class="progress-bar" :style="{ width: overallProgress + '%' }"></div>
        </div>
        <span class="progress-text">{{ Math.round(overallProgress) }}%</span>
      </div>

      <div class="stage-list">
        <div
          v-for="stage in pipelineStages"
          :key="stage.key"
          class="stage-item"
          :class="{
            completed: progress.isStageCompleted(stage.key),
            active: progress.isStageActive(stage.key),
          }"
        >
          <Icon
            :icon="progress.isStageCompleted(stage.key) ? 'mdi:check-circle' : progress.isStageActive(stage.key) ? 'mdi:loading' : 'mdi:circle-outline'"
            width="20"
            height="20"
          />
          <span>{{ stage.label }}</span>
          <span v-if="progress.isStageActive(stage.key)" class="stage-progress">
            {{ Math.round(progressState.stageProgress * 100) }}%
          </span>
        </div>
      </div>

      <div v-if="progressState.error" class="alert alert-error">
        <Icon icon="mdi:alert-circle" width="20" height="20" />
        <span>{{ progressState.error }}</span>
      </div>

      <div class="actions flex gap-2 flex-wrap justify-end mt-4">
        <button
          v-if="!progressState.isRunning"
          class="btn btn-primary touch-target"
          @click="step = 3"
        >
          {{ t('translation.view_results') }}
        </button>
        <button
          v-if="progressState.isPaused"
          class="btn btn-outline touch-target"
          @click="resumeTranslation"
        >
          {{ t('translation.resume') }}
        </button>
      </div>
    </section>

    <!-- Step 3: Results -->
    <section class="card section" v-if="step === 3">
      <h2>{{ t('translation.results_title') }}</h2>

      <div class="result-summary grid grid-auto-fit">
        <div class="stat card">
          <span class="stat-value">{{ translationStatus.total_original_segments }}</span>
          <span class="stat-label">{{ t('translation.original_segments') }}</span>
        </div>
        <div class="stat card">
          <span class="stat-value">{{ translationStatus.total_translated_segments }}</span>
          <span class="stat-label">{{ t('translation.translated_segments') }}</span>
        </div>
        <div class="stat card">
          <span class="stat-value">{{ Math.round(translationStatus.translation_ratio * 100) }}%</span>
          <span class="stat-label">{{ t('translation.coverage') }}</span>
        </div>
      </div>

      <div class="comparison-section mt-4">
        <h3>{{ t('translation.comparison_title') }}</h3>
        <p class="hint">{{ t('translation.comparison_hint') }}</p>

        <div class="audio-comparison grid grid-2">
          <div class="audio-card card">
            <h4>{{ t('translation.original_audio') }}</h4>
            <div class="audio-player flex flex-col gap-2">
              <select v-model="selectedParagraph" class="form-control" style="max-width: 100%;">
                <option v-for="p in paragraphs" :key="p.id" :value="p.id">
                  {{ t('translation.paragraph') }} {{ p.index }}
                </option>
              </select>
              <button class="btn btn-primary touch-target" @click="playOriginal" :disabled="!selectedParagraph">
                <Icon icon="mdi:play" width="16" height="16" />
                <span>{{ t('translation.play') }}</span>
              </button>
            </div>
          </div>

          <div class="audio-card card">
            <h4>{{ t('translation.translated_audio') }}</h4>
            <div class="audio-player">
              <p class="hint">{{ t('translation.translated_hint') }}</p>
            </div>
          </div>
        </div>
      </div>

      <div class="actions flex gap-2 flex-wrap justify-end mt-4">
        <button class="btn btn-outline touch-target" @click="step = 1">
          {{ t('translation.new_translation') }}
        </button>
        <button class="btn btn-outline touch-target" @click="router.push(`/projects/${projectId}`)">
          {{ t('translation.back_to_project') }}
        </button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import './TranslationView.css'
import { useTranslation } from '../composables/useTranslation'

const {
  t,
  router,
  projectId,
  step,
  targetLanguage,
  chapterMode,
  selectedChapters,
  translating,
  projectTitle,
  languages,
  chapters,
  paragraphs,
  selectedParagraph,
  translationStatus,
  pipelineStages,
  progress,
  progressState,
  overallProgress,
  startTranslate,
  resumeTranslation,
  playOriginal,
} = useTranslation()
</script>

