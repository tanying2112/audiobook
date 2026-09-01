<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import type { Paragraph, BookGenre } from '../types'
import * as api from '../api'
import { useSopCorrection } from '../composables/useSopCorrection'
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
      editNotes.value = (p as any).notes || ''
      hasChanges.value = false
    }
  },
  { immediate: true },
)

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
    emit('save', props.paragraph.id, {
      edited_text: correctedText,
    } as any)

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
        <label class="editor-label">{{ t('paragraph_editor.original_text') }}</label>
        <textarea
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
  </div>

  <div v-else class="editor-empty">
    <p>{{ t('paragraph_editor.select_hint') }}</p>
  </div>
</template>

<style scoped>
.paragraph-editor {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
}

.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
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
  background: #eff6ff;
  color: #1d4ed8;
  border-radius: 4px;
}

.editor-body { padding: 16px; }
.editor-section { margin-bottom: 12px; }
.editor-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  color: #64748b;
  margin-bottom: 6px;
}
.editor-textarea {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.7;
  font-family: inherit;
  resize: vertical;
  color: #1e293b;
  background: #fff;
  transition: border-color 0.15s;
}
.editor-textarea:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59,130,246,0.1);
}
.editor-notes { font-size: 13px; }

.editor-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid #e2e8f0;
  background: #f8fafc;
}
.status-badge { font-size: 11px; padding: 2px 10px; border-radius: 99px; text-transform: uppercase; }
.status-badge.completed { background: #dcfce7; color: #16a34a; }
.status-badge.pending { background: #fef9c3; color: #ca8a04; }
.status-badge.error { background: #fee2e2; color: #dc2626; }
.unsaved-badge { font-size: 12px; color: #f59e0b; }

.editor-empty {
  text-align: center;
  padding: 60px 20px;
  color: #94a3b8;
}
.editor-empty p { margin: 12px 0 0; font-size: 14px; }

.btn-sm { padding: 4px 12px; font-size: 13px; }
</style>