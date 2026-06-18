import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Chapter, Paragraph, AudioSegment, QualityResult } from '../types'
import * as api from '../api'

export const useChapterStore = defineStore('chapters', () => {
  const chapters = ref<Chapter[]>([])
  const currentChapter = ref<Chapter | null>(null)
  const paragraphs = ref<Paragraph[]>([])
  const audioSegments = ref<Map<number, AudioSegment[]>>(new Map())
  const qualityResults = ref<Map<number, QualityResult[]>>(new Map())
  const loading = ref(false)

  async function loadChapters(projectId: number) {
    loading.value = true
    try {
      chapters.value = await api.fetchChapters(projectId)
    } finally {
      loading.value = false
    }
  }

  async function loadChapter(projectId: number, chapterId: number) {
    loading.value = true
    try {
      currentChapter.value = await api.fetchChapter(projectId, chapterId)
    } finally {
      loading.value = false
    }
  }

  async function loadParagraphs(projectId: number, chapterId: number) {
    loading.value = true
    try {
      paragraphs.value = await api.fetchParagraphs(projectId, chapterId)
    } finally {
      loading.value = false
    }
  }

  async function updateParagraphText(
    projectId: number,
    chapterId: number,
    paragraphId: number,
    payload: Partial<Paragraph>,
  ) {
    const updated = await api.updateParagraph(projectId, chapterId, paragraphId, payload)
    const idx = paragraphs.value.findIndex((p) => p.id === paragraphId)
    if (idx !== -1) paragraphs.value[idx] = updated
    return updated
  }

  async function loadAudioSegments(paragraphId: number) {
    try {
      const segs = await api.fetchAudioSegments(paragraphId)
      audioSegments.value.set(paragraphId, segs)
    } catch {
      audioSegments.value.set(paragraphId, [])
    }
  }

  async function loadQuality(paragraphId: number) {
    try {
      const q = await api.fetchQualityResults(paragraphId)
      qualityResults.value.set(paragraphId, q)
    } catch {
      qualityResults.value.set(paragraphId, [])
    }
  }

  return {
    chapters, currentChapter, paragraphs, audioSegments, qualityResults, loading,
    loadChapters, loadChapter, loadParagraphs, updateParagraphText,
    loadAudioSegments, loadQuality,
  }
})
