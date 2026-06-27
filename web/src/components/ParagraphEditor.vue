<script setup lang="ts">
import { ref, watch } from 'vue'
import type { Paragraph } from '../types'

const props = defineProps<{
  paragraph: Paragraph | null
  projectId: number
  chapterId: number
}>()

const emit = defineEmits<{
  save: [paragraphId: number, payload: Partial<Paragraph>]
  close: []
}>()

const editText = ref('')
const editNotes = ref('')
const hasChanges = ref(false)
const isSaving = ref(false)

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
  try {
    emit('save', props.paragraph.id, {
      edited_text: editText.value,
    } as any)
    hasChanges.value = false
  } finally {
    isSaving.value = false
  }
}

function handleClose() {
  if (hasChanges.value) {
    if (!confirm('有未保存的更改，确定关闭？')) return
  }
  emit('close')
}
</script>

<template>
  <div v-if="paragraph" class="paragraph-editor">
    <div class="editor-header">
      <h3>段落编辑 — #{{ paragraph.id }}</h3>
      <div class="editor-header-actions">
        <span v-if="paragraph.speaker_canonical_name" class="role-badge">
          {{ paragraph.speaker_canonical_name }}
        </span>
        <button class="btn btn-primary btn-sm" :disabled="!hasChanges || isSaving" @click="handleSave">
          保存
        </button>
        <button class="btn btn-ghost btn-sm" @click="handleClose">
          关闭
        </button>
      </div>
    </div>

    <div class="editor-body">
      <div class="editor-section">
        <label class="editor-label">原文</label>
        <textarea
          v-model="editText"
          class="editor-textarea"
          rows="6"
          @input="onTextChange"
          placeholder="段落文本..."
        ></textarea>
      </div>

      <div class="editor-section">
        <label class="editor-label">备注</label>
        <textarea
          v-model="editNotes"
          class="editor-textarea editor-notes"
          rows="2"
          @input="onTextChange"
          placeholder="可选的备注信息..."
        ></textarea>
      </div>
    </div>

    <div class="editor-status">
      <span class="status-badge" :class="paragraph.status || 'pending'">
        {{ paragraph.status || 'pending' }}
      </span>
      <span v-if="hasChanges" class="unsaved-badge">有未保存的更改</span>
    </div>
  </div>

  <div v-else class="editor-empty">
    <p>选择一个段落以编辑</p>
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