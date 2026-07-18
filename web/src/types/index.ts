/// <reference types="vite/client" />

// Vue module augmentation is handled by vite/client

// ── API Response Types ──────────────────────────────────────────────────────

export interface Project {
  id: number
  title: string
  author: string
  description?: string
  language?: string
  status?: string
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
  confidence?: number
  status?: string
  audio_segment_id?: number
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
