import { ref, onUnmounted, type Ref } from 'vue'
import WaveSurfer from 'wavesurfer.js'

export function useWaveSurfer(containerRef: Ref<HTMLElement | null>) {
  const wavesurfer = ref<WaveSurfer | null>(null)
  const isPlaying = ref(false)
  const currentTime = ref(0)
  const duration = ref(0)
  const isReady = ref(false)
  const error = ref<string | null>(null)

  let unsubscribe: (() => void)[] = []

  async function load(url: string) {
    cleanup()
    error.value = null
    isReady.value = false

    if (!containerRef.value) {
      error.value = 'Container element not found'
      return
    }

    try {
      const ws = WaveSurfer.create({
        container: containerRef.value,
        waveColor: '#94a3b8',
        progressColor: '#3b82f6',
        cursorColor: '#3b82f6',
        cursorWidth: 1,
        barWidth: 2,
        barGap: 1,
        barRadius: 2,
        height: 80,
        normalize: true,
        backend: 'WebAudio',
        minPxPerSec: 50,
        fillParent: true,
        autoScroll: true,
        autoCenter: true,
      })

      ws.load(url)

      ws.on('ready', () => {
        isReady.value = true
        duration.value = ws.getDuration()
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

      wavesurfer.value = ws

      unsubscribe.push(() => ws.destroy())
    } catch (e: any) {
      error.value = e?.message || 'Failed to create wavesurfer'
    }
  }

  function play() {
    wavesurfer.value?.play()
  }

  function pause() {
    wavesurfer.value?.pause()
  }

  function playPause() {
    wavesurfer.value?.playPause()
  }

  function seekTo(time: number) {
    wavesurfer.value?.setTime(time)
  }

  function zoom(pxPerSec: number) {
    wavesurfer.value?.zoom(pxPerSec)
  }

  function skip(seconds: number) {
    const ws = wavesurfer.value
    if (!ws) return
    const newTime = Math.max(0, Math.min((currentTime.value + seconds), duration.value))
    ws.setTime(newTime)
  }

  function cleanup() {
    unsubscribe.forEach((fn) => fn())
    unsubscribe = []
    wavesurfer.value = null
    isReady.value = false
    isPlaying.value = false
    currentTime.value = 0
    duration.value = 0
  }

  onUnmounted(cleanup)

  return {
    wavesurfer, isPlaying, currentTime, duration, isReady, error,
    load, play, pause, playPause, seekTo, zoom, skip, cleanup,
  }
}
