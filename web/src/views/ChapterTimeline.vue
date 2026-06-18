<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChapterStore } from '../stores/chapters'
import { useWaveSurfer } from '../composables/useWaveSurfer'
import { Icon } from '@iconify/vue'

const route = useRoute()
const router = useRouter()
const store = useChapterStore()

const projectId = Number(route.params.projectId)
const chapterId = Number(route.params.chapterId)

const waveformContainer = ref<HTMLElement | null>(null)
const selectedParaId = ref<number | null>(null)
const zoomLevel = ref(50)

const {
  isPlaying, currentTime, duration, isReady, error: wsError,
  load: loadWave, playPause, skip, seekTo, zoom, cleanup,
} = useWaveSurfer(waveformContainer)

onMounted(async () => {
  await store.loadChapter(projectId, chapterId)
  await store.loadParagraphs(projectId, chapterId)
})

const currentParagraph = computed(() =>
  store.paragraphs.find((p) => p.id === selectedParaId.value),
)

function getAudioUrl(paragraphId: number): string {
  return `/api/paragraphs/${paragraphId}/audio`
}

function selectParagraph(paraId: number) {
  cleanup()
  selectedParaId.value = paraId

  const para = store.paragraphs.find((p) => p.id === paraId)
  if (!para) return

  // Load audio segments if available, otherwise try direct audio URL
  store.loadAudioSegments(paraId)
  store.loadQuality(paraId)

  // Load waveform
  nextTick(() => {
    loadWave(getAudioUrl(paraId))
  })
}

function jumpToParagraph(paraId: number) {
  selectParagraph(paraId)
  // Scroll the paragraph card into view
  const el = document.getElementById(`para-${paraId}`)
  el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function formatTime(seconds: number): string {
  if (!seconds || !isFinite(seconds)) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}
</script>

<template>
  <div class="chapter-timeline">
    <div class="page-header">
      <button class="btn btn-ghost" @click="router.push(`/projects/${projectId}`)">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        返回
      </button>
      <h1>{{ store.currentChapter?.title || `章节 ${chapterId}` }}</h1>
      <div class="header-meta" v-if="store.paragraphs.length">
        <span class="badge">{{ store.paragraphs.length }} 段落</span>
      </div>
    </div>

    <!-- Waveform Player -->
    <div class="waveform-section" v-if="selectedParaId">
      <div class="waveform-toolbar">
        <button class="btn-icon" @click="skip(-5)" title="后退 5s">
          <Icon icon="mdi:rewind-5" width="22" height="22" />
        </button>
        <button class="btn-play" @click="playPause" :title="isPlaying ? '暂停' : '播放'">
          <Icon :icon="isPlaying ? 'mdi:pause-circle' : 'mdi:play-circle'" width="36" height="36" />
        </button>
        <button class="btn-icon" @click="skip(5)" title="快进 5s">
          <Icon icon="mdi:fast-forward-5" width="22" height="22" />
        </button>
        <span class="time-display">{{ formatTime(currentTime) }} / {{ formatTime(duration) }}</span>
        <div class="zoom-controls">
          <button class="btn-icon" @click="zoomLevel = Math.max(10, zoomLevel - 10); zoom(zoomLevel)" title="缩小">
            <Icon icon="mdi:magnify-minus-outline" width="18" height="18" />
          </button>
          <span class="zoom-label">{{ zoomLevel }}px/s</span>
          <button class="btn-icon" @click="zoomLevel = Math.min(200, zoomLevel + 10); zoom(zoomLevel)" title="放大">
            <Icon icon="mdi:magnify-plus-outline" width="18" height="18" />
          </button>
        </div>
      </div>
      <div ref="waveformContainer" class="waveform-container"></div>
      <div v-if="wsError" class="waveform-error">{{ wsError }}</div>
    </div>

    <!-- Paragraph Selector Hint -->
    <div v-if="!selectedParaId && store.paragraphs.length" class="select-hint">
      点击段落可预览音频
    </div>

    <!-- Loading -->
    <div v-if="store.loading" class="loading">加载段落中...</div>

    <!-- Paragraph List -->
    <div v-else class="paragraph-list">
      <div
        v-for="(para, idx) in store.paragraphs"
        :key="para.id"
        :id="`para-${para.id}`"
        :class="['paragraph-card', { selected: selectedParaId === para.id }]"
        @click="selectParagraph(para.id)"
      >
        <div class="para-header">
          <span class="para-num">#{{ idx + 1 }}</span>
          <span class="para-role">{{ para.character_name || ' narrator' }}</span>
          <span :class="['status-dot', para.status || 'pending']" />
          <button class="btn-icon btn-jump" @click.stop="jumpToParagraph(para.id)" title="波形跳转">
            <Icon icon="mdi:waveform" width="16" height="16" />
          </button>
        </div>
        <p class="para-text">{{ para.original_text || para.text }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chapter-timeline { max-width: 900px; margin: 0 auto; }

/* Header */
.page-header { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; }
.page-header h1 { margin: 0; font-size: 22px; flex: 1; }
.badge { font-size: 11px; padding: 2px 10px; border-radius: 99px; background: #dbeafe; color: #1d4ed8; }

/* Waveform */
.waveform-section {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 20px;
}
.waveform-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.btn-play { background: none; border: none; cursor: pointer; color: #3b82f6; padding: 0; line-height: 1; }
.btn-play:hover { color: #2563eb; }
.time-display { font-size: 13px; color: #64748b; font-variant-numeric: tabular-nums; min-width: 90px; }
.zoom-controls { margin-left: auto; display: flex; align-items: center; gap: 4px; }
.zoom-label { font-size: 11px; color: #94a3b8; min-width: 40px; text-align: center; }
.waveform-container { min-height: 80px; }
.waveform-error { color: #ef4444; font-size: 13px; margin-top: 8px; }

/* Select hint */
.select-hint { text-align: center; padding: 12px; color: #94a3b8; font-size: 13px; }

/* Paragraphs */
.paragraph-list {}
.paragraph-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 18px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.paragraph-card:hover { border-color: #93c5fd; }
.paragraph-card.selected { border-color: #3b82f6; box-shadow: 0 0 0 2px rgba(59,130,246,0.15); }
.para-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.para-num { font-weight: 600; color: #3b82f6; font-size: 12px; min-width: 28px; }
.para-role { font-size: 12px; color: #64748b; background: #f1f5f9; padding: 1px 8px; border-radius: 4px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; }
.status-dot.completed { background: #22c55e; }
.status-dot.pending { background: #facc15; }
.status-dot.error { background: #ef4444; }
.btn-jump { margin-left: auto; color: #94a3b8; }
.btn-jump:hover { color: #3b82f6; }
.para-text { margin: 0; font-size: 14px; line-height: 1.7; color: #1e293b; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }

/* Utilities */
.btn-icon { background: none; border: none; cursor: pointer; color: #64748b; padding: 4px; border-radius: 6px; line-height: 1; display: inline-flex; align-items: center; }
.btn-icon:hover { background: #f1f5f9; color: #1e293b; }
.loading { text-align: center; padding: 60px; color: #64748b; }
</style>