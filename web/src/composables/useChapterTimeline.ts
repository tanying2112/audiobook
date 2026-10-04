import { ref, onMounted, nextTick, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChapterStore } from '../stores/chapters'
import { useWaveSurfer } from '../composables/useWaveSurfer'
import { usePipelineProgress } from '../composables/usePipelineProgress'
import { useI18n } from '../i18n'
import type { PipelineStage } from '../types/pipeline'
import { normalizeChapterPipeline } from '../utils/normalize'

export function useChapterTimeline() {
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

  return {
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
  }
}
