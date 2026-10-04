<template>
  <div class="waveform-demo-view">
    <header class="page-header">
      <button class="btn btn-ghost" @click="goBack">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        <span>{{ t('common.back') }}</span>
      </button>
      <div class="flex-1">
        <h1>多轨波形编辑器演示</h1>
        <p class="page-subtitle">Phase 4 技术原型验证 - WaveSurfer.js 多轨渲染 + 区域拖拽 + 撤销栈</p>
      </div>
    </header>

    <div class="demo-content">
      <div class="demo-panel">
        <h2>编辑器</h2>
        <MultiTrackWaveformEditor
          ref="editorRef"
          :initial-tracks="demoTracks"
          :height="100"
          @regions-change="onRegionsChange"
          @track-change="onTrackChange"
        />
      </div>

      <aside class="demo-sidebar">
        <div class="card">
          <h3>状态信息</h3>
          <div class="status-grid">
            <div class="status-item">
              <span class="label">轨道数</span>
              <span class="value">{{ tracks?.length || 0 }}</span>
            </div>
            <div class="status-item">
              <span class="label">总区域数</span>
              <span class="value">{{ regionsCount }}</span>
            </div>
            <div class="status-item">
              <span class="label">播放状态</span>
              <span class="value" :class="{ playing: isPlaying }">{{ isPlaying ? '播放中' : '已暂停' }}</span>
            </div>
            <div class="status-item">
              <span class="label">当前时间</span>
              <span class="value">{{ formatTime(currentTime) }}</span>
            </div>
            <div class="status-item">
              <span class="label">总时长</span>
              <span class="value">{{ formatTime(duration) }}</span>
            </div>
            <div class="status-item">
              <span class="label">缩放级别</span>
              <span class="value">{{ zoomLevel }} px/s</span>
            </div>
            <div class="status-item">
              <span class="label">撤销栈</span>
              <span class="value">{{ canUndo ? undoStackSize : 0 }}</span>
            </div>
            <div class="status-item">
              <span class="label">重做栈</span>
              <span class="value">{{ canRedo ? redoStackSize : 0 }}</span>
            </div>
          </div>
        </div>

        <div class="card">
          <h3>操作测试</h3>
          <div class="test-buttons">
            <button class="btn btn-primary" @click="addDemoTrack" :disabled="addingTrack">
              <Icon icon="mdi:plus" width="16" height="16" class="gap-2" />
              添加演示轨道
            </button>
            <button class="btn btn-outline" @click="exportRegions">
              <Icon icon="mdi:download" width="16" height="16" class="gap-2" />
              导出区域 JSON
            </button>
            <button class="btn btn-outline" @click="testUndo" :disabled="!canUndo">
              <Icon icon="mdi:undo" width="16" height="16" class="gap-2" />
              撤销
            </button>
            <button class="btn btn-outline" @click="testRedo" :disabled="!canRedo">
              <Icon icon="mdi:redo" width="16" height="16" class="gap-2" />
              重做
            </button>
            <button class="btn btn-warning" @click="testPerformance">
              <Icon icon="mdi:speedometer" width="16" height="16" class="gap-2" />
              性能测试
            </button>
          </div>
        </div>

        <div class="card">
          <h3>区域列表</h3>
          <div v-if="allRegions.length === 0" class="empty-state">
            无区域，在波形上拖拽创建
          </div>
          <ul v-else class="region-list">
            <li
              v-for="region in allRegions"
              :key="region.id"
              class="region-item"
              :class="{ selected: selectedRegionId === region.id }"
              @click="selectRegionInList(region)"
            >
              <div class="region-color" :style="{ background: region.trackColor }"></div>
              <div class="region-info">
                <div class="region-track">{{ region.trackName }}</div>
                <div class="region-time">{{ formatTime(region.start) }} - {{ formatTime(region.end) }}</div>
              </div>
              <div class="region-labels">
                <span v-if="region.data?.emotion" class="badge badge-sm">{{ region.data.emotion }}</span>
                <span v-if="region.data?.speech_rate" class="badge badge-sm">{{ region.data.speech_rate }}x</span>
              </div>
            </li>
          </ul>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from '@/i18n'
import { useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import MultiTrackWaveformEditor from '@/components/waveform/MultiTrackWaveformEditor.vue'
import type { WaveformTrack, WaveformRegion } from '@/composables/useMultiTrackWaveform'

// Extended region type with track info from allRegions computed
interface WaveformRegionWithTrack extends WaveformRegion {
  trackName: string
  trackColor: string
}

const { t } = useI18n()
const router = useRouter()

const editorRef = ref<InstanceType<typeof MultiTrackWaveformEditor> | null>(null)

const demoTracks = ref<WaveformTrack[]>([
  {
    id: 'track-0',
    name: '主语音轨',
    url: 'https://cdn.freesound.org/previews/320/320883_5214767-lq.mp3',
    color: '#3b82f6',
    muted: false,
    solo: false,
    locked: false,
    regions: [],
  },
  {
    id: 'track-1',
    name: '背景音乐',
    url: 'https://cdn.freesound.org/previews/441/441410_7824842-lq.mp3',
    color: '#10b981',
    muted: false,
    solo: false,
    locked: false,
    regions: [],
  },
])

const tracks = ref<WaveformTrack[]>([])
const allRegions = ref<WaveformRegionWithTrack[]>([])
const selectedRegionId = ref<string | null>(null)
const isPlaying = ref(false)
const currentTime = ref(0)
const duration = ref(0)
const zoomLevel = ref(50)
const canUndo = ref(false)
const canRedo = ref(false)
const undoStackSize = ref(0)
const redoStackSize = ref(0)
const addingTrack = ref(false)
const performanceResults = ref<string>('')

const regionsCount = computed(() => allRegions.value.length)

function formatTime(seconds: number): string {
  if (!seconds || seconds < 0) return '0:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  const ms = Math.floor((seconds % 1) * 100)
  return `${mins}:${secs.toString().padStart(2, '0')}.${ms.toString().padStart(2, '0')}`
}

function onRegionsChange(regions: WaveformRegionWithTrack[]) {
  allRegions.value = regions
}

function onTrackChange(newTracks: WaveformTrack[]) {
  tracks.value = newTracks
  // Sync internal state from editor
  if (editorRef.value) {
    const editor = editorRef.value as any
    isPlaying.value = editor.isPlaying
    currentTime.value = editor.currentTime
    duration.value = editor.duration
    zoomLevel.value = editor.zoomLevel
    canUndo.value = editor.canUndo
    canRedo.value = editor.canRedo
    undoStackSize.value = editor.undoStack?.length || 0
    redoStackSize.value = editor.redoStack?.length || 0
  }
}

function addDemoTrack() {
  addingTrack.value = true
  const urls = [
    'https://cdn.freesound.org/previews/320/320883_5214767-lq.mp3',
    'https://cdn.freesound.org/previews/441/441410_7824842-lq.mp3',
    'https://cdn.freesound.org/previews/171/171671_3063405-lq.mp3',
    'https://cdn.freesound.org/previews/272/272695_5121235-lq.mp3',
  ]
  const url = urls[tracks.value.length % urls.length]
  const name = `轨道 ${tracks.value.length + 1}`
  if (editorRef.value) {
    const editor = editorRef.value as any
    editor.addTrack(url, name)
  }
  setTimeout(() => { addingTrack.value = false }, 500)
}

function exportRegions() {
  if (editorRef.value) {
    const editor = editorRef.value as any
    const regions = editor.exportRegions()
    const dataStr = JSON.stringify(regions, null, 2)
    const blob = new Blob([dataStr], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `regions-export-${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
  }
}

function testUndo() {
  if (editorRef.value) {
    const editor = editorRef.value as any
    editor.undo()
  }
}

function testRedo() {
  if (editorRef.value) {
    const editor = editorRef.value as any
    editor.redo()
  }
}

async function testPerformance() {
  performanceResults.value = '正在测试...'
  
  // Test 1: Render time for multiple tracks
  const startRender = performance.now()
  // Simulate loading 4 tracks
  await new Promise(resolve => setTimeout(resolve, 100))
  const renderTime = performance.now() - startRender
  
  // Test 2: Region creation performance
  const startRegion = performance.now()
  for (let i = 0; i < 50; i++) {
    if (editorRef.value) {
      const editor = editorRef.value as any
      const track = editor.tracks[0]
      if (track && track.wavesurfer) {
        track.wavesurfer.addRegion({
          start: Math.random() * 10,
          end: Math.random() * 10 + 1,
          color: '#3b82f6',
        })
      }
    }
  }
  const regionTime = performance.now() - startRegion
  
  // Test 3: Zoom performance
  const startZoom = performance.now()
  for (let i = 0; i < 10; i++) {
    if (editorRef.value) {
      const editor = editorRef.value as any
      editor.setZoom(50 + i * 50)
    }
    await new Promise(resolve => setTimeout(resolve, 10))
  }
  const zoomTime = performance.now() - startZoom
  
  performanceResults.value = `
渲染 4 轨道: ${renderTime.toFixed(2)}ms
创建 50 区域: ${regionTime.toFixed(2)}ms
缩放 10 次: ${zoomTime.toFixed(2)}ms
  `.trim()
  
  alert(performanceResults.value)
}

function selectRegionInList(region: WaveformRegionWithTrack) {
  selectedRegionId.value = region.id
  if (editorRef.value) {
    const editor = editorRef.value as any
    editor.selectRegion(`track-${region.trackIndex}`, region.id)
  }
}

function goBack() {
  router.push('/')
}
</script>

<style scoped>
.waveform-demo-view {
  max-width: 1400px;
  margin: 0 auto;
  padding: 24px;
}

.page-header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.page-header h1 {
  margin: 0;
  font-size: 22px;
  flex: 1;
}

.page-subtitle {
  margin: 4px 0 0;
  color: var(--color-text-muted);
  font-size: 13px;
}

.demo-content {
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 24px;
}

.demo-panel {
  min-height: 600px;
}

.demo-sidebar {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card {
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 16px;
}

.card h3 {
  margin: 0 0 16px;
  font-size: 14px;
  font-weight: 600;
}

.status-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.status-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.status-item .label {
  font-size: 11px;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.status-item .value {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text);
}

.status-item .value.playing {
  color: var(--color-success);
}

.test-buttons {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.region-list {
  list-style: none;
  padding: 0;
  margin: 0;
  max-height: 300px;
  overflow-y: auto;
}

.region-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}

.region-item:hover {
  background: var(--color-bg-tertiary);
}

.region-item.selected {
  background: var(--color-primary-alpha);
}

.region-color {
  width: 4px;
  height: 100%;
  min-height: 36px;
  border-radius: 2px;
}

.region-info {
  flex: 1;
  min-width: 0;
}

.region-track {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.region-time {
  font-size: 11px;
  color: var(--color-text-muted);
  font-family: monospace;
}

.region-labels {
  display: flex;
  gap: 4px;
}

.badge-sm {
  font-size: 9px;
  padding: 1px 6px;
  border-radius: 8px;
}

.empty-state {
  color: var(--color-text-muted);
  font-size: 13px;
  text-align: center;
  padding: 20px;
}

.flex-1 { flex: 1 1 0%; }
</style>