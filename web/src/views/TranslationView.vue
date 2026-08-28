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
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import { useI18n } from '../i18n'
import { usePipelineProgress } from '../composables/usePipelineProgress'
import {
  startTranslation,
  getTranslationStatus,
  getSupportedLanguages,
  fetchProject,
  fetchChapters,
  fetchParagraphs,
  getAudioUrl,
} from '../api'
import type { TranslationLanguage, TranslationProgress } from '../api'
import type { Chapter, Paragraph } from '../types'
import type { PipelineStage } from '../types/pipeline'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const projectId = Number(route.params.projectId)
const step = ref(1)
const targetLanguage = ref('')
const chapterMode = ref<'all' | 'selected'>('all')
const selectedChapters = ref<number[]>([])
const translating = ref(false)
const projectTitle = ref('')
const languages = ref<TranslationLanguage[]>([])
const chapters = ref<Chapter[]>([])
const paragraphs = ref<Paragraph[]>([])
const selectedParagraph = ref<number | null>(null)
const translationStatus = ref<TranslationProgress>({
  project_id: projectId,
  total_original_segments: 0,
  total_translated_segments: 0,
  translation_ratio: 0,
})

const pipelineStages = [
  { key: 'extract' as PipelineStage, label: t('pipeline.stages.extract') },
  { key: 'analyze' as PipelineStage, label: t('pipeline.stages.analyze') },
  { key: 'annotate' as PipelineStage, label: t('pipeline.stages.annotate') },
  { key: 'edit' as PipelineStage, label: t('pipeline.stages.edit') },
  { key: 'audio_postprocess' as PipelineStage, label: t('pipeline.stages.audio_postprocess') },
  { key: 'synthesize' as PipelineStage, label: t('pipeline.stages.synthesize') },
  { key: 'quality' as PipelineStage, label: t('pipeline.stages.quality') },
]

// Pipeline progress composable
const progress = usePipelineProgress({
  projectId,
  autoConnect: false,
  onChapterComplete: () => {
    refreshStatus()
  },
})

const progressState = computed(() => progress.state.value)

const overallProgress = computed(() => {
  return progress.getOverallProgress() * 100
})

async function refreshStatus() {
  try {
    translationStatus.value = await getTranslationStatus(projectId)
  } catch {
    // ignore
  }
}

async function startTranslate() {
  if (!targetLanguage.value) return

  translating.value = true
  try {
    await startTranslation(projectId, {
      target_language: targetLanguage.value,
      chapter_indices: chapterMode.value === 'selected' ? selectedChapters.value : undefined,
      book_title: projectTitle.value,
    })

    step.value = 2
    progress.connect()
    await refreshStatus()
  } catch (e: any) {
    alert(t('translation.start_failed') + ': ' + (e.response?.data?.detail || e.message))
  } finally {
    translating.value = false
  }
}

function resumeTranslation() {
  // Resume is handled by the pipeline system
  progress.state.value.isPaused = false
}

function playOriginal() {
  if (!selectedParagraph.value) return
  const url = getAudioUrl(selectedParagraph.value)
  const audio = new Audio(url)
  audio.play().catch(() => {
    // ignore play errors
  })
}

onMounted(async () => {
  // Load project info
  try {
    const project = await fetchProject(projectId)
    projectTitle.value = project.title
  } catch {
    // ignore
  }

  // Load languages
  try {
    const result = await getSupportedLanguages()
    languages.value = result.languages
  } catch {
    // Fallback languages
    languages.value = [
      { code: 'en-US', name: 'English (US)', native_name: 'English' },
      { code: 'es-ES', name: 'Spanish (Spain)', native_name: 'Español' },
      { code: 'ja-JP', name: 'Japanese', native_name: '日本語' },
      { code: 'fr-FR', name: 'French (France)', native_name: 'Français' },
      { code: 'de-DE', name: 'German (Germany)', native_name: 'Deutsch' },
      { code: 'ko-KR', name: 'Korean', native_name: '한국어' },
    ]
  }

  // Load chapters
  try {
    chapters.value = await fetchChapters(projectId)
  } catch {
    // ignore
  }

  // Load paragraphs for first chapter
  if (chapters.value.length > 0) {
    try {
      paragraphs.value = await fetchParagraphs(projectId, chapters.value[0].id)
      if (paragraphs.value.length > 0) {
        selectedParagraph.value = paragraphs.value[0].id
      }
    } catch {
      // ignore
    }
  }

  // Check existing translation status
  await refreshStatus()
})
</script>

<style scoped>
/* Uses global responsive utilities from style.css */

/* Form control visual adjustments for this view */
.project-display {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  background: var(--color-card-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  color: var(--color-text);
}

.chapter-range {
  flex-wrap: wrap;
}

.radio-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 400;
  cursor: pointer;
}

.chapter-checkboxes {
  gap: 8px;
  padding: 12px;
  background: var(--color-card-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  max-height: 220px;
  overflow-y: auto;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 400;
  cursor: pointer;
  font-size: 14px;
  min-height: 44px; /* touch-friendly */
}

.progress-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}

.progress-bar-container {
  flex: 1;
  height: 14px;
  background: var(--color-border);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  background: var(--color-primary);
  border-radius: var(--radius-full);
  transition: width 0.3s ease;
}

.progress-text {
  font-weight: 600;
  min-width: 50px;
  text-align: right;
  color: var(--color-text);
}

.stage-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 20px;
}

.stage-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-radius: var(--radius);
  background: var(--color-card-bg);
  border: 1px solid var(--color-border);
  transition: all 0.2s;
  min-height: 44px;
}

.stage-item.completed {
  border-color: var(--color-success);
  background: var(--color-success-soft);
}

.stage-item.active {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
}

.stage-progress {
  margin-left: auto;
  font-size: 13px;
  color: var(--color-primary);
  font-weight: 600;
}

.result-summary {
  gap: 16px;
  margin-bottom: 20px;
}

.stat {
  flex: 1;
  min-width: 140px;
  text-align: center;
  padding: 16px;
  background: var(--color-card-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
}

.stat-value {
  display: block;
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--color-primary);
}

.stat-label {
  display: block;
  font-size: 13px;
  color: var(--color-text-secondary);
  margin-top: 4px;
}

.comparison-section {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--color-border);
}

.comparison-section h3 {
  margin: 0 0 8px;
  font-size: 1rem;
}

.hint {
  color: var(--color-text-secondary);
  font-size: 13px;
  margin: 0 0 16px;
}

.audio-comparison {
  gap: 16px;
}

.audio-card {
  padding: 16px;
  background: var(--color-card-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
}

.audio-card h4 {
  margin: 0 0 12px;
  font-size: 15px;
}

.audio-player {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.actions {
  display: flex;
  gap: 10px;
  margin-top: 20px;
  justify-content: flex-end;
  flex-wrap: wrap;
}
</style>