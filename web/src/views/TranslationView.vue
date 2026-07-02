<template>
  <div class="translation-view">
    <div class="header">
      <button class="btn btn-ghost" @click="router.back()">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        {{ t('common.back') }}
      </button>
      <h1>{{ t('translation.title') }}</h1>
      <p class="subtitle">{{ t('translation.subtitle') }}</p>
    </div>

    <!-- Step 1: Configure -->
    <section class="card" v-if="step === 1">
      <h2>{{ t('translation.config_title') }}</h2>

      <div class="form-group">
        <label>{{ t('translation.project_label') }}</label>
        <div class="project-display">
          <Icon icon="mdi:book-open-variant" width="20" height="20" />
          <span>{{ projectTitle || t('translation.loading_project') }}</span>
        </div>
      </div>

      <div class="form-group">
        <label>{{ t('translation.target_language_label') }}</label>
        <select v-model="targetLanguage" class="select">
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
        <label>{{ t('translation.chapter_range_label') }}</label>
        <div class="chapter-range">
          <label class="radio-label">
            <input type="radio" v-model="chapterMode" value="all" />
            {{ t('translation.all_chapters') }}
          </label>
          <label class="radio-label">
            <input type="radio" v-model="chapterMode" value="selected" />
            {{ t('translation.selected_chapters') }}
          </label>
        </div>
        <div v-if="chapterMode === 'selected'" class="chapter-checkboxes">
          <label
            v-for="ch in chapters"
            :key="ch.id"
            class="checkbox-label"
          >
            <input
              type="checkbox"
              :value="ch.chapter_number || ch.id"
              v-model="selectedChapters"
            />
            {{ ch.title || t('project_detail.chapter_fallback', { number: ch.chapter_number || ch.id }) }}
          </label>
        </div>
      </div>

      <div class="actions">
        <button
          class="btn primary"
          @click="startTranslate"
          :disabled="!targetLanguage || translating"
        >
          {{ translating ? t('translation.starting') : t('translation.start_btn') }}
        </button>
      </div>
    </section>

    <!-- Step 2: Progress -->
    <section class="card" v-if="step === 2">
      <h2>{{ t('translation.progress_title') }}</h2>

      <div class="progress-header">
        <div class="progress-bar-container">
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

      <div v-if="progressState.error" class="error-box">
        <Icon icon="mdi:alert-circle" width="20" height="20" />
        <span>{{ progressState.error }}</span>
      </div>

      <div class="actions">
        <button
          v-if="!progressState.isRunning"
          class="btn primary"
          @click="step = 3"
        >
          {{ t('translation.view_results') }}
        </button>
        <button
          v-if="progressState.isPaused"
          class="btn secondary"
          @click="resumeTranslation"
        >
          {{ t('translation.resume') }}
        </button>
      </div>
    </section>

    <!-- Step 3: Results -->
    <section class="card" v-if="step === 3">
      <h2>{{ t('translation.results_title') }}</h2>

      <div class="result-summary">
        <div class="stat">
          <span class="stat-value">{{ translationStatus.total_original_segments }}</span>
          <span class="stat-label">{{ t('translation.original_segments') }}</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ translationStatus.total_translated_segments }}</span>
          <span class="stat-label">{{ t('translation.translated_segments') }}</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ Math.round(translationStatus.translation_ratio * 100) }}%</span>
          <span class="stat-label">{{ t('translation.coverage') }}</span>
        </div>
      </div>

      <div class="comparison-section">
        <h3>{{ t('translation.comparison_title') }}</h3>
        <p class="hint">{{ t('translation.comparison_hint') }}</p>

        <div class="audio-comparison">
          <div class="audio-card">
            <h4>{{ t('translation.original_audio') }}</h4>
            <div class="audio-player">
              <select v-model="selectedParagraph" class="select small">
                <option v-for="p in paragraphs" :key="p.id" :value="p.id">
                  {{ t('translation.paragraph') }} {{ p.index }}
                </option>
              </select>
              <button class="btn small" @click="playOriginal" :disabled="!selectedParagraph">
                <Icon icon="mdi:play" width="16" height="16" />
                {{ t('translation.play') }}
              </button>
            </div>
          </div>

          <div class="audio-card">
            <h4>{{ t('translation.translated_audio') }}</h4>
            <div class="audio-player">
              <p class="hint">{{ t('translation.translated_hint') }}</p>
            </div>
          </div>
        </div>
      </div>

      <div class="actions">
        <button class="btn secondary" @click="step = 1">
          {{ t('translation.new_translation') }}
        </button>
        <button class="btn secondary" @click="router.push(`/projects/${projectId}`)">
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
.translation-view {
  max-width: 800px;
  margin: 0 auto;
  padding: 2rem;
}
.header {
  margin-bottom: 2rem;
}
.header h1 {
  font-size: 1.8rem;
  margin: 0.5rem 0 0;
}
.subtitle {
  color: var(--color-text-secondary, #888);
  margin: 0.5rem 0 0;
}
.card {
  background: var(--color-bg-secondary, #f9f9f9);
  border: 1px solid var(--color-border, #e0e0e0);
  border-radius: 12px;
  padding: 1.5rem;
  margin-bottom: 1.5rem;
}
.card h2 {
  margin: 0 0 1rem;
  font-size: 1.2rem;
}
.form-group {
  margin-bottom: 1.25rem;
}
.form-group label {
  display: block;
  font-weight: 500;
  margin-bottom: 0.5rem;
}
.select {
  width: 100%;
  padding: 0.6rem 0.8rem;
  border: 1px solid var(--color-border, #ccc);
  border-radius: 8px;
  font-size: 0.95rem;
  background: var(--color-bg-primary, #fff);
}
.select.small {
  width: auto;
  min-width: 200px;
}
.project-display {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 0.8rem;
  background: var(--color-bg-primary, #fff);
  border: 1px solid var(--color-border, #e0e0e0);
  border-radius: 8px;
  color: var(--color-text-primary, #333);
}
.chapter-range {
  display: flex;
  gap: 1.5rem;
  margin-bottom: 0.75rem;
}
.radio-label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-weight: 400;
  cursor: pointer;
}
.chapter-checkboxes {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.5rem;
  padding: 0.75rem;
  background: var(--color-bg-primary, #fff);
  border: 1px solid var(--color-border, #e0e0e0);
  border-radius: 8px;
  max-height: 200px;
  overflow-y: auto;
}
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-weight: 400;
  cursor: pointer;
  font-size: 0.9rem;
}
.progress-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.5rem;
}
.progress-bar-container {
  flex: 1;
  height: 12px;
  background: var(--color-border, #e0e0e0);
  border-radius: 6px;
  overflow: hidden;
}
.progress-bar {
  height: 100%;
  background: var(--color-primary, #4a90d9);
  border-radius: 6px;
  transition: width 0.3s ease;
}
.progress-text {
  font-weight: 600;
  min-width: 48px;
  text-align: right;
}
.stage-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
}
.stage-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.5rem 0.75rem;
  border-radius: 8px;
  background: var(--color-bg-primary, #fff);
  border: 1px solid var(--color-border, #e0e0e0);
  transition: all 0.2s;
}
.stage-item.completed {
  border-color: #28a745;
  background: #f0fff4;
}
.stage-item.active {
  border-color: var(--color-primary, #4a90d9);
  background: #f0f7ff;
}
.stage-progress {
  margin-left: auto;
  font-size: 0.85rem;
  color: var(--color-primary, #4a90d9);
  font-weight: 600;
}
.error-box {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background: #fff5f5;
  border: 1px solid #e53e3e;
  border-radius: 8px;
  color: #e53e3e;
  margin-bottom: 1rem;
}
.result-summary {
  display: flex;
  gap: 1.5rem;
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
}
.stat {
  flex: 1;
  min-width: 120px;
  text-align: center;
  padding: 1rem;
  background: var(--color-bg-primary, #fff);
  border: 1px solid var(--color-border, #e0e0e0);
  border-radius: 8px;
}
.stat-value {
  display: block;
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--color-primary, #4a90d9);
}
.stat-label {
  display: block;
  font-size: 0.85rem;
  color: var(--color-text-secondary, #888);
  margin-top: 0.25rem;
}
.comparison-section {
  margin-top: 1.5rem;
  padding-top: 1.5rem;
  border-top: 1px solid var(--color-border, #e0e0e0);
}
.comparison-section h3 {
  margin: 0 0 0.5rem;
  font-size: 1rem;
}
.hint {
  color: var(--color-text-secondary, #888);
  font-size: 0.85rem;
  margin: 0 0 1rem;
}
.audio-comparison {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}
.audio-card {
  padding: 1rem;
  background: var(--color-bg-primary, #fff);
  border: 1px solid var(--color-border, #e0e0e0);
  border-radius: 8px;
}
.audio-card h4 {
  margin: 0 0 0.75rem;
  font-size: 0.95rem;
}
.audio-player {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 1.5rem;
  justify-content: flex-end;
  flex-wrap: wrap;
}
.btn {
  padding: 0.6rem 1.2rem;
  border: none;
  border-radius: 8px;
  font-size: 0.95rem;
  cursor: pointer;
  transition: opacity 0.2s, background 0.2s;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn.primary {
  background: var(--color-primary, #4a90d9);
  color: white;
}
.btn.primary:hover:not(:disabled) {
  filter: brightness(1.1);
}
.btn.secondary {
  background: var(--color-bg-secondary, #eee);
  color: var(--color-text-primary, #333);
}
.btn.secondary:hover:not(:disabled) {
  background: var(--color-border, #ddd);
}
.btn.ghost {
  background: transparent;
  color: var(--color-text-secondary, #888);
  padding: 0.4rem 0.6rem;
}
.btn.ghost:hover {
  color: var(--color-text-primary, #333);
  background: var(--color-bg-secondary, #f5f5f5);
}
.btn.small {
  padding: 0.4rem 0.8rem;
  font-size: 0.85rem;
}

@media (max-width: 640px) {
  .audio-comparison {
    grid-template-columns: 1fr;
  }
  .result-summary {
    flex-direction: column;
  }
}
</style>
