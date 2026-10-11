<template>
  <div v-if="paragraph" class="review-edit-panel">
    <!-- 人工编辑表单：合成前设置与标注文本（客户最终控制） -->
    <div class="edit-section">
      <label class="edit-label">{{ t('review_gate.edited_text') }}</label>
      <textarea
        v-model="form.edited_text"
        class="edit-textarea"
        rows="4"
        :placeholder="paragraph.text"
      />
      <p class="text-secondary text-sm original-text">
        {{ t('review_gate.original_text') }}: {{ paragraph.text }}
      </p>
    </div>

    <div class="edit-grid">
      <div class="edit-field">
        <label class="edit-label">{{ t('review_gate.speaker') }}</label>
        <input v-model="form.speaker" type="text" class="edit-input" />
      </div>
      <div class="edit-field edit-field--check">
        <label class="edit-label check-label">
          <input v-model="form.is_dialogue" type="checkbox" />
          {{ t('review_gate.is_dialogue') }}
        </label>
      </div>
      <div class="edit-field">
        <label class="edit-label">{{ t('review_gate.emotion') }}</label>
        <input v-model="form.emotion" type="text" class="edit-input" />
      </div>
      <div class="edit-field">
        <label class="edit-label">{{ t('review_gate.emotion_intensity') }} (0-1)</label>
        <input
          v-model.number="form.emotion_intensity"
          type="number"
          min="0"
          max="1"
          step="0.1"
          class="edit-input"
        />
      </div>
      <div class="edit-field">
        <label class="edit-label">{{ t('review_gate.speech_rate') }} (0-3)</label>
        <input
          v-model.number="form.speech_rate"
          type="number"
          min="0.1"
          max="3"
          step="0.1"
          class="edit-input"
        />
      </div>
      <div class="edit-field">
        <label class="edit-label">{{ t('review_gate.pitch_shift') }}</label>
        <input
          v-model.number="form.pitch_shift_semitones"
          type="number"
          min="-12"
          max="12"
          step="1"
          class="edit-input"
        />
      </div>
      <div class="edit-field">
        <label class="edit-label">{{ t('review_gate.pause_before') }}</label>
        <input
          v-model.number="form.pause_before_ms"
          type="number"
          min="0"
          max="10000"
          step="50"
          class="edit-input"
        />
      </div>
      <div class="edit-field">
        <label class="edit-label">{{ t('review_gate.pause_after') }}</label>
        <input
          v-model.number="form.pause_after_ms"
          type="number"
          min="0"
          max="10000"
          step="50"
          class="edit-input"
        />
      </div>
      <div class="edit-field edit-field--check">
        <label class="edit-label check-label">
          <input v-model="form.needs_sfx" type="checkbox" />
          {{ t('review_gate.needs_sfx') }}
        </label>
      </div>
      <div class="edit-field">
        <label class="edit-label">{{ t('review_gate.sfx_tags') }}（逗号分隔）</label>
        <input v-model="form.sfx_tags" type="text" class="edit-input" />
      </div>
    </div>

    <div class="edit-section">
      <label class="edit-label">{{ t('review_gate.notes') }}</label>
      <textarea v-model="form.notes" class="edit-textarea" rows="2" />
    </div>

    <!-- 人工覆盖：客户最终控制（manual_* > 角色绑定 > 自动选择） -->
    <div class="edit-section override-section">
      <label class="edit-label">{{ t('review_gate.manual_override_badge') }}</label>
      <p class="text-secondary text-sm">{{ t('review_gate.manual_override_hint') }}</p>
      <div class="edit-grid">
        <div class="edit-field">
          <label class="edit-label">{{ t('review_gate.manual_engine') }}</label>
          <select v-model="form.manual_engine" class="edit-input">
            <option value="">{{ t('review_gate.auto_voice') }}</option>
            <option v-for="engine in engineOptions" :key="engine" :value="engine">
              {{ engine }}
            </option>
          </select>
        </div>
        <div class="edit-field">
          <label class="edit-label">{{ t('review_gate.manual_voice') }}</label>
          <input
            v-model="form.manual_voice_id"
            type="text"
            class="edit-input"
            list="review-voice-options"
          />
          <datalist id="review-voice-options">
            <option v-for="v in voiceOptions" :key="v.id" :value="v.id">
              {{ v.label }}
            </option>
          </datalist>
        </div>
      </div>
    </div>

    <!-- v6 逐句导演：按句覆盖增益/语速/音高/音色/句后停顿（缺省=继承段落级） -->
    <div class="edit-section override-section sentence-director">
      <button
        type="button"
        class="director-toggle"
        :aria-expanded="showDirector"
        @click="showDirector = !showDirector"
      >
        <Icon
          :icon="showDirector ? 'mdi:chevron-up' : 'mdi:chevron-down'"
          width="16"
          height="16"
        />
        <span class="director-title">逐句导演</span>
        <span class="text-secondary text-sm director-count">
          {{ sentenceOverridesCount ? `已设 ${sentenceOverridesCount} 句覆盖` : '未设置' }}
        </span>
      </button>
      <p class="text-secondary text-sm director-hint">
        按编辑后文本切句预览（切句规则与合成管线一致）；每句可覆盖
        增益(dB) / 语速 / 音高(st) / 音色 / 句后停顿(ms)，留空 = 继承段落级设置。
      </p>
      <template v-if="showDirector">
        <div v-if="sentencePreview.length" class="sentence-list">
          <div v-for="(s, i) in sentencePreview" :key="i" class="sentence-row">
            <div class="sentence-head">
              <span class="sentence-idx" :title="`句序号 idx=${i}`">{{ i }}</span>
              <span class="sentence-text">{{ s }}</span>
            </div>
            <div class="sentence-fields">
              <input
                v-model="sentenceRows[i].gain_db"
                type="number"
                step="0.5"
                placeholder="增益dB"
                class="edit-input"
              />
              <input
                v-model="sentenceRows[i].speed"
                type="number"
                step="0.05"
                min="0.1"
                max="3"
                placeholder="语速"
                class="edit-input"
              />
              <input
                v-model="sentenceRows[i].pitch_st"
                type="number"
                step="0.5"
                placeholder="音高st"
                class="edit-input"
              />
              <input
                v-model="sentenceRows[i].voice_id"
                type="text"
                list="review-voice-options"
                placeholder="音色 (支持 a+b*0.55)"
                class="edit-input"
              />
              <input
                v-model="sentenceRows[i].pause_after_ms"
                type="number"
                step="50"
                min="0"
                placeholder="句后停顿ms"
                class="edit-input"
              />
            </div>
          </div>
        </div>
        <p v-else class="text-secondary text-sm">当前文本没有可切分的句子。</p>
      </template>
    </div>

    <div class="edit-section">
      <label class="edit-label">{{ t('review_gate.edit_note') }}</label>
      <input v-model="form.note" type="text" class="edit-input" />
    </div>

    <div class="edit-actions">
      <button
        class="btn btn-primary"
        :disabled="saving"
        @click="handleSave"
      >
        <Icon v-if="saving" icon="mdi:loading" width="16" height="16" class="spinner" />
        <Icon v-else icon="mdi:content-save" width="16" height="16" />
        {{ saving ? t('review_gate.saving') : t('review_gate.save') }}
      </button>
    </div>
  </div>
  <p v-else class="text-secondary text-sm empty-hint">
    {{ t('review_gate.select_chapter_hint') }}
  </p>
</template>

<script setup lang="ts">
import { ref, reactive, watch, computed } from 'vue'
import { useI18n } from '../../i18n'
import { Icon } from '@iconify/vue'
import type { TTSVoicesResponse, ReviewParagraphEditPayload } from '../../api'
import type { Paragraph, SentenceOverride } from '../../types'
import { splitSentences } from '../../utils/sentences'

interface Props {
  paragraph: Paragraph | null
  ttsVoices: TTSVoicesResponse | null
  saving: boolean
}

const props = defineProps<Props>()

/** 保存 payload 本地扩展（约束：不改 api/index.ts；后端 ReviewParagraphPatch 已收编同名字段） */
type ReviewEditPayloadWithSentences = ReviewParagraphEditPayload & {
  sentence_overrides?: SentenceOverride[]
  clear_sentence_overrides?: boolean
}

const emit = defineEmits<{
  save: [payload: ReviewEditPayloadWithSentences]
}>()

const { t } = useI18n()

// EngineChoice 全集（与后端 schemas/tts_routing.py EngineChoice 一致；
// 引擎可用性由后端在合成时诚实接受/拒绝）
const ALL_ENGINES = [
  'piper',
  'kokoro',
  'edge',
  'azure',
  'gcp',
  'human_clone',
  'cosyvoice_stream',
  'seed_tts_stream',
  'melotts_stream',
  'xtts_v2',
  'openvoice_v2',
  'cosyvoice_clone',
  'voxcpm2',
] as const

const engineOptions = computed<string[]>(() => {
  if (props.ttsVoices) {
    const available = Object.values(props.ttsVoices.engines)
      .filter((e) => e.available)
      .map((e) => e.id)
    const rest = ALL_ENGINES.filter((e) => !available.includes(e))
    return [...available, ...rest]
  }
  return [...ALL_ENGINES]
})

const voiceOptions = computed(() => {
  const out: { id: string; label: string }[] = []
  if (props.ttsVoices) {
    for (const engine of Object.values(props.ttsVoices.engines)) {
      for (const voice of engine.voices || []) {
        out.push({ id: voice.id, label: `${engine.name} · ${voice.name}` })
      }
    }
  }
  return out
})

// ── v6 逐句导演（sentence_overrides）────────────────────────────────────
// 每句一行的输入态；字符串承载数字以便用空串表达「继承段落级」。
interface SentenceRowState {
  gain_db: string
  speed: string
  pitch_st: string
  voice_id: string
  pause_after_ms: string
}

const showDirector = ref(false)
const sentenceRows = reactive<SentenceRowState[]>([])

function emptySentenceRow(): SentenceRowState {
  return { gain_db: '', speed: '', pitch_st: '', voice_id: '', pause_after_ms: '' }
}

/** 切句预览：按编辑后文本（合成实际读取的文本）客户端同款规则切句 */
const sentencePreview = computed<string[]>(() => splitSentences(form.edited_text ?? ''))

// 句数随预览增减：新增句补空行（继承），缩短句裁掉尾部行（保留未裁部分的输入）
watch(
  sentencePreview,
  (list) => {
    const n = list.length
    if (sentenceRows.length > n) sentenceRows.length = n
    while (sentenceRows.length < n) sentenceRows.push(emptySentenceRow())
  },
  { immediate: true },
)

/** 载入库中已存的 sentence_overrides 到行输入态（稀疏 idx 用空行补齐） */
function loadSentenceRows(overrides: SentenceOverride[] | null | undefined): void {
  sentenceRows.length = 0
  const list = (overrides || []).filter(
    (o): o is SentenceOverride => !!o && typeof o.idx === 'number' && o.idx >= 0,
  )
  const maxIdx = list.reduce((m, o) => Math.max(m, o.idx), -1)
  for (let i = 0; i <= maxIdx; i++) {
    const o = list.find((x) => x.idx === i)
    sentenceRows.push({
      gain_db: o?.gain_db != null ? String(o.gain_db) : '',
      speed: o?.speed != null ? String(o.speed) : '',
      pitch_st: o?.pitch_st != null ? String(o.pitch_st) : '',
      voice_id: o?.voice_id ?? '',
      pause_after_ms: o?.pause_after_ms != null ? String(o.pause_after_ms) : '',
    })
  }
}

/** 组装差量：仅收集有任一字段填写的句；数字非法/为空 = 不覆盖该字段 */
function buildSentenceOverrides(): SentenceOverride[] {
  const out: SentenceOverride[] = []
  for (let i = 0; i < sentencePreview.length; i++) {
    const row = sentenceRows[i]
    if (!row) continue
    const o: SentenceOverride = { idx: i }
    let any = false
    const gain = parseFloat(row.gain_db)
    if (row.gain_db.trim() !== '' && Number.isFinite(gain)) {
      o.gain_db = gain
      any = true
    }
    const speed = parseFloat(row.speed)
    if (row.speed.trim() !== '' && Number.isFinite(speed)) {
      o.speed = speed
      any = true
    }
    const pitch = parseFloat(row.pitch_st)
    if (row.pitch_st.trim() !== '' && Number.isFinite(pitch)) {
      o.pitch_st = pitch
      any = true
    }
    const pause = parseFloat(row.pause_after_ms)
    if (row.pause_after_ms.trim() !== '' && Number.isFinite(pause)) {
      o.pause_after_ms = Math.round(pause)
      any = true
    }
    if (row.voice_id.trim()) {
      o.voice_id = row.voice_id.trim()
      any = true
    }
    if (any) out.push(o)
  }
  return out
}

/** 规范化序列化（固定键序 + idx 排序）用于与库中现值比较，避免顺序差异误判 */
function serializeOverrides(list: SentenceOverride[] | null | undefined): string {
  return JSON.stringify(
    (list || [])
      .filter((o): o is SentenceOverride => !!o && typeof o.idx === 'number')
      .map((o) => {
        const rec: Record<string, unknown> = { idx: o.idx }
        if (typeof o.gain_db === 'number') rec.gain_db = o.gain_db
        if (typeof o.speed === 'number') rec.speed = o.speed
        if (typeof o.pitch_st === 'number') rec.pitch_st = o.pitch_st
        if (typeof o.voice_id === 'string' && o.voice_id) rec.voice_id = o.voice_id
        if (typeof o.pause_after_ms === 'number') rec.pause_after_ms = o.pause_after_ms
        return rec
      })
      .sort((a, b) => (a.idx as number) - (b.idx as number)),
  )
}

const sentenceOverridesCount = computed(() => buildSentenceOverrides().length)

interface EditFormState {
  edited_text: string
  speaker: string
  is_dialogue: boolean
  emotion: string
  emotion_intensity: number | undefined
  speech_rate: number | undefined
  pitch_shift_semitones: number | undefined
  pause_before_ms: number | undefined
  pause_after_ms: number | undefined
  needs_sfx: boolean
  sfx_tags: string
  notes: string
  manual_engine: string
  manual_voice_id: string
  note: string
}

const form = reactive<EditFormState>(emptyForm())

function emptyForm(): EditFormState {
  return {
    edited_text: '',
    speaker: '',
    is_dialogue: false,
    emotion: '',
    emotion_intensity: undefined,
    speech_rate: undefined,
    pitch_shift_semitones: undefined,
    pause_before_ms: undefined,
    pause_after_ms: undefined,
    needs_sfx: false,
    sfx_tags: '',
    notes: '',
    manual_engine: '',
    manual_voice_id: '',
    note: '',
  }
}

function resetForm(para: Paragraph | null): void {
  const base = emptyForm()
  if (para) {
    base.edited_text = para.edited_text ?? para.text
    base.speaker = para.speaker_canonical_name ?? ''
    base.is_dialogue = !!para.is_dialogue
    base.emotion = para.emotion ?? ''
    base.emotion_intensity = para.emotion_intensity
    base.speech_rate = para.speech_rate
    base.pitch_shift_semitones = para.pitch_shift_semitones
    base.pause_before_ms = para.pause_before_ms
    base.pause_after_ms = para.pause_after_ms
    base.needs_sfx = !!para.needs_sfx
    base.sfx_tags = (para.sfx_tags || []).join(', ')
    base.notes = para.notes ?? ''
    base.manual_engine = para.manual_engine ?? ''
    base.manual_voice_id = para.manual_voice_id ?? ''
  }
  loadSentenceRows(para?.sentence_overrides)
  Object.assign(form, base)
}

// 切换段落（或保存后父组件更新段落对象）→ 重新装载表单
watch(
  () => props.paragraph,
  (para) => resetForm(para),
  { immediate: true },
)

/** 构造差量 payload：只发送与当前值不同的字段；manual_* / sentence_overrides 用 clear_* 开关显式清除 */
function buildPayload(): ReviewEditPayloadWithSentences {
  const para = props.paragraph
  if (!para) return {}
  const payload: ReviewParagraphEditPayload = {}

  if ((form.edited_text ?? '') !== (para.edited_text ?? para.text)) {
    payload.edited_text = form.edited_text ?? ''
  }
  if (form.speaker !== (para.speaker_canonical_name ?? '')) {
    payload.speaker_canonical_name = form.speaker
  }
  if (form.is_dialogue !== !!para.is_dialogue) payload.is_dialogue = form.is_dialogue
  if (form.emotion !== (para.emotion ?? '')) payload.emotion = form.emotion
  if (form.emotion_intensity !== para.emotion_intensity) {
    payload.emotion_intensity = form.emotion_intensity
  }
  if (form.speech_rate !== para.speech_rate) payload.speech_rate = form.speech_rate
  if (form.pitch_shift_semitones !== para.pitch_shift_semitones) {
    payload.pitch_shift_semitones = form.pitch_shift_semitones
  }
  if (form.pause_before_ms !== para.pause_before_ms) payload.pause_before_ms = form.pause_before_ms
  if (form.pause_after_ms !== para.pause_after_ms) payload.pause_after_ms = form.pause_after_ms
  if (form.needs_sfx !== !!para.needs_sfx) payload.needs_sfx = form.needs_sfx

  const formTags = form.sfx_tags
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  if (formTags.join(',') !== (para.sfx_tags || []).join(',')) {
    payload.sfx_tags = formTags
  }
  if (form.notes !== (para.notes ?? '')) payload.notes = form.notes

  if (form.manual_engine && form.manual_engine !== (para.manual_engine ?? '')) {
    payload.manual_engine = form.manual_engine
  } else if (!form.manual_engine && para.manual_engine) {
    payload.clear_manual_engine = true
  }
  if (form.manual_voice_id && form.manual_voice_id !== (para.manual_voice_id ?? '')) {
    payload.manual_voice_id = form.manual_voice_id
  } else if (!form.manual_voice_id && para.manual_voice_id) {
    payload.clear_manual_voice_id = true
  }

  // v6 逐句导演：与库中现值不同才发；行全清空 → clear_sentence_overrides 显式清除
  const builtOverrides = buildSentenceOverrides()
  if (serializeOverrides(builtOverrides) !== serializeOverrides(para.sentence_overrides)) {
    if (builtOverrides.length) {
      payload.sentence_overrides = builtOverrides
    } else if (para.sentence_overrides?.length) {
      payload.clear_sentence_overrides = true
    }
  }

  if (form.note.trim()) payload.note = form.note.trim()
  return payload
}

function handleSave(): void {
  emit('save', buildPayload())
  form.note = '' // 编辑理由随每次保存提交，不残留
}
</script>

<style scoped>
.review-edit-panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.edit-section {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.override-section {
  padding: 0.75rem;
  border: 1px dashed var(--color-border);
  border-radius: 8px;
}

.edit-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 0.75rem;
}

.edit-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.edit-field--check {
  justify-content: flex-end;
}

.edit-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-secondary, #666);
}

.check-label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  cursor: pointer;
}

.edit-input {
  padding: 0.4rem 0.5rem;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  font-size: 0.9rem;
  background: var(--color-bg, transparent);
  color: inherit;
}

.edit-textarea {
  padding: 0.5rem;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  font-size: 0.9rem;
  line-height: 1.5;
  resize: vertical;
  background: var(--color-bg, transparent);
  color: inherit;
  font-family: inherit;
}

.original-text {
  margin: 0;
  overflow-wrap: anywhere;
}

.edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}

.empty-hint {
  padding: 1rem;
  text-align: center;
}

/* v6 逐句导演 */
.director-toggle {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0;
  border: none;
  background: none;
  color: inherit;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
}

.director-title {
  color: var(--color-text, inherit);
}

.director-count {
  font-weight: 400;
}

.director-hint {
  margin: 0;
}

.sentence-list {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.sentence-row {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  padding: 0.5rem;
  border: 1px solid var(--color-border);
  border-radius: 6px;
}

.sentence-head {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
}

.sentence-idx {
  flex: none;
  min-width: 1.4rem;
  text-align: center;
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--color-text-secondary, #666);
  background: var(--color-bg-secondary, rgba(127, 127, 127, 0.12));
  border-radius: 4px;
  padding: 0.1rem 0.3rem;
}

.sentence-text {
  font-size: 0.85rem;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.sentence-fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 0.4rem;
}
</style>
