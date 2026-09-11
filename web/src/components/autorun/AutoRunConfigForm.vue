<template>
  <div>
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
          <select :value="config.target_difficulty" @change="onSelectChange('target_difficulty', $event)" class="form-control">
            <option value="A">{{ t('auto_run.difficulty_a') }}</option>
            <option value="B">{{ t('auto_run.difficulty_b') }}</option>
            <option value="C">{{ t('auto_run.difficulty_c') }}</option>
            <option value="D">{{ t('auto_run.difficulty_d') }}</option>
          </select>
        </div>

        <div>
          <label class="form-label">{{ t('auto_run.voice_preference') }}</label>
          <select :value="config.primary_voice_preference" @change="onSelectChange('primary_voice_preference', $event)" class="form-control">
            <option value="female">{{ t('auto_run.voice_female') }}</option>
            <option value="male">{{ t('auto_run.voice_male') }}</option>
            <option value="neutral">{{ t('auto_run.voice_neutral') }}</option>
            <option value="local">{{ t('auto_run.voice_local') }}</option>
            <option value="cloud">{{ t('auto_run.voice_cloud') }}</option>
          </select>
        </div>

        <div>
          <label class="form-label">{{ t('auto_run.speech_rate') }}</label>
          <select :value="config.speech_rate_preference" @change="onSelectChange('speech_rate_preference', $event)" class="form-control">
            <option value="slow">{{ t('auto_run.rate_slow') }}</option>
            <option value="standard">{{ t('auto_run.rate_standard') }}</option>
            <option value="fast">{{ t('auto_run.rate_fast') }}</option>
          </select>
        </div>

        <div>
          <label class="form-label">{{ t('auto_run.cost_limit') }}</label>
          <input
            type="number"
            :value="config.cost_limit_usd"
            @change="onNumberChange('cost_limit_usd', $event)"
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
            :value="config.quality_threshold"
            @change="onNumberChange('quality_threshold', $event)"
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
            :value="config.max_regeneration_attempts"
            @change="onNumberChange('max_regeneration_attempts', $event)"
            min="1"
            max="5"
            class="form-control"
          />
        </div>

        <div class="flex items-center gap-2">
          <input
            type="checkbox"
            id="bgm"
            :checked="config.enable_background_music"
            @change="onCheckboxChange('enable_background_music', $event)"
            class="h-4 w-4"
            style="accent-color: var(--color-primary);"
          />
          <label for="bgm" class="form-label" style="margin: 0; font-size: 14px;">{{ t('auto_run.enable_bgm') }}</label>
        </div>

        <div class="flex items-center gap-2">
          <input
            type="checkbox"
            id="sfx"
            :checked="config.enable_sfx"
            @change="onCheckboxChange('enable_sfx', $event)"
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
          <div>
            <label class="form-label">{{ t('auto_run.select_engine') }}</label>
            <select
              :value="selectedEngine"
              @change="onEngineChange($event)"
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

          <div>
            <label class="form-label">{{ t('auto_run.select_voice') }}</label>
            <select
              :value="selectedVoice"
              @change="onVoiceChange($event)"
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
  </div>
</template>

<script setup lang="ts">
import { useI18n } from '../../i18n'
import { Icon } from '@iconify/vue'
import type {
  TTSStatusResponse,
  TTSVoicesResponse,
  AutoRunConfig,
} from '../../api'

interface Props {
  ttsStatus: TTSStatusResponse | null
  ttsVoices: TTSVoicesResponse | null
  config: AutoRunConfig
  selectedEngine: string
  selectedVoice: string
  availableEngines: Array<{ id: string; name: string; voices: Array<{ id: string; name: string; language: string; gender: string }> }>
  availableVoices: Array<{ id: string; name: string; language: string; gender: string }>
  loading: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'update:config': [config: AutoRunConfig]
  'update:selectedEngine': [value: string]
  'update:selectedVoice': [value: string]
}>()

const { t } = useI18n()

function updateConfig(field: keyof AutoRunConfig, value: unknown) {
  emit('update:config', { ...props.config, [field]: value } as AutoRunConfig)
}

function onSelectChange(field: keyof AutoRunConfig, event: Event) {
  updateConfig(field, (event.target as HTMLSelectElement).value)
}

function onNumberChange(field: keyof AutoRunConfig, event: Event) {
  updateConfig(field, Number((event.target as HTMLInputElement).value))
}

function onCheckboxChange(field: keyof AutoRunConfig, event: Event) {
  updateConfig(field, (event.target as HTMLInputElement).checked)
}

function onEngineChange(event: Event) {
  emit('update:selectedEngine', (event.target as HTMLSelectElement).value)
}

function onVoiceChange(event: Event) {
  emit('update:selectedVoice', (event.target as HTMLSelectElement).value)
}
</script>

<style scoped>
.section {
  margin-bottom: 20px;
}
.flex { display: flex; }
.items-center { align-items: center; }
.gap-2 { gap: 8px; }
.gap-3 { gap: 12px; }
.gap-4 { gap: 16px; }
.grid { display: grid; }
.grid-auto-fill { grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }
</style>
