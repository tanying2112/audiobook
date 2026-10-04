/**
 * 数据清洗纯函数层（蓝图策略 A 的 Vue/TS 版本）
 *
 * 核心原则：后端"脏状态"在进入 UI 之前全部洗净，UI 组件只接触标准化数据。
 * 决不让组件写 `if (status === 'route_status')` 这种补丁代码。
 *
 * 关键事实（探索确认）：
 *   1. Chapter 的 5 个 per-stage status（annotate/edit/route/synthesize/quality）
 *      后端从不赋值，恒为 'pending'。真实进度在 Paragraph.status。
 *   2. audio_postprocess 无独立 Chapter 字段，必须从 Paragraph 聚合推断。
 *   3. route_status 是永不填充的占位字段，不可作为 audio_postprocess 的依据。
 *   4. 后端时间字段三种形态混用：ISO string / float epoch 秒 / float epoch 毫秒。
 */

import {
  PIPELINE_STAGE_ORDER,
  PARAGRAPH_STATUS_FLOW,
  type NormalizedStageState,
  type NormalizeChapterInput,
  type NormalizeParagraphInput,
  type ParagraphStatus,
  type PipelineStage,
  type StageStatus,
} from '../types/pipeline'

// ── A. Paragraph 状态清洗 ───────────────────────────────────────────────────

/** 已知的合法 ParagraphStatus 值集合（O(1) 查找） */
const _VALID_PARAGRAPH_STATUS = new Set<string>(PARAGRAPH_STATUS_FLOW)

/**
 * 把任意字符串值清洗为 6 值 ParagraphStatus 枚举。
 * 未知值 / 空值归一为 'pending'。
 */
export function normalizeParagraphStatus(raw: unknown): ParagraphStatus {
  if (typeof raw === 'string' && _VALID_PARAGRAPH_STATUS.has(raw)) {
    return raw as ParagraphStatus
  }
  return 'pending'
}

/**
 * 返回 ParagraphStatus 在流转链中的序号（越大阶段越靠后）。
 * 用于聚合推断与"进度百分比"计算。未知值视为 0（pending）。
 */
export function paragraphStatusIndex(status: ParagraphStatus): number {
  return PARAGRAPH_STATUS_FLOW.indexOf(status)
}

// ── B. 章节管线状态清洗（两者结合策略）──────────────────────────────────────

/**
 * Chapter per-stage 字段名 → 前端 7 阶段的映射。
 * audio_postprocess 无独立字段，此处不列入（由段落聚合推断）。
 */
const _CHAPTER_FIELD_TO_STAGE: Partial<Record<keyof NormalizeChapterInput, PipelineStage>> = {
  extract_status: 'extract',
  analyze_status: 'analyze',
  annotate_status: 'annotate',
  edit_status: 'edit',
  synthesize_status: 'synthesize',
  quality_status: 'quality',
}

/**
 * 判断 Chapter 字段是否表示"已完成"。
 * 后端写入值是 'completed'；默认 'pending'。兼容未来 'running'/'failed'。
 */
function _isChapterFieldCompleted(value: unknown): boolean {
  return value === 'completed'
}

/**
 * 根据段落列表聚合判断某阶段是否完成（回退策略）。
 *
 * 后端 Chapter 的 annotate/edit/synthesize/quality 等字段恒为 'pending'，
 * 真实进度写在 Paragraph.status。此处按"该阶段对应的 Paragraph.status 已出现"
 * 来推断 Chapter 级别完成。
 *
 * 各阶段对应的"完成判定"Paragraph.status：
 *   annotate   → 存在 ≥ 'annotated' 的段落
 *   edit       → 存在 ≥ 'edited' 的段落
 *   audio_postprocess → 存在 ≥ 'audio_processed' 的段落
 *   synthesize → 存在 ≥ 'synthesized' 的段落
 *   quality    → 存在 ≥ 'quality_checked' 的段落
 */
const _STAGE_PARAGRAPH_THRESHOLD: Partial<Record<PipelineStage, ParagraphStatus>> = {
  annotate: 'annotated',
  edit: 'edited',
  audio_postprocess: 'audio_processed',
  synthesize: 'synthesized',
  quality: 'quality_checked',
}

/**
 * 将后端 Chapter 数据清洗为前端统一 7 阶段状态数组。
 *
 * 策略（两者结合）：
 *   1. 第一优先级：Chapter per-stage 字段（extract/analyze 后端会写 completed）
 *   2. 第二优先级（回退）：若 Chapter 字段为 pending，从 Paragraph[] 聚合推断
 *   3. audio_postprocess 始终用段落聚合推断（无独立字段）
 *
 * @param chapter  Chapter API 响应（至少含各 *_status 字段）
 * @param paragraphs 同章节的段落列表（可选；不提供时无法回退推断）
 *
 * @example
 * const stages = normalizeChapterPipeline(chapter, paragraphs)
 * stages.forEach(({ stage, status }) => renderStageDot(stage, status))
 */
export function normalizeChapterPipeline(
  chapter: NormalizeChapterInput,
  paragraphs?: NormalizeParagraphInput[],
): NormalizedStageState[] {
  // 预计算段落状态序号的最大值，供聚合判定复用
  const paragraphStatuses = (paragraphs ?? []).map((p) =>
    paragraphStatusIndex(normalizeParagraphStatus(p?.status)),
  )

  return PIPELINE_STAGE_ORDER.map((stage): NormalizedStageState => {
    // 1. 优先读 Chapter 字段
    const chapterFieldName = (
      Object.keys(_CHAPTER_FIELD_TO_STAGE) as (keyof NormalizeChapterInput)[]
    ).find((k) => _CHAPTER_FIELD_TO_STAGE[k] === stage)

    if (chapterFieldName) {
      const raw = chapter[chapterFieldName]
      if (_isChapterFieldCompleted(raw)) {
        return { stage, status: 'completed', inferred_from: 'chapter_field' }
      }
      // 非 completed（pending/running/failed）— 若非 pending 直接采纳
      if (typeof raw === 'string' && raw === 'running') {
        return { stage, status: 'running', inferred_from: 'chapter_field' }
      }
      if (typeof raw === 'string' && raw === 'failed') {
        return { stage, status: 'failed', inferred_from: 'chapter_field' }
      }
    }

    // 2. 回退：段落聚合推断（仅当提供了 paragraphs）
    const threshold = _STAGE_PARAGRAPH_THRESHOLD[stage]
    if (threshold !== undefined && paragraphStatuses.length > 0) {
      const thresholdIdx = paragraphStatusIndex(threshold)
      const hasReached = paragraphStatuses.some((idx) => idx >= thresholdIdx)
      if (hasReached) {
        return { stage, status: 'completed', inferred_from: 'paragraph_agg' }
      }
    }

    // 3. 默认 pending
    return { stage, status: 'pending', inferred_from: 'default' }
  })
}

/**
 * 从标准化阶段数组计算整体进度百分比（0-1）。
 * completed 计 1，running 计 0.5，其余计 0。
 */
export function computePipelineProgress(stages: NormalizedStageState[]): number {
  if (stages.length === 0) return 0
  const score = stages.reduce((sum, s) => {
    if (s.status === 'completed') return sum + 1
    if (s.status === 'running') return sum + 0.5
    return sum
  }, 0)
  return score / stages.length
}

// ── C. 时间戳清洗 ───────────────────────────────────────────────────────────

/**
 * 统一清洗后端时间字段为 ISO 8601 字符串。
 *
 * 处理后端三种形态：
 *   - ISO 字符串（Project/Chapter.created_at）→ 原样返回
 *   - float epoch 秒（CircuitBreaker.last_failure_time, QuotaUsage.last_successful_request）
 *     → `new Date(x * 1000).toISOString()`
 *   - float epoch 毫秒（>1e12）→ `new Date(x).toISOString()`
 *   - relative 秒 / null / undefined → null（无绝对时间参考）
 *
 * 判定阈值：> 1e12 视为毫秒，> 1e9 视为秒（相对秒一般 < 1000）。
 */
export function normalizeTimestamp(raw: unknown): string | null {
  if (raw == null) return null
  if (typeof raw === 'string') {
    // 已是 ISO 字符串；简单校验非空
    return raw.length > 0 ? raw : null
  }
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    if (raw > 1e12) {
      // epoch 毫秒
      return new Date(raw).toISOString()
    }
    if (raw > 1e9) {
      // epoch 秒
      return new Date(raw * 1000).toISOString()
    }
    // 相对秒数，无法还原为绝对时间
    return null
  }
  return null
}

// ── D. 辅助：阶段显示名（轻量 i18n，避免引入完整 i18n 依赖）─────────────────

const _STAGE_LABEL_ZH: Record<PipelineStage, string> = {
  extract: '文本提取',
  analyze: '结构分析',
  annotate: '段落标注',
  edit: '文本编辑',
  audio_postprocess: '声学参数',
  synthesize: '音频合成',
  quality: '质量检测',
}

const _STAGE_LABEL_EN: Record<PipelineStage, string> = {
  extract: 'Extract',
  analyze: 'Analyze',
  annotate: 'Annotate',
  edit: 'Edit',
  audio_postprocess: 'Audio Post',
  synthesize: 'Synthesize',
  quality: 'Quality',
}

/** 获取阶段的本地化显示名 */
export function stageLabel(stage: PipelineStage, locale: 'zh' | 'en' = 'zh'): string {
  return locale === 'en' ? _STAGE_LABEL_EN[stage] : _STAGE_LABEL_ZH[stage]
}

const _STATUS_LABEL_ZH: Record<StageStatus, string> = {
  pending: '待处理',
  running: '进行中',
  completed: '已完成',
  failed: '失败',
}

/** 获取阶段状态的本地化显示名 */
export function statusLabel(status: StageStatus, locale: 'zh' | 'en' = 'zh'): string {
  if (locale === 'en') return status
  return _STATUS_LABEL_ZH[status]
}

// ── E. Re-export 常量（供测试与外部消费方统一从 normalize 入口引用）──────────
export { PIPELINE_STAGE_ORDER, PARAGRAPH_STATUS_FLOW }
export type { PipelineStage, StageStatus, ParagraphStatus, NormalizedStageState }
export type { NormalizeChapterInput, NormalizeParagraphInput }

