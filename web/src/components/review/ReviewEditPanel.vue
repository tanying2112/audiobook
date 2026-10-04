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
import { reactive, watch, computed } from 'vue'
import { useI18n } from '../../i18n'
import { Icon } from '@iconify/vue'
import type { TTSVoicesResponse, ReviewParagraphEditPayload } from '../../api'
import type { Paragraph } from '../../types'

interface Props {
  paragraph: Paragraph | null
  ttsVoices: TTSVoicesResponse | null
  saving: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  save: [payload: ReviewParagraphEditPayload]
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
  Object.assign(form, base)
}

// 切换段落（或保存后父组件更新段落对象）→ 重新装载表单
watch(
  () => props.paragraph,
  (para) => resetForm(para),
  { immediate: true },
)

/** 构造差量 payload：只发送与当前值不同的字段；manual_* 用 clear_* 开关显式清除 */
function buildPayload(): ReviewParagraphEditPayload {
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
</style>
