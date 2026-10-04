<template>
  <div>
    <!-- TTS Status Banner -->
    <div v-if="ttsStatus" class="tts-banner section">
      <div class="flex items-center gap-3">
        <Icon
          :icon="ttsStatus.enable_local_tts_env ? 'mdi:cpu-64-bit' : 'mdi:cloud'"
          width="24"
          height="24"
          class="text-primary"
        />
        <div>
          <p class="tts-mode-label">
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

      <!-- 运行模式：全自动 vs 人工终审（合成前暂停确认） -->
      <div class="mode-row">
        <span class="form-label">{{ t('auto_run.mode') }}</span>
        <label class="mode-option" :class="{ 'mode-option--active': mode === 'auto' }">
          <input type="radio" name="run-mode" value="auto" :checked="mode === 'auto'" @change="onModeChange" />
          <Icon icon="mdi:robot" width="16" height="16" />
          {{ t('auto_run.mode_auto') }}
        </label>
        <label class="mode-option" :class="{ 'mode-option--active': mode === 'review' }">
          <input type="radio" name="run-mode" value="review" :checked="mode === 'review'" @change="onModeChange" />
          <Icon icon="mdi:clipboard-check-search-outline" width="16" height="16" />
          {{ t('auto_run.mode_review') }}
        </label>
      </div>

      <div class="form-grid">
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

        <div class="checkbox-row">
          <input
            type="checkbox"
            id="bgm"
            :checked="config.enable_background_music"
            @change="onCheckboxChange('enable_background_music', $event)"
            class="checkbox-input"
          />
          <label for="bgm" class="form-label checkbox-label">{{ t('auto_run.enable_bgm') }}</label>
        </div>

        <div class="checkbox-row">
          <input
            type="checkbox"
            id="sfx"
            :checked="config.enable_sfx"
            @change="onCheckboxChange('enable_sfx', $event)"
            class="checkbox-input"
          />
          <label for="sfx" class="form-label checkbox-label">{{ t('auto_run.enable_sfx') }}</label>
        </div>
      </div>

      <!-- Engine Selection -->
      <div v-if="ttsVoices" class="engine-section">
        <h3 class="engine-section-title">{{ t('auto_run.engine_selection') }}</h3>

        <div class="form-grid">
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
            <p class="hint-text">
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
            <p class="hint-text" v-if="availableVoices.length > 0">
              {{ t('auto_run.voice_hint', { count: availableVoices.length }) }}
            </p>
            <p class="hint-text" v-else>
              {{ t('auto_run.no_voices_available') }}
            </p>
          </div>
        </div>

        <!-- Engine Details -->
        <div class="engine-details">
          <h4 class="engine-details-title">{{ t('auto_run.engine_details') }}</h4>
          <div class="engine-details-grid">
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
  AutoRunMode,
} from '../../api'

interface Props {
  ttsStatus: TTSStatusResponse | null
  ttsVoices: TTSVoicesResponse | null
  config: AutoRunConfig
  mode: AutoRunMode
  selectedEngine: string
  selectedVoice: string
  availableEngines: Array<{ id: string; name: string; voices: Array<{ id: string; name: string; language: string; gender: string }> }>
  availableVoices: Array<{ id: string; name: string; language: string; gender: string }>
  loading: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'update:config': [config: AutoRunConfig]
  'update:mode': [mode: AutoRunMode]
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

function onModeChange(event: Event) {
  emit('update:mode', (event.target as HTMLInputElement).value as AutoRunMode)
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

/* ── TTS Banner ───────────────────────────────────────────── */
.tts-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  background: var(--color-info-soft);
  border: 1px solid rgba(2, 132, 199, 0.15);
  border-radius: var(--radius);
}
.tts-mode-label {
  font-weight: 500;
  color: var(--color-primary);
  margin: 0;
}

/* ── Form grid ────────────────────────────────────────────── */
.mode-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.mode-option {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  cursor: pointer;
  font-size: 14px;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.mode-option input {
  accent-color: var(--color-primary);
}

.mode-option--active {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}

/* ── Checkboxes ───────────────────────────────────────────── */
.checkbox-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.checkbox-input {
  width: 16px;
  height: 16px;
  accent-color: var(--color-primary);
}
.checkbox-label {
  margin: 0;
  font-size: 14px;
}

/* ── Engine section ───────────────────────────────────────── */
.engine-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--color-border);
}
.engine-section-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-secondary);
  margin-bottom: 12px;
}
.hint-text {
  font-size: 12px;
  color: var(--color-text-muted);
  margin: 4px 0 0;
}

/* ── Engine details ───────────────────────────────────────── */
.engine-details {
  margin-top: 16px;
  padding: 12px;
  border-radius: var(--radius);
  background: var(--color-bg-tertiary);
}
.engine-details-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-secondary);
  margin-bottom: 12px;
}
.engine-details-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 16px;
  font-size: 13px;
}
</style>
