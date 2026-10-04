import { ref, computed, onUnmounted, nextTick, watch } from 'vue'
import { useI18n } from '../i18n'
import { useWaveSurfer } from './useWaveSurfer'
import { cloneVoice, previewVoice, getPreviewAudioUrl } from '../api'

export function useVoiceClone() {
  const { t } = useI18n()

  const languageOptions = [
    { value: 'zh-CN', label: '中文 (zh-CN)' },
    { value: 'en-US', label: 'English (en-US)' },
    { value: 'ja-JP', label: '日本語 (ja-JP)' },
    { value: 'ko-KR', label: '한국어 (ko-KR)' },
  ]

  // State
  const step = ref(1)
  const form = ref({
    speakerId: '',
    language: 'zh-CN',
    textContent: '',
    consentAccepted: false,
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
  const previewText = ref(t('voice_clone.preview_text_placeholder'))
  const previewAudioUrl = ref<string | null>(null)
  const previewGenerating = ref(false)
  const previewPlaying = ref(false)
  const previewError = ref<string | null>(null)
  const previewAudio = ref<HTMLAudioElement | null>(null)

  // WaveSurfer
  const waveformRef = ref<HTMLElement | null>(null)
  const { wavesurfer, isPlaying, isReady, load, play, pause, seekTo, skip, cleanup } = useWaveSurfer(waveformRef)

  const fileInput = ref<HTMLInputElement | null>(null)

  const canUpload = computed(() => {
    return form.value.speakerId.trim().length > 0 && audioFile.value !== null && form.value.consentAccepted
  })

  const qualityClass = computed(() => {
    const q = cloneResult.value?.quality?.toLowerCase()
    if (q === 'excellent') return 'badge-excellent'
    if (q === 'good') return 'badge-good'
    if (q === 'fair') return 'badge-fair'
    return 'badge-poor'
  })

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

    const allowedTypes = ['audio/wav', 'audio/wave', 'audio/x-wav', 'audio/mpeg', 'audio/mp3']
    if (!allowedTypes.includes(file.type)) {
      errors.value.file = t('voice_clone.validation_file_format')
      return
    }

    if (file.size > 50 * 1024 * 1024) {
      errors.value.file = t('voice_clone.validation_file_size')
      return
    }

    audioFile.value = file
    audioUrl.value = URL.createObjectURL(file)

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

  async function startCloning() {
    step.value = 3
    cloning.value = true

    try {
      const result = await cloneVoice(
        audioFile.value!,
        form.value.speakerId,
        form.value.language,
        form.value.textContent,
        undefined,
        form.value.consentAccepted,
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
    form.value = { speakerId: '', language: 'zh-CN', textContent: '', consentAccepted: false }
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
    alert(t('voice_clone.view_cloned_list') + ' - ' + t('voice_clone.not_implemented'))
  }

  watch(isReady, (ready) => {
    if (ready && wavesurfer.value) {
      audioDuration.value = wavesurfer.value.getDuration()
    }
  })

  onUnmounted(() => {
    cleanup()
    if (audioUrl.value) {
      URL.revokeObjectURL(audioUrl.value)
    }
  })

  return {
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
  }
}
