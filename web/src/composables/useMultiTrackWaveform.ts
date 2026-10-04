import { ref, onUnmounted, type Ref, computed } from 'vue'
import WaveSurfer from 'wavesurfer.js'

export interface WaveformRegion {
  id: string
  start: number
  end: number
  trackIndex: number
  label?: string
  color?: string
  data?: Record<string, unknown>
  editable?: boolean
}

export interface WaveformTrack {
  id: string
  name: string
  url: string
  color: string
  muted: boolean
  solo: boolean
  locked: boolean
  regions: WaveformRegion[]
  wavesurfer?: any
}

export function useMultiTrackWaveform(
  containerRef: Ref<HTMLElement | null>,
  options: {
    tracks?: WaveformTrack[]
    height?: number
    minPxPerSec?: number
    enableRegions?: boolean
  } = {}
) {
  const {
    tracks: initialTracks = [],
    height = 80,
    minPxPerSec = 50,
  } = options

  // State
  const tracks = ref<WaveformTrack[]>(initialTracks.map((t, i) => ({ ...t, id: t.id || `track-${i}`, regions: t.regions || [] })))
  const activeTrackIndex = ref(0)
  const isPlaying = ref(false)
  const currentTime = ref(0)
  const duration = ref(0)
  const isReady = ref(false)
  const error = ref<string | null>(null)
  const zoomLevel = ref(minPxPerSec)

  // Undo/Redo stacks
  const undoStack: (() => void)[] = []
  const redoStack: (() => void)[] = []
  const maxUndoSteps = 50

  // Colors for tracks/regions
  const trackColors = [
    '#3b82f6', // blue
    '#10b981', // emerald
    '#f59e0b', // amber
    '#ef4444', // red
    '#8b5cf6', // violet
    '#ec4899', // pink
    '#06b6d4', // cyan
    '#84cc16', // lime
  ]

  // Get track color
  function getTrackColor(index: number): string {
    return trackColors[index % trackColors.length]
  }

  // Add action to undo stack
  function pushUndo(action: () => void) {
    undoStack.push(action)
    if (undoStack.length > maxUndoSteps) undoStack.shift()
    redoStack.length = 0
  }

  // Undo
  function undo() {
    const action = undoStack.pop()
    if (action) {
      redoStack.push(() => {})
      action()
    }
  }

  // Redo
  function redo() {
    const action = redoStack.pop()
    if (action) {
      undoStack.push(action)
      action()
    }
  }

  // Create WaveSurfer instance for a track
  function createTrackWaveSurfer(track: WaveformTrack, trackContainer: HTMLElement): WaveSurfer | null {
    try {
      const ws = WaveSurfer.create({
        container: trackContainer,
        waveColor: track.color,
        progressColor: track.color,
        cursorColor: '#ffffff',
        cursorWidth: 1,
        barWidth: 2,
        barGap: 1,
        barRadius: 2,
        height,
        normalize: true,
        backend: 'WebAudio',
        minPxPerSec: zoomLevel.value,
        fillParent: true,
        autoScroll: true,
        autoCenter: true,
        interact: true,
      })

      ws.load(track.url)

      ws.on('ready', () => {
        isReady.value = true
        duration.value = Math.max(duration.value, ws.getDuration())
      })

      ws.on('timeupdate', (time: number) => {
        currentTime.value = time
      })

      ws.on('play', () => { isPlaying.value = true })
      ws.on('pause', () => { isPlaying.value = false })
      ws.on('finish', () => { isPlaying.value = false })

      ws.on('error', (err: Error) => {
        error.value = err?.message || 'WaveSurfer error'
      })

      track.wavesurfer = ws
      return ws
    } catch (e: any) {
      error.value = e?.message || 'Failed to create wavesurfer'
      return null
    }
  }

  // Load all tracks
  async function loadTracks(newTracks: WaveformTrack[]) {
    cleanup()
    error.value = null
    isReady.value = false

    tracks.value = newTracks.map((t, i) => ({
      ...t,
      id: t.id || `track-${i}`,
      color: t.color || getTrackColor(i),
      regions: t.regions || [],
      muted: t.muted ?? false,
      solo: t.solo ?? false,
      locked: t.locked ?? false,
    }))

    if (!containerRef.value) {
      error.value = 'Container element not found'
      return
    }

    containerRef.value.innerHTML = ''

    for (const track of tracks.value) {
      const trackContainer = document.createElement('div')
      trackContainer.className = 'waveform-track-container'
      trackContainer.style.height = `${height}px`
      trackContainer.style.marginBottom = '8px'
      trackContainer.style.position = 'relative'
      containerRef.value.appendChild(trackContainer)

      const ws = createTrackWaveSurfer(track, trackContainer)
      if (ws) {
        track.wavesurfer = ws
      }
    }
  }

  // Add a track
  function addTrack(url: string, name?: string): string {
    const index = tracks.value.length
    const newTrack: WaveformTrack = {
      id: `track-${index}`,
      name: name || `Track ${index + 1}`,
      url,
      color: getTrackColor(index),
      muted: false,
      solo: false,
      locked: false,
      regions: [],
    }
    tracks.value.push(newTrack)

    if (containerRef.value) {
      const trackContainer = document.createElement('div')
      trackContainer.className = 'waveform-track-container'
      trackContainer.style.height = `${height}px`
      trackContainer.style.marginBottom = '8px'
      trackContainer.style.position = 'relative'
      containerRef.value.appendChild(trackContainer)

      const ws = createTrackWaveSurfer(newTrack, trackContainer)
      if (ws) {
        newTrack.wavesurfer = ws
      }
    }

    return newTrack.id
  }

  // Remove a track
  function removeTrack(trackId: string) {
    const trackIndex = tracks.value.findIndex(t => t.id === trackId)
    if (trackIndex < 0) return

    const track = tracks.value[trackIndex]
    track.wavesurfer?.destroy()

    if (containerRef.value && containerRef.value.children[trackIndex]) {
      containerRef.value.removeChild(containerRef.value.children[trackIndex])
    }

    tracks.value.splice(trackIndex, 1)
    pushUndo(() => addTrack(track.url, track.name))
  }

  // Add region to track (manual creation for demo)
  function addRegion(trackIndex: number, region: WaveformRegion) {
    const track = tracks.value[trackIndex]
    if (!track || track.locked) return
    track.regions.push(region)
  }

  // Remove region from track
  function removeRegion(trackIndex: number, regionId: string) {
    const track = tracks.value[trackIndex]
    if (!track) return
    track.regions = track.regions.filter(r => r.id !== regionId)
  }

  // Select region
  const selectedRegion = ref<{ trackId: string; regionId: string } | null>(null)

  function selectRegion(trackId: string, regionId: string) {
    selectedRegion.value = { trackId, regionId }
  }

  function clearSelection() {
    selectedRegion.value = null
  }

  // Update region properties
  function updateRegion(trackId: string, regionId: string, updates: Partial<WaveformRegion>) {
    const trackIndex = tracks.value.findIndex(t => t.id === trackId)
    if (trackIndex < 0) return

    const track = tracks.value[trackIndex]
    const regionIndex = track.regions.findIndex(r => r.id === regionId)
    if (regionIndex < 0) return

    const oldRegion = { ...track.regions[regionIndex] }
    track.regions[regionIndex] = { ...track.regions[regionIndex], ...updates }

    pushUndo(() => {
      track.regions[regionIndex] = oldRegion
    })
  }

  // Playback controls
  function play() {
    tracks.value.forEach(t => {
      if (!t.muted && !t.locked) t.wavesurfer?.play()
    })
  }

  function pause() {
    tracks.value.forEach(t => t.wavesurfer?.pause())
  }

  function playPause() {
    if (isPlaying.value) {
      pause()
    } else {
      play()
    }
  }

  function seekTo(time: number) {
    tracks.value.forEach(t => t.wavesurfer?.setTime(time))
  }

  function setZoom(pxPerSec: number) {
    zoomLevel.value = pxPerSec
    tracks.value.forEach(t => t.wavesurfer?.zoom(pxPerSec))
  }

  function zoomIn() {
    setZoom(zoomLevel.value * 1.5)
  }

  function zoomOut() {
    setZoom(zoomLevel.value / 1.5)
  }

  // Track controls
  function toggleMute(trackId: string) {
    const track = tracks.value.find(t => t.id === trackId)
    if (track) {
      track.muted = !track.muted
      if (track.wavesurfer) {
        track.wavesurfer.setVolume(track.muted ? 0 : 1)
      }
    }
  }

  function toggleSolo(trackId: string) {
    const track = tracks.value.find(t => t.id === trackId)
    if (track) {
      track.solo = !track.solo
      updateSoloStates()
    }
  }

  function toggleLock(trackId: string) {
    const track = tracks.value.find(t => t.id === trackId)
    if (track) {
      track.locked = !track.locked
    }
  }

  function updateSoloStates() {
    const hasSolo = tracks.value.some(t => t.solo)
    tracks.value.forEach(t => {
      if (t.wavesurfer) {
        const shouldMute = hasSolo && !t.solo
        t.wavesurfer.setVolume(shouldMute || t.muted ? 0 : 1)
      }
    })
  }

  // Reorder tracks
  function moveTrack(trackId: string, newIndex: number) {
    const oldIndex = tracks.value.findIndex(t => t.id === trackId)
    if (oldIndex < 0 || newIndex < 0 || newIndex >= tracks.value.length) return

    const [track] = tracks.value.splice(oldIndex, 1)
    tracks.value.splice(newIndex, 0, track)

    if (containerRef.value) {
      const container = containerRef.value
      if (newIndex > oldIndex) {
        container.insertBefore(container.children[newIndex], container.children[oldIndex])
      } else {
        container.insertBefore(container.children[oldIndex], container.children[newIndex])
      }
    }

    pushUndo(() => moveTrack(trackId, oldIndex))
  }

  // Export regions data
  function exportRegions(): WaveformRegion[] {
    return tracks.value.flatMap(t => t.regions.map(r => ({ ...r, trackName: t.name })))
  }

  // Import regions
  function importRegions(regions: WaveformRegion[]) {
    regions.forEach(r => {
      const track = tracks.value.find(t => t.id === `track-${r.trackIndex}`) || tracks.value[r.trackIndex]
      if (track) {
        addRegion(tracks.value.indexOf(track), r)
      }
    })
  }

  // Cleanup
  function cleanup() {
    tracks.value.forEach(t => t.wavesurfer?.destroy())
    tracks.value.forEach(t => { t.wavesurfer = undefined })
    if (containerRef.value) {
      containerRef.value.innerHTML = ''
    }
    isReady.value = false
    isPlaying.value = false
    currentTime.value = 0
    duration.value = 0
    undoStack.length = 0
    redoStack.length = 0
  }

  onUnmounted(cleanup)

  // Computed
  const activeTrack = computed(() => tracks.value[activeTrackIndex.value] || null)
  const allRegions = computed(() => tracks.value.flatMap((t, i) =>
    t.regions.map(r => ({ ...r, trackIndex: i, trackName: t.name, trackColor: t.color }))
  ))
  const selectedRegionData = computed(() => {
    if (!selectedRegion.value) return null
    const track = tracks.value.find(t => t.id === selectedRegion.value!.trackId)
    if (!track) return null
    return track.regions.find(r => r.id === selectedRegion.value!.regionId) || null
  })
  const canUndo = computed(() => undoStack.length > 0)
  const canRedo = computed(() => redoStack.length > 0)

  return {
    // State
    tracks,
    activeTrackIndex,
    isPlaying,
    currentTime,
    duration,
    isReady,
    error,
    zoomLevel,
    selectedRegion,

    // Computed
    activeTrack,
    allRegions,
    selectedRegionData,
    canUndo,
    canRedo,

    // Methods
    loadTracks,
    addTrack,
    removeTrack,
    addRegion,
    removeRegion,
    selectRegion,
    clearSelection,
    updateRegion,
    play,
    pause,
    playPause,
    seekTo,
    setZoom,
    zoomIn,
    zoomOut,
    toggleMute,
    toggleSolo,
    toggleLock,
    moveTrack,
    exportRegions,
    importRegions,
    cleanup,
    undo,
    redo,
    getTrackColor,
  }
}