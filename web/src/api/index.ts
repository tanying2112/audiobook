import axios from 'axios'
import type { Project, Chapter, Paragraph, AudioSegment, Character, QualityResult } from '../types'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// ── Projects ────────────────────────────────────────────────────────────

export async function fetchProjects(): Promise<Project[]> {
  const { data } = await api.get('/api/projects/')
  return data
}

export async function fetchProject(id: number): Promise<Project> {
  const { data } = await api.get(`/api/projects/${id}`)
  return data
}

export async function createProject(payload: Partial<Project>): Promise<Project> {
  const { data } = await api.post('/api/projects/', payload)
  return data
}

export async function updateProject(id: number, payload: Partial<Project>): Promise<Project> {
  const { data } = await api.put(`/api/projects/${id}`, payload)
  return data
}

export async function deleteProject(id: number): Promise<void> {
  await api.delete(`/api/projects/${id}`)
}

// ── Chapters ────────────────────────────────────────────────────────────

export async function fetchChapters(projectId: number, skip = 0, limit = 100): Promise<Chapter[]> {
  const { data } = await api.get(`/api/projects/${projectId}/chapters/`, {
    params: { skip, limit },
  })
  return data
}

export async function fetchChapter(projectId: number, chapterId: number): Promise<Chapter> {
  const { data } = await api.get(`/api/projects/${projectId}/chapters/${chapterId}`)
  return data
}

// ── Paragraphs ──────────────────────────────────────────────────────────

export async function fetchParagraphs(
  projectId: number,
  chapterId: number,
  skip = 0,
  limit = 1000,
): Promise<Paragraph[]> {
  const { data } = await api.get(`/api/projects/${projectId}/chapters/${chapterId}/paragraphs/`, {
    params: { skip, limit },
  })
  return data
}

export async function fetchParagraph(projectId: number, chapterId: number, paragraphId: number): Promise<Paragraph> {
  const { data } = await api.get(
    `/api/projects/${projectId}/chapters/${chapterId}/paragraphs/${paragraphId}`,
  )
  return data
}

export async function updateParagraph(
  projectId: number,
  chapterId: number,
  paragraphId: number,
  payload: Partial<Paragraph>,
): Promise<Paragraph> {
  const { data } = await api.put(
    `/api/projects/${projectId}/chapters/${chapterId}/paragraphs/${paragraphId}`,
    payload,
  )
  return data
}

// ── Audio ───────────────────────────────────────────────────────────────

export async function fetchAudioSegments(paragraphId: number): Promise<AudioSegment[]> {
  const { data } = await api.get(`/api/paragraphs/${paragraphId}/audio-segments`)
  return data
}

export function getAudioUrl(paragraphId: number): string {
  return `${API_BASE}/api/paragraphs/${paragraphId}/audio`
}

export async function triggerRegeneration(paragraphId: number): Promise<void> {
  await api.post(`/api/paragraphs/${paragraphId}/regenerate`)
}

// ── Quality ─────────────────────────────────────────────────────────────

export async function fetchQualityResults(paragraphId: number): Promise<QualityResult[]> {
  const { data } = await api.get(`/api/paragraphs/${paragraphId}/quality`)
  return data
}

// ── Characters ──────────────────────────────────────────────────────────

export async function fetchCharacters(projectId: number): Promise<Character[]> {
  const { data } = await api.get(`/api/projects/${projectId}/characters`)
  return data
}

export async function createCharacter(projectId: number, payload: Partial<Character>): Promise<Character> {
  const { data } = await api.post(`/api/projects/${projectId}/characters`, payload)
  return data
}

export async function updateCharacter(
  projectId: number,
  characterId: number,
  payload: Partial<Character>,
): Promise<Character> {
  const { data } = await api.put(`/api/projects/${projectId}/characters/${characterId}`, payload)
  return data
}

export async function deleteCharacter(projectId: number, characterId: number): Promise<void> {
  await api.delete(`/api/projects/${projectId}/characters/${characterId}`)
}

export default api
