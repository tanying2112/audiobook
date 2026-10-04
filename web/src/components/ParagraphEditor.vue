<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import type { Paragraph, BookGenre } from '../types'
import type { ChatSuggestion } from '../types/pipeline'
import * as api from '../api'
import { useSopCorrection } from '../composables/useSopCorrection'
import { useInlineChat } from '../composables/useInlineChat'
import InlineChatPopup from './chat/InlineChatPopup.vue'
import { useI18n } from '../i18n'

const props = defineProps<{
  paragraph: Paragraph | null
  projectId: number
  chapterId: number
}>()

const emit = defineEmits<{
  save: [paragraphId: number, payload: Partial<Paragraph>]
  close: []
}>()

const { t } = useI18n()

const editText = ref('')
const editNotes = ref('')
const hasChanges = ref(false)
const isSaving = ref(false)

// ── SOP correction capture (P0.1) ─────────────────────────────────────────
// 用户翻改段落文本 = 对"剧本内容"的人工纠错，投喂 SOP 反思循环。
// genre 来自后端 Project.genre；在已知后初始化 composable，避免向空 genre 发送无意义修正。
const genre = ref<BookGenre>('')
let sendCorrection: ((
  field: string,
  originalValue: string,
  correctedValue: string,
  paragraphIndex: number,
  chapterIndex: number,
  context?: string,
) => Promise<boolean>) | null = null

onMounted(async () => {
  try {
    const project = await api.fetchProject(props.projectId)
    if (project?.genre) genre.value = project.genre as BookGenre
  } catch {
    // 体裁解析失败不阻塞编辑；用默认 genre 继续
  }
  sendCorrection = useSopCorrection({
    projectId: props.projectId,
    genre: genre.value,
    autoConnect: true,
    onFallback: (reason) => console.warn('[SOP ParagraphEditor] HTTP 回退:', reason),
  }).sendCorrection
})

watch(
  () => props.paragraph,
  (p) => {
    if (p) {
      editText.value = p.edited_text || p.text || ''
      editNotes.value = p.notes || ''
      hasChanges.value = false
    }
  },
  { immediate: true },
)

// ── 内联 AI 对话（P0-AI-8）─────────────────────────────────────────────────
// 弹窗锚定在原文 textarea 旁，与 LLM 就当前正文对话；采纳建议回写编辑区。
const chat = useInlineChat({
  projectId: () => props.projectId,
  chapterIndex: () => props.chapterId,
  targetStage: 'edit',
  onAccept: applyAiSuggestion,
})

const editorTextarea = ref<HTMLTextAreaElement | null>(null)
// 打开小窗时的正文快照：只有建议真的改了文本才回写，避免把用户已改的文本回退成原文
let textAtOpen = ''

function openAiChat() {
  const el = editorTextarea.value
  const p = props.paragraph
  if (!el || !p) return
  textAtOpen = editText.value
  chat.open(el, {
    kind: 'text_selection',
    paragraph_id: p.index ?? p.id,
    selected_text: editText.value,
    param_field: 'edited_text',
  })
}

async function applyAiSuggestion(suggestion: ChatSuggestion) {
  const after = suggestion.after as Record<string, unknown> | undefined
  const edited =
    (suggestion as unknown as { edited_text?: string }).edited_text ??
    (after?.edited_text as string | undefined) ??
    (after?.text as string | undefined)
  if (edited && edited !== textAtOpen) {
    editText.value = edited
    hasChanges.value = true
  }
}

onUnmounted(() => chat.close())

function onTextChange() {
  hasChanges.value = true
}

async function handleSave() {
  if (!props.paragraph?.id || !hasChanges.value) return
  isSaving.value = true
  const originalText = props.paragraph.original_text || props.paragraph.text || ''
  const correctedText = editText.value
  const paragraphIndex = props.paragraph.index ?? props.paragraph.id
  try {
    const payload: Partial<Paragraph> = { edited_text: correctedText }
    // 备注有改动时一并提交（此前只发 edited_text，备注被静默丢弃）
    if (editNotes.value !== (props.paragraph.notes ?? '')) {
      payload.notes = editNotes.value
    }
    emit('save', props.paragraph.id, payload)

    // ✅ 投喂 SOP 纠错（保存后入队，入队失败静默降级，不阻塞保存/emit）。
    // 仅当正文确实发生变化时投喂（备注改动不投喂——不在 SOP 学习域内）。
    if (originalText && correctedText !== originalText && sendCorrection) {
      void sendCorrection(
        'edited_text',
        originalText,
        correctedText,
        paragraphIndex,
        props.chapterId,
        'ParagraphEditor: 用户人工翻改段落正文',
      ).catch((e) => {
        console.warn('[SOP ParagraphEditor] 投喂失败（静默降级）:', e?.message || e)
      })
    }

    hasChanges.value = false
  } finally {
    isSaving.value = false
  }
}

function handleClose() {
  if (hasChanges.value) {
    if (!confirm(t('paragraph_editor.unsaved_warning'))) return
  }
  emit('close')
}
</script>

<template>
  <div v-if="paragraph" class="paragraph-editor">
    <div class="editor-header">
      <h3>{{ t('paragraph_editor.title', { id: paragraph.id }) }}</h3>
      <div class="editor-header-actions">
        <span v-if="paragraph.speaker_canonical_name" class="role-badge">
          {{ paragraph.speaker_canonical_name }}
        </span>
        <button class="btn btn-primary btn-sm" :disabled="!hasChanges || isSaving" @click="handleSave">
          {{ t('paragraph_editor.save') }}
        </button>
        <button class="btn btn-ghost btn-sm" @click="handleClose">
          {{ t('paragraph_editor.close') }}
        </button>
      </div>
    </div>

    <div class="editor-body">
      <div class="editor-section">
        <label class="editor-label">
          <span>{{ t('paragraph_editor.original_text') }}</span>
          <button
            class="btn btn-ghost btn-xs"
            :disabled="!paragraph"
            @click="openAiChat"
          >{{ t('paragraph_editor.ai_chat') }}</button>
        </label>
        <textarea
          ref="editorTextarea"
          v-model="editText"
          class="editor-textarea"
          rows="6"
          @input="onTextChange"
          :placeholder="t('paragraph_editor.placeholder_edited')"
        ></textarea>
      </div>

      <div class="editor-section">
        <label class="editor-label">{{ t('paragraph_editor.notes') }}</label>
        <textarea
          v-model="editNotes"
          class="editor-textarea editor-notes"
          rows="2"
          @input="onTextChange"
          :placeholder="t('paragraph_editor.placeholder_notes')"
        ></textarea>
      </div>
    </div>

    <div class="editor-status">
      <span class="status-badge" :class="paragraph.status || 'pending'">
        {{ paragraph.status || 'pending' }}
      </span>
      <span v-if="hasChanges" class="unsaved-badge">{{ t('paragraph_editor.unsaved_changes') }}</span>
    </div>

    <InlineChatPopup :chat="chat" />
  </div>

  <div v-else class="editor-empty">
    <p>{{ t('paragraph_editor.select_hint') }}</p>
  </div>
</template>

<style scoped>
.paragraph-editor {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-raised);
}
.editor-header h3 {
  margin: 0;
  font-size: 15px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.editor-header-actions { display: flex; align-items: center; gap: 8px; }
.role-badge {
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  border-radius: 4px;
}

.editor-body { padding: 16px; }
.editor-section { margin-bottom: 12px; }
.editor-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
.btn-xs { padding: 2px 8px; font-size: 12px; }
.editor-textarea {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  font-size: 14px;
  line-height: 1.7;
  font-family: inherit;
  resize: vertical;
  color: var(--color-text);
  background: var(--color-surface);
  transition: border-color 0.15s;
}
.editor-textarea:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px var(--color-primary-soft);
}
.editor-notes { font-size: 13px; }

.editor-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-raised);
}
.status-badge { font-size: 11px; padding: 2px 10px; border-radius: var(--radius-full); text-transform: uppercase; }
.status-badge.completed { background: var(--color-success); color: var(--color-surface); }
.status-badge.pending { background: var(--color-warning); color: var(--color-text); }
.status-badge.error { background: var(--color-danger); color: var(--color-surface); }
.unsaved-badge { font-size: 12px; color: var(--color-warning); }

.editor-empty {
  text-align: center;
  padding: 60px 20px;
  color: var(--color-text-secondary);
}
.editor-empty p { margin: 12px 0 0; font-size: 14px; }

.btn-sm { padding: 4px 12px; font-size: 13px; }
</style>