<template>
  <div class="page-container voice-clone-view">
    <header class="page-header">
      <h1>{{ t('voice_clone.title') }}</h1>
      <p class="page-subtitle">{{ t('voice_clone.subtitle') }}</p>
    </header>

    <!-- Step 1: Upload -->
    <section class="card section" v-if="step === 1">
      <h2>{{ t('voice_clone.step_upload') }}</h2>

      <div class="form-group">
        <label class="form-label">{{ t('voice_clone.speaker_id_label') }}</label>
        <input
          v-model="form.speakerId"
          :placeholder="t('voice_clone.speaker_id_placeholder')"
          class="form-control"
          maxlength="50"
        />
        <p class="hint">{{ t('voice_clone.speaker_id_hint') }}</p>
        <p v-if="errors.speakerId" class="error">{{ errors.speakerId }}</p>
      </div>

      <div class="form-group">
        <label class="form-label">{{ t('voice_clone.language_label') }}</label>
        <select v-model="form.language" class="form-control">
          <option v-for="lang in languageOptions" :key="lang.value" :value="lang.value">{{ lang.label }}</option>
        </select>
      </div>

      <div class="form-group">
        <label class="form-label">{{ t('voice_clone.text_content_label') }}</label>
        <textarea
          v-model="form.textContent"
          :placeholder="t('voice_clone.text_content_placeholder')"
          class="form-control"
          rows="3"
        ></textarea>
      </div>

      <div class="drop-zone" :class="{ active: isDragging }"
        @dragover.prevent="isDragging = true"
        @dragleave="isDragging = false"
        @drop.prevent="handleDrop"
        @click="triggerFileInput">
        <input
          ref="fileInput"
          type="file"
          accept=".wav,.mp3,.mpeg"
          style="display: none"
          @change="handleFileSelect"
        />
        <div v-if="!audioFile" class="drop-prompt">
          <Icon icon="mdi:music-note" width="40" height="40" class="drop-icon" />
          <p>{{ t('voice_clone.drag_drop') }}</p>
          <p class="hint">{{ t('voice_clone.supported_formats') }}</p>
        </div>
        <div v-else class="file-info">
          <Icon icon="mdi:check-circle" width="32" height="32" class="text-success" />
          <p>{{ audioFile.name }}</p>
          <p class="hint">{{ formatFileSize(audioFile.size) }}</p>
          <p class="hint" v-if="audioDuration">{{ t('voice_clone.duration', { duration: audioDuration.toFixed(1) }) }}</p>
        </div>
      </div>

      <p v-if="errors.file" class="error">{{ errors.file }}</p>

      <!-- P2.11 合规: 克隆前样本提供者授权勾选 (必填, 后端 422 双重校验) -->
      <div class="form-group consent-group">
        <label class="radio-label consent-label">
          <input
            type="checkbox"
            v-model="form.consentAccepted"
            class="touch-target-sm"
          />
          <span>{{ t('voice_clone.consent_label') }}</span>
        </label>
        <p class="hint">{{ t('voice_clone.consent_hint') }}</p>
      </div>

      <div class="actions">
        <button class="btn btn-primary touch-target" @click="goToPreview" :disabled="!canUpload">
          {{ t('voice_clone.upload_btn') }}
        </button>
      </div>
    </section>

    <!-- Step 2: Waveform Preview -->
    <section class="card section" v-if="step === 2 && audioUrl">
      <h2>{{ t('voice_clone.preview_title') }}</h2>

      <div class="waveform-container">
        <div ref="waveformRef" class="waveform"></div>
      </div>

      <div class="audio-meta">
        <span>{{ t('voice_clone.duration', { duration: audioDuration?.toFixed(1) || 0 }) }}</span>
        <span>{{ t('voice_clone.sample_rate', { sr: audioSampleRate || 0 }) }}</span>
        <span>{{ t('voice_clone.channels', { channels: audioChannels || 0 }) }}</span>
      </div>

      <div class="playback-controls">
        <button class="btn btn-outline touch-target" @click="skip(-5)">{{ t('chapter_timeline.rewind_5s') }}</button>
        <button class="btn btn-primary touch-target" :class="{ 'btn-playing': isPlaying }" @click="togglePlay">
          <Icon :icon="isPlaying ? 'mdi:pause' : 'mdi:play'" width="18" height="18" />
          {{ isPlaying ? t('voice_clone.pause') : t('voice_clone.play') }}
        </button>
        <button class="btn btn-outline touch-target" @click="skip(5)">{{ t('chapter_timeline.forward_5s') }}</button>
        <button class="btn btn-outline touch-target" @click="replay">{{ t('voice_clone.replay') }}</button>
      </div>

      <div class="actions">
        <button class="btn btn-outline touch-target" @click="backToUpload">{{ t('voice_clone.back_to_upload') }}</button>
        <button class="btn btn-primary touch-target" @click="startCloning" :disabled="cloning">
          {{ t('voice_clone.start_clone') }}
        </button>
      </div>
    </section>

    <!-- Step 3: Cloning Progress -->
    <section class="card section" v-if="step === 3">
      <h2>{{ t('voice_clone.step_cloning') }}</h2>

      <div class="progress-container">
        <div class="spinner spinner-lg"></div>
        <p>{{ t('voice_clone.cloning') }}</p>
      </div>
    </section>

    <!-- Step 4: Result -->
    <section class="card section" v-if="step === 4 && cloneResult">
      <h2>{{ t('voice_clone.step_result') }}</h2>

      <div v-if="cloneResult.success" class="result-success">
        <Icon icon="mdi:check-circle" width="48" height="48" class="text-success" />
        <p class="success-message">{{ t('voice_clone.clone_success') }}</p>

        <div class="result-details">
          <div class="detail-row">
            <span class="label">{{ t('voice_clone.voice_id') }}</span>
            <div class="value-with-copy">
              <code>{{ cloneResult.voice_id }}</code>
              <button class="btn btn-ghost btn-sm touch-target-sm" @click="copyVoiceId" :title="t('tooltips.copy')" aria-label="Copy voice ID">
                <Icon icon="mdi:content-copy" width="16" height="16" />
              </button>
            </div>
          </div>
          <div class="detail-row">
            <span class="label">{{ t('voice_clone.quality') }}</span>
            <span class="badge" :class="qualityClass">{{ cloneResult.quality || t('common.unknown') }}</span>
          </div>
          <div class="detail-row">
            <span class="label">{{ t('voice_clone.snr') }}</span>
            <span>{{ cloneResult.snr_db ? cloneResult.snr_db.toFixed(1) + ' dB' : t('common.na') }}</span>
          </div>
          <div class="detail-row">
            <span class="label">{{ t('voice_clone.samples') }}</span>
            <span>{{ cloneResult.sample_count || 0 }}</span>
          </div>
        </div>

        <!-- Preview Section -->
        <div class="preview-section">
          <h3>{{ t('voice_clone.preview_voice') }}</h3>
          <div class="form-group">
            <label class="form-label">{{ t('voice_clone.preview_text') }}</label>
            <textarea
              v-model="previewText"
              :placeholder="t('voice_clone.preview_text_placeholder')"
              class="form-control"
              rows="2"
            ></textarea>
          </div>
          <div class="preview-controls">
            <button
              class="btn btn-primary touch-target"
              @click="generatePreview"
              :disabled="previewGenerating || !previewText.trim()"
            >
              {{ previewGenerating ? t('voice_clone.preview_generating') : t('voice_clone.preview_btn') }}
            </button>
            <button
              v-if="previewAudioUrl"
              class="btn btn-outline touch-target"
              @click="playPreview"
              :disabled="previewPlaying"
            >
              {{ previewPlaying ? t('voice_clone.pause') : t('voice_clone.play_preview') }}
            </button>
          </div>
          <p v-if="previewError" class="error">{{ previewError }}</p>
          <audio v-if="previewAudioUrl" ref="previewAudio" :src="previewAudioUrl" @ended="previewPlaying = false"></audio>
        </div>

        <div class="actions">
          <button class="btn btn-outline touch-target" @click="cloneAnother">{{ t('voice_clone.clone_another') }}</button>
          <button class="btn btn-outline touch-target" @click="viewClonedList">{{ t('voice_clone.view_cloned_list') }}</button>
        </div>
      </div>

      <div v-else class="result-error">
        <Icon icon="mdi:close-circle" width="48" height="48" class="text-danger" />
        <p class="error-message">{{ t('voice_clone.clone_failed', { error: cloneResult.message || t('common.unknown_error') }) }}</p>
        <div class="actions">
          <button class="btn btn-outline touch-target" @click="backToUpload">{{ t('voice_clone.back_to_upload') }}</button>
          <button class="btn btn-primary touch-target" @click="cloneAnother">{{ t('voice_clone.clone_another') }}</button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { useVoiceClone } from '../composables/useVoiceClone'

const {
  t,
  languageOptions,
  step,
  form,
  errors,
  audioFile,
  audioUrl,
  audioDuration,
  audioSampleRate,
  audioChannels,
  isDragging,
  cloning,
  cloneResult,
  previewText,
  previewAudioUrl,
  previewGenerating,
  previewPlaying,
  previewError,
  previewAudio,
  waveformRef,
  fileInput,
  isPlaying,
  canUpload,
  qualityClass,
  triggerFileInput,
  handleFileSelect,
  handleDrop,
  formatFileSize,
  goToPreview,
  togglePlay,
  replay,
  skip,
  startCloning,
  generatePreview,
  playPreview,
  copyVoiceId,
  backToUpload,
  cloneAnother,
  viewClonedList,
} = useVoiceClone()

// Template refs: these are intentionally kept in scope for ref="..." bindings
void previewAudio
void waveformRef
void fileInput
</script>

<style scoped>
.voice-clone-view {
  max-width: 800px;
}

.drop-zone {
  border: 2px dashed var(--color-border);
  border-radius: var(--radius-lg);
  padding: 32px 24px;
  text-align: center;
  cursor: pointer;
  transition: border-color var(--transition-fast), background var(--transition-fast);
  margin-bottom: 12px;
}
.drop-zone:hover,
.drop-zone.active {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
}

.drop-icon {
  color: var(--color-text-muted);
  margin-bottom: 8px;
}

.file-info p {
  margin: 2px 0;
}

.waveform-container {
  margin: 16px 0;
}
.waveform {
  min-height: 100px;
}

.audio-meta {
  display: flex;
  gap: 16px;
  color: var(--color-text-secondary);
  font-size: 13px;
  margin: 8px 0 16px;
  padding: 10px 12px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius);
}

.playback-controls {
  display: flex;
  gap: 8px;
  margin: 16px 0;
  flex-wrap: wrap;
}

.preview-section {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--color-border);
}
.preview-section h3 {
  margin: 0 0 12px;
  font-size: 16px;
  font-weight: 600;
}
.preview-controls {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.result-details {
  background: var(--color-bg-tertiary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: 16px;
  margin: 16px 0;
}
.detail-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid var(--color-border);
}
.detail-row:last-child {
  border-bottom: none;
}
.detail-row .label {
  color: var(--color-text-secondary);
  font-size: 13px;
}
.detail-row .value-with-copy {
  display: flex;
  align-items: center;
  gap: 8px;
}
.detail-row code {
  background: var(--color-bg-tertiary);
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  font-size: 13px;
}

.badge-excellent { background: var(--color-success-soft); color: var(--color-success); }
.badge-good { background: var(--color-info-soft); color: var(--color-info); }
.badge-fair { background: var(--color-warning-soft); color: var(--color-warning); }
.badge-poor { background: var(--color-danger-soft); color: var(--color-danger); }

.result-success,
.result-error {
  text-align: center;
}
.success-message {
  color: var(--color-success);
  font-weight: 500;
  margin: 8px 0 16px;
}
.error-message {
  color: var(--color-danger);
  margin: 8px 0 16px;
}

.progress-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 32px;
}

@media (max-width: 767px) {
  .playback-controls {
    justify-content: center;
  }
  .audio-meta {
    flex-wrap: wrap;
    gap: 8px;
  }
}
</style>
