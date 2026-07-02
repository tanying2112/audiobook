<script setup lang="ts">
import { ref } from 'vue'
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

const loading = ref(false)
const message = ref('')
const messageType = ref<'success' | 'error'>('success')

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

  loading.value = true
  message.value = ''

  try {
    await axios.post(`${API_BASE}/feedback/`, form.value)
    message.value = t('feedback_editor.submit_success')
    messageType.value = 'success'
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
}

const parseJsonField = (field: keyof FeedbackForm) => {
  try {
    const el = document.getElementById(`json-${field}`) as HTMLTextAreaElement
    if (!el) return
    const parsed = JSON.parse(el.value)
    if (field === 'input_snapshot') form.value.input_snapshot = parsed
    else if (field === 'llm_output') form.value.llm_output = parsed
    else if (field === 'corrected_output') form.value.corrected_output = parsed
  } catch {
    message.value = t('feedback_editor.json_parse_failed')
    messageType.value = 'error'
  }
}
</script>

<template>
  <div class="feedback-editor max-w-4xl mx-auto p-6 bg-white rounded-xl shadow-sm">
    <h2 class="text-2xl font-semibold text-gray-800 mb-6">{{ t('feedback_editor.title') }}</h2>

    <div v-if="message" :class="['mb-4 p-4 rounded-lg', messageType === 'success' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700']">
      {{ message }}
    </div>

    <div class="space-y-6">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">{{ t('feedback_editor.book_id') }} *</label>
          <input
            v-model="form.book_id"
            type="text"
            class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            :placeholder="t('feedback_editor.book_id_placeholder')"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">{{ t('feedback_editor.source') }} *</label>
          <select v-model="form.source" class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500">
            <option v-for="s in sources" :key="s" :value="s">{{ t('feedback_editor.sources.' + s) }}</option>
          </select>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">{{ t('feedback_editor.stage') }} *</label>
          <select v-model="form.stage" class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500">
            <option v-for="s in stages" :key="s" :value="s">{{ t('feedback_editor.stages.' + s) }}</option>
          </select>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">{{ t('feedback_editor.chapter_index') }}</label>
          <input
            v-model.number="form.chapter_index"
            type="number"
            min="1"
            class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">{{ t('feedback_editor.paragraph_index') }}</label>
          <input
            v-model.number="form.paragraph_index"
            type="number"
            min="0"
            class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">{{ t('feedback_editor.input_snapshot') }} (JSON)</label>
        <textarea
          id="json-input_snapshot"
          rows="3"
          class="w-full px-3 py-2 border border-gray-300 rounded-lg font-mono text-sm"
          :value="JSON.stringify(form.input_snapshot, null, 2)"
          @change="() => parseJsonField('input_snapshot')"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">{{ t('feedback_editor.llm_output') }} (JSON)</label>
        <textarea
          id="json-llm_output"
          rows="3"
          class="w-full px-3 py-2 border border-gray-300 rounded-lg font-mono text-sm"
          :value="JSON.stringify(form.llm_output, null, 2)"
          @change="() => parseJsonField('llm_output')"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">{{ t('feedback_editor.corrected_output') }} (JSON)</label>
        <textarea
          id="json-corrected_output"
          rows="3"
          class="w-full px-3 py-2 border border-gray-300 rounded-lg font-mono text-sm"
          :value="JSON.stringify(form.corrected_output, null, 2)"
          @change="() => parseJsonField('corrected_output')"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">{{ t('feedback_editor.rationale') }} *</label>
        <textarea
          v-model="form.rationale"
          rows="4"
          class="w-full px-3 py-2 border border-gray-300 rounded-lg"
          :placeholder="t('feedback_editor.rationale_placeholder')"
        />
        <p class="mt-1 text-sm text-gray-500">{{ form.rationale.length }}/10 {{ t('feedback_editor.min_chars') }}</p>
      </div>

      <div class="flex gap-3">
        <button
          @click="submitFeedback"
          :disabled="loading"
          class="px-6 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
        >
          {{ loading ? t('feedback_editor.submitting') : t('feedback_editor.submit') }}
        </button>
        <button
          @click="loadSampleData"
          class="px-6 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
        >
          {{ t('feedback_editor.load_sample') }}
        </button>
      </div>
    </div>
  </div>
</template>