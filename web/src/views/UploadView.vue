<template>
  <div class="upload-view">
    <div class="header">
      <h1>{{ t('upload.title') }}</h1>
      <p class="subtitle">{{ t('upload.subtitle') }}</p>
    </div>

    <!-- Step 1: Select/Create Project -->
    <section class="card" v-if="step === 1">
      <h2>{{ t('upload.selectProject') }}</h2>
      <div class="project-options">
        <div class="option-group">
          <label>
            <input type="radio" v-model="projectMode" value="existing" />
            {{ t('upload.existingProject') }}
          </label>
          <select v-if="projectMode === 'existing'" v-model="selectedProjectId" class="select">
            <option :value="null" disabled>{{ t('upload.chooseProject') }}</option>
            <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.title }}</option>
          </select>
        </div>
        <div class="option-group">
          <label>
            <input type="radio" v-model="projectMode" value="new" />
            {{ t('upload.newProject') }}
          </label>
          <div v-if="projectMode === 'new'" class="new-project-form">
            <input v-model="newProject.title" :placeholder="t('upload.projectTitle')" class="input" />
            <input v-model="newProject.author" :placeholder="t('upload.author')" class="input" />
            <select v-model="newProject.language" class="select">
              <option value="zh">中文</option>
              <option value="en">English</option>
            </select>
          </div>
        </div>
      </div>
      <button class="btn primary" @click="goToStep2" :disabled="!canProceedStep1">
        {{ t('upload.next') }}
      </button>
    </section>

    <!-- Step 2: Upload File -->
    <section class="card" v-if="step === 2">
      <h2>{{ t('upload.uploadFile') }}</h2>
      <div
        class="drop-zone"
        :class="{ active: isDragging }"
        @dragover.prevent="isDragging = true"
        @dragleave="isDragging = false"
        @drop.prevent="handleDrop"
        @click="triggerFileInput"
      >
        <input
          ref="fileInput"
          type="file"
          accept=".pdf,.epub,.docx,.txt"
          style="display: none"
          @change="handleFileSelect"
        />
        <div v-if="!selectedFile" class="drop-prompt">
          <span class="icon">📄</span>
          <p>{{ t('upload.dragDrop') }}</p>
          <p class="hint">{{ t('upload.supportedFormats') }}</p>
        </div>
        <div v-else class="file-info">
          <span class="icon">✅</span>
          <p>{{ selectedFile.name }}</p>
          <p class="hint">{{ formatFileSize(selectedFile.size) }}</p>
        </div>
      </div>
      <div class="actions">
        <button class="btn secondary" @click="step = 1">{{ t('upload.back') }}</button>
        <button class="btn primary" @click="startUpload" :disabled="!selectedFile || uploading">
          {{ uploading ? t('upload.uploading') : t('upload.startUpload') }}
        </button>
      </div>
    </section>

    <!-- Step 3: Upload Progress -->
    <section class="card" v-if="step === 3">
      <h2>{{ t('upload.progress') }}</h2>
      <div class="progress-container">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: uploadProgress + '%' }"></div>
        </div>
        <span class="progress-text">{{ uploadProgress }}%</span>
      </div>
      <div class="status-message">
        <p>{{ statusMessage }}</p>
      </div>
      <div v-if="extractionStatus" class="extraction-status">
        <p><strong>{{ t('upload.extractionStatus') }}:</strong> {{ extractionStatus }}</p>
      </div>
      <div v-if="uploadComplete" class="actions">
        <button class="btn primary" @click="goToProject">
          {{ t('upload.viewProject') }}
        </button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '../i18n'
import { fetchProjects, createProject } from '../api'
import type { Project } from '../types'
import api from '../api'

const router = useRouter()
const { t } = useI18n()

const step = ref(1)
const projects = ref<Project[]>([])
const projectMode = ref<'existing' | 'new'>('existing')
const selectedProjectId = ref<number | null>(null)
const newProject = ref({ title: '', author: '', language: 'zh' })
const selectedFile = ref<File | null>(null)
const isDragging = ref(false)
const uploading = ref(false)
const uploadProgress = ref(0)
const statusMessage = ref('')
const extractionStatus = ref('')
const uploadComplete = ref(false)
const createdProjectId = ref<number | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

const canProceedStep1 = computed(() => {
  if (projectMode.value === 'existing') return selectedProjectId.value !== null
  return newProject.value.title.trim().length > 0
})

onMounted(async () => {
  try {
    projects.value = await fetchProjects()
  } catch (e) {
    console.error('Failed to load projects:', e)
  }
})

function triggerFileInput() {
  fileInput.value?.click()
}

function handleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.[0]) {
    selectedFile.value = input.files[0]
  }
}

function handleDrop(e: DragEvent) {
  isDragging.value = false
  if (e.dataTransfer?.files?.[0]) {
    selectedFile.value = e.dataTransfer.files[0]
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

async function goToStep2() {
  if (projectMode.value === 'new') {
    try {
      const project = await createProject(newProject.value)
      createdProjectId.value = project.id
    } catch (e) {
      statusMessage.value = t('upload.createProjectFailed')
      return
    }
  } else {
    createdProjectId.value = selectedProjectId.value
  }
  step.value = 2
}

async function startUpload() {
  if (!selectedFile.value || !createdProjectId.value) return

  uploading.value = true
  step.value = 3
  statusMessage.value = t('upload.uploading')
  uploadProgress.value = 0

  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)

    const response = await api.post(
      `/api/projects/${createdProjectId.value}/upload`,
      formData,
      {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (progressEvent) => {
          if (progressEvent.total) {
            uploadProgress.value = Math.round(
              (progressEvent.loaded * 100) / progressEvent.total
            )
          }
        },
      }
    )

    uploadProgress.value = 100
    statusMessage.value = t('upload.uploadSuccess')
    extractionStatus.value = response.data.status || 'completed'
    uploadComplete.value = true
  } catch (e: any) {
    statusMessage.value = t('upload.uploadFailed') + ': ' + (e.message || 'Unknown error')
    extractionStatus.value = 'error'
  } finally {
    uploading.value = false
  }
}

function goToProject() {
  if (createdProjectId.value) {
    router.push({ name: 'project-detail', params: { id: createdProjectId.value } })
  }
}
</script>

<style scoped>
.upload-view {
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
.project-options {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  margin-bottom: 1.5rem;
}
.option-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.option-group label {
  font-weight: 500;
  cursor: pointer;
}
.new-project-form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
.input, .select {
  padding: 0.6rem 0.8rem;
  border: 1px solid var(--color-border, #ccc);
  border-radius: 8px;
  font-size: 0.95rem;
  background: var(--color-bg-primary, #fff);
}
.drop-zone {
  border: 2px dashed var(--color-border, #ccc);
  border-radius: 12px;
  padding: 2rem;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
}
.drop-zone:hover, .drop-zone.active {
  border-color: var(--color-primary, #4a90d9);
  background: var(--color-bg-hover, #f0f7ff);
}
.drop-prompt .icon {
  font-size: 2rem;
}
.file-info .icon {
  font-size: 1.5rem;
}
.hint {
  color: var(--color-text-secondary, #888);
  font-size: 0.85rem;
}
.actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 1rem;
  justify-content: flex-end;
}
.btn {
  padding: 0.6rem 1.2rem;
  border: none;
  border-radius: 8px;
  font-size: 0.95rem;
  cursor: pointer;
  transition: opacity 0.2s;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn.primary {
  background: var(--color-primary, #4a90d9);
  color: white;
}
.btn.secondary {
  background: var(--color-bg-secondary, #eee);
  color: var(--color-text-primary, #333);
}
.progress-container {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1rem;
}
.progress-bar {
  flex: 1;
  height: 8px;
  background: var(--color-border, #e0e0e0);
  border-radius: 4px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: var(--color-primary, #4a90d9);
  border-radius: 4px;
  transition: width 0.3s;
}
.progress-text {
  font-weight: 600;
  min-width: 3rem;
  text-align: right;
}
.status-message {
  margin: 1rem 0;
}
.extraction-status {
  padding: 0.8rem;
  background: var(--color-bg-primary, #fff);
  border-radius: 8px;
  border: 1px solid var(--color-border, #e0e0e0);
}
</style>
