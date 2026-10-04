import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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

export function useTranslation() {
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

  return {
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
  }
}
