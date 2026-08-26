<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '../i18n'
import { fetchProject } from '../api'
import type { Project } from '../types'
import api from '../api'
import { Icon } from '@iconify/vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const projectId = Number(route.params.projectId || route.params.id)
const project = ref<Project | null>(null)
const availableFormats = ref([
  { value: 'm4b', label: t('export.format_m4b'), description: t('export.format_m4b_desc') },
  { value: 'srt', label: t('export.format_srt'), description: t('export.format_srt_desc') },
  { value: 'vtt', label: t('export.format_vtt'), description: t('export.format_vtt_desc') },
  { value: 'm4b_srt', label: t('export.format_m4b_srt'), description: t('export.format_m4b_srt_desc') },
  { value: 'all', label: t('export.format_all'), description: t('export.format_all_desc') },
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

function goBack() {
  router.push(`/projects/${projectId}`)
}

function getStatusClass(status: string): string {
  const map: Record<string, string> = {
    completed: 'badge-success',
    failed: 'badge-danger',
    processing: 'badge-warning',
    pending: 'badge-muted',
  }
  return map[status?.toLowerCase()] || 'badge-muted'
}
</script>

<template>
  <div class="page-container export-view">
    <header class="page-header">
      <button class="btn btn-ghost touch-target" @click="goBack">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        <span class="hidden-mobile">{{ t('common.back') }}</span>
      </button>
      <div class="flex-1">
        <h1>{{ t('export.title') }}</h1>
        <p class="page-subtitle">{{ t('export.subtitle') }}</p>
      </div>
    </header>

    <!-- Project Info -->
    <section v-if="project" class="card card-hover section">
      <div class="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 class="card-title">{{ project.title }}</h2>
          <div class="flex items-center gap-3 mt-2 text-secondary">
            <span v-if="project.author"><Icon icon="mdi:account" width="16" height="16" class="gap-2" />{{ project.author }}</span>
            <span :class="getStatusClass(project.status || 'pending')">{{ t('common.' + (project.status || 'pending')) }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- Export Configuration -->
    <section class="card card-hover section">
      <h2 class="card-title">{{ t('export.configuration') }}</h2>

      <div class="form-group mb-4">
        <label class="form-label">{{ t('export.formats') }}</label>
        <div class="format-options grid gap-3" style="grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));">
          <label v-for="fmt in availableFormats" :key="fmt.value" class="checkbox-label card p-3 cursor-pointer flex flex-col gap-2" :class="{ 'border-primary bg-primary-soft': selectedFormats.includes(fmt.value) }" @click.stop="selectedFormats.includes(fmt.value) ? selectedFormats.splice(selectedFormats.indexOf(fmt.value), 1) : selectedFormats.push(fmt.value)">
            <div class="flex items-center gap-2">
              <input type="checkbox" :value="fmt.value" v-model="selectedFormats" class="checkbox" style="accent-color: var(--color-primary); width: 18px; height: 18px;" />
              <span class="format-name font-medium">{{ fmt.label }}</span>
            </div>
            <span class="format-desc text-muted text-sm">{{ fmt.description }}</span>
          </label>
        </div>
      </div>

      <div class="form-group mb-4">
        <label class="form-label">{{ t('export.options') }}</label>
        <div class="flex flex-wrap gap-4">
          <label class="checkbox-label flex items-center gap-2 cursor-pointer">
            <input type="checkbox" v-model="exportOptions.normalize" class="checkbox" style="accent-color: var(--color-primary); width: 18px; height: 18px;" />
            {{ t('export.normalize') }}
          </label>
          <label class="checkbox-label flex items-center gap-2 cursor-pointer">
            <input type="checkbox" v-model="exportOptions.include_cover" class="checkbox" style="accent-color: var(--color-primary); width: 18px; height: 18px;" />
            {{ t('export.includeCover') }}
          </label>
        </div>
      </div>

      <div class="form-group mb-4">
        <label class="form-label">{{ t('export.maxCharsPerLine') }}</label>
        <input
          type="number"
          v-model.number="exportOptions.max_chars_per_line"
          min="20"
          max="80"
          class="form-control"
          style="max-width: 120px;"
        />
      </div>
    </section>

    <!-- Export Actions -->
    <section class="card card-hover section">
      <div class="flex justify-end gap-2 mb-4">
        <button
          class="btn btn-primary btn-lg"
          @click="startExport"
          :disabled="selectedFormats.length === 0 || exporting"
        >
          <Icon v-if="exporting" icon="mdi:loading" width="18" height="18" class="spinner gap-2" style="border-color: rgba(255,255,255,.35); border-top-color: #fff" />
          <Icon v-else icon="mdi:export" width="18" height="18" class="gap-2" />
          {{ exporting ? t('export.exporting') : t('export.startExport') }}
        </button>
      </div>

      <!-- Progress / Result -->
      <div v-if="exporting || exportResult" class="export-status">
        <div v-if="exporting" class="loading-state">
          <div class="spinner"></div>
          <span>{{ t('export.exporting') }}...</span>
        </div>

        <div v-else-if="exportResult" class="card" :class="exportResult.status === 'completed' ? 'border-success' : exportResult.status === 'failed' ? 'border-danger' : 'border-warning'">
          <div class="p-4">
            <div v-if="exportResult.status === 'completed'" class="flex items-center gap-3 text-success">
              <Icon icon="mdi:check-circle" width="24" height="24" />
              <div>
                <h3 class="font-medium">{{ t('export.success') }}</h3>
                <div v-if="exportResult.output_paths" class="output-paths mt-3 space-y-2">
                  <div v-for="(path, format) in exportResult.output_paths" :key="format" class="path-item flex items-center gap-2 p-2" style="background: var(--color-bg-tertiary); border-radius: var(--radius);">
                    <span class="badge badge-primary">{{ String(format).toUpperCase() }}</span>
                    <span class="path font-mono text-sm truncate" style="flex: 1;">{{ path }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div v-else-if="exportResult.status === 'failed'" class="flex items-center gap-3 text-danger">
              <Icon icon="mdi:alert-circle" width="24" height="24" />
              <div>
                <h3 class="font-medium">{{ t('export.failed') }}</h3>
                <p class="mt-1">{{ exportResult.error }}</p>
              </div>
            </div>
            <div v-else class="flex items-center gap-3 text-warning">
              <Icon icon="mdi:clock-outline" width="24" height="24" />
              <div>
                <h3 class="font-medium">{{ t('export.status') }}: {{ exportResult.status }}</h3>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.export-view {
  max-width: 800px;
}

.format-options {
  display: grid;
  gap: 12px;
}

.checkbox-label {
  transition: all var(--transition);
  cursor: pointer;
}

.checkbox-label:hover {
  background: var(--color-bg-tertiary);
}

.checkbox-label:has(input:checked) {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
}

.format-name {
  font-weight: 500;
}

.format-desc {
  color: var(--color-text-muted);
  font-size: 12px;
}

.path-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.path {
  font-family: monospace;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 767px) {
  .format-options {
    grid-template-columns: 1fr;
  }
}
</style>