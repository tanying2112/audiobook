// BAML Contract Layer – implementation of HARNESS_SPECIFICATIONS.md three‑layer architecture
// This file contains BAML models that mirror the Pydantic/JSON Schema definitions
// found in src/audiobook_studio/schemas/. The goal is to use BAML as the single source of truth
// for contracts, enabling validation and LLM prompting.

model BookAnalysisInput {
  raw_text string
  title_hint? string
  author_hint? string
  target_difficulty string   // "A" | "B" | "C" | "D"
  contract_version int
}

model BookMeta {
  title string
  author? string
  genre string   // "小说" | "散文" | "诗歌" | "历史" | "科普" | "童话" | "其他"
  difficulty string   // "A" | "B" | "C" | "D"
  language string     // ISO 639-1
  era? string
  total_chapters_estimated int
  contract_version int
}

model CharacterVoiceBinding {
  canonical_name string
  aliases list<string>
  gender? string   // "male" | "female" | "neutral" | "unknown"
  age_range? string // "child" | "young" | "adult" | "elderly" | "unknown"
  suggested_voice_id? string
  sample_quote string
  contract_version int
}

model EmotionSnapshot {
  chapter int
  dominant_emotion string // "neutral" | "happy" | "sad" | "angry" | "fearful" | "surprised" | "tense" | "tender" | "contemplative"
  float intensity        // 0.0 .. 1.0
  string? notes
  int
}

model BookAnalysisOutput {
  BookMeta book_meta
  list<CharacterVoiceBinding> character_voice_map
  list<EmotionSnapshot> emotion_snapshots
  string story_line_summary
  string global_style_notes
  int contract_version
}