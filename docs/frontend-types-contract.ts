/**
 * Audiobook Studio — TypeScript 数据模型契约
 * =============================================
 *
 * 本文件定义前端与后端之间的所有数据契约，严格对齐后端：
 *   - Pydantic Schemas (src/audiobook_studio/schemas/)
 *   - SQLAlchemy ORM Models (src/audiobook_studio/models/)
 *   - LLM 子系统状态 (src/audiobook_studio/llm/)
 *   - 反馈闭环 (src/audiobook_studio/feedback/)
 *   - 导出管线 (src/audiobook_studio/export/)
 *
 * 版本: v1.0-draft
 * 日期: 2026-06-25
 * 关联: docs/PROJECT_STATUS.md
 *
 * @module audiobook-studio-types
 */

// ============================================================================
//  Part 0: 工具类型
// ============================================================================

/** 0.0-1.0 范围的分数值 */
export type Score = number & { readonly __brand: unique symbol };

/** ISO 8601 日期时间字符串 */
export type ISODateTime = string;

/** UUID 字符串 */
export type UUID = string;

/** JSON 对象（unknown value 的安全替代） */
export type JsonObject = Record<string, unknown>;

// ============================================================================
//  Part 1: 枚举 & 联合类型
// ============================================================================
// 数据来源: schemas/*.py 中的 Literal[] 和 llm/config_loader.py 中的枚举
// 所有枚举均使用 type alias (非 enum)，便于前端扩展和 JSON 兼容。

// ── 1.1 管线阶段 ──────────────────────────────────────────────────────

/**
 * 管线 7 阶段（含 audio_postprocess）。
 *
 * 注意：后端存在两套阶段命名，前端统一使用此枚举。
 *   - checkpoint.py STAGE_ORDER: 6 阶段（不含 audio_postprocess）
 *   - stage_registry.py: 7 阶段（含 audio_postprocess）
 *   - llm/config_loader.py StageName: 6 阶段（route/judge 替代 synthesize/quality）
 *
 * API 层需要做映射：
 *   pipeline "audio_postprocess" ↔ llm (无对应，由 synthesize 内部调用)
 *   pipeline "synthesize"    ↔ llm "route"
 *   pipeline "quality"      ↔ llm "judge"
 */
export type PipelineStage =
  | "extract"               // ① 文本提取
  | "analyze"               // ② 结构分析
  | "annotate"              // ③ 段落标注
  | "edit"                  // ④ 文本编辑
  | "audio_postprocess"     // ⑤ 声学参数生成
  | "synthesize"            // ⑥ 音频合成
  | "quality";              // ⑦ 质量检测

/** LLM 路由用的 6 阶段名 (config_loader.py:40-47) */
export type LlmStageName =
  | "extract"
  | "analyze"
  | "annotate"
  | "edit"
  | "route"
  | "judge";

/** 管线阶段顺序（用于进度条计算） */
export const PIPELINE_STAGE_ORDER: PipelineStage[] = [
  "extract",
  "analyze",
  "annotate",
  "edit",
  "audio_postprocess",
  "synthesize",
  "quality",
];

// ── 1.2 通用状态 ────────────────────────────────────────────────────────

/**
 * 阶段状态（用于 Chapter per-stage status 字段）。
 * 后端为字符串字面量 (models/chapter.py:38-45)，默认 "pending"。
 */
export type StageStatus = "pending" | "running" | "completed" | "failed";

/**
 * 项目状态 (models/book.py:74)。
 * 后端为字符串，默认 "draft"。
 */
export type ProjectStatus =
  | "draft"
  | "processing"
  | "completed"
  | "failed"
  | "archived";

/**
 * 音频片段状态 (models/audio_segment.py:65)。
 */
export type AudioSegmentStatus = "pending" | "ready" | "failed" | "archived";

/**
 * 段落单字段状态流转 (models/paragraph.py:103)。
 * 流转路径: pending → annotated → edited → audio_processed → synthesized → quality_checked
 */
export type ParagraphStatus =
  | "pending"
  | "annotated"
  | "edited"
  | "audio_processed"
  | "synthesized"
  | "quality_checked";

/**
 * ProcessingRun 状态 (models/processing_run.py:48)。
 */
export type RunStatus = "running" | "completed" | "failed";

// ── 1.3 书籍元数据枚举 ─────────────────────────────────────────────────

/** 体裁 (schemas/book.py:35) — 7 值 */
export type BookGenre =
  | "小说" | "散文" | "诗歌" | "历史" | "科普" | "童话" | "其他";

/** 书级别难度 (schemas/book.py:38) — 4 级 */
export type DifficultyLevel = "A" | "B" | "C" | "D";

/** 段落级别难度 (schemas/paragraph.py:28) — 3 级 */
export type ParagraphDifficulty = "A" | "B" | "C";

/** 性别 (schemas/book.py:52) */
export type Gender = "male" | "female" | "neutral" | "unknown";

/** 年龄段 (schemas/book.py:55) */
export type AgeRange = "child" | "young" | "adult" | "elderly" | "unknown";

// ── 1.4 情感枚举 ───────────────────────────────────────────────────────

/**
 * 段落级情感 — 14 种 (schemas/paragraph.py:77-91)
 * 取超集覆盖 ChapterEmotion 的 10 种。
 */
export type ParagraphEmotion =
  | "neutral" | "happy" | "sad" | "angry" | "fearful"
  | "surprised" | "disgusted" | "tense" | "tender" | "contemplative"
  | "whisper" | "cold_laugh" | "sigh" | "sarcastic";

/** 章节级情感 — 10 种 (schemas/book.py:71-82) */
export type ChapterEmotion =
  | "neutral" | "happy" | "sad" | "angry" | "fearful"
  | "surprised" | "disgusted" | "tense" | "tender" | "contemplative";

// ── 1.5 TTS 引擎 ───────────────────────────────────────────────────────

/**
 * TTS 引擎选择 (schemas/tts_routing.py:54)
 * 含 VoxCPM2/CosyVoice (pro_studio 档位独有)
 */
export type TTSEngineChoice =
  | "kokoro"        // 默认，CPU 本地
  | "edge"          // Azure Edge-TTS，免费云
  | "azure"         // Azure 认知服务
  | "gcp"           // Google Cloud
  | "human_clone"   // 声音克隆
  | "voxcpm2"       // GPU 专业模式
  | "cosyvoice";    // GPU 专业模式

/** VoxCPM2 量化模式 (tts/voxcpm2_backend.py:22-38) */
export type VoxCPM2Quantization = "fp32" | "fp16" | "bf16" | "int8";

/** VoxCPM2 预设音色 (tts/voxcpm2_backend.py) */
export type VoxCPM2Voice =
  | "zh_female_1" | "zh_female_2" | "zh_male_1"
  | "zh_male_2"   | "en_female_1" | "en_male_1";

// ── 1.6 质量检测 ─────────────────────────────────────────────────────

/** 质量问题类型 (schemas/quality.py:69-79) — 8 种 */
export type QualityIssue =
  | "wrong_speaker"
  | "emotion_mismatch"
  | "silent_segment"
  | "stuttering"
  | "truncation"
  | "sensitive_content"
  | "wrong_speed"
  | "wrong_pitch";

/** 修复建议类型 (schemas/quality.py:32-39) — 7 种 */
export type FixSuggestionType =
  | "voice_adjustment"
  | "emotion_adjustment"
  | "pacing_adjustment"
  | "content_edit"
  | "emphasis_change"
  | "pause_insertion"
  | "prosody_correction";

/** 优先级 */
export type Priority = "low" | "medium" | "high";

// ── 1.7 LLM 子系统枚举 ─────────────────────────────────────────────────

/** 熔断器状态 (llm/circuit_breaker.py:27) */
export type CircuitState = "closed" | "open" | "half_open";

/** 免费层整体健康 (llm/router.py:919-969) */
export type FreeTierHealth = "green" | "yellow" | "red";

/** Kill Switch 降级等级 (feedback/kill_switch.py:17) */
export type DegradationLevel = "normal" | "partial" | "degraded" | "emergency";

/**
 * LLM 提供商类型 (llm/config_loader.py:15-37) — 22 种。
 * 运行时主键为 ProviderConfig.name，非 provider 类型。
 */
export type ProviderType =
  | "groq" | "deepseek" | "openrouter" | "ollama" | "gemini"
  | "openai" | "anthropic" | "cerebras" | "alibaba" | "zhipu"
  | "siliconcloud" | "mistral" | "volcengine" | "tencent" | "cohere"
  | "together" | "huggingface" | "baidu_qianfan" | "cloudflare"
  | "github" | "duck2api";

/** 硬件档位 (config/hardware_profile.yaml) */
export type HardwareProfile = "potato" | "cloud_hybrid" | "pro_studio";

/** 密钥轮换策略 (llm/key_pool.py) */
export type KeyRotationStrategy = "round_robin" | "weighted";

// ── 1.8 反馈枚举 ───────────────────────────────────────────────────────

/** 反馈来源 (schemas/feedback.py:28) */
export type FeedbackSource = "human_edit" | "quality_judge" | "user_rating";

/** 反馈发生环节 (schemas/feedback.py:31-38) */
export type FeedbackStage =
  | "extract"
  | "analyze_structure"
  | "annotate_paragraph"
  | "edit_for_tts"
  | "tts_routing"
  | "quality_judge";

/** 严重程度 (schemas/feedback_analysis.py:12) */
export type Severity = "high" | "medium" | "low";

/** Pattern 标签分类 (feedback/processor.py:43-67) — 21 种 */
export type PatternTag =
  | "dialogue_attribution" | "emotion_too_mild" | "emotion_too_strong"
  | "wrong_speaker" | "pacing_issue" | "pause_placement"
  | "prosody_unnatural" | "sensitive_content" | "formatting_error"
  | "content_loss" | "truncation" | "stuttering" | "tone_mismatch"
  | "emphasis_wrong" | "speed_wrong" | "pitch_wrong"
  | "volume_inconsistent" | "character_inconsistency"
  | "missing_sfx" | "sfx_overuse" | "narration_style";

// ── 1.9 导出枚举 ──────────────────────────────────────────────────────

/** 导出格式 (export/batch_exporter.py:26) */
export type ExportFormat = "m4b" | "srt" | "vtt" | "m4b_srt" | "all";

/** 导出进度 (export/batch_exporter.py:35-44) — 8 种 */
export type ExportProgress =
  | "pending"
  | "concatenating"
  | "chaptering"
  | "subtitles"
  | "ducking"
  | "compressing"
  | "complete"
  | "failed";

// ── 1.10 文件类型 ───────────────────────────────────────────────────────

/** 文件 MIME 类型 (schemas/extraction.py:17-22) */
export type MimeType =
  | "application/pdf"
  | "application/epub+zip"
  | "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
  | "text/plain"
  | "image/*";

// ── 1.11 Critic 枚举 ───────────────────────────────────────────────────

/** Critic 类型 (feedback/critics/base.py:28) */
export type CriticType = "SEMANTIC" | "STRUCTURAL" | "OBJECTIVE";

/** Critic 判定 (feedback/critics/base.py:35) */
export type CriticVerdict = "PASS" | "FAIL" | "WARNING" | "ABSTAIN";

// ── 1.12 Canary / Version 枚举 ───────────────────────────────────────

/** Canary 灰度状态 */
export type CanaryRunStatus = "running" | "completed" | "rolled_back";

/** 版本操作类型 */
export type VersionAction = "promotion" | "rollback";

/** 版本生命周期 */
export type VersionLifecycle =
  | "draft" | "testing" | "canary" | "promoted" | "rolled-back";

// ── 1.13 告警枚举 ────────────────────────────────────────────────────

/** 告警级别 (monitoring/alert.py:31) */
export type AlertLevel = "INFO" | "WARNING" | "CRITICAL";

/** Ducking 片段类型 (export/audio_ducking.py) */
export type DuckingType = "speech" | "sfx" | "silence";


// ============================================================================
//  Part 2: 核心实体接口
// ============================================================================
// 对齐: schemas/*.py (Pydantic) + models/*.py (SQLAlchemy ORM)

// ── 2.1 BookMeta (环节②输出 — 书籍元信息) ───────────────────────────────
// 来源: schemas/book.py:30-44

export interface BookMeta {
  title: string;
  author: string | null;
  genre: BookGenre;
  difficulty: DifficultyLevel;
  language: string;           // ISO 639-1
  era: string | null;
  total_chapters_estimated: number;
  contract_version: number;
}

// ── 2.2 CharacterVoiceBinding (角色声音绑定) ───────────────────────────
// 来源: schemas/book.py:47-64, models/character.py:17

export interface CharacterVoiceBinding {
  canonical_name: string;     // 全本唯一
  aliases: string[];
  gender: Gender;
  age_range: AgeRange;
  suggested_voice_id: string | null;
  sample_quote: string;
  contract_version: number;
}

// ── 2.3 EmotionSnapshot (章节情感快照) ─────────────────────────────────
// 来源: schemas/book.py:67-87, models/emotion_snapshot.py

export interface EmotionSnapshot {
  chapter: number;            // 1-based
  dominant_emotion: ChapterEmotion;
  intensity: number;          // 0.0 - 1.0
  notes: string;
  contract_version: number;
}

// ── 2.4 BookAnalysisOutput (环节②完整输出 — 上帝视角剧本档案) ─────────
// 来源: schemas/book.py:90-111

export interface BookAnalysisOutput {
  book_meta: BookMeta;
  character_voice_map: CharacterVoiceBinding[];
  emotion_snapshots: EmotionSnapshot[];
  story_line_summary: string;
  global_style_notes: string;
  contract_version: number;
}

// ── 2.5 Project (书籍项目 — 上帝视角完整档案) ───────────────────────────
// 来源: schemas/project.py:14-49, models/book.py:53

export interface Project {
  id: number;
  title: string;
  author: string | null;
  genre: BookGenre | null;
  difficulty: DifficultyLevel | null;
  language: string;           // ISO 639-1
  era: string | null;
  total_chapters_estimated: number | null;

  // 全局文风
  global_style_notes: string | null;
  story_line_summary: string | null;

  // 状态追踪
  status: ProjectStatus;
  current_stage: PipelineStage | null;
  progress: number;            // 0.0 - 1.0

  // 成本追踪
  total_cost_usd: number;
  cost_limit_per_book: number;
  cost_limit_per_chapter: number;

  // 时间戳
  created_at: ISODateTime | null;
  updated_at: ISODateTime | null;
  completed_at: ISODateTime | null;

  /** 聚合统计（懒加载，避免 N+1 查询） */
  _embedded?: ProjectEmbeddedSummary;
}

export interface ProjectEmbeddedSummary {
  characters_count: number;
  chapters_count: number;
  total_paragraphs: number;
  audio_segments_count: number;
  quality_avg_score: number | null;
}

// ── 2.6 Chapter (章节 — 7 个 per-stage status) ──────────────────────────
// 来源: models/chapter.py:19, api/projects.py:ChapterOut

export interface Chapter {
  id: number;
  project_id: number;
  index: number;              // 1-based
  title: string | null;

  // 文本数据
  raw_text: string | null;
  extracted_text: string | null;
  analyzed_json: string | null;   // JSON string → BookAnalysisOutput
  annotated_json: string | null;  // JSON string → ParagraphAnnotation[]
  edited_json: string | null;

  // 8 个独立阶段状态
  status: StageStatus;
  extract_status: StageStatus;
  analyze_status: StageStatus;
  annotate_status: StageStatus;
  edit_status: StageStatus;
  route_status: StageStatus;     // 注意：含 audio_postprocess
  synthesize_status: StageStatus;
  quality_status: StageStatus;

  // 统计
  cost_usd: number;
  token_count: number;
  tts_chars: number;

  /** 聚合统计（懒加载） */
  _embedded?: ChapterEmbeddedSummary;
}

export interface ChapterEmbeddedSummary {
  paragraphs_count: number;
  audio_segments_count: number;
  quality_issues_count: number;   // needs_regeneration=true 的段落数
}

// ── 2.7 ParagraphAnnotation (环节③输出 — 段落语义标注 v2 极简版) ─────
// 来源: schemas/paragraph.py:60-111

export interface ParagraphAnnotation {
  paragraph_id: number | null;
  chapter_id: number | null;
  paragraph_index: number;
  text: string;

  // 语义层参数（v2 核心）
  speaker_canonical_name: string;
  is_dialogue: boolean;
  emotion: ParagraphEmotion;
  emotion_intensity: number;     // 0.0 - 1.0
  confidence: number;             // 0.0 - 1.0
  difficulty: ParagraphDifficulty;
  notes: string | null;

  // v1 兼容字段（可选，迁移期保留）
  speech_rate?: number;           // 0.7 - 1.3
  pitch_shift_semitones?: number; // -5 to +5
  needs_sfx?: boolean;
  sfx_tags?: string[];
  pause_before_ms?: number;
  pause_after_ms?: number;

  contract_version: number;
}

// ── 2.8 Paragraph (段落 — 宽表：标注+编辑+路由+质检嵌入) ─────────────
// 来源: models/paragraph.py:26 (ORM 宽表)
// 注意: 当前 API ParagraphOut 只有 12 字段，需新增 ParagraphDetailOut

export interface Paragraph {
  id: number;
  project_id: number;
  chapter_id: number;
  chapter_index: number;
  index: number;              // 0-based

  // 原文
  text: string | null;
  original_text: string | null;

  // 环节③ — 语义标注
  speaker: string | null;
  speaker_canonical_name: string | null;
  is_dialogue: boolean | null;
  emotion: ParagraphEmotion | null;
  emotion_intensity: number | null;   // 0.0 - 1.0
  confidence: number | null;          // 0.0 - 1.0
  difficulty: ParagraphDifficulty | null;
  notes: string | null;

  // 环节④ — 编辑
  edited_text: string | null;
  forbid_edit: boolean | null;

  // 环节⑤ — TTS 路由
  tts_engine: TTSEngineChoice | null;
  tts_voice_id: string | null;
  prosody_overrides: JsonObject | null;

  // 环节⑤b — 声学参数
  speech_rate: number | null;           // 0.7 - 1.3
  pitch_shift_semitones: number | null; // -5 to +5
  needs_sfx: boolean | null;
  sfx_tags: string[] | null;
  pause_before_ms: number | null;
  pause_after_ms: number | null;

  // 总体状态（单字段流转）
  status: ParagraphStatus;

  /** 子关联（懒加载，替代 N+1 查询） */
  _embedded?: ParagraphEmbedded;
}

export interface ParagraphEmbedded {
  tts_edits: TTSEdit[];
  routings: Routing[];
  qualities: Quality[];
  audio_segment: AudioSegment | null;
}

// ── 2.9 AudioSegment (音频片段 — 版本控制) ─────────────────────────────
// 来源: models/audio_segment.py:21

export interface AudioSegment {
  id: number;
  project_id: number;
  chapter_id: number;
  paragraph_id: number | null;

  file_path: string;
  format: string;              // "mp3" | "wav" | ...
  duration_ms: number;
  sample_rate: number;
  channels: number;

  engine: TTSEngineChoice;
  voice_id: string;
  prosody_overrides: JsonObject | null;

  // 版本控制
  version: number;
  is_current: boolean;
  parent_segment_id: number | null;  // 版本追溯链

  status: AudioSegmentStatus;
}

// ── 2.10 TTSEdit (编辑历史版本) ─────────────────────────────────────────
// 来源: models/tts_edit.py:19

export interface TTSEdit {
  id: number;
  paragraph_id: number;
  version: number;
  edited_text: string;
  changes_made: string[];              // ["数字归一化", "长句拆分"]
  forbidden_content_removed: string[];
  confidence: number;                  // 0.0 - 1.0
  rationale: string;
  difficulty: DifficultyLevel;
  forbid_edit: boolean;
  voice: string;
  source: string;                       // "llm" | "human"
  llm_model: string | null;
  prompt_version: string | null;
}

// ── 2.11 TtsEditOutput (环节④输出) ──────────────────────────────────────
// 来源: schemas/tts_edit.py:39-58

export interface TtsEditOutput {
  edited_text: string;
  changes_made: string[];
  forbidden_content_removed: string[];
  confidence: number;
  rationale: string;
  difficulty: DifficultyLevel;
  forbid_edit: boolean;
}

// ── 2.12 Routing (TTS 路由决策历史) ─────────────────────────────────────
// 来源: models/routing.py:19, schemas/tts_routing.py:48-73

export interface Routing {
  id: number;
  paragraph_id: number;

  // 决策
  engine_choice: TTSEngineChoice;
  voice_id: string;
  prosody_overrides: JsonObject | null;
  fallback_engine: TTSEngineChoice | null;
  reasoning: string;
  estimated_cost_usd: number;
  estimated_duration_ms: number;

  // 实际执行结果
  actual_engine: string | null;
  actual_cost: number | null;

  status: string;                    // "pending" | ...
}

// ── 2.13 TtsRoutingDecision (环节⑤输出) ────────────────────────────────
// 来源: schemas/tts_routing.py:48-73

export interface TtsRoutingDecision {
  segment_id: string;
  engine_choice: TTSEngineChoice;
  voice_id: string;
  prosody_overrides: JsonObject | null;
  fallback_engine: TTSEngineChoice;
  reasoning: string;
  estimated_cost_usd: number;
  estimated_duration_ms: number;
  contract_version: number;
}

// ── 2.14 FixSuggestion (结构化修复建议) ─────────────────────────────────
// 来源: schemas/quality.py:29-56

export interface FixSuggestion {
  suggestion_type: FixSuggestionType;
  target_text: string;
  current_value: string | null;
  suggested_value: string;
  confidence: number;                 // 0.0 - 1.0
  rationale: string;
  priority: Priority;
}

// ── 2.15 Quality (质检记录 — 4 维评分) ─────────────────────────────────
// 来源: models/quality.py:20, schemas/quality.py:59-96

export interface Quality {
  id: number;
  tts_edit_id: number | null;

  // 4 维评分 (0.0 - 1.0)
  speaker_clarity: number;
  emotion_match: number;
  prosody_naturalness: number;
  text_audio_alignment: number;
  overall_score: number;

  // 问题与建议
  issues: QualityIssue[];
  fix_suggestions: FixSuggestion[];

  // 核心标志
  needs_regeneration: boolean;         // 任一维度 < 0.7 或致命问题

  judge_model: string | null;
  judge_prompt_version: string | null;
}

// ── 2.16 AudioPostProcessParams (声学参数) ──────────────────────────────
// 来源: schemas/audio_postprocess.py:20-38

export interface AudioPostProcessParams {
  speech_rate: number;               // 0.7 - 1.3
  pitch_shift_semitones: number;      // -5 to +5
  needs_sfx: boolean;
  sfx_tags: string[];
  pause_before_ms: number;            // 0 - 2000
  pause_after_ms: number;             // 0 - 2000
}

// ── 2.17 ExtractionResult (环节①输出) ──────────────────────────────────
// 来源: schemas/extraction.py:30-50

export interface ExtractionResult {
  raw_text: string;
  language: string;                  // ISO 639-1
  page_count: number;
  has_ocr: boolean;
  ocr_page_ratio: number;            // 0.0 - 1.0
  warnings: string[];
  contract_version: number;
}


// ============================================================================
//  Part 3: LLM 子系统接口
// ============================================================================
// 数据来源: src/audiobook_studio/llm/
// 后端各子系统已有 get_status() 方法，但缺少统一聚合端点。

// ── 3.1 LLMProviderConfig (提供商配置) ──────────────────────────────────
// 来源: llm/config_loader.py:50-113, config/llm_providers.yaml

export interface LLMProviderConfig {
  name: string;                       // 运行时主键 (e.g. "opencode_zen")
  provider: ProviderType;
  model: string;
  api_key_env: string | null;
  api_key_pool_env: string[];         // 多密钥池环境变量名
  key_rotation_strategy: KeyRotationStrategy;
  base_url: string | null;
  priority: number;                   // 越小越优先
  max_tokens_per_minute: number;
  max_requests_per_minute: number;
  max_daily_cost_usd: number;         // 0 = 免费层 provider
  stages: LlmStageName[];
  enabled: boolean;
  extra_params: JsonObject;
}

// ── 3.2 CircuitBreakerStatus (熔断器状态) ───────────────────────────────
// 来源: llm/circuit_breaker.py:93-106

export interface CircuitBreakerStatus {
  provider: string;
  state: CircuitState;
  failure_count: number;
  failure_threshold: number;          // 默认 3
  recovery_timeout_s: number;          // 默认 120
  seconds_since_last_failure: number | null;
}

// ── 3.3 RateLimiterStatus (速率限制器状态) ──────────────────────────────
// 来源: llm/router.py:110-136
// 注意: 后端当前无 get_status() 方法，需补充。

export interface RateLimiterStatus {
  provider: string;
  max_tpm: number;
  max_rpm: number;
  tokens_used_in_window: number;
  requests_used_in_window: number;
  window_start: number;               // epoch seconds
  tokens_remaining_pct: number;       // 派生: 1 - tokens_used/max_tpm
  requests_remaining_pct: number;     // 派生
}

// ── 3.4 CostStatusEntry (成本追踪 per model) ───────────────────────────
// 来源: llm/router.py:184-201

export interface CostStatusEntry {
  model: string;
  daily_cost_usd: number;
  daily_limit_usd: number | null;
  limit_exceeded: boolean;
  alert_triggered: boolean;
  usage_pct: number;                  // 0.0 - 1.0+
}

// ── 3.5 QuotaUsageEntry (配额状态 per provider) ──────────────────────────
// 来源: llm/quota_registry.py:292-319

export interface QuotaUsageEntry {
  provider: string;
  configured: boolean;
  daily: {
    requests_used: number;
    requests_limit: number;
    requests_pct: number;            // 四舍五入 1 位
    tokens_used: number;
    tokens_limit: number;
    tokens_pct: number;
  };
  minute: {
    requests_used: number;
    requests_limit: number;
    requests_pct: number;
    tokens_used: number;
    tokens_limit: number;
    tokens_pct: number;
  };
  health: {
    consecutive_failures: number;
    total_failures_today: number;
    last_successful_request: number | null;  // epoch seconds
  };
  healthy: boolean;
}

// ── 3.6 HealthStatus (健康探针 per provider) ────────────────────────────
// 来源: llm/health_probe.py:19-40

export interface HealthProbeStatus {
  provider: string;
  is_healthy: boolean;
  latency_ms: number;
  last_check: ISODateTime;
  error_message: string | null;
  quota_remaining: number | null;
  quota_limit: number | null;
}

// ── 3.7 KeyPoolStats (密钥池 per provider) ──────────────────────────────
// 来源: llm/key_pool.py:113-122

export interface KeyPoolStats {
  provider: string;
  strategy: KeyRotationStrategy;
  total_keys: number;
  available_keys: number;
  total_requests: number;
  total_failures: number;
}

// ── 3.8 FreeTierHealthReport (免费层整体健康) ───────────────────────────
// 来源: llm/router.py:919-969

export interface FreeTierHealthReport {
  total_free_providers: number;
  healthy_free_providers: number;
  free_quota_success_rate: number;    // 0.0 - 1.0
  free_quota_success: number;
  free_quota_fail: number;
  local_model_available: boolean;
  overall_health: FreeTierHealth;
  circuit_breaker_states: Record<string, CircuitBreakerStatus>;
}

// ── 3.9 KillSwitchReport (Kill Switch 状态报告) ─────────────────────────
// 来源: feedback/kill_switch.py:278-299

export interface KillSwitchReport {
  level: DegradationLevel;
  providers: Record<string, KillSwitchProviderEntry>;
  config: KillSwitchConfig;
}

export interface KillSwitchProviderEntry {
  is_alive: boolean;
  consecutive_failures: number;
  error_rate: string;                 // "12.3%" 格式
  total_calls: number;
  failed_calls: number;
  last_error: string | null;
}

export interface KillSwitchConfig {
  max_consecutive_failures: number;   // 默认 5
  max_error_rate: number;             // 默认 0.3
  fallback_to_rules: boolean;
  fallback_to_cache: boolean;
  health_check_interval_sec: number;
  recovery_check_interval_sec: number;
}

// ── 3.10 LLMCallResult (单次 LLM 调用结果) ─────────────────────────────
// 来源: llm/client.py:76-88

export interface LLMCallResult {
  output: unknown;
  model: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_ms: number;
  schema_compliance: boolean;
  contract_version: number;
}

// ── 3.11 LLMStatusAggregate (聚合状态 — 建议后端新增) ──────────────────
// 前端一次性获取所有 LLM 子系统状态。

export interface LLMStatusAggregate {
  free_tier_health: FreeTierHealthReport;
  kill_switch: KillSwitchReport;
  providers: LLMProviderConfig[];
  circuit_breakers: Record<string, CircuitBreakerStatus>;
  rate_limiters: Record<string, RateLimiterStatus>;
  costs: Record<string, CostStatusEntry>;
  quotas: Record<string, QuotaUsageEntry>;
  health_probes: Record<string, HealthProbeStatus>;
  key_pools: Record<string, KeyPoolStats>;
  stage_configs: Record<string, StageRoutingView>;
}

export interface StageRoutingView {
  stage: string;
  models: Array<{
    name: string;
    priority: number;
    enabled: boolean;
  }>;
  fallback_model: string | null;
}


// ============================================================================
//  Part 4: 反馈 & 版本管理接口
// ============================================================================
// 数据来源: schemas/feedback.py, schemas/feedback_analysis.py, feedback/release.py

// ── 4.1 FeedbackRecord (统一反馈记录) ──────────────────────────────────
// 来源: schemas/feedback.py:21-63, models/feedback_record.py:19

export interface FeedbackRecord {
  id: UUID;
  timestamp: ISODateTime;
  source: FeedbackSource;
  stage: FeedbackStage;
  book_id: string;
  paragraph_index: number | null;
  chapter_index: number | null;

  // 快照数据
  input_snapshot: JsonObject;
  llm_output: JsonObject;
  corrected_output: JsonObject;

  // 分析
  rationale: string;                  // ≥ 10 字
  diff_summary: string;
  pattern_tags: PatternTag[];

  // 处理状态
  processed: boolean;
  promoted: boolean;

  /** 关联的 LLM 语义分析结果 */
  _embedded?: FeedbackAnalysis;
}

// ── 4.2 FeedbackAnalysis (LLM 语义分析结果) ─────────────────────────────
// 来源: schemas/feedback_analysis.py:15-62

export interface FeedbackAnalysis {
  pattern_tags: string[];             // 可含未知 tag（LLM 新发现）
  semantic_summary: string;
  severity: Severity;
  actionable_instruction: string;
  root_cause: string;
  confidence: number;                // 0.0 - 1.0, < 0.5 建议人工复核
}

// ── 4.3 ABTest 相关 ────────────────────────────────────────────────────
// 来源: feedback/ab_test.py, feedback/ab_test_manager.py

export interface ABTestConfig {
  test_id: string;
  name: string;
  variant_a_prompt: string;
  variant_b_prompt: string;
  test_segments: string[];
  judge_criteria: string[];
}

export interface ABTestResult {
  test_id: string;
  score_a: number;
  score_b: number;
  improvement_pct: number;
  p_value: number;
  confidence_interval: [number, number];
  winner_variant: "a" | "b" | "tie";
  sample_size: number;
  statistically_significant: boolean;
}

// ── 4.4 PromotionGate (4 硬指标门禁) ───────────────────────────────────
// 来源: feedback/release.py:26-187

export interface PromotionMetrics {
  format_compliance_rate: number;     // ≥ 0.99
  golden_dataset_pass_rate: number;   // ≥ 0.95
  quality_score_ratio: number;        // ≥ 1.02 (相对旧版)
  human_preference_score: number;     // ≥ 0.80
  timestamp: ISODateTime;
}

export interface PromotionGateResult {
  passed: boolean;
  failed_criteria: string[];
  metrics: PromotionMetrics;
  timestamp: ISODateTime;
}

export interface PromotionGateConfig {
  format_compliance_threshold: number;
  golden_dataset_threshold: number;
  quality_score_threshold: number;
  human_preference_threshold: number;
}

// ── 4.5 CanaryRelease (灰度发布) ───────────────────────────────────────
// 来源: feedback/release.py:190-318

export interface CanaryConfig {
  enabled: boolean;
  traffic_percentage: number;         // 10%
  min_samples: number;               // 100
  max_duration_hours: number;         // 24
  rollback_threshold: number;        // 0.95
  check_interval_minutes: number;     // 15
}

export interface CanaryStatus {
  canary_id: string;
  stage: string;
  version: string;
  baseline_score: number;
  started_at: ISODateTime;
  status: CanaryRunStatus;
  rolled_back_at?: ISODateTime;
  rollback_reason?: string;
  completed_at?: ISODateTime;
}

export interface CanaryMetrics {
  version: string;
  stage: string;
  samples_collected: number;
  avg_quality_score: number;
  baseline_quality_score: number;
  quality_ratio: number;              // avg / baseline
  error_rate: number;
  timestamp: ISODateTime;
}

// ── 4.6 VersionStore (Prompt 版本管理) ─────────────────────────────────
// 来源: feedback/release.py:323-434

export interface RollbackLogEntry {
  timestamp: ISODateTime;
  stage: string;
  from_version: number;
  to_version: number;
  action: VersionAction;
  success: boolean;
}

export interface VersionStoreStatus {
  current_versions: Record<string, number>;  // stage → version number
  rollback_history: RollbackLogEntry[];
}

// ── 4.7 ProcessingRun (管线运行版本快照) ───────────────────────────────
// 来源: models/processing_run.py:18

export interface ProcessingRun {
  id: number;
  project_id: number;
  parent_run_id: number | null;       // 版本追溯链

  config_json: string;               // ProcessingConfig 快照
  prompt_versions: Record<string, string | number>;  // stage → version
  stages_completed: string[];
  golden_score: number | null;

  status: RunStatus;
  error_message: string | null;
  version_tag: string | null;
  commit_message: string | null;

  started_at: ISODateTime;
  completed_at: ISODateTime | null;
}

// ── 4.8 CriticResult ──────────────────────────────────────────────────
// 来源: feedback/critics/base.py:50

export interface CriticResult {
  score: number;
  verdict: CriticVerdict;
  reasoning: string;
  evidence: string[];
}


// ============================================================================
//  Part 5: 导出 & 发布接口
// ============================================================================
// 数据来源: export/batch_exporter.py, export/m4b.py, export/srt.py,
//           publish/podcast_rss_generator.py

// ── 5.1 ExportJob (导出任务) ───────────────────────────────────────────
// 来源: export/batch_exporter.py:47-65
// 注意: 当前无 ORM，需补充持久化 ID。

export interface ExportJob {
  job_id: string;                     // 建议新增 UUID
  project_id: number;
  chapter_ids: number[] | null;       // null = 全部章节
  formats: ExportFormat[];
  bgm_path: string | null;
  include_cover: boolean;
  cover_image: string | null;
  normalize: boolean;
  subtitle_config: SubtitleConfig | null;
  mix_config: MixConfig | null;
  output_dir: string | null;

  // 运行时状态
  progress: ExportProgress;
  output_paths: Record<string, string>;
  error: string | null;

  // 时间戳
  created_at: ISODateTime;
  completed_at: ISODateTime | null;
}

// ── 5.2 MixConfig (混音配置) ───────────────────────────────────────────
// 来源: export/audio_ducking.py

export interface MixConfig {
  bgm_path: string;
  bgm_volume_db: number;
  duck_attack_ms: number;
  duck_release_ms: number;
  sidechain_enabled: boolean;
  loudness_target_lufs: number;
}

// ── 5.3 DuckingSegment (Ducking 片段) ─────────────────────────────────
// 来源: export/audio_ducking.py:21-43

export interface DuckingSegment {
  start_ms: number;
  end_ms: number;
  type: DuckingType;
  duck_gain_db: number;
}

// ── 5.4 ChapterMarker (章节标记) ─────────────────────────────────────
// 来源: export/m4b.py:19-45

export interface ChapterMarker {
  title: string;
  start_ms: number;
  duration_ms: number;
}

// ── 5.5 M4bMetadata (M4B 元数据) ───────────────────────────────────────
// 来源: export/m4b.py

export interface M4bMetadata {
  title: string;
  artist: string;
  album: string;
  year?: number;
  narrator?: string;
  chapters: ChapterMarker[];
  cover_image?: string;
}

// ── 5.6 SubtitleEntry / SubtitleConfig (字幕) ──────────────────────────
// 来源: export/srt.py

export interface SubtitleEntry {
  index: number;
  start_ms: number;
  end_ms: number;
  text: string;
  speaker: string | null;
}

export interface SubtitleConfig {
  max_chars_per_line: number;
  max_lines: number;
  format: "srt" | "vtt";
}

// ── 5.7 Podcast (播客 RSS) ─────────────────────────────────────────────
// 来源: publish/podcast_rss_generator.py

export interface PodcastEpisode {
  title: string;
  description: string;
  audio_file_path: string;
  duration_seconds: number;
  pub_date: string;
  guid: string;
  episode_type: "full" | "trailer" | "bonus";
  season_number: number | null;
  episode_number: number | null;
  explicit: boolean;
}

export interface PodcastFeed {
  title: string;
  description: string;
  link: string;
  language: string;
  categories: string[];
}


// ============================================================================
//  Part 6: 断点续传 & 管线运行时接口
// ============================================================================
// 数据来源: pipeline/checkpoint.py, pipeline/orchestrator.py

// ── 6.1 PipelineCheckpoint (断点续传状态) ─────────────────────────────
// 来源: pipeline/checkpoint.py:61-65
// 存储位置: storage/books/<project_id>/reports/checkpoints.json

export interface ChapterCheckpoint {
  stages_done: PipelineStage[];
  paragraphs_done: number[];
  current_stage: PipelineStage | null;
}

export interface PipelineCheckpoint {
  project_id: number;
  chapters: Record<string, ChapterCheckpoint>;
  version: number;
  metadata: JsonObject;
}

// ── 6.2 PipelineEvent (WebSocket/SSE 推送事件) ──────────────────────────
// 来源: pipeline/orchestrator.py:50-142 (观察者模式 hook)

export interface StageEvent {
  type: "stage_enter" | "stage_exit";
  stage: PipelineStage;
  chapter_index: number;
  project_id: number;
  timestamp: ISODateTime;
  result?: unknown;
  error?: string;
}

export interface PipelineStartEndEvent {
  type: "pipeline_start" | "pipeline_end";
  project_id: number;
  timestamp: ISODateTime;
  result?: unknown;
  error?: string;
}

export type PipelineWSMessage = StageEvent | PipelineStartEndEvent;


// ============================================================================
//  Part 7: 监控 & 基准测试接口
// ============================================================================
// 数据来源: monitoring/baseline.py, monitoring/alert.py, benchmarks/

// ── 7.1 PerformanceMetric (性能指标) ────────────────────────────────────
// 来源: monitoring/baseline.py:18-43

export interface PerformanceMetric {
  timestamp: ISODateTime;
  stage: string;
  latency_ms: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  success: boolean;
  quality_score: number | null;
  provider: string;
  model: string;
  schema_compliance: boolean;
}

// ── 7.2 AlertRecord (告警记录) ──────────────────────────────────────────
// 来源: monitoring/alert.py:35-44

export interface AlertRecord {
  level: AlertLevel;
  metric_name: string;
  threshold: number;
  current_value: number;
  triggered_at: ISODateTime;
  message: string;
}

// ── 7.3 ComplianceSummary (契约合规率) ──────────────────────────────────
// 来源: monitoring/compliance.py:20-58

export interface StageComplianceSummary {
  stage: string;
  total_samples: number;
  compliant_samples: number;
  compliance_rate: number;           // 0.0 - 1.0
  non_compliant_examples: string[];
}

// ── 7.4 BenchmarkReport (基准测试报告) ──────────────────────────────────
// 来源: benchmarks/bench_voxcpm2.py

export interface HardwareProfileInfo {
  system: string;
  cpu_model: string;
  cpu_cores: number;
  ram_gb: number;
  gpu_model: string | null;
  gpu_vram_gb: number | null;
  cuda_available: boolean;
  mps_available: boolean;
  meets_int8_min: boolean;           // ≥ 8GB
  meets_fp16_min: boolean;           // ≥ 16GB
  recommended_mode: "cpu_simulation" | "int8_gpu" | "fp16_gpu";
}

export interface TtsBenchmarkResult {
  engine: string;
  text_length_chars: number;
  audio_duration_sec: number;
  synthesis_time_sec: number;
  rtf: number;                       // Real-Time Factor (越低越好)
  throughput_cps: number;            // chars per second
  success: boolean;
  error: string | null;
}

export interface BenchmarkReport {
  hardware: HardwareProfileInfo;
  results: TtsBenchmarkResult[];
  acceptance_criteria_met: boolean;
  recommendations: string[];
}


// ============================================================================
//  Part 8: API 请求/响应 DTO
// ============================================================================
// 对齐: api/projects.py 中的 Pydantic schema

// ── 8.1 ProjectCreate (创建项目 DTO) ────────────────────────────────────
// 来源: api/projects.py:29-37

export interface ProjectCreateRequest {
  title: string;
  author?: string;
  genre?: BookGenre;
  language?: string;                // 默认 "zh"
  difficulty?: DifficultyLevel;
  global_style_notes?: string;
  story_line_summary?: string;
}

// ── 8.2 PipelineAction (管线操作 DTO) ─────────────────────────────────
// 后端待实现

export interface PipelineStartRequest {
  project_id: number;
  resume_from_checkpoint?: boolean;  // 默认 true
  stages?: PipelineStage[];          // 空数组 = 全部阶段
  chapter_range?: [number, number];  // [start, end], null = 全部
}

export interface ReprocessRequest {
  project_id: number;
  chapter_index: number;
  paragraph_index?: number;
  from_stage: PipelineStage;         // 从此阶段开始重新处理
  to_stage?: PipelineStage;           // 到此阶段结束（默认到最后）
}

// ── 8.3 FeedbackSubmit (提交反馈 DTO) ──────────────────────────────────

export interface FeedbackSubmitRequest {
  source: FeedbackSource;
  stage: FeedbackStage;
  book_id: string;
  paragraph_index?: number;
  chapter_index?: number;
  input_snapshot: JsonObject;
  llm_output: JsonObject;
  corrected_output: JsonObject;
  rationale: string;                  // ≥ 10 字
}

// ── 8.4 VersionAction (版本操作 DTO) ────────────────────────────────────

export interface VersionRollbackRequest {
  stage: string;
  target_version: number;
}

// ── 8.5 ExportCreate (导出创建 DTO) ─────────────────────────────────────

export interface ExportCreateRequest {
  project_id: number;
  chapter_ids?: number[];            // null = 全部
  formats: ExportFormat[];
  bgm_path?: string;
  include_cover?: boolean;          // 默认 true
  cover_image?: string;
  normalize?: boolean;               // 默认 true
  subtitle_config?: SubtitleConfig;
  mix_config?: MixConfig;
}

// ── 8.6 通用分页 DTO ───────────────────────────────────────────────────

export interface PaginatedRequest {
  skip?: number;                     // 默认 0
  limit?: number;                    // 默认 100
  sort_by?: string;
  sort_order?: "asc" | "desc";
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  skip: number;
  limit: number;
}


// ============================================================================
//  Part 9: 前端 UI 状态类型（非后端契约）
// ============================================================================
// 以下类型仅用于前端状态管理，不对应后端实体。

/** 全局通知 */
export interface AppNotification {
  id: string;
  type: "success" | "warning" | "error" | "info";
  title: string;
  message: string;
  timestamp: ISODateTime;
  auto_dismiss_ms?: number;
}

/** 主题配置 */
export interface ThemeConfig {
  mode: "light" | "dark" | "system";
  accent_color: string;              // CSS color
  compact_mode: boolean;
}

/** 面板布局 */
export interface PanelLayout {
  sidebar_collapsed: boolean;
  detail_panel_width: number;        // px
  audio_editor_waveform_height: number;
}


// ============================================================================
//  Part 10: 数据清洗层类型签名
// ============================================================================
// 核心原则: 后端"脏状态"在进入 UI 之前全部洗净，UI 组件只接触标准化数据。
// 对应: docs/PROJECT_STATUS.md 策略 A

/** 标准化的单阶段状态（UI 组件唯一消费的类型） */
export interface NormalizedStageState {
  stage: PipelineStage;
  status: StageStatus;               // 永远是 'pending'|'running'|'completed'|'failed'
  /** 原始后端字段名（用于调试，UI 不应使用） */
  _source_field?: string;
}

/**
 * normalizeChapterPipeline(serverData) 的返回类型。
 * UI 组件只遍历此数组渲染阶段节点。
 *
 * @example
 * // ✅ 正确 — UI 只消费清洗后的数据
 * normalizedStages.forEach(({ stage, status }) => renderDot(stage, status));
 *
 * @example
 * // ❌ 禁止 — UI 直接访问后端原始字段
 * if (chapter.route_status === 'completed') { ... }
 */
export type NormalizedPipeline = NormalizedStageState[];

/**
 * normalizeTimestamp(raw) 的类型签名。
 * 处理三种后端时间格式：
 *   - ISO 8601 string → 原样返回
 *   - epoch seconds (number > 1e9) → 转为 ISO string
 *   - epoch milliseconds (number > 1e12) → 转为 ISO string
 *   - relative seconds (number < 1000) → 返回 null（无绝对时间参考）
 *   - null/undefined → 返回 null
 */
export type RawTimestamp = string | number | null | undefined;

/**
 * normalizeParagraphStatus(serverStatus) 的类型签名。
 * 将后端 Paragraph.status 的任意字符串值（含历史遗留值）清洗为
 * 标准化的 ParagraphStatus 枚举。
 */
export const PARAGRAPH_STATUS_FLOW: ParagraphStatus[] = [
  "pending",
  "annotated",
  "edited",
  "audio_processed",
  "synthesized",
  "quality_checked",
];

/**
 * 全局 API 配置（mock/real 模式切换）。
 * 对应: docs/PROJECT_STATUS.md 策略 B
 */
export interface ApiConfig {
  /** 基础 URL，默认 '/api'，开发环境可切换为 '/api/mock' */
  baseUrl: string;
  /** WebSocket 基础 URL */
  wsUrl: string;
  /** 是否使用 mock 数据 */
  mockMode: boolean;
  /** 轮询降级间隔（ms），WS 断开时使用 */
  pollingIntervalMs: number;          // 默认 3000
  /** 请求超时（ms） */
  requestTimeoutMs: number;           // 默认 10000
}

/**
 * WebSocket 连接状态。
 * 对应: docs/PROJECT_STATUS.md 策略 C
 */
export type WSConnectionState = "connecting" | "connected" | "polling" | "disconnected";

export interface WSConnectionStatus {
  state: WSConnectionState;
  projectId: number | null;
  reconnectAttempts: number;
  lastEventAt: ISODateTime | null;
  pollingIntervalId: ReturnType<typeof setInterval> | null;
}

/**
 * i18n 字典条目类型。
 * 对应: docs/PROJECT_STATUS.md 策略 F
 */
export type I18nDict = Record<string, string>;
export type SupportedLocale = "zh" | "en";

export interface I18nConfig {
  currentLocale: SupportedLocale;
  dictionaries: Record<SupportedLocale, I18nDict>;
}

/**
 * 枚举值 ↔ 显示文本映射（用于 i18n 下拉/徽章组件）。
 * 对齐: TypeScript 契约中的所有枚举类型。
 */
export type EnumDisplayMap<T extends string> = Record<T, { zh: string; en: string }>;

/** 预构建的枚举显示映射（在 i18n.js 中填充实际值） */
export interface EnumDisplayMaps {
  pipelineStage: EnumDisplayMap<PipelineStage>;
  stageStatus: EnumDisplayMap<StageStatus>;
  paragraphEmotion: EnumDisplayMap<ParagraphEmotion>;
  chapterEmotion: EnumDisplayMap<ChapterEmotion>;
  bookGenre: EnumDisplayMap<BookGenre>;
  difficultyLevel: EnumDisplayMap<DifficultyLevel>;
  gender: EnumDisplayMap<Gender>;
  ageRange: EnumDisplayMap<AgeRange>;
  ttsEngine: EnumDisplayMap<TTSEngineChoice>;
  qualityIssue: EnumDisplayMap<QualityIssue>;
  circuitState: EnumDisplayMap<CircuitState>;
  freeTierHealth: EnumDisplayMap<FreeTierHealth>;
  degradationLevel: EnumDisplayMap<DegradationLevel>;
  feedbackSource: EnumDisplayMap<FeedbackSource>;
  exportFormat: EnumDisplayMap<ExportFormat>;
  exportProgress: EnumDisplayMap<ExportProgress>;
  priority: EnumDisplayMap<Priority>;
  severity: EnumDisplayMap<Severity>;
}


// ============================================================================
//  Part 11: AI 智能工作台类型（P0-AI）
// ============================================================================
// 对应: docs/PROJECT_STATUS.md 的 P0-AI-1 ~ P0-AI-7
// 核心理念: 把 HARNESS 马具系统（LLM 全链路参与 + 自我迭代）变为前端可对话、
//           可干预、可反哺的智能工作台。

// ── 11.1 对话式编辑/标注 (P0-AI-1, P0-AI-2) ──────────────────────────────

/**
 * LLM 对话角色。
 * 对应 HARNESS 6 阶段，每个阶段可发起对应的对话式编辑。
 */
export type ChatEditTargetStage =
  | "annotate"   // P0-AI-2 对话式标注
  | "edit";      // P0-AI-1 对话式文本编辑

/** 对话消息角色（OpenAI 风格） */
export type ChatRole = "user" | "assistant" | "system";

/** 单条对话消息 */
export interface ChatMessage {
  id: string;                         // UUID
  role: ChatRole;
  content: string;
  timestamp: ISODateTime;
  /** assistant 消息附带的结构化编辑建议（仅 role=assistant 时存在） */
  suggestion?: ChatSuggestion;
  /** 用户采纳状态（仅当 suggestion 存在时） */
  adoption?: "pending" | "accepted" | "rejected";
}

/**
 * LLM 返回的结构化编辑建议。
 * 对话式编辑的每次 assistant 回复都可携带一个 suggestion，
 * 用户可采纳/拒绝/继续对话。
 */
export interface ChatSuggestion {
  /** 建议类型 */
  kind: "text_edit" | "annotation_adjust" | "voice_binding";
  /** 针对的段落 ID */
  paragraph_id: number;
  /** 修改前的值（原文或原标注） */
  before: JsonObject;
  /** 修改后的值（编辑后文本或调整后标注） */
  after: JsonObject;
  /** 变更说明（LLM 自述做了哪些改动） */
  changes_made: string[];
  /** LLM 置信度 0.0-1.0 */
  confidence: number;
  /** LLM 给出此建议的理由 */
  rationale: string;
  /** 若涉及角色声音绑定，附带建议的绑定信息 */
  voice_binding?: CharacterVoiceBinding;
}

/** 对话式编辑请求（SSE 流式响应） */
export interface ChatEditRequest {
  project_id: number;
  chapter_index: number;
  paragraph_index: number;
  target_stage: ChatEditTargetStage;
  /** 用户本轮输入的自然语言意图 */
  intent: string;
  /** 历史对话（多轮上下文记忆） */
  conversation_history: ChatMessage[];
  /** 自动注入的段落上下文（speaker/emotion/difficulty 等） */
  annotation_context: ParagraphAnnotation;
  /** 快捷指令（可选，对应快捷按钮） */
  shortcut?: EditShortcut;
}

/** 文本编辑快捷指令（P0-AI-1 功能点 5） */
export type EditShortcut =
  | "normalize_numbers"      // 数字归一化
  | "split_long_sentences"   // 长句拆分
  | "colloquialize"          // 口语化
  | "formalize"              // 书面化
  | "remove_sensitive"       // 删除敏感词
  | "adjust_pace_hint";      // 调整语速提示

/** 对话式编辑流式响应（SSE 事件序列） */
export type ChatEditStreamEvent =
  | { type: "token"; content: string }                    // 逐 token 文本
  | { type: "suggestion"; suggestion: ChatSuggestion }    // 完整建议
  | { type: "done"; message_id: string }
  | { type: "error"; message: string; code?: string };

/** 对话式标注请求（P0-AI-2） */
export interface ChatAnnotateRequest {
  project_id: number;
  chapter_index: number;
  paragraph_index: number;
  intent: string;
  conversation_history: ChatMessage[];
  current_annotation: ParagraphAnnotation;
}

/** 对话式标注响应 */
export interface ChatAnnotateResponse {
  suggestion: ChatSuggestion;
}

/** 整章批量标注建议（P0-AI-2 功能点 6） */
export interface BatchAnnotateRequest {
  project_id: number;
  chapter_index: number;
  /** 限定段落范围，null = 整章未标注段落 */
  paragraph_indices?: number[];
}

export interface BatchAnnotateResponse {
  suggestions: Array<ChatSuggestion & { paragraph_index: number }>;
  /** LLM 扫描的整体置信度 */
  overall_confidence: number;
}


// ── 11.2 范本管理 & 全书应用 (P0-AI-3) ──────────────────────────────────

/** 范本类型 */
export type TemplateKind = "edit" | "annotate";

/**
 * 范本（Golden Sample 候选）。
 * 用户在对话编辑中确认（采纳）的结果自动成为范本，进入待确认队列。
 * 对应 FeedbackRecord with source=human_edit, processed=false。
 */
export interface ProjectTemplate {
  id: string;                         // = FeedbackRecord.id
  project_id: number;
  kind: TemplateKind;
  source_paragraph: {
    chapter_index: number;
    paragraph_index: number;
  };
  /** 修改前快照 */
  before: JsonObject;
  /** 修改后范本 */
  after: JsonObject;
  /** LLM 自动归类的 pattern 标签 */
  pattern_tags: PatternTag[];
  /** 修改摘要 */
  summary: string;
  /** 置信度 */
  confidence: number;
  timestamp: ISODateTime;
  /** 确认状态 */
  status: "pending" | "confirmed" | "rejected";
}

/** 全书应用范本请求（向导收集） */
export interface TemplateApplyRequest {
  project_id: number;
  /** 选中的范本 ID 列表 */
  template_ids: string[];
  /** 应用范围 */
  scope: TemplateApplyScope;
  /** 注入范本作为 few-shot 的强度 0.0-1.0 */
  few_shot_strength?: number;
}

export interface TemplateApplyScope {
  /** 范围类型 */
  type: "whole_book" | "chapters" | "pattern_match";
  /** type=chapters 时的章节列表 */
  chapter_indices?: number[];
  /** type=pattern_match 时的匹配条件 */
  pattern_filter?: {
    tags?: PatternTag[];
    min_confidence?: number;
  };
}

/** 全书应用进度（WebSocket 推送） */
export interface TemplateApplyProgress {
  job_id: string;
  project_id: number;
  status: "scanning" | "previewing" | "applying" | "completed" | "failed";
  /** 匹配到的总段落数 */
  total_matched: number;
  /** 已处理段落数 */
  processed: number;
  /** 当前正在处理的段落 diff（实时） */
  current_diff?: ChatSuggestion;
  /** 生成的 ProcessingRun ID（用于回滚） */
  processing_run_id?: number;
  error?: string;
}

/** 应用前预览（命中范围） */
export interface TemplateApplyPreview {
  total_matched: number;
  /** 样例 diff（最多 10 条） */
  sample_diffs: Array<{ paragraph_index: number; diff: ChatSuggestion }>;
  /** 按章节分布 */
  chapter_distribution: Record<number, number>;
}


// ── 11.3 一键全自动生成 (P0-AI-4) ──────────────────────────────────────

/** 一键生成的用户偏好配置 */
export interface AutoRunConfig {
  /** 目标难度 */
  target_difficulty: DifficultyLevel;
  /** 主音色偏好 */
  voice_preference: "male" | "female" | "neutral" | "auto";
  /** 语速偏好 */
  pace_preference: "slow" | "normal" | "fast";
  /** 成本上限（USD） */
  cost_limit_usd: number;
  /** 质量阈值：低于此分的段落自动重合成 */
  auto_resynth_threshold: number;     // 默认 0.7
  /** 自动重合成最大次数 */
  max_resynth_attempts: number;       // 默认 3
  /** 是否在每阶段完成后暂停等待用户确认（false = 纯全自动） */
  pause_between_stages: boolean;      // 默认 false
}

/** 一键生成请求 */
export interface AutoRunRequest {
  project_id: number;
  config: AutoRunConfig;
  /** 输出格式 */
  output_formats: ExportFormat[];
}

/** 一键生成运行状态 */
export interface AutoRunStatus {
  project_id: number;
  processing_run_id: number;
  status: "running" | "paused" | "completed" | "failed";
  /** 当前阶段 */
  current_stage: PipelineStage;
  /** 各阶段 LLM 调用统计 */
  stage_stats: Record<PipelineStage, AutoRunStageStat>;
  /** 自动重合成统计 */
  auto_resynth: {
    total_triggered: number;
    successful: number;
    failed: number;
  };
  /** 累计成本 */
  total_cost_usd: number;
  /** 预估剩余时间（秒） */
  estimated_remaining_sec: number | null;
  started_at: ISODateTime;
  completed_at: ISODateTime | null;
  error?: string;
}

export interface AutoRunStageStat {
  stage: PipelineStage;
  status: StageStatus;
  llm_calls: number;
  tokens_used: number;
  cost_usd: number;
  progress: number;                   // 0.0-1.0
}


// ── 11.4 HARNESS 自我迭代控制台 (P0-AI-5) ────────────────────────────────
// 数据来源: feedback/integration.py, feedback/release.py, feedback/promotion_gate.py

/** 自我迭代总状态 */
export interface SelfIterationStatus {
  running: boolean;
  /** 累计迭代次数 */
  iteration_count: number;
  /** 上次迭代时间 */
  last_iteration_at: ISODateTime | null;
  /** 自动处理器状态 */
  auto_processor: {
    unprocessed_feedback_count: number;
    min_feedback_count: number;       // 默认 10
    check_interval_seconds: number;   // 默认 300
  };
  /** 上次升级的 prompts */
  upgraded_prompts: Record<string, string>;  // stage → new prompt path
  /** 上次分析报告 */
  last_analysis: {
    total_analyzed: number;
    top_patterns: Array<{ tag: PatternTag; count: number }>;
  };
}

/** 反馈漏斗（P0-AI-5 功能点 2） */
export interface FeedbackFunnel {
  total_feedback: number;
  analyzed: number;
  triggered_upgrade: number;
  passed_promotion_gate: number;
  published: number;
  /** 各层转化率 */
  conversion_rates: {
    to_analyzed: number;              // analyzed / total
    to_upgrade: number;
    to_promotion: number;
    to_publish: number;
  };
}

/** Critics Ensemble 评审结果（P0-AI-5 功能点 10） */
export interface CriticEnsembleResult {
  /** 最终融合裁决 */
  final_verdict: CriticVerdict;
  /** 加权融合分数 0.0-1.0 */
  final_score: number;
  /** 三派权重 */
  weights: {
    semantic: number;                 // 默认 0.30
    structural: number;               // 默认 0.20
    objective: number;                // 默认 0.50
  };
  /** 各派详细结果 */
  critics: {
    semantic: CriticDetail;
    structural: CriticDetail;
    objective: CriticDetail;
  };
  /** 校准结果 */
  calibration: {
    f1_macro: number;
    passed: boolean;                  // F1 >= 0.7
    accuracy: number;
  };
  timestamp: ISODateTime;
}

export interface CriticDetail {
  verdict: CriticVerdict;
  score: number;
  confidence: number;
  reasoning: string;
  evidence: JsonObject;
  tags: string[];
}

/** HARNESS 控制台聚合状态（建议后端新增 GET /api/harness/status） */
export interface HarnessConsoleAggregate {
  self_iteration: SelfIterationStatus;
  feedback_funnel: FeedbackFunnel;
  version_store: VersionStoreStatus;
  active_canaries: CanaryStatus[];
  latest_promotion: PromotionGateResult;
  latest_ab_test: ABTestResult | null;
  latest_critics: CriticEnsembleResult | null;
  /** 各 stage 当前 prompt 版本概览 */
  prompt_versions: Array<{
    stage: string;
    current_version: number;
    status: VersionLifecycle;
    last_updated: ISODateTime;
  }>;
}


// ── 11.5 Golden Dataset 管理 (P0-AI-6) ──────────────────────────────────
// 数据来源: tests/golden/, schemas/chapter_source.py

/** 金样本（Few-shot 样本） */
export interface GoldenSample {
  id: string;
  stage: LlmStageName;
  /** 输入契约 */
  input: JsonObject;
  /** 期望输出（金标准） */
  expected_output: JsonObject;
  /** 是否人工验证 */
  human_verified: boolean;
  /** 质量评分 0.0-1.0 */
  quality_score: number;
  /** 来源（项目贡献 or 初始内置） */
  source: "builtin" | "contributed";
  /** 贡献来源项目（若 source=contributed） */
  source_project_id?: number;
  created_at: ISODateTime;
}

/** 范本贡献到金数据集的请求 */
export interface GoldenContribution {
  /** 来自哪个范本 */
  template_id: string;
  source_project_id: number;
  stage: LlmStageName;
  input: JsonObject;
  expected_output: JsonObject;
  /** 贡献者备注 */
  note?: string;
}

/** 贡献审核状态 */
export type ContributionStatus = "pending_review" | "approved" | "rejected" | "needs_revision";

/** 待审核的贡献 */
export interface GoldenContributionRecord extends GoldenContribution {
  id: string;
  status: ContributionStatus;
  pattern_tags: PatternTag[];
  submitted_at: ISODateTime;
  reviewed_at: ISODateTime | null;
  reviewer_note?: string;
}

/** 回归测试报告 */
export interface GoldenTestReport {
  stage: LlmStageName;
  prompt_version: number;
  timestamp: ISODateTime;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  pass_rate: number;                  // 0.0-1.0
  /** 每个用例的明细 */
  case_results: Array<{
    case_id: string;
    passed: boolean;
    score?: number;
    failure_reason?: string;
  }>;
}


// ── 11.6 全局智能助手 (P0-AI-7) ────────────────────────────────────────

/** 助手问答请求 */
export interface AssistantQuery {
  /** 用户自然语言问题 */
  question: string;
  /** 当前页面上下文（自动注入） */
  context: AssistantContext;
}

/** 助手感知的页面上下文 */
export interface AssistantContext {
  /** 当前路由 */
  route: string;
  /** 当前项目 ID（若在项目页） */
  project_id?: number;
  /** 当前章节索引 */
  chapter_index?: number;
  /** 当前段落索引 */
  paragraph_index?: number;
  /** 用户选中的文本（若有） */
  selected_text?: string;
}

/** 助手响应 */
export interface AssistantResponse {
  answer: string;
  /** 建议的快捷操作（若有） */
  suggested_actions?: Array<{
    label: string;
    route?: string;
    action?: string;
  }>;
  /** 引用的 HARNESS 知识条目 */
  knowledge_refs?: string[];
}
