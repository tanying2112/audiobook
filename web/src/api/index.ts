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

// ── Upload ──────────────────────────────────────────────────────────────

export interface UploadStatusResponse {
  upload_id: string
  project_id: number
  filename: string
  status: string
  message: string
}

export async function uploadFile(
  projectId: number,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<UploadStatusResponse> {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await api.post(`/api/projects/${projectId}/upload`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (e.total && onProgress) {
        onProgress(Math.round((e.loaded * 100) / e.total))
      }
    },
  })
  return data
}

// ── Export ──────────────────────────────────────────────────────────────

export interface ExportRequest {
  formats: string[]
  normalize?: boolean
  include_cover?: boolean
  max_chars_per_line?: number
}

export interface ExportStatusResponse {
  status: string
  output_paths: Record<string, string>
  error?: string
  chapter_count: number
}

export async function startExport(projectId: number, config: ExportRequest): Promise<ExportStatusResponse> {
  const { data } = await api.post(`/api/projects/${projectId}/export/`, config)
  return data
}

export async function getExportStatus(projectId: number): Promise<ExportStatusResponse> {
  const { data } = await api.get(`/api/projects/${projectId}/export/status`)
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

// ── Auto-Run Autopilot ────────────────────────────────────────────────────

export interface AutopilotConfig {
  target_difficulty: string
  primary_voice_preference: string
  speech_rate_preference: string
  cost_limit_usd: number | null
  quality_threshold: number
  max_regeneration_attempts: number
  enable_background_music: boolean
  enable_sfx: boolean
  reasoning: string
  confidence: number
}

export async function startAutopilot(projectId: number): Promise<AutoRunStatusResponse> {
  const { data } = await api.post(`/api/projects/${projectId}/auto-run/autopilot`)
  return data
}

export async function previewAutopilotConfig(projectId: number): Promise<AutopilotConfig> {
  const { data } = await api.get(`/api/projects/${projectId}/auto-run/autopilot/preview`)
  return data
}

// ── Voice Cloning ──────────────────────────────────────────────────────

export interface CloneVoiceRequest {
  speaker_id: string
  language?: string
  text_content?: string
}

export interface CloneVoiceResponse {
  success: boolean
  speaker_id: string
  voice_id: string
  message: string
  quality?: string
  snr_db?: number
  sample_count?: number
}

export interface ClonedVoice {
  speaker_id: string
  voice_id: string
  quality: string
  snr_db: number
  sample_count: number
  created_at: string
}

export interface ListClonedVoicesResponse {
  cloned_voices: ClonedVoice[]
  count: number
}

export async function cloneVoice(
  file: File,
  speakerId: string,
  language: string = 'zh-CN',
  textContent: string = '',
  onProgress?: (percent: number) => void,
): Promise<CloneVoiceResponse> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('speaker_id', speakerId)
  formData.append('language', language)
  formData.append('text_content', textContent)

  const { data } = await api.post('/api/tts/voices/clone', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (e.total && onProgress) {
        onProgress(Math.round((e.loaded * 100) / e.total))
      }
    },
  })
  return data
}

export async function listClonedVoices(): Promise<ListClonedVoicesResponse> {
  const { data } = await api.get('/api/tts/voices/cloned')
  return data
}

export async function previewVoice(voiceId: string, text: string = '这是一个语音试听样本。'): Promise<{ preview_url: string }> {
  const { data } = await api.get(`/api/tts/voices/preview/${voiceId}`, { params: { text } })
  return data
}

export function getPreviewAudioUrl(voiceId: string): string {
  return `${API_BASE}/api/tts/voices/preview/${voiceId}`
}

// ── TTS Voices & Status ──────────────────────────────────────────────────

export interface TTSVoice {
  id: string
  name: string
  gender: string
  language: string
  description?: string
  sample_url?: string
}

export interface TTSEngine {
  id: string
  name: string
  available: boolean
  voices: TTSVoice[]
  priority: number
  supports_prosody: boolean
  supports_ssml: boolean
}

export interface TTSVoicesResponse {
  engines: Record<string, TTSEngine>
  total_voices: number
  default_engine: string
  default_voice: string
}

export interface TTSStatusResponse {
  local_engines_available: boolean
  kokoro_available: boolean
  kokoro_model_loaded: boolean
  voxcpm2_available: boolean
  voxcpm2_model_loaded: boolean
  sherpa_onnx_available: boolean
  cloud_engines_available: boolean
  edge_tts_available: boolean
  azure_available: boolean
  gcp_available: boolean
  recommended_engine: string
  recommended_voice: string
  enable_local_tts_env: boolean
}

export async function fetchTTSVoices(
  includeUnavailable = false,
  language?: string,
  gender?: string,
): Promise<TTSVoicesResponse> {
  const params: Record<string, string | boolean> = {}
  if (includeUnavailable) params.include_unavailable = 'true'
  if (language) params.language = language
  if (gender) params.gender = gender
  const { data } = await api.get('/api/tts/voices', { params })
  return data
}

export async function fetchTTSStatus(): Promise<TTSStatusResponse> {
  const { data } = await api.get('/api/tts/status')
  return data
}

export async function getRecommendedVoices(
  context?: string,
  language = 'zh-CN',
): Promise<{ context: string; recommended: TTSVoice[]; count: number }> {
  const params: Record<string, string> = {}
  if (context) params.context = context
  if (language) params.language = language
  const { data } = await api.get('/api/tts/voices/recommended', { params })
  return data
}

// ── Translation ─────────────────────────────────────────────────────────

export interface TranslationLanguage {
  code: string
  name: string
  native_name: string
}

export interface TranslationStartRequest {
  target_language: string
  chapter_indices?: number[]
  book_title?: string
  author?: string
}

export interface TranslationStatusResponse {
  status: string
  message: string
  progress: number
  total_segments: number
  successful_translations: number
  failed_translations: number
  emotional_continuity_passed: boolean | null
  semantic_coherence_score: number | null
}

export interface TranslationProgress {
  project_id: number
  total_original_segments: number
  total_translated_segments: number
  translation_ratio: number
}

export async function startTranslation(
  projectId: number,
  request: TranslationStartRequest,
): Promise<TranslationStatusResponse> {
  const { data } = await api.post(`/api/projects/${projectId}/pipeline/translate`, request)
  return data
}

export async function getTranslationStatus(projectId: number): Promise<TranslationProgress> {
  const { data } = await api.get(`/api/projects/${projectId}/pipeline/translate/status`)
  return data
}

export async function getSupportedLanguages(): Promise<{ languages: TranslationLanguage[] }> {
  const { data } = await api.get('/api/projects/1/pipeline/translate/languages')
  return data
}

// ── Monitoring / Telemetry ────────────────────────────────────────────────

export interface ProjectMetrics {
  metadata: {
    project_id: number
    pipeline_id: string
    started_at: string
    ended_at: string | null
    duration_ms: number
    success: boolean
  }
  cost_accounting: {
    total_cost_usd: number
    providers: Record<string, {
      provider: string
      model: string
      prompt_tokens: number
      completion_tokens: number
      cost_usd: number
      call_count: number
      avg_latency_ms: number
      success_rate: number
    }>
  }
  latency_profiles: {
    synthesis_rate_ratio: number
    real_time_factor: number
    total_audio_duration_ms: number
    stage_wall_times_ms: Record<string, { duration_ms: number; success: boolean }>
  }
  resilience_metrics: {
    llm: { total_calls: number; total_retries: number; total_fallbacks: number }
    tts: { total_segments: number; successful_segments: number; failed_segments: number }
  }
}

export interface MetricsHistoryItem {
  file: string
  timestamp: string
  duration_ms: number
  success: boolean
  total_cost_usd: number
  synthesis_rate_ratio: number
}

export interface MetricsHistoryResponse {
  history: MetricsHistoryItem[]
}

export interface ProjectWithMetrics {
  project_id: number
  title: string
  latest_metrics: string
  last_updated: string
}

export interface ProjectsWithMetricsResponse {
  projects: ProjectWithMetrics[]
}

export async function fetchProjectMetrics(
  projectId: number,
  chapterIndex?: number
): Promise<ProjectMetrics> {
  const params: Record<string, number> = {}
  if (chapterIndex !== undefined) params.chapter_index = chapterIndex
  const { data } = await api.get<ProjectMetrics>(`/monitoring/projects/${projectId}/metrics`, { params })
  return data
}

export async function fetchLatestProjectMetrics(projectId: number): Promise<ProjectMetrics> {
  const { data } = await api.get<ProjectMetrics>(`/monitoring/projects/${projectId}/metrics/latest`)
  return data
}

export async function fetchMetricsHistory(
  projectId: number,
  limit = 30
): Promise<MetricsHistoryResponse> {
  const { data } = await api.get<MetricsHistoryResponse>(`/monitoring/projects/${projectId}/metrics/history`, {
    params: { limit }
  })
  return data
}

export async function fetchProjectsWithMetrics(): Promise<ProjectsWithMetricsResponse> {
  const { data } = await api.get<ProjectsWithMetricsResponse>('/monitoring/projects')
  return data
}

export default api
