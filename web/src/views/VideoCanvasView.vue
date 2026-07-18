<template>
  <div class="video-canvas-view" :class="{ 'auto-mode': isAutoMode }">
    <!-- 16:9 Video Canvas Container -->
    <div class="canvas-container" ref="canvasContainer">
      <!-- Video Element (for audio visualization) -->
      <video
        ref="videoElement"
        class="canvas-video"
        :src="currentAudioUrl"
        @timeupdate="onTimeUpdate"
        @ended="onAudioEnded"
        @loadedmetadata="onLoadedMetadata"
        @error="onVideoError"
        playsinline
        crossorigin="anonymous"
      ></video>

      <!-- Canvas for Visual Effects -->
      <canvas
        ref="canvasElement"
        class="canvas-element"
        :width="canvasWidth"
        :height="canvasHeight"
      ></canvas>

      <!-- Subtitle Overlay -->
      <div class="subtitle-overlay" v-if="currentSubtitle">
        <div class="subtitle-text" :class="{ 'highlight': isSpeaking }">
          {{ currentSubtitle.text }}
        </div>
        <div class="speaker-indicator" v-if="currentSubtitle.speaker">
          <div class="avatar" :style="{ backgroundImage: currentSubtitle.avatar ? `url(${currentSubtitle.avatar})` : '' }">
            <span v-if="!currentSubtitle.avatar" class="avatar-initial">
              {{ currentSubtitle.speaker.charAt(0) }}
            </span>
          </div>
          <span class="speaker-name">{{ currentSubtitle.speaker }}</span>
        </div>
      </div>

      <!-- Character Avatars Sidebar (hidden in auto mode) -->
      <div class="avatars-sidebar" v-if="!isAutoMode && characters.length > 0">
        <div class="sidebar-header">
          <h3>{{ t('video_canvas.characters') }}</h3>
        </div>
        <div class="avatars-list">
          <div
            v-for="char in characters"
            :key="char.id"
            class="avatar-item"
            :class="{ 'active': currentSubtitle && currentSubtitle.speaker === char.name, 'speaking': isSpeaking && currentSubtitle && currentSubtitle.speaker === char.name }"
            @click="seekToCharacter(char)"
          >
            <div class="avatar-circle" :style="{ backgroundImage: char.avatar ? `url(${char.avatar})` : '' }">
              <span v-if="!char.avatar" class="avatar-initial">{{ char.name.charAt(0) }}</span>
              <div class="speaking-ring" v-if="isSpeaking && currentSubtitle && currentSubtitle.speaker === char.name"></div>
            </div>
            <span class="avatar-name">{{ char.name }}</span>
          </div>
        </div>
      </div>

      <!-- Progress Bar (hidden in auto mode) -->
      <div class="progress-bar-container" v-if="!isAutoMode" ref="progressBar">
        <div class="progress-bar">
          <div
            class="progress-fill"
            :style="{ width: `${progressPercent}%` }"
            @click="seekToPosition"
          ></div>
        </div>
        <div class="time-display">
          <span>{{ formatTime(currentTime) }}</span>
          <span>/</span>
          <span>{{ formatTime(duration) }}</span>
        </div>
      </div>

      <!-- Auto Mode Indicator -->
      <div class="auto-indicator" v-if="isAutoMode">
        <span class="auto-badge">{{ t('video_canvas.auto_mode') }}</span>
        <div class="auto-controls" v-if="showAutoControls">
          <button @click="togglePlayPause" class="auto-btn" :aria-label="isPlaying ? 'Pause' : 'Play'">
            <Icon :icon="isPlaying ? 'mdi:pause' : 'mdi:play'" size="24" />
          </button>
          <button @click="exitAutoMode" class="auto-btn" :aria-label="t('video_canvas.exit_auto')">
            <Icon icon="mdi:fullscreen-exit" size="24" />
          </button>
        </div>
      </div>

      <!-- Loading State -->
      <div class="loading-overlay" v-if="loading">
        <div class="spinner"></div>
        <p>{{ t('video_canvas.loading') }}</p>
      </div>

      <!-- Error State -->
      <div class="error-overlay" v-if="error">
        <Icon icon="mdi:alert-circle" size="48" class="error-icon" />
        <p>{{ error }}</p>
        <button @click="loadData" class="retry-btn">{{ t('video_canvas.retry') }}</button>
      </div>
    </div>

    <!-- Controls Panel (hidden in auto mode) -->
    <div class="controls-panel" v-if="!isAutoMode">
      <div class="controls-row">
        <div class="playback-controls">
          <button @click="skipBackward" class="control-btn" :disabled="!duration" :aria-label="t('video_canvas.skip_back')">
            <Icon icon="mdi:skip-previous" size="24" />
          </button>
          <button @click="togglePlayPause" class="control-btn play-btn" :disabled="!duration" :aria-label="isPlaying ? 'Pause' : 'Play'">
            <Icon :icon="isPlaying ? 'mdi:pause' : 'mdi:play'" size="32" />
          </button>
          <button @click="skipForward" class="control-btn" :disabled="!duration" :aria-label="t('video_canvas.skip_forward')">
            <Icon icon="mdi:skip-next" size="24" />
          </button>
        </div>

        <div class="speed-control">
          <label>{{ t('video_canvas.speed') }}</label>
          <select v-model="playbackRate" @change="setPlaybackRate" class="speed-select">
            <option value="0.5">0.5x</option>
            <option value="0.75">0.75x</option>
            <option value="1">1x</option>
            <option value="1.25">1.25x</option>
            <option value="1.5">1.5x</option>
            <option value="2">2x</option>
          </select>
        </div>

        <div class="volume-control">
          <button @click="toggleMute" class="control-btn" :aria-label="muted ? 'Unmute' : 'Mute'">
            <Icon :icon="muted || volume === 0 ? 'mdi:volume-off' : volume < 0.5 ? 'mdi:volume-low' : 'mdi:volume-high'" size="24" />
          </button>
          <input
            type="range"
            v-model="volume"
            min="0"
            max="1"
            step="0.1"
            class="volume-slider"
            @input="setVolume"
          />
        </div>

        <div class="fullscreen-control">
          <button @click="toggleFullscreen" class="control-btn" :aria-label="isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'">
            <Icon :icon="isFullscreen ? 'mdi:fullscreen-exit' : 'mdi:fullscreen'" size="24" />
          </button>
        </div>
      </div>

      <!-- Chapter Navigation -->
      <div class="chapter-nav" v-if="chapters.length > 0">
        <div class="chapter-select">
          <label>{{ t('video_canvas.chapter') }}</label>
          <select v-model="currentChapterIndex" @change="changeChapter" class="chapter-select">
            <option v-for="(ch, idx) in chapters" :key="ch.id" :value="idx">
              {{ ch.index }}. {{ ch.title }}
            </option>
          </select>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '../i18n'
import { fetchProject } from '../api'
import { fetchChapters } from '../api'
import { fetchParagraphs } from '../api'
import { fetchAudioSegments } from '../api'
import { getAudioUrl } from '../api'
import { Icon } from '@iconify/vue'
import type { Project, Chapter, Paragraph, AudioSegment } from '../types'

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
const characters = ref<Array<{ id: number; name: string; avatar?: string }>>([])

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

const currentSubtitle = ref<{
  text: string
  speaker: string
  avatar?: string
  startTime: number
  endTime: number
} | null>(null)

const isSpeaking = ref(false)

let animationFrameId: number | null = null
let canvasCtx: CanvasRenderingContext2D | null = null
let visualizerData: Uint8Array<ArrayBuffer> | null = null
let audioContext: AudioContext | null = null
let analyser: AnalyserNode | null = null

// Initialize canvas and audio context
async function initCanvas() {
  if (!canvasElement.value) return

  canvasCtx = canvasElement.value.getContext('2d')
  resizeCanvas()

  // Initialize Web Audio API for visualization
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

  // Start render loop
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

  // Clear canvas
  canvasCtx.clearRect(0, 0, canvasWidth.value, canvasHeight.value)

  // Draw audio visualization if playing
  if (isPlaying.value && analyser && visualizerData) {
    analyser.getByteFrequencyData(visualizerData)
    drawVisualizer(canvasCtx, visualizerData)
  }

  // Draw ambient background
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

  // Draw subtle particles
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

  // Mirror visualization
  for (let i = 0; i < data.length; i++) {
    const value = data[i] / 255
    const height = value * (canvasHeight.value * 0.4)
    const x = i * barWidth

    const hue = 200 + value * 60
    ctx.fillStyle = `hsla(${hue}, 80%, 60%, ${0.3 + value * 0.5})`

    // Top bar
    ctx.fillRect(x, -height / 2, barWidth * 0.8, -height / 2)
    // Bottom bar (mirror)
    ctx.fillRect(x, height / 2, barWidth * 0.8, height / 2)
  }

  ctx.restore()
}

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

    // Load characters for avatars
    loadCharacters()
  } catch (e: any) {
    error.value = e.response?.data?.detail || e.message || 'Failed to load data'
  } finally {
    loading.value = false
  }
}

async function loadCharacters() {
  try {
    // This would come from an API call
    // For now, extract unique speakers from paragraphs
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
      // In real app, this would come from character database
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

    // Fetch audio segments for all paragraphs in this chapter
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

  // Get audio URL for this paragraph
  const segment = audioSegments.value.get(para.id)
  if (segment) {
    currentAudioUrl.value = getAudioUrl(segment.id)
  } else if (para.id) {
    // Fallback to paragraph audio endpoint
    currentAudioUrl.value = `${import.meta.env.VITE_API_BASE || 'http://localhost:8000'}/api/paragraphs/${para.id}/audio`
  }

  // Get duration from audio segment if available
  const paraDuration = segment?.duration_ms ? segment.duration_ms / 1000 : 3

  // Update subtitle
  currentSubtitle.value = {
    text: para.edited_text || para.text,
    speaker: para.speaker_canonical_name || 'Narrator',
    avatar: undefined,
    startTime: 0,
    endTime: paraDuration,
  }

  // Load audio
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

function onLoadedMetadata() {
  duration.value = videoElement.value?.duration || 0
}

function onTimeUpdate() {
  if (!videoElement.value) return

  currentTime.value = videoElement.value.currentTime
  progressPercent.value = duration.value > 0 ? (currentTime.value / duration.value) * 100 : 0

  // Check for subtitle changes
  updateSubtitle()

  // Auto-advance to next paragraph
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

      // Highlight speaking
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
    // Loop back to start in auto mode
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

function seekToCharacter(char: { id: number; name: string }) {
  // Find first paragraph by this speaker
  for (let i = 0; i < paragraphs.value.length; i++) {
    if (paragraphs.value[i].speaker_canonical_name === char.name) {
      loadParagraph(i)
      break
    }
  }
}

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
    // Show auto controls on any key press
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

// Mouse move to show auto controls
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

  // Listen for fullscreen changes
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
    // Enter auto mode - start playing
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
</script>

<style scoped>
.video-canvas-view {
  width: 100%;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #000;
  color: #fff;
  overflow: hidden;
}

.video-canvas-view.auto-mode {
  cursor: none;
}

.video-canvas-view.auto-mode .controls-panel,
.video-canvas-view.auto-mode .progress-bar-container,
.video-canvas-view.auto-mode .avatars-sidebar {
  display: none !important;
}

.canvas-container {
  position: relative;
  flex: 1;
  width: 100%;
  max-width: 100%;
  aspect-ratio: 16 / 9;
  margin: 0 auto;
  background: #000;
  overflow: hidden;
}

.canvas-video {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  opacity: 0;
  pointer-events: none;
}

.canvas-element {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  display: block;
}

.subtitle-overlay {
  position: absolute;
  bottom: 80px;
  left: 50%;
  transform: translateX(-50%);
  max-width: 90%;
  text-align: center;
  z-index: 10;
  pointer-events: none;
  transition: opacity 0.3s ease;
}

.subtitle-text {
  font-size: clamp(1.2rem, 3vw, 2.5rem);
  font-weight: 500;
  line-height: 1.4;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.8);
  background: linear-gradient(135deg, rgba(0, 0, 0, 0.7), rgba(0, 0, 0, 0.4));
  padding: 1rem 2rem;
  border-radius: 12px;
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  animation: subtitleFadeIn 0.3s ease;
}

.subtitle-text.highlight {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.8), rgba(79, 70, 229, 0.6));
  border-color: rgba(99, 102, 241, 0.5);
}

@keyframes subtitleFadeIn {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

.speaker-indicator {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background-size: cover;
  background-position: center;
  border: 2px solid #6366f1;
  box-shadow: 0 0 20px rgba(99, 102, 241, 0.5);
}

.avatar-initial {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  font-weight: 600;
  font-size: 1.2rem;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 50%;
}

.speaker-name {
  font-size: 0.9rem;
  color: #cbd5e1;
  font-weight: 500;
}

.speaking-ring {
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  border: 2px solid #6366f1;
  animation: speakingPulse 1.5s ease-out infinite;
}

@keyframes speakingPulse {
  0% { transform: scale(1); opacity: 0.8; }
  100% { transform: scale(1.5); opacity: 0; }
}

.avatars-sidebar {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 200px;
  background: rgba(15, 15, 35, 0.95);
  border-left: 1px solid rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(20px);
  display: flex;
  flex-direction: column;
  z-index: 5;
}

.sidebar-header {
  padding: 1rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.sidebar-header h3 {
  margin: 0;
  font-size: 1rem;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.avatars-list {
  flex: 1;
  overflow-y: auto;
  padding: 0.5rem;
}

.avatar-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.avatar-item:hover {
  background: rgba(255, 255, 255, 0.05);
}

.avatar-item.active {
  background: rgba(99, 102, 241, 0.2);
}

.avatar-item.speaking .avatar-circle {
  box-shadow: 0 0 20px rgba(99, 102, 241, 0.8);
}

.avatar-circle {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background-size: cover;
  background-position: center;
  position: relative;
  flex-shrink: 0;
  border: 2px solid transparent;
  transition: all 0.3s ease;
}

.avatar-item.active .avatar-circle {
  border-color: #6366f1;
}

.avatar-name {
  font-size: 0.9rem;
  color: #e2e8f0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.progress-bar-container {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 0 1rem 1rem;
  z-index: 10;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.8), transparent);
}

.progress-bar {
  height: 4px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 2px;
  cursor: pointer;
  position: relative;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #6366f1, #8b5cf6);
  border-radius: 2px;
  transition: width 0.1s linear;
}

.time-display {
  display: flex;
  justify-content: center;
  gap: 0.5rem;
  margin-top: 0.5rem;
  font-size: 0.75rem;
  color: #94a3b8;
  font-variant-numeric: tabular-nums;
}

.auto-indicator {
  position: absolute;
  top: 1rem;
  right: 1rem;
  z-index: 20;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.5rem;
}

.auto-badge {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  padding: 0.35rem 0.75rem;
  border-radius: 20px;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  box-shadow: 0 4px 20px rgba(99, 102, 241, 0.4);
  animation: autoPulse 2s ease-in-out infinite;
}

@keyframes autoPulse {
  0%, 100% { box-shadow: 0 4px 20px rgba(99, 102, 241, 0.4); }
  50% { box-shadow: 0 4px 30px rgba(99, 102, 241, 0.6); }
}

.auto-controls {
  display: flex;
  gap: 0.5rem;
  opacity: 0;
  transform: translateX(20px);
  transition: all 0.3s ease;
}

.auto-indicator:hover .auto-controls,
.auto-controls.visible {
  opacity: 1;
  transform: translateX(0);
}

.auto-btn {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  backdrop-filter: blur(10px);
  transition: all 0.2s ease;
}

.auto-btn:hover {
  background: rgba(99, 102, 241, 0.8);
  border-color: #6366f1;
  transform: scale(1.1);
}

.loading-overlay,
.error-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(15, 15, 35, 0.95);
  z-index: 100;
  gap: 1rem;
}

.spinner {
  width: 48px;
  height: 48px;
  border: 3px solid rgba(255, 255, 255, 0.1);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.error-icon {
  color: #ef4444;
}

.error-overlay p {
  color: #fca5a5;
  font-size: 1.1rem;
}

.retry-btn {
  padding: 0.75rem 1.5rem;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.2s ease;
}

.retry-btn:hover {
  transform: scale(1.05);
}

.controls-panel {
  padding: 1.5rem;
  background: linear-gradient(to top, rgba(15, 15, 35, 0.98), rgba(15, 15, 35, 0.8));
  backdrop-filter: blur(20px);
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.controls-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.5rem;
  flex-wrap: wrap;
}

.playback-controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.control-btn {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;
}

.control-btn:hover:not(:disabled) {
  background: rgba(99, 102, 241, 0.8);
  border-color: #6366f1;
  transform: scale(1.1);
}

.control-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.play-btn {
  width: 56px;
  height: 56px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-color: transparent;
}

.play-btn:hover:not(:disabled) {
  box-shadow: 0 0 30px rgba(99, 102, 241, 0.5);
}

.speed-control,
.volume-control {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.speed-control label {
  font-size: 0.85rem;
  color: #94a3b8;
}

.speed-select {
  padding: 0.35rem 0.75rem;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  color: #fff;
  font-size: 0.85rem;
  cursor: pointer;
}

.volume-slider {
  width: 100px;
  accent-color: #6366f1;
}

.fullscreen-control .control-btn {
  width: 44px;
  height: 44px;
}

.chapter-nav {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.chapter-select {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.chapter-select label {
  font-size: 0.85rem;
  color: #94a3b8;
}

.chapter-select select {
  flex: 1;
  max-width: 400px;
  padding: 0.5rem 1rem;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  color: #fff;
  font-size: 0.9rem;
  cursor: pointer
}

.chapter-select select option {
  background: #0f0f23;
  color: #fff;
}

/* Responsive */
@media (max-width: 768px) {
  .avatars-sidebar {
    width: 160px;
  }

  .avatar-circle {
    width: 40px;
    height: 40px;
  }

  .controls-row {
    flex-direction: column;
    gap: 1rem;
  }

  .speed-control,
  .volume-control {
    width: 100%;
    justify-content: space-between;
  }

  .volume-slider {
    width: 80px;
  }
}

/* Reduced motion */
@media (prefers-reduced-motion: reduce) {
  .subtitle-text,
  .progress-fill,
  .auto-badge,
  .speaking-ring {
    animation: none;
  }
}
</style>