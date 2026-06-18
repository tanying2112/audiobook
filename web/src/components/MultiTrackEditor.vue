<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import WaveSurfer from 'wavesurfer.js'
// import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.esm.js'

const props = defineProps<{
  projectId: string
  chapterId: string
}>()

const mainTrackRef = ref<HTMLElement | null>(null)
const bgmTrackRef = ref<HTMLElement | null>(null)
const sfxTrackRef = ref<HTMLElement | null>(null)

let mainSurfer: WaveSurfer | null = null
let bgmSurfer: WaveSurfer | null = null
let sfxSurfer: WaveSurfer | null = null

onMounted(() => {
  if (mainTrackRef.value) {
    mainSurfer = WaveSurfer.create({
      container: mainTrackRef.value,
      waveColor: '#4f46e5',
      progressColor: '#312e81',
      height: 80,
      cursorWidth: 2,
    })
  }

  if (bgmTrackRef.value) {
    bgmSurfer = WaveSurfer.create({
      container: bgmTrackRef.value,
      waveColor: '#10b981',
      progressColor: '#065f46',
      height: 60,
    })
  }

  if (sfxTrackRef.value) {
    sfxSurfer = WaveSurfer.create({
      container: sfxTrackRef.value,
      waveColor: '#f59e0b',
      progressColor: '#b45309',
      height: 60,
    })
  }
})

onUnmounted(() => {
  mainSurfer?.destroy()
  bgmSurfer?.destroy()
  sfxSurfer?.destroy()
})

const handlePlayPause = () => {
  mainSurfer?.playPause()
  bgmSurfer?.playPause()
  sfxSurfer?.playPause()
}
</script>

<template>
  <div class="multi-track-editor">
    <div class="toolbar flex items-center justify-between mb-4 p-2 bg-gray-100 rounded">
      <div class="controls">
        <button @click="handlePlayPause" class="btn btn-primary px-4 py-2 bg-indigo-600 text-white rounded shadow hover:bg-indigo-700">
          Play/Pause
        </button>
      </div>
      <div class="tools flex gap-2">
        <button class="btn bg-gray-200 px-3 py-1 rounded">Select</button>
        <button class="btn bg-gray-200 px-3 py-1 rounded">Cut</button>
        <button class="btn bg-gray-200 px-3 py-1 rounded">Undo (⌘Z)</button>
        <button class="btn bg-gray-200 px-3 py-1 rounded">Redo (⇧⌘Z)</button>
      </div>
    </div>

    <div class="tracks flex flex-col gap-4">
      <div class="track-row flex gap-4 items-center">
        <div class="track-info w-32 shrink-0 font-medium">Main Voice</div>
        <div class="track-waveform flex-1 border border-gray-300 rounded bg-gray-50" ref="mainTrackRef"></div>
      </div>
      <div class="track-row flex gap-4 items-center">
        <div class="track-info w-32 shrink-0 font-medium text-green-600">Background (BGM)</div>
        <div class="track-waveform flex-1 border border-gray-300 rounded bg-gray-50" ref="bgmTrackRef"></div>
      </div>
      <div class="track-row flex gap-4 items-center">
        <div class="track-info w-32 shrink-0 font-medium text-yellow-600">Sound Effects (SFX)</div>
        <div class="track-waveform flex-1 border border-gray-300 rounded bg-gray-50" ref="sfxTrackRef"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.track-waveform {
  position: relative;
  overflow: hidden;
}
</style>
