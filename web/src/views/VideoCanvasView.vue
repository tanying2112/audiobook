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
import { Icon } from '@iconify/vue'
import { useVideoCanvas } from '../composables/useVideoCanvas'
import './VideoCanvasView.css'

const {
  t,
  loading,
  error,
  chapters,
  characters,
  currentChapterIndex,
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
} = useVideoCanvas()
</script>
