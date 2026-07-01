/**
 * Pipeline / Normalize / Inline-Chat 类型定义
 *
 * 对齐 docs/frontend-types-contract.ts 的 Part 1（枚举）与 Part 11（AI 工作台）。
 * 本文件聚焦前端实际消费的子集，供 normalize.ts / sse.ts / useInlineChat.ts 使用。
 */

// ── 管线阶段 ────────────────────────────────────────────────────────────────

/**
 * 管线 7 阶段（含 audio_postprocess）。
 *
 * 注意后端存在三套命名，前端统一用此枚举：
 *   - ORM Chapter per-stage 字段（extract_status / analyze_status / ...）
 *   - LLM 路由阶段（route / judge 替代 synthesize / quality）
 *   - Checkpoint STAGE_ORDER（6 阶段，不含 audio_postprocess）
 */
export type PipelineStage =
  | 'extract'
  | 'analyze'
  | 'annotate'
  | 'edit'
  | 'audio_postprocess'
  | 'synthesize'
  | 'quality'

/** 管线阶段顺序（用于进度条 / normalize 计算） */
export const PIPELINE_STAGE_ORDER: PipelineStage[] = [
  'extract',
  'analyze',
  'annotate',
  'edit',
  'audio_postprocess',
  'synthesize',
  'quality',
]

// ── 状态枚举 ────────────────────────────────────────────────────────────────

/** 阶段状态（Chapter per-stage 字段的清洗后标准值） */
export type StageStatus = 'pending' | 'running' | 'completed' | 'failed'

/**
 * Paragraph 单字段状态流转（models/paragraph.py:103 + orchestrator 写入值）。
 * 流转路径: pending → annotated → edited → audio_processed → synthesized → quality_checked
 */
export type ParagraphStatus =
  | 'pending'
  | 'annotated'
  | 'edited'
  | 'audio_processed'
  | 'synthesized'
  | 'quality_checked'

/** 段落状态有序数组（索引越大代表阶段越靠后） */
export const PARAGRAPH_STATUS_FLOW: ParagraphStatus[] = [
  'pending',
  'annotated',
  'edited',
  'audio_processed',
  'synthesized',
  'quality_checked',
]

// ── Normalize 输出类型 ──────────────────────────────────────────────────────

/** normalizeChapterPipeline 的单阶段标准输出（UI 唯一消费的类型） */
export interface NormalizedStageState {
  stage: PipelineStage
  status: StageStatus
  /** 来源标记，便于调试：'chapter_field' = Chapter 字段直接读取，'paragraph_agg' = 段落聚合推断 */
  inferred_from: 'chapter_field' | 'paragraph_agg' | 'default'
}

/**
 * 数据清洗后的最小 Chapter 输入结构。
 * 仅声明 normalize 需要读取的字段，避免与 web/src/types/index.ts 的完整 Chapter 强耦合。
 */
export interface NormalizeChapterInput {
  extract_status?: string
  analyze_status?: string
  annotate_status?: string
  edit_status?: string
  route_status?: string
  synthesize_status?: string
  quality_status?: string
  [key: string]: unknown
}

/** normalize 所需的最小 Paragraph 输入 */
export interface NormalizeParagraphInput {
  status?: string
  [key: string]: unknown
}

// ── AI 对话（P0-AI-1/2/8）────────────────────────────────────────────────────

export type ChatRole = 'user' | 'assistant' | 'system'

export type ChatEditTargetStage = 'edit' | 'annotate'

/** 对话窗口形态：右侧固定面板 / Cursor 风格内联小窗 */
export type ChatWindowMode = 'panel' | 'inline'

/** 单条对话消息 */
export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  timestamp: string
  /** assistant 消息附带的结构化编辑建议 */
  suggestion?: ChatSuggestion
  /** 用户采纳状态 */
  adoption?: 'pending' | 'accepted' | 'rejected'
}

/**
 * LLM 返回的结构化编辑建议。
 * 内联小窗与右侧面板共用同一结构。
 */
export interface ChatSuggestion {
  kind: 'text_edit' | 'annotation_adjust' | 'voice_binding'
  paragraph_id: string
  before: Record<string, unknown>
  after: Record<string, unknown>
  changes_made: string[]
  confidence: number
  rationale: string
  pattern_tag?: string
}

/** 文本编辑快捷指令（P0-AI-1） */
export type EditShortcut =
  | 'normalize_numbers'
  | 'split_long_sentences'
  | 'colloquialize'
  | 'formalize'
  | 'remove_sensitive'
  | 'adjust_pace_hint'

/** 对话式编辑请求（SSE POST body） */
export interface ChatEditRequest {
  project_id: number
  chapter_index: number
  paragraph_index: number
  target_stage: ChatEditTargetStage
  intent: string
  conversation_history: ChatMessage[]
  annotation_context?: Record<string, unknown>
  shortcut?: EditShortcut
}

/** 对话式编辑 SSE 流式事件 */
export type ChatEditStreamEvent =
  | { type: 'thinking'; message_id: string }
  | { type: 'token'; content: string; message_id: string }
  | { type: 'suggestion'; suggestion: ChatSuggestion; message_id: string }
  | { type: 'done'; message_id: string }
  | { type: 'error'; message: string; code?: string }

/**
 * Cursor 风格内联小窗的锚点上下文（P0-AI-8）。
 * 描述小窗"锚定"在哪个选区/参数控件旁边。
 */
export interface InlineChatAnchor {
  /** 锚点类型：文本选区 / 参数控件 / 段落 */
  kind: 'text_selection' | 'param_control' | 'paragraph'
  /** 目标段落 ID（paragraph / text_selection 时） */
  paragraph_id?: number
  /** 选中文本（text_selection 时） */
  selected_text?: string
  /** 选区在段落内的起止偏移（text_selection 时） */
  selection_start?: number
  selection_end?: number
  /** 锚定的参数字段名（param_control 时，如 'emotion' / 'speech_rate'） */
  param_field?: string
  /** 参数当前值（param_control 时） */
  param_value?: unknown
  /** 小窗定位锚（像素坐标，由触发元素的 getBoundingClientRect 计算） */
  rect: { x: number; y: number; width: number; height: number }
}

/** 内联小窗运行时状态 */
export interface InlineChatState {
  /** 是否激活 */
  active: boolean
  /** 锚点上下文 */
  anchor: InlineChatAnchor | null
  /** 当前对话消息 */
  messages: ChatMessage[]
  /** 流式接收中的文本（打字机缓冲） */
  streamingText: string
  /** 加载中 */
  loading: boolean
  /** 错误信息 */
  error: string | null
}
