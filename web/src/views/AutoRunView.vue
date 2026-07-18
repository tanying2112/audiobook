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
  return !autoRunStatus.value || autoRunStatus.value.status === 'not_started' || autoRunStatus.value.status === 'completed' || autoRunStatus.value.status === 'failed' || autoRunStatus.value.status === 'cancelled'
})

const progressPercent = computed(() => {
  return Math.round((autoRunStatus.value?.progress || 0) * 100)
})

const stageLabels: Record<string, string> = {
  extract: '文本提取',
  analyze: '结构分析',
  annotate: '段落标注',
  edit: 'TTS 编辑',
  audio_postprocess: '声学后处理',
  synthesize: '语音合成',
  quality: '质量检测',
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
      fetchTTSVoices(true), // include unavailable for admin view
    ])
    ttsStatus.value = status
    ttsVoices.value = voices

    // Auto-select recommended engine/voice
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
    // Update config with selected engine/voice if provided
    const startConfig = { ...config.value }
    if (selectedEngine.value) {
      // Map engine ID to preference
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
  // Reset voice selection when engine changes
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
  <div class="auto-run-view max-w-4xl mx-auto p-6">
    <!-- Header -->
    <div class="page-header mb-8">
      <button class="btn btn-ghost mb-4" @click="goBack">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        {{ t('common.back') }}
      </button>
      <h1 class="text-2xl font-semibold text-gray-800">{{ t('auto_run.title') }}</h1>
      <p class="text-gray-500 mt-1">{{ t('auto_run.subtitle') }}</p>
    </div>

    <!-- TTS Status Banner -->
    <div v-if="ttsStatus" class="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <Icon
            :icon="ttsStatus.enable_local_tts_env ? 'mdi:cpu-64-bit' : 'mdi:cloud'"
            width="24"
            height="24"
            class="text-blue-600"
          />
          <div>
            <p class="font-medium text-blue-800">
              {{ ttsStatus.enable_local_tts_env ? t('auto_run.local_mode_active') : t('auto_run.cloud_mode_active') }}
            </p>
            <p class="text-sm text-blue-600">
              {{ ttsStatus.recommended_engine === 'kokoro'
                ? t('auto_run.using_kokoro')
                : t('auto_run.using_edge_tts') }}
            </p>
          </div>
        </div>
        <span class="px-3 py-1 text-xs font-medium rounded-full"
          :class="ttsStatus.local_engines_available ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'">
          {{ ttsStatus.local_engines_available
            ? t('auto_run.local_engines_available')
            : t('auto_run.local_engines_unavailable') }}
        </span>
      </div>
    </div>

    <!-- Configuration Form -->
    <div class="card bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-6">
      <h2 class="text-lg font-semibold text-gray-800 mb-4">{{ t('auto_run.configuration') }}</h2>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <!-- Target Difficulty -->
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">{{ t('auto_run.target_difficulty') }}</label>
          <select v-model="config.target_difficulty" class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500">
            <option value="A">{{ t('auto_run.difficulty_a') }}</option>
            <option value="B">{{ t('auto_run.difficulty_b') }}</option>
            <option value="C">{{ t('auto_run.difficulty_c') }}</option>
            <option value="D">{{ t('auto_run.difficulty_d') }}</option>
          </select>
        </div>

        <!-- Voice Preference -->
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">{{ t('auto_run.voice_preference') }}</label>
          <select v-model="config.primary_voice_preference" class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500">
            <option value="female">{{ t('auto_run.voice_female') }}</option>
            <option value="male">{{ t('auto_run.voice_male') }}</option>
            <option value="neutral">{{ t('auto_run.voice_neutral') }}</option>
            <option value="local">{{ t('auto_run.voice_local') }}</option>
            <option value="cloud">{{ t('auto_run.voice_cloud') }}</option>
          </select>
        </div>

        <!-- Speech Rate -->
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">{{ t('auto_run.speech_rate') }}</label>
          <select v-model="config.speech_rate_preference" class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500">
            <option value="slow">{{ t('auto_run.rate_slow') }}</option>
            <option value="standard">{{ t('auto_run.rate_standard') }}</option>
            <option value="fast">{{ t('auto_run.rate_fast') }}</option>
          </select>
        </div>

        <!-- Cost Limit -->
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">{{ t('auto_run.cost_limit') }}</label>
          <input
            type="number"
            v-model.number="config.cost_limit_usd"
            step="0.1"
            min="0"
            placeholder="10.00"
            class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>

        <!-- Quality Threshold -->
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">{{ t('auto_run.quality_threshold') }}</label>
          <input
            type="number"
            v-model.number="config.quality_threshold"
            step="0.1"
            min="0"
            max="1"
            class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>

        <!-- Max Regeneration Attempts -->
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">{{ t('auto_run.max_regen_attempts') }}</label>
          <input
            type="number"
            v-model.number="config.max_regeneration_attempts"
            min="1"
            max="5"
            class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>

        <!-- Enable Background Music -->
        <div class="flex items-center">
          <input
            type="checkbox"
            id="bgm"
            v-model="config.enable_background_music"
            class="h-4 w-4 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500"
          />
          <label for="bgm" class="ml-2 text-sm text-gray-700">{{ t('auto_run.enable_bgm') }}</label>
        </div>

        <!-- Enable SFX -->
        <div class="flex items-center">
          <input
            type="checkbox"
            id="sfx"
            v-model="config.enable_sfx"
            class="h-4 w-4 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500"
          />
          <label for="sfx" class="ml-2 text-sm text-gray-700">{{ t('auto_run.enable_sfx') }}</label>
        </div>
      </div>

      <!-- Engine Selection (Dynamic based on TTS Status) -->
      <div v-if="ttsVoices" class="mt-6 pt-6 border-t border-gray-200">
        <h3 class="text-md font-medium text-gray-800 mb-3">{{ t('auto_run.engine_selection') }}</h3>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <!-- Engine Selector -->
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">{{ t('auto_run.select_engine') }}</label>
            <select
              v-model="selectedEngine"
              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              :disabled="loading"
            >
              <option v-for="engine in availableEngines" :key="engine.id" :value="engine.id">
                {{ engine.name }} ({{ engine.voices.length }} {{ t('auto_run.voices') }})
              </option>
              <!-- Show unavailable engines when include_unavailable -->
              <optgroup v-if="ttsVoices" :label="t('auto_run.unavailable_engines')">
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
            <p class="mt-1 text-xs text-gray-500">
              {{ t('auto_run.engine_hint', { recommended: ttsStatus?.recommended_engine || 'kokoro' }) }}
            </p>
          </div>

          <!-- Voice Selector -->
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">{{ t('auto_run.select_voice') }}</label>
            <select
              v-model="selectedVoice"
              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              :disabled="loading || availableVoices.length === 0"
            >
              <option v-for="voice in availableVoices" :key="voice.id" :value="voice.id">
                {{ voice.name }} ({{ voice.language }}, {{ voice.gender }})
              </option>
            </select>
            <p class="mt-1 text-xs text-gray-500" v-if="availableVoices.length > 0">
              {{ t('auto_run.voice_hint', { count: availableVoices.length }) }}
            </p>
            <p class="mt-1 text-xs text-gray-400" v-else>
              {{ t('auto_run.no_voices_available') }}
            </p>
          </div>
        </div>

        <!-- Engine Details -->
        <div class="mt-4 p-3 bg-gray-50 rounded-lg">
          <h4 class="text-sm font-medium text-gray-700 mb-2">{{ t('auto_run.engine_details') }}</h4>
          <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div v-if="ttsStatus">
              <span class="text-gray-500">{{ t('auto_run.local_tts_env') }}</span>
              <p class="font-medium">{{ ttsStatus.enable_local_tts_env ? t('common.enabled') : t('common.disabled') }}</p>
            </div>
            <div v-if="ttsStatus">
              <span class="text-gray-500">{{ t('auto_run.kokoro_status') }}</span>
              <p class="font-medium" :class="ttsStatus.kokoro_available ? 'text-green-600' : 'text-red-600'">
                {{ ttsStatus.kokoro_available ? t('common.available') : t('common.unavailable') }}
              </p>
            </div>
            <div v-if="ttsStatus">
              <span class="text-gray-500">{{ t('auto_run.edge_tts_status') }}</span>
              <p class="font-medium" :class="ttsStatus.edge_tts_available ? 'text-green-600' : 'text-red-600'">
                {{ ttsStatus.edge_tts_available ? t('common.available') : t('common.unavailable') }}
              </p>
            </div>
            <div v-if="ttsStatus">
              <span class="text-gray-500">{{ t('auto_run.recommended') }}</span>
              <p class="font-medium text-indigo-600">{{ ttsStatus.recommended_engine }} / {{ ttsStatus.recommended_voice }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Status Display -->
    <div class="card bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-6" v-if="autoRunStatus">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-semibold text-gray-800">{{ t('auto_run.status') }}</h2>
        <span
          class="px-3 py-1 text-sm font-medium rounded-full"
          :class="[
            autoRunStatus.status === 'running' && 'bg-blue-100 text-blue-800',
            autoRunStatus.status === 'paused' && 'bg-yellow-100 text-yellow-800',
            autoRunStatus.status === 'completed' && 'bg-green-100 text-green-800',
            autoRunStatus.status === 'failed' && 'bg-red-100 text-red-800',
            autoRunStatus.status === 'cancelled' && 'bg-gray-100 text-gray-600',
            autoRunStatus.status === 'not_started' && 'bg-gray-100 text-gray-500',
            autoRunStatus.status === 'pending' && 'bg-gray-100 text-gray-500',
          ]"
        >
          {{ t('auto_run.status_' + autoRunStatus.status) }}
        </span>
      </div>

      <!-- Progress Bar -->
      <div class="mb-4">
        <div class="flex justify-between text-sm mb-1">
          <span>{{ t('auto_run.progress') }}</span>
          <span>{{ progressPercent }}%</span>
        </div>
        <div class="w-full bg-gray-200 rounded-full h-2">
          <div
            class="bg-indigo-600 h-2 rounded-full transition-all duration-300"
            :style="{ width: progressPercent + '%' }"
          ></div>
        </div>
      </div>

      <!-- Current Stage -->
      <div v-if="autoRunStatus.current_stage" class="mb-4 p-3 bg-gray-50 rounded-lg">
        <p class="text-sm text-gray-600">{{ t('auto_run.current_stage') }}</p>
        <p class="font-medium text-gray-800">{{ getStageLabel(autoRunStatus.current_stage) }}</p>
      </div>

      <!-- Completed Stages -->
      <div v-if="autoRunStatus.completed_stages && autoRunStatus.completed_stages.length > 0" class="mb-4">
        <p class="text-sm text-gray-600 mb-2">{{ t('auto_run.completed_stages') }}</p>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="stage in autoRunStatus.completed_stages"
            :key="stage"
            class="px-2 py-1 text-xs font-medium bg-green-100 text-green-800 rounded"
          >
            {{ getStageLabel(stage) }}
          </span>
        </div>
      </div>

      <!-- Error Message -->
      <div v-if="autoRunStatus.error_message" class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
        {{ autoRunStatus.error_message }}
      </div>

      <!-- Cost Info -->
      <div v-if="autoRunStatus.cost_usd > 0" class="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
        <p class="text-sm text-blue-700">{{ t('auto_run.current_cost', { cost: autoRunStatus.cost_usd.toFixed(4) }) }}</p>
      </div>
    </div>

    <!-- Action Buttons -->
    <div class="flex gap-3" v-if="autoRunStatus">
      <button
        v-if="canStart"
        @click="handleStartAutoRun"
        :disabled="starting"
        class="btn btn-primary flex-1"
      >
        <Icon v-if="starting" icon="mdi:loading" width="18" height="18" class="animate-spin mr-2" />
        {{ starting ? t('auto_run.starting') : t('auto_run.start') }}
      </button>

      <button
        v-if="canStart"
        @click="handleAutopilotPreview"
        :disabled="starting || autopilotStarting || previewLoading"
        class="btn btn-accent"
        :title="t('auto_run.autopilot_tooltip')"
      >
        <Icon v-if="autopilotStarting || previewLoading" icon="mdi:loading" width="18" height="18" class="animate-spin mr-2" />
        <Icon icon="mdi:robot-outline" width="18" height="18" class="mr-2" />
        {{ t('auto_run.autopilot') }}
      </button>

      <button
        v-else-if="autoRunStatus.status === 'running' && autoRunStatus.can_pause"
        @click="handlePause"
        class="btn btn-warning"
      >
        <Icon icon="mdi:pause" width="18" height="18" class="mr-2" />
        {{ t('auto_run.pause') }}
      </button>

      <button
        v-else-if="autoRunStatus.status === 'paused' && autoRunStatus.can_resume"
        @click="handleResume"
        class="btn btn-primary"
      >
        <Icon icon="mdi:play" width="18" height="18" class="mr-2" />
        {{ t('auto_run.resume') }}
      </button>

      <button
        v-if="autoRunStatus.can_cancel"
        @click="handleCancel"
        class="btn btn-danger"
      >
        <Icon icon="mdi:stop" width="18" height="18" class="mr-2" />
        {{ t('auto_run.cancel') }}
      </button>

      <button
        v-if="autoRunStatus.status === 'completed' || autoRunStatus.status === 'failed' || autoRunStatus.status === 'cancelled'"
        @click="loadAutoRunStatus"
        class="btn btn-outline"
      >
        <Icon icon="mdi:refresh" width="18" height="18" class="mr-2" />
        {{ t('auto_run.refresh') }}
      </button>
    </div>
  </div>

  <!-- Autopilot Preview Modal -->
  <teleport to="body">
    <div v-if="showAutopilotPreview" class="modal-overlay" @click="showAutopilotPreview = false">
      <div class="modal-content" @click.stop>
          <div class="modal-header">
            <h3 class="text-lg font-semibold text-gray-800">
              <Icon icon="mdi:robot-outline" width="20" height="20" class="mr-2 text-indigo-600" />
              {{ t('auto_run.autopilot_preview_title') }}
            </h3>
            <button class="btn btn-ghost text-gray-400 hover:text-gray-600" @click="showAutopilotPreview = false">
              <Icon icon="mdi:close" width="20" height="20" />
            </button>
          </div>

          <div class="modal-body p-6 max-h-[70vh] overflow-y-auto">
            <div v-if="previewLoading" class="flex items-center justify-center py-12">
              <Icon icon="mdi:loading" width="32" height="32" class="animate-spin text-indigo-600 mr-3" />
              <span class="text-gray-600">{{ t('auto_run.loading_preview') }}</span>
            </div>

            <template v-else-if="autopilotPreview">
              <div class="space-y-4">
                <div class="p-4 bg-indigo-50 border border-indigo-200 rounded-lg">
                  <p class="text-sm text-indigo-800">{{ autopilotPreview.reasoning }}</p>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div class="config-item">
                    <label class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">
                      {{ t('auto_run.target_difficulty') }}
                    </label>
                    <p class="font-medium text-gray-800">{{ getDifficultyLabel(autopilotPreview.target_difficulty) }}</p>
                  </div>

                  <div class="config-item">
                    <label class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">
                      {{ t('auto_run.voice_preference') }}
                    </label>
                    <p class="font-medium text-gray-800 capitalize">{{ autopilotPreview.primary_voice_preference }}</p>
                  </div>

                  <div class="config-item">
                    <label class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">
                      {{ t('auto_run.speech_rate') }}
                    </label>
                    <p class="font-medium text-gray-800 capitalize">{{ autopilotPreview.speech_rate_preference }}</p>
                  </div>

                  <div class="config-item">
                    <label class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">
                      {{ t('auto_run.cost_limit') }}
                    </label>
                    <p class="font-medium text-gray-800">${{ autopilotPreview.cost_limit_usd?.toFixed(2) || '—' }}</p>
                  </div>

                  <div class="config-item">
                    <label class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">
                      {{ t('auto_run.quality_threshold') }}
                    </label>
                    <p class="font-medium text-gray-800">{{ (autopilotPreview.quality_threshold * 100).toFixed(0) }}%</p>
                  </div>

                  <div class="config-item">
                    <label class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">
                      {{ t('auto_run.max_regen_attempts') }}
                    </label>
                    <p class="font-medium text-gray-800">{{ autopilotPreview.max_regeneration_attempts }}</p>
                  </div>

                  <div class="config-item">
                    <label class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">
                      {{ t('auto_run.enable_bgm') }}
                    </label>
                    <p class="font-medium text-gray-800">
                      <span :class="autopilotPreview.enable_background_music ? 'text-green-600' : 'text-red-600'">
                        {{ autopilotPreview.enable_background_music ? t('common.enabled') : t('common.disabled') }}
                      </span>
                    </p>
                  </div>

                  <div class="config-item">
                    <label class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">
                      {{ t('auto_run.enable_sfx') }}
                    </label>
                    <p class="font-medium text-gray-800">
                      <span :class="autopilotPreview.enable_sfx ? 'text-green-600' : 'text-red-600'">
                        {{ autopilotPreview.enable_sfx ? t('common.enabled') : t('common.disabled') }}
                      </span>
                    </p>
                  </div>
                </div>

                <div class="pt-4 border-t border-gray-200">
                  <p class="text-xs text-gray-500 mb-2">{{ t('auto_run.confidence') }}: <span class="font-medium text-gray-700">{{ (autopilotPreview.confidence * 100).toFixed(0) }}%</span></p>
                  <div class="w-full bg-gray-200 rounded-full h-2">
                    <div
                      class="bg-indigo-600 h-2 rounded-full transition-all duration-300"
                      :style="{ width: (autopilotPreview.confidence * 100) + '%' }"
                    ></div>
                  </div>
                </div>
              </div>
            </template>
          </div>

          <div class="modal-footer p-4 border-t border-gray-200 flex justify-end gap-3">
            <button
              class="btn btn-outline"
              @click="showAutopilotPreview = false"
            >
              {{ t('common.cancel') }}
            </button>
            <button
              class="btn btn-accent"
              @click="handleStartAutopilot"
              :disabled="autopilotStarting"
            >
              <Icon v-if="autopilotStarting" icon="mdi:loading" width="18" height="18" class="animate-spin mr-2" />
              <Icon icon="mdi:rocket-launch" width="18" height="18" class="mr-2" />
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

.card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.page-header h1 {
  margin: 0;
  font-size: 22px;
  flex: 1;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 20px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: all 0.15s;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: #4f46e5;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #4338ca;
}

.btn-warning {
  background: #f59e0b;
  color: white;
}

.btn-warning:hover:not(:disabled) {
  background: #d97706;
}

.btn-danger {
  background: #ef4444;
  color: white;
}

.btn-danger:hover:not(:disabled) {
  background: #dc2626;
}

.btn-outline {
  background: white;
  color: #4f46e5;
  border: 1px solid #4f46e5;
}

.btn-outline:hover:not(:disabled) {
  background: #eef2ff;
}

.btn-ghost {
  background: transparent;
  color: #64748b;
  padding: 8px 12px;
}

.btn-ghost:hover {
  background: #f1f5f9;
}

.select, .input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.select:focus, .input:focus {
  outline: none;
  border-color: #4f46e5;
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
}

.select:disabled, .input:disabled {
  background: #f9fafb;
  color: #9ca3af;
  cursor: not-allowed;
}

label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  margin-bottom: 6px;
}

h2, h3, h4 {
  margin: 0;
}

.text-sm { font-size: 14px; }
.text-xs { font-size: 12px; }
.text-gray-400 { color: #9ca3af; }
.text-gray-500 { color: #6b7280; }
.text-gray-600 { color: #4b5563; }
.text-gray-700 { color: #374151; }
.text-gray-800 { color: #1f2937; }
.text-blue-600 { color: #2563eb; }
.text-blue-800 { color: #1e40af; }
.text-green-600 { color: #16a34a; }
.text-green-800 { color: #166534; }
.text-yellow-800 { color: #854d0e; }
.text-red-600 { color: #dc2626; }
.text-red-700 { color: #b91c1c; }
.text-indigo-600 { color: #4f46e5; }

.bg-blue-50 { background-color: #eff6ff; }
.bg-blue-100 { background-color: #dbeafe; }
.bg-blue-200 { background-color: #bfdbfe; }
.bg-green-100 { background-color: #dcfce7; }
.bg-green-200 { background-color: #bbf7d0; }
.bg-yellow-100 { background-color: #fef9c3; }
.bg-red-50 { background-color: #fef2f2; }
.bg-red-100 { background-color: #fee2e2; }
.bg-red-200 { background-color: #fecaca; }
.bg-gray-50 { background-color: #f9fafb; }
.bg-gray-100 { background-color: #f3f4f6; }
.bg-gray-200 { background-color: #e5e7eb; }

.border { border-width: 1px; }
.border-blue-200 { border-color: #bfdbfe; }
.border-gray-200 { border-color: #e5e7eb; }
.border-gray-300 { border-color: #d1d5db; }

.rounded { border-radius: 0.375rem; }
.rounded-lg { border-radius: 0.5rem; }
.rounded-full { border-radius: 9999px; }

.p-3 { padding: 0.75rem; }
.p-4 { padding: 1rem; }
.p-6 { padding: 1.5rem; }
.px-2 { padding-left: 0.5rem; padding-right: 0.5rem; }
.px-3 { padding-left: 0.75rem; padding-right: 0.75rem; }
.py-1 { padding-top: 0.25rem; padding-bottom: 0.25rem; }
.py-2 { padding-top: 0.5rem; padding-bottom: 0.5rem; }
.mb-1 { margin-bottom: 0.25rem; }
.mb-2 { margin-bottom: 0.5rem; }
.mb-3 { margin-bottom: 0.75rem; }
.mb-4 { margin-bottom: 1rem; }
.mb-6 { margin-bottom: 1.5rem; }
.mb-8 { margin-bottom: 2rem; }
.mt-1 { margin-top: 0.25rem; }
.mt-2 { margin-top: 0.5rem; }
.mt-3 { margin-top: 0.75rem; }
.mt-4 { margin-top: 1rem; }
.ml-2 { margin-left: 0.5rem; }
.mr-2 { margin-right: 0.5rem; }
.gap-2 { gap: 0.5rem; }
.gap-3 { gap: 0.75rem; }
.gap-4 { gap: 1rem; }
.gap-6 { gap: 1.5rem; }
.flex { display: flex; }
.flex-1 { flex: 1 1 0%; }
.items-center { align-items: center; }
.justify-between { justify-content: space-between; }
.flex-wrap { flex-wrap: wrap; }
.grid { display: grid; }
.grid-cols-1 { grid-template-columns: repeat(1, minmax(0, 1fr)); }
.grid-cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.grid-cols-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }

@media (min-width: 768px) {
  .md\\:grid-cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .md\\:grid-cols-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}

.w-full { width: 100%; }
.h-2 { height: 0.5rem; }
.h-4 { height: 1rem; }
.w-4 { width: 1rem; }

.transition-all { transition-property: all; transition-timing-function: cubic-bezier(0.4, 0, 0.2, 1); transition-duration: 150ms; }
.duration-300 { transition-duration: 300ms; }

.animate-spin { animation: spin 1s linear infinite; }

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* Autopilot Modal Styles */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  z-index: 1000;
  animation: fadeIn 0.2s ease-out;
}

.modal-content {
  background: white;
  border-radius: 16px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
  width: 100%;
  max-width: 640px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  animation: slideUp 0.2s ease-out;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  border-bottom: 1px solid #e5e7eb;
}

.modal-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
}

.modal-header button {
  background: none;
  border: none;
  padding: 8px;
  border-radius: 8px;
  color: #9ca3af;
  cursor: pointer;
  transition: all 0.15s;
}

.modal-header button:hover {
  background: #f3f4f6;
  color: #374151;
}

.modal-body {
  flex: 1;
  overflow-y: auto;
}

.config-item {
  padding: 12px 0;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes slideUp {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>