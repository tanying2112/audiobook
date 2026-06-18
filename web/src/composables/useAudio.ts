import { ref } from 'vue'
import * as api from '../api'

export function useAudio() {
  const regenerating = ref<Set<number>>(new Set())
  const audioError = ref<string | null>(null)

  function getAudioUrl(paragraphId: number): string {
    return `/api/paragraphs/${paragraphId}/audio`
  }

  async function regenerate(paragraphId: number): Promise<boolean> {
    if (regenerating.value.has(paragraphId)) return false

    regenerating.value = new Set([...regenerating.value, paragraphId])
    audioError.value = null

    try {
      await api.triggerRegeneration(paragraphId)
      // After regeneration, bust the audio cache by adding a timestamp
      const updated = new Set(regenerating.value)
      updated.delete(paragraphId)
      regenerating.value = updated
      return true
    } catch (e: any) {
      audioError.value = e?.response?.data?.detail || e?.message || '再生失败'
      const updated = new Set(regenerating.value)
      updated.delete(paragraphId)
      regenerating.value = updated
      return false
    }
  }

  function clearError() {
    audioError.value = null
  }

  return {
    regenerating,
    audioError,
    getAudioUrl,
    regenerate,
    clearError,
  }
}
