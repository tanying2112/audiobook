<template>
  <div class="waveform-editor-wrapper">
    <div class="waveform-editor">
      <!-- Toolbar -->
      <div class="editor-toolbar">
        <div class="toolbar-group playback">
          <button class="btn btn-icon" @click="playPause" :disabled="!isReady" :title="t('waveform.play_pause')">
            <Icon :icon="isPlaying ? 'mdi:pause' : 'mdi:play'" width="20" height="20" />
          </button>
          <button class="btn btn-icon" @click="seekTo(currentTime - 10)" :disabled="!isReady" :title="t('waveform.skip_backward')">
            <Icon icon="mdi:skip-backward" width="20" height="20" />
          </button>
          <button class="btn btn-icon" @click="seekTo(currentTime + 10)" :disabled="!isReady" :title="t('waveform.skip_forward')">
            <Icon icon="mdi:skip-forward" width="20" height="20" />
          </button>
          <div class="divider"></div>
          <div class="time-display">
            <span>{{ formatTime(currentTime) }}</span> / <span>{{ formatTime(duration) }}</span>
          </div>
        </div>

        <div class="toolbar-group zoom">
          <button class="btn btn-icon" @click="zoomOut" :title="t('waveform.zoom_out')">
            <Icon icon="mdi:magnify-minus" width="20" height="20" />
          </button>
          <input
            type="range"
            v-model="zoomLevel"
            :min="10"
            :max="500"
            :step="10"
            class="zoom-slider"
            @input="setZoom(zoomLevel)"
          />
          <button class="btn btn-icon" @click="zoomIn" :title="t('waveform.zoom_in')">
            <Icon icon="mdi:magnify-plus" width="20" height="20" />
          </button>
          <button class="btn btn-icon" @click="setZoom(50)" :title="t('waveform.zoom_fit')">
            <Icon icon="mdi:fit-to-screen" width="20" height="20" />
          </button>
        </div>

        <div class="toolbar-group undo">
          <button class="btn btn-icon" @click="undo" :disabled="!canUndo" :title="t('waveform.undo')">
            <Icon icon="mdi:undo" width="20" height="20" />
          </button>
          <button class="btn btn-icon" @click="redo" :disabled="!canRedo" :title="t('waveform.redo')">
            <Icon icon="mdi:redo" width="20" height="20" />
          </button>
        </div>

        <div class="toolbar-group regions">
          <button class="btn btn-icon" @click="enableRegionMode" :class="{ active: regionMode }" :title="t('waveform.add_region')">
            <Icon icon="mdi:segment" width="20" height="20" />
          </button>
          <button class="btn btn-icon" @click="clearSelection" :disabled="!selectedRegion" :title="t('waveform.clear_selection')">
            <Icon icon="mdi:deselect" width="20" height="20" />
          </button>
        </div>

        <div class="toolbar-group track-actions">
          <button class="btn btn-primary" @click="addTrackDialog = true" :title="t('waveform.add_track')">
            <Icon icon="mdi:plus" width="18" height="18" class="gap-2" />
            {{ t('waveform.add_track') }}
          </button>
        </div>
      </div>

      <!-- Track List + Waveform Container -->
      <div class="editor-main">
        <!-- Track List Sidebar -->
        <aside class="track-list-sidebar" :style="{ height: trackListHeight + 'px' }">
          <div class="track-header">
            <span class="track-col track-col-name">{{ t('waveform.track') }}</span>
            <span class="track-col track-col-controls">{{ t('waveform.controls') }}</span>
          </div>
          <div class="track-rows">
            <div
              v-for="(track, index) in tracks"
              :key="track.id"
              class="track-row"
              :class="{ active: activeTrackIndex === index, solo: track.solo, muted: track.muted, locked: track.locked }"
              @click="activeTrackIndex = index"
            >
              <div class="track-col track-col-color" :style="{ background: track.color }"></div>
              <div class="track-col track-col-name" :title="track.name">
                <input
                  v-if="renamingTrack === track.id"
                  v-model="renameValue"
                  @blur="finishRename(track.id)"
                  @keyup.enter="finishRename(track.id)"
                  @keyup.esc="cancelRename"
                  class="track-name-input"
                  ref="renameInput"
                />
                <span v-else @dblclick="startRename(track.id)">{{ track.name }}</span>
              </div>
              <div class="track-col track-col-controls">
                <button
                  class="btn btn-icon btn-sm"
                  @click.stop="toggleMute(track.id)"
                  :class="{ active: track.muted }"
                  :title="t('waveform.mute')"
                >
                  <Icon :icon="track.muted ? 'mdi:volume-off' : 'mdi:volume-high'" width="16" height="16" />
                </button>
                <button
                  class="btn btn-icon btn-sm"
                  @click.stop="toggleSolo(track.id)"
                  :class="{ active: track.solo }"
                  :title="t('waveform.solo')"
                >
                  <Icon icon="mdi:star" width="16" height="16" />
                </button>
                <button
                  class="btn btn-icon btn-sm"
                  @click.stop="toggleLock(track.id)"
                  :class="{ active: track.locked }"
                  :title="t('waveform.lock')"
                >
                  <Icon :icon="track.locked ? 'mdi:lock' : 'mdi:lock-open'" width="16" height="16" />
                </button>
                <button
                  class="btn btn-icon btn-sm"
                  @click.stop="removeTrack(track.id)"
                  :title="t('waveform.remove_track')"
                >
                  <Icon icon="mdi:delete" width="16" height="16" />
                </button>
                <button
                  class="btn btn-icon btn-sm drag-handle"
                  @mousedown.stop="startDragTrack(track.id, $event)"
                  :title="t('waveform.drag_reorder')"
                >
                  <Icon icon="mdi:drag" width="16" height="16" />
                </button>
              </div>
            </div>
          </div>
        </aside>

        <!-- Waveform Container -->
        <div class="waveform-container-wrapper">
          <div class="waveform-tracks" ref="tracksContainer">
            <!-- WaveSurfer creates its own canvases here -->
          </div>
          
          <!-- Playhead overlay -->
          <div 
            v-if="isReady" 
            class="playhead-overlay" 
            :style="{ left: playheadPosition + '%' }"
          >
            <div class="playhead-line"></div>
            <div class="playhead-time">{{ formatTime(currentTime) }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Region Inspector (when region selected) -->
    <div v-if="selectedRegionData" class="region-inspector">
      <h4>{{ t('waveform.region_properties') }}</h4>
      <div class="inspector-fields">
        <div class="field">
          <label>{{ t('waveform.track') }}</label>
          <span>{{ getTrackName(selectedRegionData.trackIndex) || 'Unknown' }}</span>
        </div>
        <div class="field">
          <label>{{ t('waveform.start_time') }}</label>
          <input 
            type="number" 
            step="0.01" 
            :value="selectedRegionData.start" 
            @input="updateRegionSelected({ start: Number(($event.target as HTMLInputElement).value) })" 
          />
          <span>{{ formatTime(selectedRegionData.start) }}</span>
        </div>
        <div class="field">
          <label>{{ t('waveform.end_time') }}</label>
          <input 
            type="number" 
            step="0.01" 
            :value="selectedRegionData.end" 
            @input="updateRegionSelected({ end: Number(($event.target as HTMLInputElement).value) })" 
          />
          <span>{{ formatTime(selectedRegionData.end) }}</span>
        </div>
        <div class="field">
          <label>{{ t('waveform.duration') }}</label>
          <span>{{ formatTime(selectedRegionData.end - selectedRegionData.start) }}</span>
        </div>
        <div class="field">
          <label>{{ t('waveform.label') }}</label>
          <input 
            type="text" 
            :value="selectedRegionData.data?.label || ''" 
            @input="updateRegionSelected({ data: { ...(selectedRegionData.data || {}), label: ($event.target as HTMLInputElement).value } })" 
          />
        </div>
        <div class="field">
          <label>{{ t('waveform.emotion') }}</label>
          <select 
            :value="selectedRegionData.data?.emotion || ''" 
            @change="updateRegionSelected({ data: { ...(selectedRegionData.data || {}), emotion: ($event.target as HTMLSelectElement).value } })"
          >
            <option value="">{{ t('waveform.select_emotion') }}</option>
            <option value="neutral">{{ t('waveform.emotion_neutral') }}</option>
            <option value="happy">{{ t('waveform.emotion_happy') }}</option>
            <option value="sad">{{ t('waveform.emotion_sad') }}</option>
            <option value="angry">{{ t('waveform.emotion_angry') }}</option>
            <option value="fearful">{{ t('waveform.emotion_fearful') }}</option>
            <option value="surprised">{{ t('waveform.emotion_surprised') }}</option>
            <option value="disgusted">{{ t('waveform.emotion_disgusted') }}</option>
            <option value="calm">{{ t('waveform.emotion_calm') }}</option>
          </select>
        </div>
        <div class="field">
          <label>{{ t('waveform.speech_rate') }}</label>
          <input 
            type="number" 
            step="0.1" 
            :value="selectedRegionData.data?.speech_rate || 1" 
            @input="updateRegionSelected({ data: { ...(selectedRegionData.data || {}), speech_rate: Number(($event.target as HTMLInputElement).value) } })" 
          />
        </div>
        <div class="field">
          <label>{{ t('waveform.pitch') }}</label>
          <input 
            type="number" 
            step="0.1" 
            :value="selectedRegionData.data?.pitch || 1" 
            @input="updateRegionSelected({ data: { ...(selectedRegionData.data || {}), pitch: Number(($event.target as HTMLInputElement).value) } })" 
          />
        </div>
        <div class="field">
          <label>{{ t('waveform.sfx') }}</label>
          <input 
            type="text" 
            :value="selectedRegionData.data?.sfx || ''" 
            @input="updateRegionSelected({ data: { ...(selectedRegionData.data || {}), sfx: ($event.target as HTMLInputElement).value } })" 
            :placeholder="t('waveform.sfx_placeholder')" 
          />
        </div>
        <div class="inspector-actions">
          <button class="btn btn-danger btn-sm" @click="removeRegion(selectedRegionData.trackIndex, selectedRegionData.id)">
            <Icon icon="mdi:delete" width="16" height="16" class="gap-2" />
            {{ t('waveform.delete_region') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Add Track Dialog -->
    <Teleport to="body">
      <div v-if="addTrackDialog" class="modal-overlay" @click="addTrackDialog = false">
        <div class="modal" @click.stop>
          <h3>{{ t('waveform.add_track_title') }}</h3>
          <div class="modal-field">
            <label>{{ t('waveform.track_name') }}</label>
            <input v-model="newTrackName" type="text" placeholder="{{ t('waveform.track_name_placeholder') }}" />
          </div>
          <div class="modal-field">
            <label>{{ t('waveform.audio_file') }}</label>
            <input type="file" accept="audio/*" @change="handleTrackFileSelect" style="display: none" ref="fileInput" />
            <button class="btn btn-outline" @click="fileInput?.click()">
              <Icon icon="mdi:file-upload" width="18" height="18" class="gap-2" />
              {{ newTrackFile ? newTrackFile.name : t('waveform.select_file') }}
            </button>
          </div>
          <div class="modal-actions">
            <button class="btn btn-outline" @click="cancelAddTrack">{{ t('common.cancel') }}</button>
            <button class="btn btn-primary" @click="confirmAddTrack" :disabled="!newTrackFile">{{ t('common.confirm') }}</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Export Regions Button -->
    <div class="editor-footer">
      <button class="btn btn-outline" @click="exportRegionsData">
        <Icon icon="mdi:download" width="18" height="18" class="gap-2" />
        {{ t('waveform.export_regions') }}
      </button>
      <span class="regions-count">{{ allRegions.length }} {{ t('waveform.regions_total') }}</span>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { useI18n } from '@/i18n'
import { Icon } from '@iconify/vue'
import { useMultiTrackWaveform, type WaveformTrack, type WaveformRegion } from '@/composables/useMultiTrackWaveform'

interface WaveformRegionWithTrack extends WaveformRegion {
  trackName: string
  trackColor: string
}

const props = defineProps<{
  initialTracks?: WaveformTrack[]
  height?: number
}>()

const emit = defineEmits<{
  'regions-change': [regions: WaveformRegionWithTrack[]]
  'track-change': [tracks: WaveformTrack[]]
}>()

const { t } = useI18n()

const tracksContainer = ref<HTMLElement | null>(null)
const renameInput = ref<HTMLInputElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

const renamingTrack = ref<string | null>(null)
const renameValue = ref('')
const addTrackDialog = ref(false)
const newTrackName = ref('')
const newTrackFile = ref<File | null>(null)
const regionMode = ref(false)
const draggedTrackId = ref<string | null>(null)

const {
  tracks,
  activeTrackIndex,
  isPlaying,
  currentTime,
  duration,
  isReady,
  zoomLevel,
  selectedRegion,
  allRegions,
  selectedRegionData,
  canUndo,
  canRedo,
  loadTracks,
  addTrack,
  removeTrack,
  removeRegion,
  clearSelection,
  updateRegion,
  playPause,
  seekTo,
  setZoom,
  zoomIn,
  zoomOut,
  toggleMute,
  toggleSolo,
  toggleLock,
  exportRegions,
  undo,
  redo,
} = useMultiTrackWaveform(tracksContainer, {
  tracks: props.initialTracks || [],
  height: props.height || 80,
  minPxPerSec: 50,
  enableRegions: true,
})

// Computed
const trackListHeight = computed(() => {
  return Math.max(200, tracks.value.length * 48 + 60)
})

const playheadPosition = computed(() => {
  if (duration.value <= 0) return 0
  return (currentTime.value / duration.value) * 100
})

// Initialize
onMounted(async () => {
  if (props.initialTracks && props.initialTracks.length > 0) {
    await loadTracks(props.initialTracks)
  }
})

// Format time helper
function formatTime(seconds: number): string {
  if (!seconds || seconds < 0) return '0:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  const ms = Math.floor((seconds % 1) * 100)
  return `${mins}:${secs.toString().padStart(2, '0')}.${ms.toString().padStart(2, '0')}`
}

// Track renaming
function startRename(trackId: string) {
  const track = tracks.value.find(t => t.id === trackId)
  if (track) {
    renamingTrack.value = trackId
    renameValue.value = track.name
    nextTick(() => renameInput.value?.focus())
  }
}

function finishRename(trackId: string) {
  const track = tracks.value.find(t => t.id === trackId)
  if (track && renameValue.value.trim()) {
    track.name = renameValue.value.trim()
  }
  renamingTrack.value = null
  renameValue.value = ''
}

function cancelRename() {
  renamingTrack.value = null
  renameValue.value = ''
}

function getTrackName(trackIndex: number): string {
  return tracks.value[trackIndex]?.name || `Track ${trackIndex + 1}`
}

// Track drag reorder
function startDragTrack(trackId: string, event: MouseEvent) {
  draggedTrackId.value = trackId
  event.preventDefault()
}

// Region mode (placeholder - regions are added manually for demo)
function enableRegionMode() {
  regionMode.value = !regionMode.value
  // Note: Full drag-to-create regions requires WaveSurfer Regions plugin
  // which has API changes in v7. This is a simplified demo.
}

// Update selected region
function updateRegionSelected(updates: Partial<WaveformRegion>) {
  if (selectedRegion.value) {
    updateRegion(selectedRegion.value.trackId, selectedRegion.value.regionId, updates)
  }
}

// Add track dialog
function handleTrackFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files && input.files[0]) {
    newTrackFile.value = input.files[0]
    if (!newTrackName.value) {
      newTrackName.value = newTrackFile.value.name.replace(/\.[^/.]+$/, '')
    }
  }
}

function cancelAddTrack() {
  addTrackDialog.value = false
  newTrackName.value = ''
  newTrackFile.value = null
}

function confirmAddTrack() {
  if (newTrackFile.value) {
    const url = URL.createObjectURL(newTrackFile.value)
    addTrack(url, newTrackName.value)
    cancelAddTrack()
  }
}

// Export regions
function exportRegionsData() {
  const regions = exportRegions()
  const dataStr = JSON.stringify(regions, null, 2)
  const blob = new Blob([dataStr], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `regions-${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.waveform-editor-wrapper {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.waveform-editor {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  overflow: hidden;
}
</style>
