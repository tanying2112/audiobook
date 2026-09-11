<template>
  <div class="voice-clone-view">
    <div class="header">
      <h1>{{ t('voice_clone.title') }}</h1>
      <p class="subtitle">{{ t('voice_clone.subtitle') }}</p>
    </div>

    <!-- Step 1: Upload -->
    <section class="card" v-if="step === 1">
      <h2>{{ t('voice_clone.step_upload') }}</h2>
      
      <div class="form-group">
        <label>{{ t('voice_clone.speaker_id_label') }}</label>
        <input
          v-model="form.speakerId"
          :placeholder="t('voice_clone.speaker_id_placeholder')"
          class="input"
          maxlength="50"
        />
        <p class="hint">{{ t('voice_clone.speaker_id_hint') }}</p>
        <p v-if="errors.speakerId" class="error">{{ errors.speakerId }}</p>
      </div>

      <div class="form-group">
        <label>{{ t('voice_clone.language_label') }}</label>
        <select v-model="form.language" class="select">
          <option v-for="lang in languageOptions" :key="lang.value" :value="lang.value">{{ lang.label }}</option>
        </select>
      </div>

      <div class="form-group">
        <label>{{ t('voice_clone.text_content_label') }}</label>
        <textarea
          v-model="form.textContent"
          :placeholder="t('voice_clone.text_content_placeholder')"
          class="input"
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
          <span class="icon">🎵</span>
          <p>{{ t('voice_clone.drag_drop') }}</p>
          <p class="hint">{{ t('voice_clone.supported_formats') }}</p>
        </div>
        <div v-else class="file-info">
          <span class="icon">✅</span>
          <p>{{ audioFile.name }}</p>
          <p class="hint">{{ formatFileSize(audioFile.size) }}</p>
          <p class="hint" v-if="audioDuration">{{ t('voice_clone.duration', { duration: audioDuration.toFixed(1) }) }}</p>
        </div>
      </div>

      <p v-if="errors.file" class="error">{{ errors.file }}</p>

      <!-- P2.11 合规: 克隆前样本提供者授权勾选 (必填, 后端 422 双重校验) -->
      <div class="form-group consent-group">
        <label class="consent-label">
          <input
            type="checkbox"
            v-model="form.consentAccepted"
            class="consent-checkbox"
          />
          <span>{{ t('voice_clone.consent_label') }}</span>
        </label>
        <p class="hint">{{ t('voice_clone.consent_hint') }}</p>
      </div>

      <div class="actions">
        <button class="btn primary" @click="goToPreview" :disabled="!canUpload">
          {{ t('voice_clone.upload_btn') }}
        </button>
      </div>
    </section>

    <!-- Step 2: Waveform Preview -->
    <section class="card" v-if="step === 2 && audioUrl">
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
        <button class="btn secondary" @click="skip(-5)">{{ t('chapter_timeline.rewind_5s') }}</button>
        <button class="btn primary" :class="{ playing: isPlaying }" @click="togglePlay">
          {{ isPlaying ? t('voice_clone.pause') : t('voice_clone.play') }}
        </button>
        <button class="btn secondary" @click="skip(5)">{{ t('chapter_timeline.forward_5s') }}</button>
        <button class="btn secondary" @click="replay">{{ t('voice_clone.replay') }}</button>
      </div>

      <div class="actions">
        <button class="btn secondary" @click="backToUpload">{{ t('voice_clone.back_to_upload') }}</button>
        <button class="btn primary" @click="startCloning" :disabled="cloning">{{ t('voice_clone.start_clone') }}</button>
      </div>
    </section>

    <!-- Step 3: Cloning Progress -->
    <section class="card" v-if="step === 3">
      <h2>{{ t('voice_clone.step_cloning') }}</h2>
      
      <div class="progress-container">
        <div class="spinner"></div>
        <p>{{ t('voice_clone.cloning') }}</p>
      </div>
    </section>

    <!-- Step 4: Result -->
    <section class="card" v-if="step === 4 && cloneResult">
      <h2>{{ t('voice_clone.step_result') }}</h2>
      
      <div v-if="cloneResult.success" class="result-success">
        <div class="success-icon">✅</div>
        <p class="success-message">{{ t('voice_clone.clone_success') }}</p>
        
        <div class="result-details">
          <div class="detail-row">
            <span class="label">{{ t('voice_clone.voice_id') }}</span>
            <div class="value-with-copy">
              <code>{{ cloneResult.voice_id }}</code>
              <button class="btn-icon" @click="copyVoiceId" :title="t('tooltips.copy')">
                📋
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
            <label>{{ t('voice_clone.preview_text') }}</label>
            <textarea
              v-model="previewText"
              :placeholder="t('voice_clone.preview_text_placeholder')"
              class="input"
              rows="2"
            ></textarea>
          </div>
          <div class="preview-controls">
            <button 
              class="btn primary" 
              @click="generatePreview" 
              :disabled="previewGenerating || !previewText.trim()"
            >
              {{ previewGenerating ? t('voice_clone.preview_generating') : t('voice_clone.preview_btn') }}
            </button>
            <button 
              v-if="previewAudioUrl" 
              class="btn secondary" 
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
          <button class="btn secondary" @click="cloneAnother">{{ t('voice_clone.clone_another') }}</button>
          <button class="btn secondary" @click="viewClonedList">{{ t('voice_clone.view_cloned_list') }}</button>
        </div>
      </div>

      <div v-else class="result-error">
        <div class="error-icon">❌</div>
        <p class="error-message">{{ t('voice_clone.clone_failed', { error: cloneResult.message || t('common.unknown_error') }) }}</p>
        <div class="actions">
          <button class="btn secondary" @click="backToUpload">{{ t('voice_clone.back_to_upload') }}</button>
          <button class="btn primary" @click="cloneAnother">{{ t('voice_clone.clone_another') }}</button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { useVoiceClone } from '../composables/useVoiceClone'
import './VoiceCloneView.css'

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
