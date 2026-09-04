/** Audio segment editing API — 音频精修（/api/audio-segments/*） */
import api from './index'

export interface AudioSegment {
  id: string
  file_path: string
  duration_ms: number
  text_hash?: string | null
  speaker?: string | null
  paragraph_index?: number | null
}

export async function fetchAudioSegments(bookId: string): Promise<AudioSegment[]> {
  const { data } = await api.get(`/api/audio-segments/book/${bookId}`)
  return data
}

export async function trimAudioSegment(
  segmentId: string,
  payload: { start_ms: number; end_ms: number },
  bookId?: string,
): Promise<unknown> {
  const { data } = await api.post(`/api/audio-segments/${segmentId}/trim`, payload, {
    params: bookId ? { book_id: bookId } : undefined,
  })
  return data
}

export async function mergeAudioSegments(
  segmentIds: string[],
  bookId?: string,
): Promise<unknown> {
  const { data } = await api.post(
    '/api/audio-segments/merge',
    { segment_ids: segmentIds },
    { params: bookId ? { book_id: bookId } : undefined },
  )
  return data
}

export async function reorderAudioSegments(
  segmentId: string,
  segmentIds: string[],
  crossfadeMs = 50,
  bookId?: string,
): Promise<unknown> {
  const { data } = await api.patch(
    `/api/audio-segments/${segmentId}/reorder`,
    { segment_ids: segmentIds, crossfade_ms: crossfadeMs },
    { params: bookId ? { book_id: bookId } : undefined },
  )
  return data
}

export async function deleteAudioSegment(segmentId: string, bookId?: string): Promise<void> {
  await api.delete(`/api/audio-segments/${segmentId}`, {
    params: bookId ? { book_id: bookId } : undefined,
  })
}
