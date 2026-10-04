import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '../i18n'
import { fetchProject, fetchChapters, fetchParagraphs, fetchAudioSegments, getAudioUrl } from '../api'
import type { Project, Chapter, Paragraph, AudioSegment } from '../types'

interface Character {
  id: number
  name: string
  avatar?: string
}

interface Subtitle {
  text: string
  speaker: string
  avatar?: string
  startTime: number
  endTime: number
}

export function useVideoCanvas() {
  const route = useRoute()
  const router = useRouter()
  const { t } = useI18n()

  const projectId = Number(route.params.projectId)

  // URL parameter detection for auto mode
  const isAutoMode = computed(() => route.query.auto === '1' || route.query.auto === 'true')

  // State
  const loading = ref(true)
  const error = ref<string | null>(null)
  const project = ref<Project | null>(null)
  const chapters = ref<Chapter[]>([])
  const characters = ref<Character[]>([])

  const currentChapterIndex = ref(0)
  const currentParagraphIndex = ref(0)
  const paragraphs = ref<Paragraph[]>([])
  const audioSegments = ref<Map<number, AudioSegment>>(new Map())

  const videoElement = ref<HTMLVideoElement | null>(null)
  const canvasElement = ref<HTMLCanvasElement | null>(null)
  const canvasContainer = ref<HTMLElement | null>(null)
  const progressBar = ref<HTMLElement | null>(null)

  const currentAudioUrl = ref<string>('')
  const currentTime = ref(0)
  const duration = ref(0)
  const isPlaying = ref(false)
  const muted = ref(false)
  const volume = ref(1)
  const playbackRate = ref(1)
  const progressPercent = ref(0)
  const isFullscreen = ref(false)
  const showAutoControls = ref(false)

  const canvasWidth = ref(1920)
  const canvasHeight = ref(1080)

  const currentSubtitle = ref<Subtitle | null>(null)

  const isSpeaking = ref(false)

  let animationFrameId: number | null = null
  let canvasCtx: CanvasRenderingContext2D | null = null
  let visualizerData: Uint8Array<ArrayBuffer> | null = null
  let audioContext: AudioContext | null = null
  let analyser: AnalyserNode | null = null

  // Canvas / audio setup
  async function initCanvas() {
    if (!canvasElement.value) return

    canvasCtx = canvasElement.value.getContext('2d')
    resizeCanvas()

    if (videoElement.value && !audioContext) {
      try {
        audioContext = new AudioContext()
        const source = audioContext.createMediaElementSource(videoElement.value)
        analyser = audioContext.createAnalyser()
        analyser.fftSize = 256
        source.connect(analyser)
        analyser.connect(audioContext.destination)
        visualizerData = new Uint8Array(analyser.frequencyBinCount)
      } catch (e) {
        console.warn('Web Audio API not available:', e)
      }
    }

    renderLoop()
  }

  function resizeCanvas() {
    if (!canvasElement.value || !canvasContainer.value) return

    const containerRect = canvasContainer.value.getBoundingClientRect()
    const aspectRatio = 16 / 9

    let width = containerRect.width
    let height = width / aspectRatio

    if (height > containerRect.height) {
      height = containerRect.height
      width = height * aspectRatio
    }

    canvasWidth.value = width
    canvasHeight.value = height

    if (canvasElement.value) {
      canvasElement.value.width = width * window.devicePixelRatio
      canvasElement.value.height = height * window.devicePixelRatio
      canvasElement.value.style.width = `${width}px`
      canvasElement.value.style.height = `${height}px`

      if (canvasCtx) {
        canvasCtx.scale(window.devicePixelRatio, window.devicePixelRatio)
      }
    }
  }

  function renderLoop() {
    if (!canvasCtx || !canvasElement.value) return

    canvasCtx.clearRect(0, 0, canvasWidth.value, canvasHeight.value)

    if (isPlaying.value && analyser && visualizerData) {
      analyser.getByteFrequencyData(visualizerData)
      drawVisualizer(canvasCtx, visualizerData)
    }

    drawBackground(canvasCtx)

    animationFrameId = requestAnimationFrame(renderLoop)
  }

  function drawBackground(ctx: CanvasRenderingContext2D) {
    const gradient = ctx.createLinearGradient(0, 0, canvasWidth.value, canvasHeight.value)
    gradient.addColorStop(0, '#1a1a2e')
    gradient.addColorStop(0.5, '#16213e')
    gradient.addColorStop(1, '#0f0f23')
    ctx.fillStyle = gradient
    ctx.fillRect(0, 0, canvasWidth.value, canvasHeight.value)

    ctx.fillStyle = 'rgba(255, 255, 255, 0.03)'
    for (let i = 0; i < 50; i++) {
      const x = (Math.sin(Date.now() / 5000 + i) * 0.5 + 0.5) * canvasWidth.value
      const y = (Math.cos(Date.now() / 3000 + i * 2) * 0.5 + 0.5) * canvasHeight.value
      const size = Math.max(1, Math.sin(Date.now() / 2000 + i) * 3 + 2)
      ctx.beginPath()
      ctx.arc(x, y, size, 0, Math.PI * 2)
      ctx.fill()
    }
  }

  function drawVisualizer(ctx: CanvasRenderingContext2D, data: Uint8Array) {
    const barWidth = canvasWidth.value / data.length * 2
    const centerY = canvasHeight.value / 2

    ctx.save()
    ctx.translate(0, centerY)

    for (let i = 0; i < data.length; i++) {
      const value = data[i] / 255
      const height = value * (canvasHeight.value * 0.4)
      const x = i * barWidth

      const hue = 200 + value * 60
      ctx.fillStyle = `hsla(${hue}, 80%, 60%, ${0.3 + value * 0.5})`

      ctx.fillRect(x, -height / 2, barWidth * 0.8, -height / 2)
      ctx.fillRect(x, height / 2, barWidth * 0.8, height / 2)
    }

    ctx.restore()
  }

  // Data loading
  async function loadData() {
    loading.value = true
    error.value = null

    try {
      const [proj, chs] = await Promise.all([
        fetchProject(projectId),
        fetchChapters(projectId),
      ])

      project.value = proj
      chapters.value = chs

      if (chs.length > 0) {
        await loadChapter(0)
      }

      loadCharacters()
    } catch (e: any) {
      error.value = e.response?.data?.detail || e.message || 'Failed to load data'
    } finally {
      loading.value = false
    }
  }

  async function loadCharacters() {
    try {
      const speakers = new Set<string>()
      for (const ch of chapters.value) {
        const paras = await fetchParagraphs(projectId, ch.id)
        for (const p of paras) {
          if (p.speaker_canonical_name) speakers.add(p.speaker_canonical_name)
        }
      }

      characters.value = Array.from(speakers).map((name, idx) => ({
        id: idx,
        name,
        avatar: undefined,
      }))
    } catch (e) {
      console.warn('Failed to load characters:', e)
    }
  }

  async function loadChapter(chapterIdx: number) {
    if (chapterIdx >= chapters.value.length) return

    currentChapterIndex.value = chapterIdx
    currentParagraphIndex.value = 0

    try {
      const paras = await fetchParagraphs(projectId, chapters.value[chapterIdx].id)
      paragraphs.value = paras

      for (const para of paras) {
        if (para.audio_segment_id) {
          try {
            const segments = await fetchAudioSegments(para.id)
            if (segments.length > 0) {
              audioSegments.value.set(para.id, segments[0])
            }
          } catch (e) {
            console.warn(`Failed to fetch audio segment for paragraph ${para.id}:`, e)
          }
        }
      }

      if (paras.length > 0) {
        await loadParagraph(0)
      }
    } catch (e: any) {
      error.value = e.response?.data?.detail || e.message || 'Failed to load chapter'
    }
  }

  async function loadParagraph(paragraphIdx: number) {
    if (paragraphIdx >= paragraphs.value.length) return

    currentParagraphIndex.value = paragraphIdx
    const para = paragraphs.value[paragraphIdx]

    const segment = audioSegments.value.get(para.id)
    if (segment) {
      currentAudioUrl.value = getAudioUrl(segment.id)
    } else if (para.id) {
      currentAudioUrl.value = `${import.meta.env.VITE_API_BASE || 'http://localhost:8000'}/api/paragraphs/${para.id}/audio`
    }

    const paraDuration = segment?.duration_ms ? segment.duration_ms / 1000 : 3

    currentSubtitle.value = {
      text: para.edited_text || para.text,
      speaker: para.speaker_canonical_name || 'Narrator',
      avatar: undefined,
      startTime: 0,
      endTime: paraDuration,
    }

    if (videoElement.value) {
      videoElement.value.src = currentAudioUrl.value
      videoElement.value.load()

      if (isAutoMode.value || isPlaying.value) {
        try {
          await videoElement.value.play()
        } catch (e) {
          console.warn('Autoplay prevented:', e)
        }
      }
    }
  }

  // Playback events
  function onLoadedMetadata() {
    duration.value = videoElement.value?.duration || 0
  }

  function onTimeUpdate() {
    if (!videoElement.value) return

    currentTime.value = videoElement.value.currentTime
    progressPercent.value = duration.value > 0 ? (currentTime.value / duration.value) * 100 : 0

    updateSubtitle()

    if (currentTime.value >= duration.value - 0.5 && !isAutoMode.value) {
      nextParagraph()
    }
  }

  function updateSubtitle() {
    if (!paragraphs.value.length) return

    let cumulativeTime = 0
    for (let i = 0; i < paragraphs.value.length; i++) {
      const para = paragraphs.value[i]
      const segment = audioSegments.value.get(para.id)
      const paraDuration = segment?.duration_ms ? segment.duration_ms / 1000 : 3
      const nextCumulative = cumulativeTime + paraDuration

      if (currentTime.value >= cumulativeTime && currentTime.value < nextCumulative) {
        if (i !== currentParagraphIndex.value) {
          currentParagraphIndex.value = i
          currentSubtitle.value = {
            text: para.edited_text || para.text,
            speaker: para.speaker_canonical_name || 'Narrator',
            avatar: undefined,
            startTime: cumulativeTime,
            endTime: nextCumulative,
          }
        }

        isSpeaking.value = true
        break
      }
      cumulativeTime = nextCumulative
    }
  }

  function onAudioEnded() {
    isPlaying.value = false

    if (isAutoMode.value) {
      nextParagraph()
    }
  }

  function onVideoError(e: Event) {
    console.error('Video error:', e)
    error.value = 'Failed to load audio'
  }

  async function nextParagraph() {
    if (currentParagraphIndex.value < paragraphs.value.length - 1) {
      await loadParagraph(currentParagraphIndex.value + 1)
    } else if (currentChapterIndex.value < chapters.value.length - 1) {
      await loadChapter(currentChapterIndex.value + 1)
    } else if (isAutoMode.value) {
      await loadChapter(0)
    }
  }

  function changeChapter() {
    loadChapter(currentChapterIndex.value)
  }

  function seekToPosition(e: MouseEvent) {
    if (!progressBar.value || !videoElement.value || !duration.value) return

    const rect = progressBar.value.getBoundingClientRect()
    const percent = (e.clientX - rect.left) / rect.width
    videoElement.value.currentTime = percent * duration.value
  }

  function seekToCharacter(char: Character) {
    for (let i = 0; i < paragraphs.value.length; i++) {
      if (paragraphs.value[i].speaker_canonical_name === char.name) {
        loadParagraph(i)
        break
      }
    }
  }

  // Playback controls
  function togglePlayPause() {
    if (!videoElement.value) return

    if (isPlaying.value) {
      videoElement.value.pause()
    } else {
      videoElement.value.play()
    }
    isPlaying.value = !isPlaying.value
  }

  function skipForward() {
    if (videoElement.value) {
      videoElement.value.currentTime = Math.min(videoElement.value.currentTime + 10, duration.value)
    }
  }

  function skipBackward() {
    if (videoElement.value) {
      videoElement.value.currentTime = Math.max(videoElement.value.currentTime - 10, 0)
    }
  }

  function setPlaybackRate() {
    if (videoElement.value) {
      videoElement.value.playbackRate = playbackRate.value
    }
  }

  function setVolume() {
    if (videoElement.value) {
      videoElement.value.volume = volume.value
      muted.value = volume.value === 0
    }
  }

  function toggleMute() {
    if (videoElement.value) {
      muted.value = !muted.value
      videoElement.value.muted = muted.value
    }
  }

  function toggleFullscreen() {
    if (!canvasContainer.value) return

    if (!isFullscreen.value) {
      if (canvasContainer.value.requestFullscreen) {
        canvasContainer.value.requestFullscreen()
      }
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen()
      }
    }
  }

  function exitAutoMode() {
    router.push({ path: route.path, query: { ...route.query, auto: undefined } })
  }

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  // Keyboard shortcuts
  function handleKeyDown(e: KeyboardEvent) {
    if (isAutoMode.value && !showAutoControls.value) {
      showAutoControls.value = true
      setTimeout(() => { showAutoControls.value = false }, 3000)
    }

    switch (e.key) {
      case ' ':
        e.preventDefault()
        togglePlayPause()
        break
      case 'ArrowRight':
        e.preventDefault()
        skipForward()
        break
      case 'ArrowLeft':
        e.preventDefault()
        skipBackward()
        break
      case 'ArrowUp':
        e.preventDefault()
        volume.value = Math.min(volume.value + 0.1, 1)
        setVolume()
        break
      case 'ArrowDown':
        e.preventDefault()
        volume.value = Math.max(volume.value - 0.1, 0)
        setVolume()
        break
      case 'f':
        toggleFullscreen()
        break
      case 'm':
        toggleMute()
        break
    }
  }

  function handleMouseMove() {
    if (isAutoMode.value) {
      showAutoControls.value = true
      clearTimeout((window as any).autoControlsTimer)
      ;(window as any).autoControlsTimer = setTimeout(() => {
        showAutoControls.value = false
      }, 3000)
    }
  }

  onMounted(async () => {
    await loadData()
    await nextTick()
    await initCanvas()

    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('resize', resizeCanvas)

    document.addEventListener('fullscreenchange', () => {
      isFullscreen.value = !!document.fullscreenElement
    })
  })

  onUnmounted(() => {
    window.removeEventListener('keydown', handleKeyDown)
    window.removeEventListener('mousemove', handleMouseMove)
    window.removeEventListener('resize', resizeCanvas)

    if (animationFrameId) {
      cancelAnimationFrame(animationFrameId)
    }

    if (audioContext) {
      audioContext.close()
    }

    if (videoElement.value) {
      videoElement.value.pause()
      videoElement.value.src = ''
    }
  })

  // Watch for auto mode changes
  watch(isAutoMode, (newVal) => {
    if (newVal) {
      if (videoElement.value && !isPlaying.value) {
        videoElement.value.play().catch(() => {})
        isPlaying.value = true
      }
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
  })

  // Watch for current audio URL changes
  watch(currentAudioUrl, (newUrl) => {
    if (newUrl && videoElement.value) {
      videoElement.value.src = newUrl
      videoElement.value.load()
      if (isAutoMode.value || isPlaying.value) {
        videoElement.value.play().catch(() => {})
      }
    }
  })

  return {
    t,
    loading,
    error,
    project,
    chapters,
    characters,
    currentChapterIndex,
    currentParagraphIndex,
    paragraphs,
    audioSegments,
    videoElement,
    canvasElement,
    canvasContainer,
    progressBar,
    currentAudioUrl,
    currentTime,
    duration,
    isPlaying,
    muted,
    volume,
    playbackRate,
    progressPercent,
    isFullscreen,
    showAutoControls,
    canvasWidth,
    canvasHeight,
    currentSubtitle,
    isSpeaking,
    isAutoMode,
    loadData,
    changeChapter,
    seekToPosition,
    seekToCharacter,
    togglePlayPause,
    skipForward,
    skipBackward,
    setPlaybackRate,
    setVolume,
    toggleMute,
    toggleFullscreen,
    exitAutoMode,
    formatTime,
    onLoadedMetadata,
    onTimeUpdate,
    onAudioEnded,
    onVideoError,
  }
}
