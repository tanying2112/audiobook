<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import WaveSurfer from 'wavesurfer.js'
import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.esm.js'

const props = defineProps<{
  projectId: string
  chapterId: string
}>()

// 撤销/重做动作类型
interface UndoAction {
  type: 'create_region' | 'delete_region' | 'move_region' | 'trim_audio' | 'mute_segment' | 'volume_change'
  regionId?: string
  trackIndex?: number
  startTime?: number
  endTime?: number
  previousValue?: any
  newValue?: any
}

// 区域标注数据结构
interface EditorRegion {
  id: string
  startTime: number
  endTime: number
  label: string
  color: string
  track: 'main' | 'bgm' | 'sfx'
}

const undoStack = ref<UndoAction[]>([])
const redoStack = ref<UndoAction[]>([])
const MAX_UNDO_STEPS = 50

// 工具状态
const currentTool = ref<'select' | 'cut' | 'move' | 'region'>('select')
const zoomLevel = ref(10)

// 轨道静音状态
const mainTrackMuted = ref(false)
const bgmTrackMuted = ref(false)
const sfxTrackMuted = ref(false)

// 音量状态
const mainVolume = ref(1)
const bgmVolume = ref(0.5)
const sfxVolume = ref(0.8)

// 区域标注
const regions = ref<EditorRegion[]>([])
const selectedRegionId = ref<string | null>(null)
const isCreatingRegion = ref(false)
const regionStart = ref(0)
const regionEnd = ref(0)
const regionLabel = ref('')

// DOM 引用
const mainTrackRef = ref<HTMLElement | null>(null)
const bgmTrackRef = ref<HTMLElement | null>(null)
const sfxTrackRef = ref<HTMLElement | null>(null)

let mainSurfer: WaveSurfer | null = null
let bgmSurfer: WaveSurfer | null = null
let sfxSurfer: WaveSurfer | null = null
let mainRegions: ReturnType<typeof RegionsPlugin.create> | null = null
let bgmRegions: ReturnType<typeof RegionsPlugin.create> | null = null
let sfxRegions: ReturnType<typeof RegionsPlugin.create> | null = null

// 撤销：添加动作到栈
function pushUndo(action: UndoAction) {
  if (undoStack.value.length >= MAX_UNDO_STEPS) {
    undoStack.value.shift()
  }
  undoStack.value.push(action)
  redoStack.value = []
  saveToLocalStorage()
}

// 撤销
function undo() {
  if (undoStack.value.length === 0) return
  const action = undoStack.value.pop()
  if (!action) return

  executeUndo(action)
  redoStack.value.push(action)
  saveToLocalStorage()
}

// 重做
function redo() {
  if (redoStack.value.length === 0) return
  const action = redoStack.value.pop()
  if (!action) return

  executeRedo(action)
  undoStack.value.push(action)
  saveToLocalStorage()
}

// 执行撤销逻辑
function executeUndo(action: UndoAction) {
  switch (action.type) {
    case 'create_region':
      if (action.regionId) {
        removeRegionById(action.regionId)
      }
      break
    case 'delete_region':
      if (action.previousValue) {
        regions.value.push(action.previousValue as EditorRegion)
        addRegionToWaveSurfer(action.previousValue as EditorRegion)
      }
      break
    case 'move_region':
      if (action.regionId && action.previousValue) {
        updateRegion(action.regionId, action.previousValue as Partial<EditorRegion>)
      }
      break
  }
}

// 执行重做逻辑
function executeRedo(action: UndoAction) {
  switch (action.type) {
    case 'create_region':
      if (action.newValue) {
        regions.value.push(action.newValue as EditorRegion)
        addRegionToWaveSurfer(action.newValue as EditorRegion)
      }
      break
    case 'delete_region':
      if (action.regionId) {
        removeRegionById(action.regionId)
      }
      break
    case 'move_region':
      if (action.regionId && action.newValue) {
        updateRegion(action.regionId, action.newValue as Partial<EditorRegion>)
      }
      break
  }
}

// 移除区域
function removeRegionById(id: string) {
  const idx = regions.value.findIndex(r => r.id === id)
  if (idx !== -1) {
    regions.value.splice(idx, 1)
    // 从 WaveSurfer 移除
    mainRegions?.getRegions().forEach((r: any) => {
      if (r.id === id) r.remove()
    })
    bgmRegions?.getRegions().forEach((r: any) => {
      if (r.id === id) r.remove()
    })
    sfxRegions?.getRegions().forEach((r: any) => {
      if (r.id === id) r.remove()
    })
  }
}

// 更新区域
function updateRegion(id: string, updates: Partial<EditorRegion>) {
  const region = regions.value.find(r => r.id === id)
  if (region) {
    Object.assign(region, updates)
    // 同步到 WaveSurfer
    mainRegions?.getRegions().forEach((r: any) => {
      if (r.id === id) {
        if (updates.startTime !== undefined) r.setOptions({ start: updates.startTime })
        if (updates.endTime !== undefined) r.setOptions({ end: updates.endTime })
      }
    })
  }
}

// 添加区域到 WaveSurfer
function addRegionToWaveSurfer(region: EditorRegion) {
  const options = {
    id: region.id,
    start: region.startTime,
    end: region.endTime,
    color: region.color + '40',
    drag: true,
    resize: true,
  }

  if (region.track === 'main') {
    mainRegions?.addRegion(options)
  } else if (region.track === 'bgm') {
    bgmRegions?.addRegion(options)
  } else if (region.track === 'sfx') {
    sfxRegions?.addRegion(options)
  }
}

// 保存状态到 localStorage
function saveToLocalStorage() {
  const state = {
    undoStack: undoStack.value,
    redoStack: redoStack.value,
    currentTool: currentTool.value,
    zoomLevel: zoomLevel.value,
    regions: regions.value,
  }
  localStorage.setItem(`multi-track-editor-${props.projectId}-${props.chapterId}`, JSON.stringify(state))
}

// 从 localStorage 加载
function loadFromLocalStorage() {
  const saved = localStorage.getItem(`multi-track-editor-${props.projectId}-${props.chapterId}`)
  if (saved) {
    const state = JSON.parse(saved)
    undoStack.value = state.undoStack || []
    redoStack.value = state.redoStack || []
    currentTool.value = state.currentTool || 'select'
    zoomLevel.value = state.zoomLevel || 10
    regions.value = state.regions || []

    // 恢复选中的区域
    if (state.selectedRegionId) {
      selectedRegionId.value = state.selectedRegionId
    }
  }
}

// 工具选择
function selectTool(tool: 'select' | 'cut' | 'move' | 'region') {
  currentTool.value = tool
}

// 缩放控制
function zoomIn() {
  zoomLevel.value = Math.min(zoomLevel.value + 5, 50)
  mainSurfer?.zoom(zoomLevel.value)
}

function zoomOut() {
  zoomLevel.value = Math.max(zoomLevel.value - 5, 5)
  mainSurfer?.zoom(zoomLevel.value)
}

// 静音切换
function toggleMainMute() {
  mainTrackMuted.value = !mainTrackMuted.value
  mainSurfer?.setMuted(mainTrackMuted.value)
}

function toggleBGMMute() {
  bgmTrackMuted.value = !bgmTrackMuted.value
  bgmSurfer?.setMuted(bgmTrackMuted.value)
}

function toggleSFXMute() {
  sfxTrackMuted.value = !sfxTrackMuted.value
  sfxSurfer?.setMuted(sfxTrackMuted.value)
}

// 音量调整
function handleMainVolumeChange(e: Event) {
  const value = (e.target as HTMLInputElement).value
  mainVolume.value = parseFloat(value)
  mainSurfer?.setVolume(mainVolume.value)
}

function handleBGMVolumeChange(e: Event) {
  const value = (e.target as HTMLInputElement).value
  bgmVolume.value = parseFloat(value)
  bgmSurfer?.setVolume(bgmVolume.value)
}

function handleSFXVolumeChange(e: Event) {
  const value = (e.target as HTMLInputElement).value
  sfxVolume.value = parseFloat(value)
  sfxSurfer?.setVolume(sfxVolume.value)
}

// 创建区域
function startCreatingRegion() {
  isCreatingRegion.value = true
  selectTool('region')
}

// 确认创建区域
function confirmCreateRegion() {
  if (!regionLabel.value.trim()) {
    alert('请输入区域标签')
    return
  }

  const newRegion: EditorRegion = {
    id: `region-${Date.now()}`,
    startTime: Math.min(regionStart.value, regionEnd.value),
    endTime: Math.max(regionStart.value, regionEnd.value),
    label: regionLabel.value.trim(),
    color: getCurrentToolColor(),
    track: 'main',
  }

  pushUndo({
    type: 'create_region',
    newValue: { ...newRegion },
  })

  regions.value.push(newRegion)
  addRegionToWaveSurfer(newRegion)

  // 重置状态
  isCreatingRegion.value = false
  regionLabel.value = ''
  regionStart.value = 0
  regionEnd.value = 0
}

// 取消创建区域
function cancelCreateRegion() {
  isCreatingRegion.value = false
  regionLabel.value = ''
  regionStart.value = 0
  regionEnd.value = 0
  selectTool('select')
}

// 删除选中区域
function deleteSelectedRegion() {
  if (!selectedRegionId.value) return

  const region = regions.value.find(r => r.id === selectedRegionId.value)
  if (!region) return

  pushUndo({
    type: 'delete_region',
    regionId: region.id,
    previousValue: { ...region },
  })

  removeRegionById(region.id)
  selectedRegionId.value = null
}

// 获取当前工具颜色
function getCurrentToolColor(): string {
  switch (currentTool.value) {
    case 'region':
      return '#4f46e5'
    default:
      return '#4f46e5'
  }
}

// 键盘快捷键
function handleKeyDown(e: KeyboardEvent) {
  // Cmd/Ctrl + Z 撤销
  if ((e.metaKey || e.ctrlKey) && e.key === 'z' && !e.shiftKey) {
    e.preventDefault()
    undo()
    return
  }

  // Cmd/Ctrl + Shift + Z 重做
  if ((e.metaKey || e.ctrlKey) && e.key === 'z' && e.shiftKey) {
    e.preventDefault()
    redo()
    return
  }

  // Delete 删除选中区域
  if (e.key === 'Delete' && selectedRegionId.value) {
    e.preventDefault()
    deleteSelectedRegion()
    return
  }

  // 空格键播放/暂停
  if (e.key === ' ' && e.target === document.body) {
    e.preventDefault()
    handlePlayPause()
  }

  // +/- 缩放
  if (e.key === '+' || e.key === '=') {
    zoomIn()
  }
  if (e.key === '-') {
    zoomOut()
  }
}

// 播放/暂停
const handlePlayPause = () => {
  mainSurfer?.playPause()
  bgmSurfer?.playPause()
  sfxSurfer?.playPause()
}

// 计算属性
const canUndo = computed(() => undoStack.value.length > 0)
const canRedo = computed(() => redoStack.value.length > 0)
const hasSelectedRegion = computed(() => selectedRegionId.value !== null)

onMounted(() => {
  // 创建主轨道 WaveSurfer + Regions
  if (mainTrackRef.value) {
    mainRegions = RegionsPlugin.create()
    mainSurfer = WaveSurfer.create({
      container: mainTrackRef.value,
      waveColor: '#4f46e5',
      progressColor: '#312e81',
      height: 80,
      cursorWidth: 2,
      plugins: [mainRegions],
    })

    // 加载音频
    mainSurfer.load('/audio/main-track.wav').catch(() => {
      console.log('Main track audio not found, using placeholder')
    })

    // 监听区域点击
    mainRegions.on('region-clicked', (region: any, e: Event) => {
      e.stopPropagation()
      selectedRegionId.value = region.id
    })

    // 监听区域创建
    mainRegions.on('region-created', (region: any) => {
      if (isCreatingRegion.value) {
        regionStart.value = region.start
        regionEnd.value = region.end
      }
    })

    // 监听时间更新（用于显示当前播放位置）
    mainSurfer.on('audioprocess', () => {
      // 可在此实现播放头同步
    })
  }

  // BGM 轨道
  if (bgmTrackRef.value) {
    bgmRegions = RegionsPlugin.create()
    bgmSurfer = WaveSurfer.create({
      container: bgmTrackRef.value,
      waveColor: '#10b981',
      progressColor: '#065f46',
      height: 60,
      plugins: [bgmRegions],
    })
  }

  // SFX 轨道
  if (sfxTrackRef.value) {
    sfxRegions = RegionsPlugin.create()
    sfxSurfer = WaveSurfer.create({
      container: sfxTrackRef.value,
      waveColor: '#f59e0b',
      progressColor: '#b45309',
      height: 60,
      plugins: [sfxRegions],
    })
  }

  // 加载 localStorage
  loadFromLocalStorage()

  // 恢复已存储的区域
  regions.value.forEach(region => {
    addRegionToWaveSurfer(region)
  })

  // 绑定键盘事件
  window.addEventListener('keydown', handleKeyDown)

  // 同步播放
  if (mainSurfer && bgmSurfer && sfxSurfer) {
    mainSurfer.on('play', () => {
      bgmSurfer!.play()
      sfxSurfer!.play()
    })
    mainSurfer.on('pause', () => {
      bgmSurfer!.pause()
      sfxSurfer!.pause()
    })
  }
})

onUnmounted(() => {
  mainSurfer?.destroy()
  bgmSurfer?.destroy()
  sfxSurfer?.destroy()
  window.removeEventListener('keydown', handleKeyDown)
})
</script>

<template>
  <div class="multi-track-editor p-4 bg-white rounded-lg shadow">
    <!-- 工具栏 -->
    <div class="toolbar flex items-center justify-between mb-4 p-2 bg-gray-100 rounded">
      <div class="controls flex items-center gap-2">
        <button @click="handlePlayPause" class="btn btn-primary px-4 py-2 bg-indigo-600 text-white rounded shadow hover:bg-indigo-700">
          Play/Pause
        </button>
        <button @click="zoomIn" class="btn bg-gray-200 px-3 py-1 rounded hover:bg-gray-300" title="Zoom In (+)">
          Zoom +
        </button>
        <button @click="zoomOut" class="btn bg-gray-200 px-3 py-1 rounded hover:bg-gray-300" title="Zoom Out (-)">
          Zoom -
        </button>
      </div>
      <div class="tools flex gap-2">
        <button
          @click="selectTool('select')"
          :class="['btn px-3 py-1 rounded', currentTool === 'select' ? 'bg-indigo-500 text-white' : 'bg-gray-200 hover:bg-gray-300']"
          title="选择工具 (V)"
        >
          Select
        </button>
        <button
          @click="selectTool('region')"
          :class="['btn px-3 py-1 rounded', currentTool === 'region' ? 'bg-indigo-500 text-white' : 'bg-gray-200 hover:bg-gray-300']"
          title="区域标注工具 (R)"
        >
          Region
        </button>
        <button
          @click="startCreatingRegion"
          class="btn px-3 py-1 rounded bg-green-500 text-white hover:bg-green-600"
          title="创建新区域"
        >
          + Region
        </button>
        <button @click="undo" :disabled="!canUndo" class="btn bg-gray-200 px-3 py-1 rounded hover:bg-gray-300 disabled:opacity-50" title="Undo (Cmd+Z)">
          Undo (⌘Z)
        </button>
        <button @click="redo" :disabled="!canRedo" class="btn bg-gray-200 px-3 py-1 rounded hover:bg-gray-300 disabled:opacity-50" title="Redo (Cmd+Shift+Z)">
          Redo (⇧⌘Z)
        </button>
        <button
          v-if="hasSelectedRegion"
          @click="deleteSelectedRegion"
          class="btn bg-red-500 px-3 py-1 rounded text-white hover:bg-red-600"
          title="删除选中区域 (Delete)"
        >
          Delete
        </button>
      </div>
    </div>

    <!-- 创建区域对话框 -->
    <div v-if="isCreatingRegion" class="region-creator mb-4 p-4 bg-indigo-50 rounded border border-indigo-200">
      <h4 class="font-bold mb-2 text-indigo-800">创建区域标注</h4>
      <div class="flex items-center gap-4">
        <input
          v-model="regionLabel"
          type="text"
          placeholder="输入区域标签（如：对白、旁白、紧张场景）"
          class="flex-1 px-3 py-2 border rounded focus:outline-none focus:ring-2 focus:ring-indigo-500"
          @keyup.enter="confirmCreateRegion"
        />
        <button @click="confirmCreateRegion" class="btn bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700">
          确认
        </button>
        <button @click="cancelCreateRegion" class="btn bg-gray-300 text-gray-700 px-4 py-2 rounded hover:bg-gray-400">
          取消
        </button>
      </div>
      <p class="text-sm text-indigo-600 mt-2">提示：在波形上拖拽选择区域，或使用播放头位置定义起点和终点</p>
    </div>

    <!-- 状态栏 -->
    <div class="status-bar mb-4 p-2 bg-gray-50 rounded text-sm text-gray-600 flex items-center justify-between">
      <span>撤销：{{ undoStack.length }} / 重做：{{ redoStack.length }}</span>
      <span>工具：{{ currentTool }}</span>
      <span>区域：{{ regions.length }}</span>
      <span>缩放：{{ zoomLevel }}px/s</span>
      <span v-if="selectedRegionId">选中：{{ selectedRegionId }}</span>
    </div>

    <!-- 音轨 -->
    <div class="tracks flex flex-col gap-4">
      <!-- 主音轨 -->
      <div class="track-row flex gap-4 items-center">
        <div class="track-info w-32 shrink-0 font-medium flex flex-col gap-2">
          <span>Main Voice</span>
          <div class="flex items-center gap-2">
            <button @click="toggleMainMute" :class="['px-2 py-1 rounded text-xs', mainTrackMuted ? 'bg-red-500 text-white' : 'bg-gray-200']">
              {{ mainTrackMuted ? 'Muted' : 'Mute' }}
            </button>
            <input type="range" :value="mainVolume" @input="handleMainVolumeChange" min="0" max="1" step="0.1" class="w-16" />
          </div>
        </div>
        <div class="track-waveform flex-1 border border-gray-300 rounded bg-gray-50" ref="mainTrackRef"></div>
      </div>

      <!-- BGM 轨道 -->
      <div class="track-row flex gap-4 items-center">
        <div class="track-info w-32 shrink-0 font-medium text-green-600 flex flex-col gap-2">
          <span>Background (BGM)</span>
          <div class="flex items-center gap-2">
            <button @click="toggleBGMMute" :class="['px-2 py-1 rounded text-xs', bgmTrackMuted ? 'bg-red-500 text-white' : 'bg-gray-200']">
              {{ bgmTrackMuted ? 'Muted' : 'Mute' }}
            </button>
            <input type="range" :value="bgmVolume" @input="handleBGMVolumeChange" min="0" max="1" step="0.1" class="w-16" />
          </div>
        </div>
        <div class="track-waveform flex-1 border border-gray-300 rounded bg-gray-50" ref="bgmTrackRef"></div>
      </div>

      <!-- SFX 轨道 -->
      <div class="track-row flex gap-4 items-center">
        <div class="track-info w-32 shrink-0 font-medium text-yellow-600 flex flex-col gap-2">
          <span>Sound Effects (SFX)</span>
          <div class="flex items-center gap-2">
            <button @click="toggleSFXMute" :class="['px-2 py-1 rounded text-xs', sfxTrackMuted ? 'bg-red-500 text-white' : 'bg-gray-200']">
              {{ sfxTrackMuted ? 'Muted' : 'Mute' }}
            </button>
            <input type="range" :value="sfxVolume" @input="handleSFXVolumeChange" min="0" max="1" step="0.1" class="w-16" />
          </div>
        </div>
        <div class="track-waveform flex-1 border border-gray-300 rounded bg-gray-50" ref="sfxTrackRef"></div>
      </div>
    </div>

    <!-- 区域列表 -->
    <div v-if="regions.length > 0" class="region-list mt-4 p-4 bg-gray-50 rounded">
      <h4 class="font-bold mb-2">区域标注列表</h4>
      <div class="flex flex-wrap gap-2">
        <div
          v-for="region in regions"
          :key="region.id"
          :class="['px-3 py-1 rounded text-sm cursor-pointer border', selectedRegionId === region.id ? 'bg-indigo-100 border-indigo-400' : 'bg-white border-gray-300 hover:bg-gray-100']"
          @click="selectedRegionId = region.id"
          :style="{ borderLeftColor: region.color }"
        >
          <span class="font-medium">{{ region.label }}</span>
          <span class="text-gray-500 text-xs ml-2">{{ region.startTime.toFixed(1) }}s - {{ region.endTime.toFixed(1) }}s</span>
        </div>
      </div>
    </div>

    <!-- 快捷键提示 -->
    <div class="shortcuts mt-4 p-3 bg-gray-50 rounded text-sm text-gray-600">
      <h4 class="font-bold mb-2">快捷键：</h4>
      <ul class="grid grid-cols-2 gap-2">
        <li><kbd class="px-2 py-1 bg-gray-200 rounded">Space</kbd> 播放/暂停</li>
        <li><kbd class="px-2 py-1 bg-gray-200 rounded">⌘Z</kbd> 撤销</li>
        <li><kbd class="px-2 py-1 bg-gray-200 rounded">⇧⌘Z</kbd> 重做</li>
        <li><kbd class="px-2 py-1 bg-gray-200 rounded">Delete</kbd> 删除选中区域</li>
        <li><kbd class="px-2 py-1 bg-gray-200 rounded">+</kbd> 放大</li>
        <li><kbd class="px-2 py-1 bg-gray-200 rounded">-</kbd> 缩小</li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.track-waveform {
  position: relative;
  overflow: hidden;
  min-height: 60px;
}

input[type="range"] {
  cursor: pointer;
}

.shortcuts kbd {
  font-family: monospace;
}

.region-list {
  max-height: 200px;
  overflow-y: auto;
}
</style>