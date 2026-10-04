<template>
  <teleport to="body">
    <div v-if="show" class="modal-overlay" @click="close">
      <div class="modal-content" @click.stop>
        <div class="modal-header">
          <h3 class="modal-title">
            <Icon icon="mdi:robot-outline" width="20" height="20" class="text-primary gap-2" />
            {{ t('auto_run.autopilot_preview_title') }}
          </h3>
          <button class="btn btn-ghost" @click="close" aria-label="Close">
            <Icon icon="mdi:close" width="20" height="20" />
          </button>
        </div>

        <div class="modal-body p-4 max-h-[70vh] overflow-y-auto">
          <div v-if="loading" class="loading-state">
            <Icon icon="mdi:loading" width="32" height="32" class="spinner" style="border-color: var(--color-primary-alpha); border-top-color: var(--color-primary)" />
            <span>{{ t('auto_run.loading_preview') }}</span>
          </div>

          <template v-else-if="preview">
            <div class="space-y-4">
              <div class="alert alert-info">
                <p class="text-sm">{{ preview.reasoning }}</p>
              </div>

              <div class="grid grid-auto-fill gap-4">
                <div class="config-item p-3 rounded" style="background: var(--color-bg-tertiary);">
                  <label class="text-muted" style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;">{{ t('auto_run.target_difficulty') }}</label>
                  <p class="font-medium">{{ difficultyLabel(preview.target_difficulty) }}</p>
                </div>

                <div class="config-item p-3 rounded" style="background: var(--color-bg-tertiary);">
                  <label class="text-muted" style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;">{{ t('auto_run.voice_preference') }}</label>
                  <p class="font-medium capitalize">{{ preview.primary_voice_preference }}</p>
                </div>

                <div class="config-item p-3 rounded" style="background: var(--color-bg-tertiary);">
                  <label class="text-muted" style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;">{{ t('auto_run.speech_rate') }}</label>
                  <p class="font-medium capitalize">{{ preview.speech_rate_preference }}</p>
                </div>

                <div class="config-item p-3 rounded" style="background: var(--color-bg-tertiary);">
                  <label class="text-muted" style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;">{{ t('auto_run.cost_limit') }}</label>
                  <p class="font-medium">${{ preview.cost_limit_usd?.toFixed(2) || '—' }}</p>
                </div>

                <div class="config-item p-3 rounded" style="background: var(--color-bg-tertiary);">
                  <label class="text-muted" style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;">{{ t('auto_run.quality_threshold') }}</label>
                  <p class="font-medium">{{ (preview.quality_threshold * 100).toFixed(0) }}%</p>
                </div>

                <div class="config-item p-3 rounded" style="background: var(--color-bg-tertiary);">
                  <label class="text-muted" style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;">{{ t('auto_run.max_regen_attempts') }}</label>
                  <p class="font-medium">{{ preview.max_regeneration_attempts }}</p>
                </div>

                <div class="config-item p-3 rounded" style="background: var(--color-bg-tertiary);">
                  <label class="text-muted" style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;">{{ t('auto_run.enable_bgm') }}</label>
                  <p class="font-medium">
                    <span :class="preview.enable_background_music ? 'text-success' : 'text-danger'">
                      {{ preview.enable_background_music ? t('common.enabled') : t('common.disabled') }}
                    </span>
                  </p>
                </div>

                <div class="config-item p-3 rounded" style="background: var(--color-bg-tertiary);">
                  <label class="text-muted" style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;">{{ t('auto_run.enable_sfx') }}</label>
                  <p class="font-medium">
                    <span :class="preview.enable_sfx ? 'text-success' : 'text-danger'">
                      {{ preview.enable_sfx ? t('common.enabled') : t('common.disabled') }}
                    </span>
                  </p>
                </div>
              </div>

              <div class="pt-3 border-t" style="border-color: var(--color-border);">
                <p class="text-muted text-xs mb-2">{{ t('auto_run.confidence') }}: <span class="font-medium text-secondary">{{ (preview.confidence * 100).toFixed(0) }}%</span></p>
                <div class="w-full rounded-full h-2" style="background: var(--color-border); overflow: hidden;">
                  <div
                    class="h-full rounded-full transition-all duration-300"
                    :style="{ width: (preview.confidence * 100) + '%' }"
                    style="background: var(--color-primary);"
                  ></div>
                </div>
              </div>
            </div>
          </template>
        </div>

        <div class="modal-footer flex justify-end gap-2 p-4 border-t" style="border-color: var(--color-border);">
          <button class="btn btn-outline" @click="close">{{ t('common.cancel') }}</button>
          <button class="btn btn-primary" @click="confirm" :disabled="starting">
            <Icon v-if="starting" icon="mdi:loading" width="18" height="18" class="spinner gap-2" style="border-color: rgba(255,255,255,.35); border-top-color: #fff" />
            <Icon icon="mdi:rocket-launch" width="18" height="18" class="gap-2" />
            {{ t('auto_run.launch_autopilot') }}
          </button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { useI18n } from '../../i18n'
import type { AutopilotConfig } from '../../api'

const props = defineProps<{
  show: boolean
  loading: boolean
  starting: boolean
  preview: AutopilotConfig | null
}>()

const emit = defineEmits<{
  close: []
  confirm: []
}>()

const { t } = useI18n()

function close() {
  emit('close')
}
function confirm() {
  emit('confirm')
}

function difficultyLabel(difficulty: string): string {
  const labels: Record<string, string> = {
    A: t('auto_run.difficulty_a'),
    B: t('auto_run.difficulty_b'),
    C: t('auto_run.difficulty_c'),
    D: t('auto_run.difficulty_d'),
  }
  return labels[difficulty] || difficulty
}
</script>

<style scoped>
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
.grid-auto-fill {
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
}
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes slideUp {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
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
