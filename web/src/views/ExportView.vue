<template>
  <div class="export-view">
    <div class="header">
      <h1>{{ t('export.title') }}</h1>
      <p class="subtitle">{{ t('export.subtitle') }}</p>
    </div>

    <!-- Project Info -->
    <section class="card" v-if="project">
      <h2>{{ project.title }}</h2>
      <p class="meta">
        <span v-if="project.author">{{ project.author }}</span>
        <span class="status-badge" :class="project.status">{{ project.status }}</span>
      </p>
    </section>

    <!-- Export Configuration -->
    <section class="card">
      <h2>{{ t('export.configuration') }}</h2>

      <div class="form-group">
        <label>{{ t('export.formats') }}</label>
        <div class="format-options">
          <label v-for="fmt in availableFormats" :key="fmt.value" class="checkbox-label">
            <input
              type="checkbox"
              :value="fmt.value"
              v-model="selectedFormats"
            />
            <span class="format-name">{{ fmt.label }}</span>
            <span class="format-desc">{{ fmt.description }}</span>
          </label>
        </div>
      </div>

      <div class="form-group">
        <label>{{ t('export.options') }}</label>
        <label class="checkbox-label">
          <input type="checkbox" v-model="exportOptions.normalize" />
          {{ t('export.normalize') }}
        </label>
        <label class="checkbox-label">
          <input type="checkbox" v-model="exportOptions.include_cover" />
          {{ t('export.includeCover') }}
        </label>
      </div>

      <div class="form-group">
        <label>{{ t('export.maxCharsPerLine') }}</label>
        <input
          type="number"
          v-model.number="exportOptions.max_chars_per_line"
          min="20"
          max="80"
          class="input short"
        />
      </div>
    </section>

    <!-- Export Actions -->
    <section class="card">
      <div class="actions">
        <button
          class="btn primary"
          @click="startExport"
          :disabled="selectedFormats.length === 0 || exporting"
        >
          {{ exporting ? t('export.exporting') : t('export.startExport') }}
        </button>
      </div>

      <!-- Progress -->
      <div v-if="exporting || exportResult" class="export-status">
        <div v-if="exporting" class="progress-container">
          <div class="spinner"></div>
          <span>{{ t('export.exporting') }}...</span>
        </div>

        <div v-if="exportResult" class="result">
          <div v-if="exportResult.status === 'completed'" class="success">
            <h3>{{ t('export.success') }}</h3>
            <div v-if="exportResult.output_paths" class="output-paths">
              <div v-for="(path, format) in exportResult.output_paths" :key="format" class="path-item">
                <span class="format-tag">{{ format }}</span>
                <span class="path">{{ path }}</span>
              </div>
            </div>
          </div>
          <div v-else-if="exportResult.status === 'failed'" class="error">
            <h3>{{ t('export.failed') }}</h3>
            <p>{{ exportResult.error }}</p>
          </div>
          <div v-else class="info">
            <p>{{ t('export.status') }}: {{ exportResult.status }}</p>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from '../i18n'
import { fetchProject } from '../api'
import type { Project } from '../types'
import api from '../api'

const route = useRoute()
const { t } = useI18n()

const projectId = Number(route.params.projectId || route.params.id)
const project = ref<Project | null>(null)
const availableFormats = ref([
  { value: 'm4b', label: 'M4B', description: '有声书格式,含章节标记' },
  { value: 'srt', label: 'SRT', description: '字幕格式' },
  { value: 'vtt', label: 'WebVTT', description: 'Web字幕格式' },
  { value: 'm4b_srt', label: 'M4B + SRT', description: '有声书+字幕' },
  { value: 'all', label: '全部', description: '所有格式+ZIP包' },
])
const selectedFormats = ref<string[]>(['m4b_srt'])
const exportOptions = ref({
  normalize: true,
  include_cover: true,
  max_chars_per_line: 40,
})
const exporting = ref(false)
const exportResult = ref<any>(null)

onMounted(async () => {
  try {
    project.value = await fetchProject(projectId)
  } catch (e) {
    console.error('Failed to load project:', e)
  }
})

async function startExport() {
  exporting.value = true
  exportResult.value = null

  try {
    const { data } = await api.post(`/api/projects/${projectId}/export/`, {
      formats: selectedFormats.value,
      normalize: exportOptions.value.normalize,
      include_cover: exportOptions.value.include_cover,
      max_chars_per_line: exportOptions.value.max_chars_per_line,
    })
    exportResult.value = data
  } catch (e: any) {
    exportResult.value = {
      status: 'failed',
      error: e.response?.data?.detail || e.message || 'Export failed',
    }
  } finally {
    exporting.value = false
  }
}
</script>

<style scoped>
.export-view {
  max-width: 700px;
  margin: 0 auto;
  padding: 2rem;
}
.header {
  margin-bottom: 2rem;
}
.header h1 {
  font-size: 1.8rem;
  margin: 0;
}
.subtitle {
  color: var(--color-text-secondary, #888);
  margin: 0.5rem 0 0;
}
.card {
  background: var(--color-bg-secondary, #f9f9f9);
  border: 1px solid var(--color-border, #e0e0e0);
  border-radius: 12px;
  padding: 1.5rem;
  margin-bottom: 1.5rem;
}
.card h2 {
  margin: 0 0 1rem;
  font-size: 1.2rem;
}
.meta {
  display: flex;
  gap: 1rem;
  align-items: center;
  color: var(--color-text-secondary, #888);
}
.status-badge {
  padding: 0.2rem 0.6rem;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: 500;
}
.form-group {
  margin-bottom: 1rem;
}
.form-group > label:first-child {
  display: block;
  font-weight: 600;
  margin-bottom: 0.5rem;
}
.format-options {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  padding: 0.4rem 0;
}
.format-name {
  font-weight: 500;
}
.format-desc {
  color: var(--color-text-secondary, #888);
  font-size: 0.85rem;
}
.input.short {
  width: 100px;
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--color-border, #ccc);
  border-radius: 6px;
}
.actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 1rem;
}
.btn {
  padding: 0.6rem 1.2rem;
  border: none;
  border-radius: 8px;
  font-size: 0.95rem;
  cursor: pointer;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn.primary {
  background: var(--color-primary, #4a90d9);
  color: white;
}
.export-status {
  margin-top: 1rem;
}
.progress-container {
  display: flex;
  align-items: center;
  gap: 0.8rem;
}
.spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--color-border, #ccc);
  border-top-color: var(--color-primary, #4a90d9);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.result {
  padding: 1rem;
  border-radius: 8px;
  margin-top: 0.5rem;
}
.success {
  background: #e6f7e6;
  border: 1px solid #b7eb8f;
}
.error {
  background: #fff2f0;
  border: 1px solid #ffccc7;
}
.output-paths {
  margin-top: 0.5rem;
}
.path-item {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  padding: 0.3rem 0;
}
.format-tag {
  background: var(--color-primary, #4a90d9);
  color: white;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
}
.path {
  font-family: monospace;
  font-size: 0.85rem;
}
</style>
