import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '../i18n'
import { usePipelineProgress } from './usePipelineProgress'
import { PIPELINE_STAGE_ORDER, type PipelineStage } from '../types/pipeline'
import {
  fetchTTSStatus,
  fetchTTSVoices,
  startAutoRun,
  getAutoRunStatus,
  pauseAutoRun,
  resumeAutoRun,
  cancelAutoRun,
  startAutopilot,
  previewAutopilotConfig,
  type AutoRunConfig,
  type AutoRunStatusResponse,
  type TTSVoicesResponse,
  type TTSStatusResponse,
  type AutopilotConfig,
} from '../api'

/**
 * AutoRun 视图逻辑（AutoRunView.vue 抽离）。
 * 集中管理流水线自动运行的全部状态、计算属性与异步动作，
 * 视图层只负责渲染与事件绑定。
 */
export function useAutoRun() {
  const route = useRoute()
  const router = useRouter()
  const { t } = useI18n()

  const projectId = Number(route.params.projectId)

  // WebSocket 实时进度
  const pipelineProgress = usePipelineProgress({
    projectId,
    autoConnect: true,
  })

  // State
  const loading = ref(false)
  const starting = ref(false)
  const autopilotStarting = ref(false)
  const ttsStatus = ref<TTSStatusResponse | null>(null)
  const ttsVoices = ref<TTSVoicesResponse | null>(null)
  const autoRunStatus = ref<AutoRunStatusResponse | null>(null)
  // 保留轮询作为 WebSocket 降级/补充，但不再作为主数据源
  let statusPollInterval: ReturnType<typeof setInterval> | null = null

  // Autopilot preview state
  const showAutopilotPreview = ref(false)
  const autopilotPreview = ref<AutopilotConfig | null>(null)
  const previewLoading = ref(false)

  // Form config
  const config = ref<AutoRunConfig>({
    target_difficulty: 'B',
    primary_voice_preference: 'female',
    speech_rate_preference: 'standard',
    cost_limit_usd: null,
    quality_threshold: 0.7,
    max_regeneration_attempts: 3,
    enable_background_music: false,
    enable_sfx: true,
  })

  // Local state for dynamic engine selection
  const selectedEngine = ref<string>('')
  const selectedVoice = ref<string>('')

  // Computed
  const availableEngines = computed(() => {
    if (!ttsVoices.value) return []
    return Object.values(ttsVoices.value.engines)
      .filter((e) => e.available)
      .sort((a, b) => a.priority - b.priority)
  })

  const availableVoices = computed(() => {
    if (!selectedEngine.value || !ttsVoices.value) return []
    const engine = ttsVoices.value.engines[selectedEngine.value]
    return engine?.voices || []
  })

  const canStart = computed(() => {
    return !autoRunStatus.value ||
      autoRunStatus.value.status === 'not_started' ||
      autoRunStatus.value.status === 'completed' ||
      autoRunStatus.value.status === 'failed' ||
      autoRunStatus.value.status === 'cancelled'
  })

  const progressPercent = computed(() => {
    // 优先使用 WebSocket 实时进度
    if (pipelineProgress.state.value.isRunning && pipelineProgress.state.value.currentStage) {
      const wsProgress = pipelineProgress.getOverallProgress()
      return Math.round(wsProgress * 100)
    }
    return Math.round((autoRunStatus.value?.progress || 0) * 100)
  })

  const isPipelineRunning = computed(() => {
    return pipelineProgress.state.value.isRunning || autoRunStatus.value?.status === 'running'
  })

  const isPipelinePaused = computed(() => {
    return pipelineProgress.state.value.isPaused || autoRunStatus.value?.status === 'paused'
  })

  const currentStage = computed(() => {
    return (pipelineProgress.state.value.currentStage || autoRunStatus.value?.current_stage || null) as PipelineStage | null
  })

  const completedStages = computed(() => {
    // 合并 WebSocket 和 REST 状态
    const wsStages = pipelineProgress.state.value.completedStages
    const restStages = (autoRunStatus.value?.completed_stages || []) as PipelineStage[]
    const merged = new Set([...wsStages, ...restStages])
    return Array.from(merged).sort((a, b) =>
      PIPELINE_STAGE_ORDER.indexOf(a) - PIPELINE_STAGE_ORDER.indexOf(b)
    )
  })

  const stageLabels: Record<string, string> = {
    extract: t('pipeline.stages.extract'),
    analyze: t('pipeline.stages.analyze'),
    annotate: t('pipeline.stages.annotate'),
    edit: t('pipeline.stages.edit'),
    audio_postprocess: t('pipeline.stages.audio_postprocess'),
    synthesize: t('pipeline.stages.synthesize'),
    quality: t('pipeline.stages.quality'),
  }

  function startStatusPolling() {
    statusPollInterval = setInterval(async () => {
      if (autoRunStatus.value && (autoRunStatus.value.status === 'running' || autoRunStatus.value.status === 'paused')) {
        await loadAutoRunStatus()
      }
    }, 2000)
  }

  function stopStatusPolling() {
    if (statusPollInterval) {
      clearInterval(statusPollInterval)
      statusPollInterval = null
    }
  }

  async function loadTTSInfo() {
    try {
      loading.value = true
      const [status, voices] = await Promise.all([
        fetchTTSStatus(),
        fetchTTSVoices(true),
      ])
      ttsStatus.value = status
      ttsVoices.value = voices

      if (status.recommended_engine && !selectedEngine.value) {
        selectedEngine.value = status.recommended_engine
      }
      if (status.recommended_voice && !selectedVoice.value) {
        selectedVoice.value = status.recommended_voice
      }
    } catch (error) {
      console.error('Failed to load TTS info:', error)
    } finally {
      loading.value = false
    }
  }

  async function loadAutoRunStatus() {
    try {
      const status = await getAutoRunStatus(projectId)
      autoRunStatus.value = status

      // 同步 WebSocket 状态到 autoRunStatus（用于显示已完成阶段等）
      if (pipelineProgress.state.value.completedStages.length > 0) {
        autoRunStatus.value.completed_stages = completedStages.value
      }
      if (pipelineProgress.state.value.currentStage) {
        autoRunStatus.value.current_stage = pipelineProgress.state.value.currentStage
      }
      autoRunStatus.value.status = pipelineProgress.state.value.isRunning ? 'running' :
        pipelineProgress.state.value.isPaused ? 'paused' :
        status.status
    } catch (error) {
      console.error('Failed to load auto-run status:', error)
    }
  }

  async function handleStartAutoRun() {
    starting.value = true
    try {
      const startConfig = { ...config.value }
      if (selectedEngine.value) {
        if (selectedEngine.value === 'kokoro' || selectedEngine.value === 'voxcpm2') {
          startConfig.primary_voice_preference = 'local'
        } else {
          startConfig.primary_voice_preference = 'cloud'
        }
      }
      await startAutoRun(projectId, startConfig)
      await loadAutoRunStatus()
    } catch (error: any) {
      console.error('Failed to start auto-run:', error)
      alert(t('auto_run.start_failed') + ': ' + (error.response?.data?.detail || error.message))
    } finally {
      starting.value = false
    }
  }

  async function handlePause() {
    try {
      await pauseAutoRun(projectId)
      await loadAutoRunStatus()
    } catch (error: any) {
      alert(t('auto_run.pause_failed') + ': ' + (error.response?.data?.detail || error.message))
    }
  }

  async function handleResume() {
    try {
      await resumeAutoRun(projectId)
      await loadAutoRunStatus()
    } catch (error: any) {
      alert(t('auto_run.resume_failed') + ': ' + (error.response?.data?.detail || error.message))
    }
  }

  async function handleCancel() {
    if (!confirm(t('auto_run.confirm_cancel'))) return
    try {
      await cancelAutoRun(projectId)
      await loadAutoRunStatus()
    } catch (error: any) {
      alert(t('auto_run.cancel_failed') + ': ' + (error.response?.data?.detail || error.message))
    }
  }

  async function handleAutopilotPreview() {
    previewLoading.value = true
    try {
      const preview = await previewAutopilotConfig(projectId)
      autopilotPreview.value = preview
      showAutopilotPreview.value = true
    } catch (error: any) {
      console.error('Failed to preview autopilot config:', error)
      alert(t('auto_run.preview_failed') + ': ' + (error.response?.data?.detail || error.message))
    } finally {
      previewLoading.value = false
    }
  }

  async function handleStartAutopilot() {
    autopilotStarting.value = true
    try {
      await startAutopilot(projectId)
      await loadAutoRunStatus()
      showAutopilotPreview.value = false
    } catch (error: any) {
      console.error('Failed to start autopilot:', error)
      alert(t('auto_run.autopilot_start_failed') + ': ' + (error.response?.data?.detail || error.message))
    } finally {
      autopilotStarting.value = false
    }
  }

  function goBack() {
    router.push('/projects/' + projectId)
  }

  function getStageLabel(stage: string): string {
    return stageLabels[stage] || stage
  }

  function getDifficultyLabel(difficulty: string): string {
    const labels: Record<string, string> = {
      A: t('auto_run.difficulty_a'),
      B: t('auto_run.difficulty_b'),
      C: t('auto_run.difficulty_c'),
      D: t('auto_run.difficulty_d'),
    }
    return labels[difficulty] || difficulty
  }

  // Watch for engine selection changes
  watch(selectedEngine, () => {
    if (ttsVoices.value && ttsVoices.value.engines[selectedEngine.value]) {
      const engine = ttsVoices.value.engines[selectedEngine.value]
      if (engine.voices.length > 0) {
        selectedVoice.value = engine.voices[0].id
      }
    }
  })

  onMounted(async () => {
    await loadTTSInfo()
    await loadAutoRunStatus()
    startStatusPolling()
  })

  onUnmounted(() => {
    stopStatusPolling()
  })

  return {
    loading,
    starting,
    autopilotStarting,
    ttsStatus,
    ttsVoices,
    autoRunStatus,
    showAutopilotPreview,
    autopilotPreview,
    previewLoading,
    config,
    selectedEngine,
    selectedVoice,
    availableEngines,
    availableVoices,
    canStart,
    progressPercent,
    // WebSocket 实时状态
    isPipelineRunning,
    isPipelinePaused,
    currentStage,
    completedStages,
    pipelineProgress: pipelineProgress.state,
    handleStartAutoRun,
    handlePause,
    handleResume,
    handleCancel,
    handleAutopilotPreview,
    handleStartAutopilot,
    loadAutoRunStatus,
    goBack,
    getStageLabel,
    getDifficultyLabel,
  }
}