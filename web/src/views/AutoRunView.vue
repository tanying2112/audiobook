<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '../i18n'
import { Icon } from '@iconify/vue'
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

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const projectId = Number(route.params.projectId)

// State
const loading = ref(false)
const starting = ref(false)
const autopilotStarting = ref(false)
const ttsStatus = ref<TTSStatusResponse | null>(null)
const ttsVoices = ref<TTSVoicesResponse | null>(null)
const autoRunStatus = ref<AutoRunStatusResponse | null>(null)
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
    .filter(e => e.available)
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
  return Math.round((autoRunStatus.value?.progress || 0) * 100)
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

// Load TTS status and voices on mount
onMounted(async () => {
  await loadTTSInfo()
  await loadAutoRunStatus()
  startStatusPolling()
})

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
  router.push(`/projects/${projectId}`)
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

onUnmounted(() => {
  stopStatusPolling()
})
</script>

<template>
  <div class="page-container auto-run-view">
    <!-- Header -->
    <header class="page-header">
      <button class="btn btn-ghost touch-target" @click="goBack">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        <span class="hidden-mobile">{{ t('common.back') }}</span>
      </button>
      <div class="flex-1">
        <h1>{{ t('auto_run.title') }}</h1>
        <p class="page-subtitle">{{ t('auto_run.subtitle') }}</p>
      </div>
    </header>

    <!-- TTS Status Banner -->
    <div v-if="ttsStatus" class="alert alert-info section" style="display: flex; align-items: center; justify-content: space-between; gap: 16px;">
      <div class="flex items-center gap-3">
        <Icon
          :icon="ttsStatus.enable_local_tts_env ? 'mdi:cpu-64-bit' : 'mdi:cloud'"
          width="24"
          height="24"
          class="text-primary"
        />
        <div>
          <p class="font-medium" style="color: var(--color-primary);">
            {{ ttsStatus.enable_local_tts_env ? t('auto_run.local_mode_active') : t('auto_run.cloud_mode_active') }}
          </p>
          <p class="text-sm text-secondary">
            {{ ttsStatus.recommended_engine === 'kokoro'
              ? t('auto_run.using_kokoro')
              : t('auto_run.using_edge_tts') }}
          </p>
        </div>
      </div>
      <span class="badge" :class="ttsStatus.local_engines_available ? 'badge-success' : 'badge-muted'">
        {{ ttsStatus.local_engines_available
          ? t('auto_run.local_engines_available')
          : t('auto_run.local_engines_unavailable') }}
      </span>
    </div>

    <!-- Configuration Form -->
    <div class="card card-hover section">
      <h2 class="card-title">{{ t('auto_run.configuration') }}</h2>

      <div class="grid grid-auto-fill gap-4">
        <div>
          <label class="form-label">{{ t('auto_run.target_difficulty') }}</label>
          <select v-model="config.target_difficulty" class="form-control">
            <option value="A">{{ t('auto_run.difficulty_a') }}</option>
            <option value="B">{{ t('auto_run.difficulty_b') }}</option>
            <option value="C">{{ t('auto_run.difficulty_c') }}</option>
            <option value="D">{{ t('auto_run.difficulty_d') }}</option>
          </select>
        </div>

        <div>
          <label class="form-label">{{ t('auto_run.voice_preference') }}</label>
          <select v-model="config.primary_voice_preference" class="form-control">
            <option value="female">{{ t('auto_run.voice_female') }}</option>
            <option value="male">{{ t('auto_run.voice_male') }}</option>
            <option value="neutral">{{ t('auto_run.voice_neutral') }}</option>
            <option value="local">{{ t('auto_run.voice_local') }}</option>
            <option value="cloud">{{ t('auto_run.voice_cloud') }}</option>
          </select>
        </div>

        <div>
          <label class="form-label">{{ t('auto_run.speech_rate') }}</label>
          <select v-model="config.speech_rate_preference" class="form-control">
            <option value="slow">{{ t('auto_run.rate_slow') }}</option>
            <option value="standard">{{ t('auto_run.rate_standard') }}</option>
            <option value="fast">{{ t('auto_run.rate_fast') }}</option>
          </select>
        </div>

        <div>
          <label class="form-label">{{ t('auto_run.cost_limit') }}</label>
          <input
            type="number"
            v-model.number="config.cost_limit_usd"
            step="0.1"
            min="0"
            placeholder="10.00"
            class="form-control"
          />
        </div>

        <div>
          <label class="form-label">{{ t('auto_run.quality_threshold') }}</label>
          <input
            type="number"
            v-model.number="config.quality_threshold"
            step="0.1"
            min="0"
            max="1"
            class="form-control"
          />
        </div>

        <div>
          <label class="form-label">{{ t('auto_run.max_regen_attempts') }}</label>
          <input
            type="number"
            v-model.number="config.max_regeneration_attempts"
            min="1"
            max="5"
            class="form-control"
          />
        </div>

        <div class="flex items-center gap-2">
          <input
            type="checkbox"
            id="bgm"
            v-model="config.enable_background_music"
            class="h-4 w-4"
            style="accent-color: var(--color-primary);"
          />
          <label for="bgm" class="form-label" style="margin: 0; font-size: 14px;">{{ t('auto_run.enable_bgm') }}</label>
        </div>

        <div class="flex items-center gap-2">
          <input
            type="checkbox"
            id="sfx"
            v-model="config.enable_sfx"
            class="h-4 w-4"
            style="accent-color: var(--color-primary);"
          />
          <label for="sfx" class="form-label" style="margin: 0; font-size: 14px;">{{ t('auto_run.enable_sfx') }}</label>
        </div>
      </div>

      <!-- Engine Selection (Dynamic based on TTS Status) -->
      <div v-if="ttsVoices" class="mt-4 pt-4 border-t" style="border-color: var(--color-border);">
        <h3 class="text-secondary" style="font-size: 14px; font-weight: 500; margin-bottom: 12px;">{{ t('auto_run.engine_selection') }}</h3>

        <div class="grid grid-auto-fill gap-4">
          <!-- Engine Selector -->
          <div>
            <label class="form-label">{{ t('auto_run.select_engine') }}</label>
            <select
              v-model="selectedEngine"
              class="form-control"
              :disabled="loading"
            >
              <option v-for="engine in availableEngines" :key="engine.id" :value="engine.id">
                {{ engine.name }} ({{ engine.voices.length }} {{ t('auto_run.voices') }})
              </option>
              <optgroup :label="t('auto_run.unavailable_engines')">
                <option
                  v-for="engine in Object.values(ttsVoices.engines).filter(e => !e.available)"
                  :key="engine.id"
                  :value="engine.id"
                  disabled
                >
                  {{ engine.name }} - {{ t('auto_run.unavailable') }}
                </option>
              </optgroup>
            </select>
            <p class="text-muted" style="font-size: 12px; margin-top: 4px;">
              {{ t('auto_run.engine_hint', { recommended: ttsStatus?.recommended_engine || 'kokoro' }) }}
            </p>
          </div>

          <!-- Voice Selector -->
          <div>
            <label class="form-label">{{ t('auto_run.select_voice') }}</label>
            <select
              v-model="selectedVoice"
              class="form-control"
              :disabled="loading || availableVoices.length === 0"
            >
              <option v-for="voice in availableVoices" :key="voice.id" :value="voice.id">
                {{ voice.name }} ({{ voice.language }}, {{ voice.gender }})
              </option>
            </select>
            <p class="text-muted" style="font-size: 12px; margin-top: 4px;" v-if="availableVoices.length > 0">
              {{ t('auto_run.voice_hint', { count: availableVoices.length }) }}
            </p>
            <p class="text-muted" style="font-size: 12px; margin-top: 4px;" v-else>
              {{ t('auto_run.no_voices_available') }}
            </p>
          </div>
        </div>

        <!-- Engine Details -->
        <div class="mt-4 p-3 rounded" style="background: var(--color-bg-tertiary);">
          <h4 class="text-secondary" style="font-size: 13px; font-weight: 500; margin-bottom: 12px;">{{ t('auto_run.engine_details') }}</h4>
          <div class="grid gap-4" style="grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); font-size: 13px;">
            <div v-if="ttsStatus">
              <span class="text-muted">{{ t('auto_run.local_tts_env') }}</span>
              <p class="font-medium">{{ ttsStatus.enable_local_tts_env ? t('common.enabled') : t('common.disabled') }}</p>
            </div>
            <div v-if="ttsStatus">
              <span class="text-muted">{{ t('auto_run.kokoro_status') }}</span>
              <p class="font-medium" :class="ttsStatus.kokoro_available ? 'text-success' : 'text-danger'">
                {{ ttsStatus.kokoro_available ? t('common.available') : t('common.unavailable') }}
              </p>
            </div>
            <div v-if="ttsStatus">
              <span class="text-muted">{{ t('auto_run.edge_tts_status') }}</span>
              <p class="font-medium" :class="ttsStatus.edge_tts_available ? 'text-success' : 'text-danger'">
                {{ ttsStatus.edge_tts_available ? t('common.available') : t('common.unavailable') }}
              </p>
            </div>
            <div v-if="ttsStatus">
              <span class="text-muted">{{ t('auto_run.recommended') }}</span>
              <p class="font-medium text-primary">{{ ttsStatus.recommended_engine }} / {{ ttsStatus.recommended_voice }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Status Display -->
    <div class="card card-hover section" v-if="autoRunStatus">
      <div class="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h2 class="card-title">{{ t('auto_run.status') }}</h2>
        <span
          class="badge"
          :class="[
            autoRunStatus.status === 'running' && 'badge-info',
            autoRunStatus.status === 'paused' && 'badge-warning',
            autoRunStatus.status === 'completed' && 'badge-success',
            autoRunStatus.status === 'failed' && 'badge-danger',
            autoRunStatus.status === 'cancelled' && 'badge-muted',
            (autoRunStatus.status === 'not_started' || autoRunStatus.status === 'pending') && 'badge-muted',
          ]"
        >
          {{ t('auto_run.status_' + autoRunStatus.status) }}
        </span>
      </div>

      <!-- Progress Bar -->
      <div class="mb-4">
        <div class="flex justify-between text-sm mb-1">
          <span class="text-secondary">{{ t('auto_run.progress') }}</span>
          <span class="font-medium">{{ progressPercent }}%</span>
        </div>
        <div class="w-full rounded-full h-2" style="background: var(--color-border); overflow: hidden;">
          <div
            class="h-full rounded-full transition-all duration-300"
            :style="{ width: progressPercent + '%' }"
            style="background: var(--color-primary);"
          ></div>
        </div>
      </div>

      <!-- Current Stage -->
      <div v-if="autoRunStatus.current_stage" class="mb-4 p-3 rounded" style="background: var(--color-bg-tertiary);">
        <p class="text-secondary text-sm">{{ t('auto_run.current_stage') }}</p>
        <p class="font-medium">{{ getStageLabel(autoRunStatus.current_stage) }}</p>
      </div>

      <!-- Completed Stages -->
      <div v-if="autoRunStatus.completed_stages && autoRunStatus.completed_stages.length > 0" class="mb-4">
        <p class="text-secondary text-sm mb-2">{{ t('auto_run.completed_stages') }}</p>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="stage in autoRunStatus.completed_stages"
            :key="stage"
            class="badge badge-success"
          >
            {{ getStageLabel(stage) }}
          </span>
        </div>
      </div>

      <!-- Error Message -->
      <div v-if="autoRunStatus.error_message" class="alert alert-error mb-4" style="font-size: 13px;">
        {{ autoRunStatus.error_message }}
      </div>

      <!-- Cost Info -->
      <div v-if="autoRunStatus.cost_usd > 0" class="alert alert-info mb-4" style="font-size: 13px;">
        {{ t('auto_run.current_cost', { cost: autoRunStatus.cost_usd.toFixed(4) }) }}
      </div>
    </div>

    <!-- Action Buttons -->
    <div class="flex gap-2 flex-wrap section" v-if="autoRunStatus">
      <button
        v-if="canStart"
        @click="handleStartAutoRun"
        :disabled="starting"
        class="btn btn-primary btn-lg flex-1 min-w-[140px]"
      >
        <Icon v-if="starting" icon="mdi:loading" width="18" height="18" class="spinner" style="border-color: rgba(255,255,255,.35); border-top-color: #fff" />
        {{ starting ? t('auto_run.starting') : t('auto_run.start') }}
      </button>

      <button
        v-if="canStart"
        @click="handleAutopilotPreview"
        :disabled="starting || autopilotStarting || previewLoading"
        class="btn btn-outline btn-lg"
        :title="t('auto_run.autopilot_tooltip')"
      >
        <Icon v-if="autopilotStarting || previewLoading" icon="mdi:loading" width="18" height="18" class="spinner" style="border-color: var(--color-primary-alpha); border-top-color: var(--color-primary)" />
        <Icon icon="mdi:robot-outline" width="18" height="18" class="gap-2" />
        {{ t('auto_run.autopilot') }}
      </button>

      <button
        v-else-if="autoRunStatus.status === 'running' && autoRunStatus.can_pause"
        @click="handlePause"
        class="btn btn-warning btn-lg"
      >
        <Icon icon="mdi:pause" width="18" height="18" class="gap-2" />
        {{ t('auto_run.pause') }}
      </button>

      <button
        v-else-if="autoRunStatus.status === 'paused' && autoRunStatus.can_resume"
        @click="handleResume"
        class="btn btn-primary btn-lg"
      >
        <Icon icon="mdi:play" width="18" height="18" class="gap-2" />
        {{ t('auto_run.resume') }}
      </button>

      <button
        v-if="autoRunStatus.can_cancel"
        @click="handleCancel"
        class="btn btn-danger btn-lg"
      >
        <Icon icon="mdi:stop" width="18" height="18" class="gap-2" />
        {{ t('auto_run.cancel') }}
      </button>

      <button
        v-if="autoRunStatus.status === 'completed' || autoRunStatus.status === 'failed' || autoRunStatus.status === 'cancelled'"
        @click="loadAutoRunStatus"
        class="btn btn-outline btn-lg"
      >
        <Icon icon="mdi:refresh" width="18" height="18" class="gap-2" />
        {{ t('auto_run.refresh') }}
      </button>
    </div>
  </div>

  <!-- Autopilot Preview Modal -->
  <teleport to="body">
    <div v-if="showAutopilotPreview" class="modal-overlay" @click="showAutopilotPreview = false">
      <div class="modal-content" @click.stop>
        <div class="modal-header">
          <h3 class="modal-title">
            <Icon icon="mdi:robot-outline" width="20" height="20" class="text-primary gap-2" />
            {{ t('auto_run.autopilot_preview_title') }}
          </h3>
          <button class="btn btn-ghost" @click="showAutopilotPreview = false" aria-label="Close">
            <Icon icon="mdi:close" width="20" height="20" />
          </button>
        </div>

        <div class="modal-body p-4 max-h-[70vh] overflow-y-auto">
          <div v-if="previewLoading" class="loading-state">
            <Icon icon="mdi:loading" width="32" height="32" class="spinner" style="border-color: var(--color-primary-alpha); border-top-color: var(--color-primary)" />
            <span>{{ t('auto_run.loading_preview') }}</span>
          </div>

          <template v-else-if="autopilotPreview">
            <div class="space-y-4">
              <div class="alert alert-info">
                <p class="text-sm">{{ autopilotPreview.reasoning }}</p>
              </div>

              <div class="grid grid-auto-fill gap-4">
                <div class="config-item p-3 rounded" style="background: var(--color-bg-tertiary);">
                  <label class="text-muted" style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;">{{ t('auto_run.target_difficulty') }}</label>
                  <p class="font-medium">{{ getDifficultyLabel(autopilotPreview.target_difficulty) }}</p>
                </div>

                <div class="config-item p-3 rounded" style="background: var(--color-bg-tertiary);">
                  <label class="text-muted" style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;">{{ t('auto_run.voice_preference') }}</label>
                  <p class="font-medium capitalize">{{ autopilotPreview.primary_voice_preference }}</p>
                </div>

                <div class="config-item p-3 rounded" style="background: var(--color-bg-tertiary);">
                  <label class="text-muted" style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;">{{ t('auto_run.speech_rate') }}</label>
                  <p class="font-medium capitalize">{{ autopilotPreview.speech_rate_preference }}</p>
                </div>

                <div class="config-item p-3 rounded" style="background: var(--color-bg-tertiary);">
                  <label class="text-muted" style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;">{{ t('auto_run.cost_limit') }}</label>
                  <p class="font-medium">${{ autopilotPreview.cost_limit_usd?.toFixed(2) || '—' }}</p>
                </div>

                <div class="config-item p-3 rounded" style="background: var(--color-bg-tertiary);">
                  <label class="text-muted" style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;">{{ t('auto_run.quality_threshold') }}</label>
                  <p class="font-medium">{{ (autopilotPreview.quality_threshold * 100).toFixed(0) }}%</p>
                </div>

                <div class="config-item p-3 rounded" style="background: var(--color-bg-tertiary);">
                  <label class="text-muted" style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;">{{ t('auto_run.max_regen_attempts') }}</label>
                  <p class="font-medium">{{ autopilotPreview.max_regeneration_attempts }}</p>
                </div>

                <div class="config-item p-3 rounded" style="background: var(--color-bg-tertiary);">
                  <label class="text-muted" style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;">{{ t('auto_run.enable_bgm') }}</label>
                  <p class="font-medium">
                    <span :class="autopilotPreview.enable_background_music ? 'text-success' : 'text-danger'">
                      {{ autopilotPreview.enable_background_music ? t('common.enabled') : t('common.disabled') }}
                    </span>
                  </p>
                </div>

                <div class="config-item p-3 rounded" style="background: var(--color-bg-tertiary);">
                  <label class="text-muted" style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;">{{ t('auto_run.enable_sfx') }}</label>
                  <p class="font-medium">
                    <span :class="autopilotPreview.enable_sfx ? 'text-success' : 'text-danger'">
                      {{ autopilotPreview.enable_sfx ? t('common.enabled') : t('common.disabled') }}
                    </span>
                  </p>
                </div>
              </div>

              <div class="pt-3 border-t" style="border-color: var(--color-border);">
                <p class="text-muted text-xs mb-2">{{ t('auto_run.confidence') }}: <span class="font-medium text-secondary">{{ (autopilotPreview.confidence * 100).toFixed(0) }}%</span></p>
                <div class="w-full rounded-full h-2" style="background: var(--color-border); overflow: hidden;">
                  <div
                    class="h-full rounded-full transition-all duration-300"
                    :style="{ width: (autopilotPreview.confidence * 100) + '%' }"
                    style="background: var(--color-primary);"
                  ></div>
                </div>
              </div>
            </div>
          </template>
        </div>

        <div class="modal-footer flex justify-end gap-2 p-4 border-t" style="border-color: var(--color-border);">
          <button
            class="btn btn-outline"
            @click="showAutopilotPreview = false"
          >
            {{ t('common.cancel') }}
          </button>
          <button
            class="btn btn-primary"
            @click="handleStartAutopilot"
            :disabled="autopilotStarting"
          >
            <Icon v-if="autopilotStarting" icon="mdi:loading" width="18" height="18" class="spinner gap-2" style="border-color: rgba(255,255,255,.35); border-top-color: #fff" />
            <Icon icon="mdi:rocket-launch" width="18" height="18" class="gap-2" />
            {{ t('auto_run.launch_autopilot') }}
          </button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
.auto-run-view {
  max-width: 960px;
}

.page-header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.page-header h1 {
  margin: 0;
  font-size: 22px;
  flex: 1;
}

.page-subtitle {
  margin: 4px 0 0;
  color: var(--color-text-muted);
  font-size: 13px;
}

.section {
  margin-bottom: 20px;
}

.flex { display: flex; }
.flex-1 { flex: 1 1 0%; }
.items-center { align-items: center; }
.justify-between { justify-content: space-between; }
.flex-wrap { flex-wrap: wrap; }
.gap-2 { gap: 8px; }
.gap-4 { gap: 16px; }
.grid { display: grid; }
.grid-auto-fill { grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }

/* Modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  z-index: 1000;
  animation: fadeIn var(--transition) ease-out;
}

.modal-content {
  background: var(--color-card-bg);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xl);
  width: 100%;
  max-width: 640px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  animation: slideUp var(--transition) ease-out;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-border);
}

.modal-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--color-text);
}

.modal-body {
  flex: 1;
  overflow-y: auto;
}

.config-item {
  min-width: 0;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid var(--color-border);
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes slideUp {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Responsive */
@media (max-width: 767px) {
  .modal-content {
    margin: 12px;
    max-height: calc(100vh - 24px);
  }
  .grid-auto-fill {
    grid-template-columns: 1fr;
  }
}
</style>