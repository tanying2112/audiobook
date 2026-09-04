<script setup lang="ts">
import { ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import { useI18n } from '../i18n'

const { t } = useI18n()

const API_BASE = '/api'

interface FeedbackForm {
  source: string
  stage: string
  book_id: string
  paragraph_index: number | null
  chapter_index: number | null
  input_snapshot: Record<string, any>
  llm_output: Record<string, any>
  corrected_output: Record<string, any>
  rationale: string
}

const sources = ['human_edit', 'quality_guess', 'user_rating']
const stages = [
  'extract',
  'analyze_structure',
  'annotate_paragraph',
  'edit_for_tts',
  'tts_routing',
  'quality_judge'
]

const form = ref<FeedbackForm>({
  source: 'human_edit',
  stage: 'annotate_paragraph',
  book_id: '',
  paragraph_index: null,
  chapter_index: null,
  input_snapshot: {},
  llm_output: {},
  corrected_output: {},
  rationale: ''
})

// JSON 文本字段（v-model 绑定，提交时解析回 form）
const jsonText = reactive({
  input_snapshot: JSON.stringify(form.value.input_snapshot, null, 2),
  llm_output: JSON.stringify(form.value.llm_output, null, 2),
  corrected_output: JSON.stringify(form.value.corrected_output, null, 2)
})

const loading = ref(false)
const message = ref('')
const messageType = ref<'success' | 'error'>('success')

function syncJsonText() {
  jsonText.input_snapshot = JSON.stringify(form.value.input_snapshot, null, 2)
  jsonText.llm_output = JSON.stringify(form.value.llm_output, null, 2)
  jsonText.corrected_output = JSON.stringify(form.value.corrected_output, null, 2)
}

function parseJsonText(): boolean {
  try {
    form.value.input_snapshot = JSON.parse(jsonText.input_snapshot)
  } catch {
    message.value = t('feedback_editor.json_parse_failed')
    messageType.value = 'error'
    return false
  }
  try {
    form.value.llm_output = JSON.parse(jsonText.llm_output)
  } catch {
    message.value = t('feedback_editor.json_parse_failed')
    messageType.value = 'error'
    return false
  }
  try {
    form.value.corrected_output = JSON.parse(jsonText.corrected_output)
  } catch {
    message.value = t('feedback_editor.json_parse_failed')
    messageType.value = 'error'
    return false
  }
  return true
}

const submitFeedback = async () => {
  if (!form.value.book_id) {
    message.value = t('feedback_editor.validation_book_id')
    messageType.value = 'error'
    return
  }
  if (!form.value.rationale || form.value.rationale.length < 10) {
    message.value = t('feedback_editor.validation_rationale')
    messageType.value = 'error'
    return
  }
  if (!parseJsonText()) return

  loading.value = true
  message.value = ''

  try {
    await axios.post(`${API_BASE}/feedback/`, form.value)
    message.value = t('feedback_editor.submit_success')
    messageType.value = 'success'
    ElMessage.success(message.value)
    form.value = {
      source: 'human_edit',
      stage: 'annotate_paragraph',
      book_id: '',
      paragraph_index: null,
      chapter_index: null,
      input_snapshot: {},
      llm_output: {},
      corrected_output: {},
      rationale: ''
    }
    syncJsonText()
  } catch (error: any) {
    message.value = t('feedback_editor.submit_failed') + (error.response?.data?.detail || error.message)
    messageType.value = 'error'
  } finally {
    loading.value = false
  }
}

const loadSampleData = () => {
  form.value = {
    source: 'human_edit',
    stage: 'annotate_paragraph',
    book_id: 'hongloumeng',
    paragraph_index: 0,
    chapter_index: 1,
    input_snapshot: {
      paragraph_text: 'Alexander 在图书馆里查阅边防要塞的最新回报时，突然接获了宫女的紧急通报。',
      paragraph_index: 0,
      chapter_index: 1,
      book_meta: { title: '智慧君主', genre: '小说', difficulty: 'B', language: 'zh' }
    },
    llm_output: {
      speaker_canonical_name: '旁白',
      emotion: 'neutral',
      emotion_intensity: 0.4,
      is_dialogue: false
    },
    corrected_output: {
      speaker_canonical_name: 'Alexander',
      emotion: 'tense',
      emotion_intensity: 0.8,
      is_dialogue: false
    },
    rationale: '该段落描述 Alexander 亲自处理危机，说话人应为 Alexander 而非旁白，且情感应为紧张而非中性。'
  }
  syncJsonText()
}
</script>

<template>
  <div class="feedback-editor">
    <div class="page-header">
      <h2>{{ t('feedback_editor.title') }}</h2>
    </div>

    <el-alert
      v-if="message"
      :title="message"
      :type="messageType"
      show-icon
      :closable="false"
      class="message-alert"
    />

    <el-form label-position="top">
      <el-row :gutter="16">
        <el-col :xs="24" :md="12">
          <el-form-item :label="t('feedback_editor.book_id') + ' *'">
            <el-input v-model="form.book_id" :placeholder="t('feedback_editor.book_id_placeholder')" />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :md="12">
          <el-form-item :label="t('feedback_editor.source') + ' *'">
            <el-select v-model="form.source" style="width: 100%">
              <el-option v-for="s in sources" :key="s" :label="t('feedback_editor.sources.' + s)" :value="s" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="24" :md="12">
          <el-form-item :label="t('feedback_editor.stage') + ' *'">
            <el-select v-model="form.stage" style="width: 100%">
              <el-option v-for="s in stages" :key="s" :label="t('feedback_editor.stages.' + s)" :value="s" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="24" :md="6">
          <el-form-item :label="t('feedback_editor.chapter_index')">
            <el-input-number v-model="form.chapter_index" :min="1" style="width: 100%" />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :md="6">
          <el-form-item :label="t('feedback_editor.paragraph_index')">
            <el-input-number v-model="form.paragraph_index" :min="0" style="width: 100%" />
          </el-form-item>
        </el-col>
      </el-row>

      <el-form-item :label="t('feedback_editor.input_snapshot') + ' (JSON)'">
        <el-input v-model="jsonText.input_snapshot" type="textarea" :rows="3" class="json-input" />
      </el-form-item>

      <el-form-item :label="t('feedback_editor.llm_output') + ' (JSON)'">
        <el-input v-model="jsonText.llm_output" type="textarea" :rows="3" class="json-input" />
      </el-form-item>

      <el-form-item :label="t('feedback_editor.corrected_output') + ' (JSON)'">
        <el-input v-model="jsonText.corrected_output" type="textarea" :rows="3" class="json-input" />
      </el-form-item>

      <el-form-item :label="t('feedback_editor.rationale') + ' *'">
        <el-input
          v-model="form.rationale"
          type="textarea"
          :rows="4"
          :placeholder="t('feedback_editor.rationale_placeholder')"
        />
        <div class="char-count">{{ form.rationale.length }}/10 {{ t('feedback_editor.min_chars') }}</div>
      </el-form-item>

      <div class="actions">
        <el-button type="primary" :loading="loading" @click="submitFeedback">
          {{ loading ? t('feedback_editor.submitting') : t('feedback_editor.submit') }}
        </el-button>
        <el-button @click="loadSampleData">{{ t('feedback_editor.load_sample') }}</el-button>
      </div>
    </el-form>
  </div>
</template>

<style scoped>
.feedback-editor { max-width: 760px; margin: 0 auto; padding: 24px; }
.page-header { margin-bottom: 16px; }
.page-header h2 { margin: 0; font-size: 20px; color: var(--color-text); }
.message-alert { margin-bottom: 16px; }
.json-input :deep(textarea) { font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace); }
.char-count { font-size: 12px; color: var(--color-text-muted); margin-top: 4px; }
.actions { display: flex; gap: 8px; margin-top: 8px; }
</style>