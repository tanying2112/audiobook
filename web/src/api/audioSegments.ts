/** Audio segment editing API — 音频精修（/api/audio-segments/*） */
import api from './index'

export async function trimAudioSegment(
  segmentId: number,
  payload: { start_ms: number; end_ms: number },
): Promise<unknown> {
  const { data } = await api.post(`/api/audio-segments/${segmentId}/trim`, payload)
  return data
}

export async function mergeAudioSegments(payload: {
  segment_ids: number[]
}): Promise<unknown> {
  const { data } = await api.post('/api/audio-segments/merge', payload)
  return data
}

export async function reorderAudioSegment(
  segmentId: number,
  payload: { new_index: number },
): Promise<unknown> {
  const { data } = await api.patch(`/api/audio-segments/${segmentId}/reorder`, payload)
  return data
}

export async function deleteAudioSegment(segmentId: number): Promise<void> {
  await api.delete(`/api/audio-segments/${segmentId}`)
}
