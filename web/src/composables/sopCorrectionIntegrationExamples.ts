/**
 * SOP Correction Integration Examples
 *
 * 以下示例展示如何在 ParagraphEditor.vue 和 CharacterManager.vue 中集成 useSopCorrection
 * 这些是参考实现，实际集成时请根据项目现有组件结构调整
 */

// ============================================================================
// 1. ParagraphEditor.vue 集成示例
// ============================================================================

/*
<script setup lang="ts">
import { useSopCorrection } from '@/composables/useSopCorrection'
import { useContextStore } from '@/stores/context'
import type { BookGenre, ParagraphEmotion } from '@/types'

const props = defineProps<{
  paragraphIndex: number
  chapterIndex: number
  initialEmotion: ParagraphEmotion
  initialSpeechRate: number
  // ... 其他字段
}>()

const ctx = useContextStore()
const projectId = computed(() => ctx.projectId)
const genre = computed(() => ctx.bookMeta?.genre ?? '小说')

// 初始化 SOP 修正捕获
const {
  sendCorrection,
  connectionState,
  isUsingFallback,
  pendingCount,
} = useSopCorrection({
  projectId: projectId.value,
  genre: genre.value,
  autoConnect: true,
  debounceFlushIntervalMs: 500,
  // 合并键：同一段落同一字段保留最新值
  getMergeKey: (c) => `${c.chapter_index}-${c.paragraph_index}-${c.field}`,
  onStateChange: (state) => {
    console.log('[SOP] 连接状态:', state)
  },
  onFallback: (reason) => {
    console.warn('[SOP] 切换到 HTTP 回退:', reason)
    // 可选：显示非阻塞 toast 提示
  },
  onError: (err) => {
    console.error('[SOP] 错误:', err)
  },
})

// 情感变更处理
async function handleEmotionChange(newEmotion: ParagraphEmotion) {
  if (newEmotion === props.initialEmotion) return

  await sendCorrection(
    'emotion',
    props.initialEmotion,
    newEmotion,
    props.paragraphIndex,
    props.chapterIndex,
    'ParagraphEditor: 用户在下拉框选择新情感',
  )

  // 本地状态立即更新（乐观 UI）
  props.initialEmotion = newEmotion
}

// 语速变更处理
async function handleSpeechRateChange(newRate: number) {
  if (Math.abs(newRate - props.initialSpeechRate) < 0.01) return

  await sendCorrection(
    'speech_rate',
    String(props.initialSpeechRate),
    String(newRate),
    props.paragraphIndex,
    props.chapterIndex,
    'ParagraphEditor: 用户拖动语速滑块',
  )

  props.initialSpeechRate = newRate
}

// 音高变更处理
async function handlePitchChange(newPitch: number) {
  // ... 类似逻辑
}

// SFX 标签变更
async function handleSfxTagsChange(newTags: string[]) {
  await sendCorrection(
    'sfx_tags',
    JSON.stringify(props.initialSfxTags),
    JSON.stringify(newTags),
    props.paragraphIndex,
    props.chapterIndex,
    'ParagraphEditor: 用户编辑 SFX 标签',
  )
}
</script>
*/

// ============================================================================
// 2. CharacterManager.vue 集成示例
// ============================================================================

/*
<script setup lang="ts">
import { useSopCorrection } from '@/composables/useSopCorrection'
import { useContextStore } from '@/stores/context'
import type { BookGenre } from '@/types'

const props = defineProps<{
  characterId: number
  canonicalName: string
  initialVoiceId: string | null
}>()

const ctx = useContextStore()
const projectId = computed(() => ctx.projectId)
const genre = computed(() => ctx.bookMeta?.genre ?? '小说')

const {
  sendCorrection,
  connectionState,
  isUsingFallback,
} = useSopCorrection({
  projectId: projectId.value,
  genre: genre.value,
  autoConnect: true,
  onFallback: (reason) => {
    console.warn('[SOP CharacterManager] 回退:', reason)
  },
})

// 声音绑定变更
async function handleVoiceBindingChange(newVoiceId: string | null) {
  if (newVoiceId === props.initialVoiceId) return

  await sendCorrection(
    'voice_binding',
    props.initialVoiceId ?? '',
    newVoiceId ?? '',
    0, // 角色级修正不依赖段落，使用 0
    0, // 章节级修正不依赖章节，使用 0
    `CharacterManager: 角色 "${props.canonicalName}" 声音绑定变更`,
  )

  props.initialVoiceId = newVoiceId
}

// 性别变更
async function handleGenderChange(newGender: string) {
  await sendCorrection(
    'gender',
    props.initialGender,
    newGender,
    0,
    0,
    `CharacterManager: 角色 "${props.canonicalName}" 性别变更`,
  )
}

// 年龄段变更
async function handleAgeRangeChange(newAgeRange: string) {
  await sendCorrection(
    'age_range',
    props.initialAgeRange,
    newAgeRange,
    0,
    0,
    `CharacterManager: 角色 "${props.canonicalName}" 年龄段变更`,
  )
}
</script>
*/

// ============================================================================
// 3. 通用 Hook 封装示例（推荐用法）
// ============================================================================

/*
// composables/useSopCorrectionIntegration.ts
import { useSopCorrection } from './useSopCorrection'
import { useContextStore } from '@/stores/context'
import type { BookGenre, ParagraphEmotion } from '@/types'

export function useParagraphSopCorrection(
  paragraphIndex: number,
  chapterIndex: number,
) {
  const ctx = useContextStore()

  return useSopCorrection({
    projectId: ctx.projectId,
    genre: ctx.bookMeta?.genre ?? '小说',
    autoConnect: true,
    getMergeKey: (c) => `${c.chapter_index}-${c.paragraph_index}-${c.field}`,
  })
}

export function useCharacterSopCorrection() {
  const ctx = useContextStore()

  return useSopCorrection({
    projectId: ctx.projectId,
    genre: ctx.bookMeta?.genre ?? '小说',
    autoConnect: true,
    getMergeKey: (c) => `character-${c.field}`, // 角色级修正合并键
  })
}

// 在组件中使用：
// const { sendCorrection } = useParagraphSopCorrection(paragraphIndex, chapterIndex)
// await sendCorrection('emotion', 'neutral', 'happy', paragraphIndex, chapterIndex)
*/

// ============================================================================
// 4. TypeScript 类型补充（如需扩展字段类型）
// ============================================================================

/*
// 在 types/index.ts 或 types/pipeline.ts 中补充：

export type SopCorrectionField =
  // 段落级字段
  | 'emotion'
  | 'emotion_intensity'
  | 'speech_rate'
  | 'pitch_shift_semitones'
  | 'speaker_canonical_name'
  | 'is_dialogue'
  | 'sfx_tags'
  | 'needs_sfx'
  | 'pause_before_ms'
  | 'pause_after_ms'
  | 'edited_text'
  // 角色级字段
  | 'voice_binding'
  | 'gender'
  | 'age_range'
  | 'suggested_voice_id'
  // 章节级字段
  | 'chapter_emotion'
  | 'chapter_style_notes'
  // 全书级字段
  | 'global_style_notes'
  | 'genre'
  | 'difficulty'
*/

// ============================================================================
// 5. 后端 API 契约参考（需后端实现）
// ============================================================================

/*
// WebSocket 端点: GET /api/sop/corrections/ws/{project_id}
//   - 连接后发送心跳: {type: "ping", timestamp}
//   - 接收 pong: {type: "pong", timestamp}
//   - 发送修正: {type: "correction", ...SopCorrectionMessage}
//   - 接收确认: {type: "ack", correction_id, status}

// HTTP 回退端点: POST /api/sop/corrections/{project_id}
//   Body: SopCorrectionRequest
//   Response: {correction_id, status, message}

// 消息示例:
// Client -> Server (WS):
// {
//   "type": "correction",
//   "project_id": 42,
//   "chapter_index": 0,
//   "paragraph_index": 5,
//   "field": "emotion",
//   "original_value": "neutral",
//   "corrected_value": "happy",
//   "genre": "小说",
//   "context": "ParagraphEditor: 用户在下拉框选择新情感",
//   "timestamp": "2026-07-17T10:30:00.000Z"
// }

// Server -> Client (WS):
// {
//   "type": "ack",
//   "correction_id": "42-0-5-emotion-1721172600000",
//   "status": "accepted"
// }
*/