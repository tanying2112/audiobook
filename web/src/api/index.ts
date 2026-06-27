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

// ── HARNESS Self-Iteration Dashboard ─────────────────────────────────────

export interface SelfIterationStatus {
  running: boolean
  iteration_count: number
  last_iteration_time: string | null
  next_trigger_estimate: string | null
  unprocessed_feedback_count: number
  min_feedback_threshold: number
}

export interface FeedbackFunnel {
  total_feedback: number
  analyzed_count: number
  triggered_upgrade_count: number
  promotion_passed_count: number
  published_count: number
  conversion_rates: Record<string, number>
}

export interface PatternTagFrequency {
  tag: string
  count: number
  stage: string
  severity: string | null
}

export interface PatternHeatmapResponse {
  patterns: PatternTagFrequency[]
  by_stage: Record<string, string[]>
  top_patterns: string[]
}

export interface PromptVersionTimelineItem {
  version: string
  stage: string
  created_at: string
  status: string
  triggered_by_patterns: string[]
  golden_score: number | null
}

export interface PromptVersionTimelineResponse {
  stages: Record<string, PromptVersionTimelineItem[]>
}

export interface PromotionGateResult {
  format_compliance_rate: number
  golden_pass_rate: number
  quality_score_ratio: number
  human_preference_rate: number
  overall_pass: boolean
  thresholds: Record<string, number>
}

export interface CanaryStatus {
  canary_id: string
  version: string
  stage: string
  traffic_pct: number
  samples_collected: number
  quality_ratio: number
  max_duration_hours: number
  remaining_hours: number
  auto_rollback_triggered: boolean
  status: string
}

export interface CanaryDashboardResponse {
  active_canaries: CanaryStatus[]
  total_active: number
}

export interface ABTestResult {
  test_id: string
  variant_a: string
  variant_b: string
  sample_count: number
  score_a: number
  score_b: number
  improvement_pct: number
  p_value: number
  statistically_significant: boolean
  winner: string | null
  confidence_interval: string | null
}

export interface ABTestDashboardResponse {
  tests: ABTestResult[]
  total_tests: number
}

export interface CriticVerdict {
  critic_type: string
  verdict: string
  score: number
  reasoning: string
}

export interface CriticEnsembleResult {
  verdicts: CriticVerdict[]
  weighted_verdict: string
  weighted_score: number
  calibration_f1: number
}

export interface HarnessDashboardResponse {
  iteration_status: SelfIterationStatus
  feedback_funnel: FeedbackFunnel
  pattern_heatmap: PatternHeatmapResponse
  prompt_timeline: PromptVersionTimelineResponse
  promotion_gate: PromotionGateResult
  canary_dashboard: CanaryDashboardResponse
  ab_tests: ABTestDashboardResponse
  critics_latest: CriticEnsembleResult
}

export async function fetchHarnessDashboard(): Promise<HarnessDashboardResponse> {
  const { data } = await api.get('/api/harness/dashboard')
  return data
}

export async function fetchHarnessStatus(): Promise<SelfIterationStatus> {
  const { data } = await api.get('/api/harness/status')
  return data
}

export async function fetchFeedbackFunnel(): Promise<FeedbackFunnel> {
  const { data } = await api.get('/api/harness/feedback-funnel')
  return data
}

export async function fetchPatternHeatmap(): Promise<PatternHeatmapResponse> {
  const { data } = await api.get('/api/harness/pattern-heatmap')
  return data
}

export async function fetchPromptTimeline(stage?: string): Promise<PromptVersionTimelineResponse> {
  const params = stage ? { stage } : {}
  const { data } = await api.get('/api/harness/prompt-timeline', { params })
  return data
}

export async function fetchPromotionGate(): Promise<PromotionGateResult> {
  const { data } = await api.get('/api/harness/promotion-gate')
  return data
}

export async function fetchCanaries(): Promise<CanaryDashboardResponse> {
  const { data } = await api.get('/api/harness/canaries')
  return data
}

export async function fetchABTests(): Promise<ABTestDashboardResponse> {
  const { data } = await api.get('/api/harness/ab-tests')
  return data
}

export async function fetchCriticResults(): Promise<CriticEnsembleResult> {
  const { data } = await api.get('/api/harness/critics/latest')
  return data
}

export async function triggerIteration(): Promise<{ status: string; message: string }> {
  const { data } = await api.post('/api/harness/trigger-iteration')
  return data
}

export async function rollbackVersion(
  stage: string,
  version: string,
): Promise<{ status: string; stage: string; version: string; message: string }> {
  const { data } = await api.post(`/api/harness/rollback/${stage}/${version}`)
  return data
}

// ── Auto-Run Pipeline ───────────────────────────────────────────────────

export interface AutoRunConfig {
  target_difficulty?: string
  primary_voice_preference?: string
  speech_rate_preference?: string
  cost_limit_usd?: number | null
  quality_threshold?: number
  max_regeneration_attempts?: number
  enable_background_music?: boolean
  enable_sfx?: boolean
}

export interface AutoRunStatusResponse {
  project_id: number
  run_id: string
  status: string
  current_stage: string | null
  completed_stages: string[]
  progress: number
  cost_usd: number
  quality_score: number | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  can_pause: boolean
  can_resume: boolean
  can_cancel: boolean
}

export async function startAutoRun(
  projectId: number,
  config?: AutoRunConfig,
): Promise<AutoRunStatusResponse> {
  const { data } = await api.post(`/api/projects/${projectId}/auto-run/start`, {
    config: config || {},
  })
  return data
}

export async function getAutoRunStatus(projectId: number): Promise<AutoRunStatusResponse> {
  const { data } = await api.get(`/api/projects/${projectId}/auto-run/status`)
  return data
}

export async function pauseAutoRun(projectId: number): Promise<{ action: string; status: string; message: string; run_id: string }> {
  const { data } = await api.post(`/api/projects/${projectId}/auto-run/pause`)
  return data
}

export async function resumeAutoRun(projectId: number): Promise<{ action: string; status: string; message: string; run_id: string }> {
  const { data } = await api.post(`/api/projects/${projectId}/auto-run/resume`)
  return data
}

export async function cancelAutoRun(projectId: number): Promise<{ action: string; status: string; message: string; run_id: string }> {
  const { data } = await api.post(`/api/projects/${projectId}/auto-run/cancel`)
  return data
}

export default api
