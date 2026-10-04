/** SOP self-iteration API — 自我迭代规则库（/api/sop/*） */
import api from './index'

export interface SopGenreRules {
  genre: string
  rules: Record<string, unknown>
  version?: number
  updated_at?: string
}

export async function fetchSopGenres(): Promise<{ genres: string[] }> {
  const { data } = await api.get('/api/sop/genres')
  return data
}

export async function fetchSopGenreRules(genre: string): Promise<SopGenreRules> {
  const { data } = await api.get(`/api/sop/genres/${encodeURIComponent(genre)}/rules`)
  return data
}

export async function fetchSopSnapshot(): Promise<Record<string, unknown>> {
  const { data } = await api.get('/api/sop/config/snapshot')
  return data
}

export async function triggerSopReflection(genre: string): Promise<unknown> {
  const { data } = await api.post(`/api/sop/reflect/${encodeURIComponent(genre)}`)
  return data
}

export async function fetchSopBackgroundStatus(): Promise<Record<string, unknown>> {
  const { data } = await api.get('/api/sop/background/status')
  return data
}

export async function startSopBackground(): Promise<unknown> {
  const { data } = await api.post('/api/sop/background/start')
  return data
}

export async function stopSopBackground(): Promise<unknown> {
  const { data } = await api.post('/api/sop/background/stop')
  return data
}

export async function fetchSopQueueSize(): Promise<{ size: number }> {
  const { data } = await api.get('/api/sop/queue/size')
  return data
}

export async function applySopRules(payload: Record<string, unknown>): Promise<unknown> {
  const { data } = await api.post('/api/sop/import/apply-rules', payload)
  return data
}
