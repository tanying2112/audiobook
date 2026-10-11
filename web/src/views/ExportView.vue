<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '../i18n'
import { useProjectStore } from '../stores/projects'
import { Icon } from '@iconify/vue'
import api from '../api'
import { fetchExportFiles, downloadExportFile } from '../api'
import type { ExportFileInfo } from '../api'
import '../views/ExportView.css'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const projectStore = useProjectStore()

const projectId = Number(route.params.projectId || route.params.id)

const availableFormats = [
  { value: 'm4b', label: t('export.format_m4b'), description: t('export.format_m4b_desc') },
  { value: 'srt', label: t('export.format_srt'), description: t('export.format_srt_desc') },
  { value: 'vtt', label: t('export.format_vtt'), description: t('export.format_vtt_desc') },
  { value: 'm4b_srt', label: t('export.format_m4b_srt'), description: t('export.format_m4b_srt_desc') },
  { value: 'all', label: t('export.format_all'), description: t('export.format_all_desc') },
]

const selectedFormats = ref<string[]>(['m4b_srt'])
const exportOptions = ref({
  normalize: true,
  include_cover: true,
  max_chars_per_line: 40,
})
const exporting = ref(false)
const exportResult = ref<any>(null)
const exportFiles = ref<ExportFileInfo[]>([])
const downloadingPath = ref<string | null>(null)
const downloadError = ref<string | null>(null)

onMounted(async () => {
  if (!projectStore.currentProject || projectStore.currentProject.id !== projectId) {
    await projectStore.loadProject(projectId)
  }
})

async function startExport() {
  exporting.value = true
  exportResult.value = null
  exportFiles.value = []
  downloadError.value = null
  try {
    const { data } = await api.post(`/api/projects/${projectId}/export/`, {
      formats: selectedFormats.value,
      normalize: exportOptions.value.normalize,
      include_cover: exportOptions.value.include_cover,
      max_chars_per_line: exportOptions.value.max_chars_per_line,
    })
    exportResult.value = data
    // Poll until terminal state (queued/running/pending → complete/completed/failed)
    if (data.status === 'queued' || data.status === 'running' || data.status === 'pending') {
      await pollExportStatus()
    }
    if (isTerminalComplete(exportResult.value?.status)) {
      await refreshExportFiles()
    }
  } catch (e: any) {
    exportResult.value = {
      status: 'failed',
      error: e.response?.data?.detail || e.message || 'Export failed',
    }
  } finally {
    exporting.value = false
  }
}

function isTerminalComplete(status: string): boolean {
  return status === 'completed' || status === 'complete'
}

async function pollExportStatus() {
  const maxAttempts = 120 // ~4 minutes at 2s interval
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise((r) => setTimeout(r, 2000))
    try {
      const status = await api.getExportStatus(projectId)
      exportResult.value = status
      if (isTerminalComplete(status.status) || status.status === 'failed') return
    } catch (e) {
      // Transient error — keep polling
    }
  }
  // Timeout — keep whatever state we have
}

async function refreshExportFiles() {
  try {
    const res = await fetchExportFiles(projectId)
    exportFiles.value = res.files || []
  } catch (e: any) {
    // Non-fatal: the output paths list still shows server-side paths.
    console.warn('[ExportView] 加载导出产物清单失败:', e?.message || e)
  }
}

/** Derive the artifact filename from a server-side output path. */
function basenameOf(path: string): string {
  if (!path) return ''
  const parts = path.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || ''
}

/** Find the file entry matching an output path (by basename). */
function fileForPath(path: string): ExportFileInfo | undefined {
  const name = basenameOf(path)
  return exportFiles.value.find((f) => f.filename === name)
}

function formatSize(bytes: number): string {
  // Number() coercion: guards against the backend's ISO-timestamp middleware
  // stringifying very large (>1GB) numeric values in edge cases.
  const n = Number(bytes)
  if (!Number.isFinite(n)) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

async function downloadPath(path: string) {
  const rel = fileForPath(path)?.rel_path || basenameOf(path)
  if (!rel) return
  downloadingPath.value = rel
  downloadError.value = null
  try {
    const blob = await downloadExportFile(projectId, rel)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = basenameOf(path) || rel
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch (e: any) {
    downloadError.value = e?.message || String(e)
  } finally {
    downloadingPath.value = null
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

function toggleFormat(fmtValue: string) {
  const idx = selectedFormats.value.indexOf(fmtValue)
  if (idx >= 0) {
    selectedFormats.value.splice(idx, 1)
  } else {
    selectedFormats.value.push(fmtValue)
  }
}
</script>

<template>
  <div class="page-container export-view">
    <header class="page-header">
      <button class="btn btn-ghost touch-target" @click="goBack">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        <span class="hidden-mobile">{{ t('common.back') }}</span>
      </button>
      <div class="header-text">
        <h1>{{ t('export.title') }}</h1>
        <p class="page-subtitle">{{ t('export.subtitle') }}</p>
      </div>
    </header>

    <!-- Project Info -->
    <section v-if="projectStore.currentProject" class="card card-hover section">
      <div class="project-info-row">
        <div class="project-info-text">
          <h2 class="card-title">{{ projectStore.currentProject.title }}</h2>
          <div class="project-meta">
            <span v-if="projectStore.currentProject.author" class="meta-item">
              <Icon icon="mdi:account" width="16" height="16" />
              {{ projectStore.currentProject.author }}
            </span>
            <span :class="getStatusClass(projectStore.currentProject.status || 'pending')">
              {{ t('common.' + (projectStore.currentProject.status || 'pending')) }}
            </span>
          </div>
        </div>
      </div>
    </section>

    <!-- Export Configuration -->
    <section class="card card-hover section">
      <h2 class="card-title">{{ t('export.configuration') }}</h2>

      <div class="form-group">
        <label class="form-label">{{ t('export.formats') }}</label>
        <div class="format-grid">
          <label
            v-for="fmt in availableFormats"
            :key="fmt.value"
            class="format-card"
            :class="{ 'format-card-selected': selectedFormats.includes(fmt.value) }"
            @click.stop="toggleFormat(fmt.value)"
          >
            <div class="format-card-row">
              <input
                type="checkbox"
                :value="fmt.value"
                v-model="selectedFormats"
                class="format-checkbox"
              />
              <span class="format-name">{{ fmt.label }}</span>
            </div>
            <span class="format-desc">{{ fmt.description }}</span>
          </label>
        </div>
      </div>

      <div class="form-group">
        <label class="form-label">{{ t('export.options') }}</label>
        <div class="option-checks">
          <label class="option-check">
            <input type="checkbox" v-model="exportOptions.normalize" class="format-checkbox" />
            <span>{{ t('export.normalize') }}</span>
          </label>
          <label class="option-check">
            <input type="checkbox" v-model="exportOptions.include_cover" class="format-checkbox" />
            <span>{{ t('export.includeCover') }}</span>
          </label>
        </div>
      </div>

      <div class="form-group">
        <label class="form-label">{{ t('export.maxCharsPerLine') }}</label>
        <input
          type="number"
          v-model.number="exportOptions.max_chars_per_line"
          min="20"
          max="80"
          class="form-control max-w-input"
        />
      </div>
    </section>

    <!-- Export Actions -->
    <section class="card card-hover section">
      <div class="export-actions">
        <button
          class="btn btn-primary btn-lg"
          @click="startExport"
          :disabled="selectedFormats.length === 0 || exporting"
        >
          <Icon v-if="exporting" icon="mdi:loading" width="18" height="18" class="spinner" />
          <Icon v-else icon="mdi:export" width="18" height="18" />
          {{ exporting ? t('export.exporting') : t('export.startExport') }}
        </button>
      </div>

      <!-- Progress / Result -->
      <div v-if="exporting || exportResult" class="export-status">
        <div v-if="exporting" class="loading-state">
          <div class="spinner"></div>
          <span>{{ t('export.exporting') }}...</span>
        </div>

        <div v-else-if="exportResult" class="export-result-card" :class="`result-${exportResult.status}`">
          <!-- Completed -->
          <div v-if="isTerminalComplete(exportResult.status)" class="result-body">
            <div class="result-header text-success">
              <Icon icon="mdi:check-circle" width="24" height="24" />
              <div>
                <h3 class="result-title">{{ t('export.success') }}</h3>
                <div v-if="exportResult.output_paths" class="output-paths">
                  <div
                    v-for="(path, format) in exportResult.output_paths"
                    :key="format"
                    class="path-item download-row"
                  >
                    <span class="badge badge-primary">{{ String(format).toUpperCase() }}</span>
                    <span class="path-text">{{ basenameOf(String(path)) || path }}</span>
                    <span v-if="fileForPath(String(path))" class="file-size text-muted">
                      {{ formatSize(fileForPath(String(path))!.size_bytes) }}
                    </span>
                    <button
                      class="btn btn-primary btn-sm touch-target"
                      :disabled="downloadingPath === (fileForPath(String(path))?.rel_path || basenameOf(String(path)))"
                      @click="downloadPath(String(path))"
                    >
                      <Icon
                        :icon="downloadingPath === (fileForPath(String(path))?.rel_path || basenameOf(String(path))) ? 'mdi:loading' : 'mdi:download'"
                        width="16"
                        height="16"
                        :class="{ spinner: downloadingPath === (fileForPath(String(path))?.rel_path || basenameOf(String(path))) }"
                      />
                      {{ downloadingPath === (fileForPath(String(path))?.rel_path || basenameOf(String(path)))
                        ? t('common.loading')
                        : t('common.download') }}
                    </button>
                  </div>
                </div>
                <p v-if="downloadError" class="result-detail text-danger">{{ downloadError }}</p>
              </div>
            </div>
          </div>

          <!-- Failed -->
          <div v-else-if="exportResult.status === 'failed'" class="result-body">
            <div class="result-header text-danger">
              <Icon icon="mdi:alert-circle" width="24" height="24" />
              <div>
                <h3 class="result-title">{{ t('export.failed') }}</h3>
                <p class="result-detail">{{ exportResult.error }}</p>
              </div>
            </div>
          </div>

          <!-- Other status -->
          <div v-else class="result-body">
            <div class="result-header text-warning">
              <Icon icon="mdi:clock-outline" width="24" height="24" />
              <div>
                <h3 class="result-title">{{ t('export.status') }}: {{ exportResult.status }}</h3>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>
