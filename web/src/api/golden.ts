/** Golden dataset API — 金标数据集管理（/api/golden/*） */
import api from './index'

export interface GoldenSample {
  id: string
  stage: string
  status?: string
  input?: unknown
  expected?: unknown
  created_at?: string
  [key: string]: unknown
}

export interface GoldenTrendPoint {
  date: string
  score: number
  [key: string]: unknown
}

export async function fetchGoldenSamples(params?: {
  stage?: string
  status?: string
  limit?: number
}): Promise<{ samples: GoldenSample[]; total?: number }> {
  const { data } = await api.get('/api/golden/samples', { params })
  return data
}

export async function fetchGoldenSample(stage: string, sampleId: string): Promise<GoldenSample> {
  const { data } = await api.get(`/api/golden/samples/${stage}/${sampleId}`)
  return data
}

export async function approveGoldenSample(sampleId: string): Promise<void> {
  await api.post(`/api/golden/approve/${sampleId}`)
}

export async function rejectGoldenSample(sampleId: string): Promise<void> {
  await api.post(`/api/golden/reject/${sampleId}`)
}

export async function contributeGoldenSample(payload: {
  stage: string
  input: unknown
  expected: unknown
}): Promise<{ id: string }> {
  const { data } = await api.post('/api/golden/contribute', payload)
  return data
}

export async function runGoldenRegression(): Promise<unknown> {
  const { data } = await api.post('/api/golden/run-regression')
  return data
}

export async function fetchGoldenTrend(): Promise<{ points: GoldenTrendPoint[] }> {
  const { data } = await api.get('/api/golden/trend')
  return data
}

export async function bootstrapFewshot(): Promise<unknown> {
  const { data } = await api.post('/api/golden/bootstrap-fewshot')
  return data
}
