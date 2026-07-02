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
          <option value="zh-CN">中文 (zh-CN)</option>
          <option value="en-US">English (en-US)</option>
          <option value="ja-JP">日本語 (ja-JP)</option>
          <option value="ko-KR">한국어 (ko-KR)</option>
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
import { ref, computed, onUnmounted, nextTick } from 'vue'
import { useI18n } from '../i18n'
import { useWaveSurfer } from '../composables/useWaveSurfer'
import { cloneVoice, previewVoice, getPreviewAudioUrl } from '../api'

const { t } = useI18n()

// State
const step = ref(1)
const form = ref({
  speakerId: '',
  language: 'zh-CN',
  textContent: '',
})
const errors = ref<Record<string, string>>({})
const audioFile = ref<File | null>(null)
const audioUrl = ref<string | null>(null)
const audioDuration = ref<number | null>(null)
const audioSampleRate = ref<number | null>(null)
const audioChannels = ref<number | null>(null)
const isDragging = ref(false)
const cloning = ref(false)
const cloneResult = ref<{
  success: boolean
  voice_id: string
  speaker_id: string
  message: string
  quality?: string
  snr_db?: number
  sample_count?: number
} | null>(null)

// Preview state
const previewText = ref('这是一个语音试听样本。')
const previewAudioUrl = ref<string | null>(null)
const previewGenerating = ref(false)
const previewPlaying = ref(false)
const previewError = ref<string | null>(null)
const previewAudio = ref<HTMLAudioElement | null>(null)

// WaveSurfer
const waveformRef = ref<HTMLElement | null>(null)
const { wavesurfer, isPlaying, isReady, load, play, pause, seekTo, skip, cleanup } = useWaveSurfer(waveformRef)

const canUpload = computed(() => {
  return form.value.speakerId.trim().length > 0 && audioFile.value !== null
})

const qualityClass = computed(() => {
  const q = cloneResult.value?.quality?.toLowerCase()
  if (q === 'excellent') return 'badge-excellent'
  if (q === 'good') return 'badge-good'
  if (q === 'fair') return 'badge-fair'
  return 'badge-poor'
})

const fileInput = ref<HTMLInputElement | null>(null)

function triggerFileInput() {
  fileInput.value?.click()
}

function handleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.[0]) {
    validateAndSetFile(input.files[0])
  }
}

function handleDrop(e: DragEvent) {
  isDragging.value = false
  if (e.dataTransfer?.files?.[0]) {
    validateAndSetFile(e.dataTransfer.files[0])
  }
}

function validateAndSetFile(file: File) {
  errors.value.file = ''
  
  // Check format
  const allowedTypes = ['audio/wav', 'audio/wave', 'audio/x-wav', 'audio/mpeg', 'audio/mp3']
  if (!allowedTypes.includes(file.type)) {
    errors.value.file = t('voice_clone.validation_file_format')
    return
  }
  
  // Check size (50MB)
  if (file.size > 50 * 1024 * 1024) {
    errors.value.file = t('voice_clone.validation_file_size')
    return
  }
  
  audioFile.value = file
  audioUrl.value = URL.createObjectURL(file)
  
  // Load in WaveSurfer to get metadata
  nextTick(() => {
    if (audioUrl.value) {
      load(audioUrl.value)
    }
  })
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

// Step 1 → Step 2: Go to waveform preview (no API call yet)
function goToPreview() {
  if (!canUpload.value) {
    if (!form.value.speakerId.trim()) {
      errors.value.speakerId = t('voice_clone.validation_speaker_id')
    }
    if (!audioFile.value) {
      errors.value.file = t('voice_clone.validation_file_required')
    }
    return
  }
  errors.value = {}
  step.value = 2
}


function togglePlay() {
  if (isPlaying.value) {
    pause()
  } else {
    play()
  }
}

function replay() {
  seekTo(0)
  play()
}

// Step 2 → Step 3+4: Call clone API
async function startCloning() {
  step.value = 3
  cloning.value = true

  try {
    const result = await cloneVoice(
      audioFile.value!,
      form.value.speakerId,
      form.value.language,
      form.value.textContent,
    )
    cloneResult.value = result
    step.value = 4
  } catch (e: any) {
    const message = e.response?.data?.detail || e.message || t('common.unknown_error')
    cloneResult.value = {
      success: false,
      voice_id: '',
      speaker_id: form.value.speakerId,
      message,
    }
    step.value = 4
  } finally {
    cloning.value = false
  }
}

async function generatePreview() {
  if (!cloneResult.value || !previewText.value.trim()) return
  
  previewGenerating.value = true
  previewError.value = null
  
  try {
    await previewVoice(cloneResult.value.voice_id, previewText.value)
    previewAudioUrl.value = getPreviewAudioUrl(cloneResult.value.voice_id) + '?text=' + encodeURIComponent(previewText.value)
    
    // Try to load the preview audio
    if (previewAudio.value) {
      previewAudio.value.src = previewAudioUrl.value
      await previewAudio.value.load()
    }
  } catch (e: any) {
    previewError.value = t('voice_clone.preview_failed') + ': ' + (e.message || t('common.unknown_error'))
  } finally {
    previewGenerating.value = false
  }
}

function playPreview() {
  if (!previewAudio.value) return
  
  if (previewPlaying.value) {
    previewAudio.value.pause()
    previewPlaying.value = false
  } else {
    previewAudio.value.play().catch(e => {
      previewError.value = t('voice_clone.preview_failed') + ': ' + e.message
    })
    previewPlaying.value = true
  }
}

function copyVoiceId() {
  if (!cloneResult.value) return
  navigator.clipboard.writeText(cloneResult.value.voice_id)
  alert(t('voice_clone.voice_id_copied'))
}

function backToUpload() {
  step.value = 1
  cloneResult.value = null
  previewAudioUrl.value = null
  previewError.value = null
}

function cloneAnother() {
  step.value = 1
  form.value = { speakerId: '', language: 'zh-CN', textContent: '' }
  audioFile.value = null
  audioUrl.value = null
  audioDuration.value = null
  audioSampleRate.value = null
  audioChannels.value = null
  cloneResult.value = null
  previewAudioUrl.value = null
  previewError.value = null
  errors.value = {}
  cleanup()
}

function viewClonedList() {
  // Navigate to a future page or open modal
  alert(t('voice_clone.view_cloned_list') + ' - 待实现')
}

// Watch WaveSurfer ready state for metadata
import { watch } from 'vue'
watch(isReady, (ready) => {
  if (ready && wavesurfer.value) {
    audioDuration.value = wavesurfer.value.getDuration()
    // We can't easily get sample rate and channels from wavesurfer
    // Would need to decode the audio file separately
  }
})

onUnmounted(() => {
  cleanup()
  if (audioUrl.value) {
    URL.revokeObjectURL(audioUrl.value)
  }
})
</script>

<style scoped>
.voice-clone-view {
  max-width: 800px;
  margin: 0 auto;
  padding: 2rem;
}
.header {
  margin-bottom: 2rem;
}
.header h1 {
  font-size: 1.8rem;
  margin: 0;
}
.subtitle {
  color: var(--color-text-secondary, #888);
  margin: 0.5rem 0 0;
}
.card {
  background: var(--color-bg-secondary, #f9f9f9);
  border: 1px solid var(--color-border, #e0e0e0);
  border-radius: 12px;
  padding: 1.5rem;
  margin-bottom: 1.5rem;
}
.card h2 {
  margin: 0 0 1rem;
  font-size: 1.2rem;
}
.form-group {
  margin-bottom: 1.25rem;
}
.form-group label {
  display: block;
  font-weight: 500;
  margin-bottom: 0.5rem;
}
.input, .select, textarea.input {
  width: 100%;
  padding: 0.6rem 0.8rem;
  border: 1px solid var(--color-border, #ccc);
  border-radius: 8px;
  font-size: 0.95rem;
  background: var(--color-bg-primary, #fff);
  box-sizing: border-box;
}
.input:focus, .select:focus {
  outline: none;
  border-color: var(--color-primary, #4a90d9);
  box-shadow: 0 0 0 3px rgba(74, 144, 217, 0.15);
}
.hint {
  color: var(--color-text-secondary, #888);
  font-size: 0.85rem;
  margin: 0.25rem 0 0;
}
.error {
  color: var(--color-error, #e53e3e);
  font-size: 0.85rem;
  margin: 0.25rem 0 0;
}
.drop-zone {
  border: 2px dashed var(--color-border, #ccc);
  border-radius: 12px;
  padding: 2rem;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
}
.drop-zone:hover, .drop-zone.active {
  border-color: var(--color-primary, #4a90d9);
  background: var(--color-bg-hover, #f0f7ff);
}
.drop-prompt .icon {
  font-size: 2.5rem;
}
.file-info .icon {
  font-size: 1.5rem;
}
.waveform-container {
  margin: 1rem 0;
}
.waveform {
  min-height: 100px;
}
.audio-meta {
  display: flex;
  gap: 1.5rem;
  color: var(--color-text-secondary, #888);
  font-size: 0.85rem;
  margin: 0.5rem 0 1rem;
  padding: 0.5rem;
  background: var(--color-bg-primary, #fff);
  border-radius: 8px;
  border: 1px solid var(--color-border, #e0e0e0);
}
.playback-controls {
  display: flex;
  gap: 0.5rem;
  margin: 1rem 0;
  flex-wrap: wrap;
}
.preview-section {
  margin-top: 1.5rem;
  padding-top: 1.5rem;
  border-top: 1px solid var(--color-border, #e0e0e0);
}
.preview-section h3 {
  margin: 0 0 1rem;
  font-size: 1rem;
}
.preview-controls {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
.result-details {
  background: var(--color-bg-primary, #fff);
  border: 1px solid var(--color-border, #e0e0e0);
  border-radius: 8px;
  padding: 1rem;
  margin: 1rem 0;
}
.detail-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 0;
  border-bottom: 1px solid var(--color-border, #f0f0f0);
}
.detail-row:last-child {
  border-bottom: none;
}
.detail-row .label {
  color: var(--color-text-secondary, #888);
  font-size: 0.9rem;
}
.detail-row .value-with-copy {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.detail-row code {
  background: var(--color-bg-secondary, #f5f5f5);
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.85rem;
}
.badge {
  padding: 0.2rem 0.6rem;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}
.badge-excellent { background: #d4edda; color: #155724; }
.badge-good { background: #d1ecf1; color: #0c5460; }
.badge-fair { background: #fff3cd; color: #856404; }
.badge-poor { background: #f8d7da; color: #721c24; }
.btn-icon {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 1rem;
  padding: 0.25rem;
  border-radius: 4px;
}
.btn-icon:hover {
  background: var(--color-bg-secondary, #eee);
}
.result-success .success-icon,
.result-error .error-icon {
  font-size: 3rem;
  text-align: center;
  margin-bottom: 0.5rem;
}
.success-message {
  text-align: center;
  color: var(--color-success, #28a745);
  font-weight: 500;
}
.error-message {
  text-align: center;
  color: var(--color-error, #e53e3e);
}
.progress-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
  padding: 2rem;
}
.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--color-border, #e0e0e0);
  border-top-color: var(--color-primary, #4a90d9);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 1.5rem;
  justify-content: flex-end;
  flex-wrap: wrap;
}
.btn {
  padding: 0.6rem 1.2rem;
  border: none;
  border-radius: 8px;
  font-size: 0.95rem;
  cursor: pointer;
  transition: opacity 0.2s, background 0.2s;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn.primary {
  background: var(--color-primary, #4a90d9);
  color: white;
}
.btn.primary:hover:not(:disabled) {
  filter: brightness(1.1);
}
.btn.secondary {
  background: var(--color-bg-secondary, #eee);
  color: var(--color-text-primary, #333);
}
.btn.secondary:hover:not(:disabled) {
  background: var(--color-border, #ddd);
}
</style>
