/// <reference types="vite/client" />

// Vue module augmentation is handled by vite/client

// ── API Response Types ──────────────────────────────────────────────────────

export interface Project {
  id: number
  title: string
  author: string
  description?: string
  language?: string
  /** Book genre — drives SOP reflection rule-bucketing (matches backend Project.genre). */
  genre?: string
  status?: string
  /** 当前 7 阶段之一 (extract/analyze/annotate/edit/audio_postprocess/synthesize/quality) */
  current_stage?: string
  /** 0-1 进度 */
  progress?: number
  total_cost_usd?: number
  difficulty?: string
  created_at?: string
  updated_at?: string
}

export interface Chapter {
  id: number
  project_id: number
  index: number
  title?: string
  status?: string
  extract_status?: string
  analyze_status?: string
  annotate_status?: string
  edit_status?: string
  synthesize_status?: string
  quality_status?: string
  chapter_number?: number
  /** 人工终审门：null=未在审 | pending_review | approved */
  review_status?: string | null
}

/** v6 逐句三轴导演：单句韵律覆盖（字段全可选，缺省继承段落级；idx 为句序号从 0 起） */
export interface SentenceOverride {
  idx: number
  /** 句级增益 delta (dB)，加在段落级 volume 上 */
  gain_db?: number
  /** 替换段落级 rate */
  speed?: number
  /** 替换段落级 pitch (semitones) */
  pitch_st?: number
  /** 替换该句音色（支持 blend 语法 am_onyx+am_fenrir*0.55） */
  voice_id?: string
  /** 该句后静音毫秒（缺省段落级 micro 间隙 220ms，末句缺省 0） */
  pause_after_ms?: number
}

export interface Paragraph {
  id: number
  project_id: number
  chapter_id: number
  index: number
  text: string
  original_text?: string
  edited_text?: string
  speaker_canonical_name?: string
  character_name?: string
  is_dialogue?: boolean
  emotion?: string
  emotion_intensity?: number
  speech_rate?: number
  pitch_shift_semitones?: number
  needs_sfx?: boolean
  sfx_tags?: string[]
  pause_before_ms?: number
  pause_after_ms?: number
  notes?: string
  confidence?: number
  status?: string
  audio_segment_id?: number
  /** 人工终审覆盖：客户在合成前逐段强制指定（null=自动决策） */
  manual_voice_id?: string | null
  manual_engine?: string | null
  /** v6 逐句三轴导演：逐句韵律覆盖数组（null=无覆盖） */
  sentence_overrides?: SentenceOverride[] | null
  // Phase 5: Extended fields for detail view
  tts_edit_history?: any[]
  quality_records?: any[]
  routing_decision?: any
  annotations_full?: any
}

export interface AudioSegment {
  id: number
  paragraph_id: number
  segment_id: string
  file_path?: string
  duration_ms: number
  engine?: string
  voice_id?: string
  status?: string
}

export interface Character {
  id?: number
  project_id: number
  canonical_name: string
  name?: string
  aliases?: string[]
  gender?: string
  age_range?: string
  suggested_voice_id?: string
  sample_quote?: string
  /** P3b: per-character TTS prosody defaults */
  emotion?: string
  speech_rate?: number
  pitch_shift_semitones?: number
}

export interface QualityResult {
  id?: number
  paragraph_id: number
  overall_score: number
  speaker_clarity?: number
  emotion_match?: number
  prosody_naturalness?: number
  text_audio_alignment?: number
  issues?: string[]
  needs_regeneration?: boolean
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// Supported UI locales (mirrors SUPPORTED_LOCALES in i18n.js)
export type SupportedLocale = 'zh-CN' | 'en-US'

// Book Genre Type
export type BookGenre =
  | '古典小说'
  | '现代小说'
  | '武侠小说'
  | '科幻小说'
  | '奇幻小说'
  | '历史小说'
  | '悬疑小说'
  | '言情小说'
  | '传记文学'
  | '散文随笔'
  | '诗歌'
  | '戏剧'
  | '儿童文学'
  | '青春文学'
  | '其他'
  | ''
