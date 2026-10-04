<script setup lang="ts">
import './UploadView.css'
import { useUpload } from '../composables/useUpload'

const {
  t,
  step,
  projects,
  projectMode,
  selectedProjectId,
  newProject,
  selectedFile,
  isDragging,
  uploading,
  uploadProgress,
  statusMessage,
  extractionStatus,
  uploadComplete,
  createdProjectId,
  fileInput,
  canProceedStep1,
  triggerFileInput,
  handleFileSelect,
  handleDrop,
  formatFileSize,
  goToStep2,
  startUpload,
  goToProject,
  goBack,
  clearFile,
} = useUpload()

void createdProjectId
void fileInput
</script>


<template>
  <div class="page-container upload-view">
    <header class="page-header section">
      <button class="btn btn-ghost touch-target" @click="goBack">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        <span class="hidden-mobile">{{ t('common.back') }}</span>
      </button>
      <div class="flex-1">
        <h1>{{ t('upload.title') }}</h1>
        <p class="page-subtitle">{{ t('upload.subtitle') }}</p>
      </div>
    </header>

    <!-- Step indicator -->
    <div class="step-indicator section flex gap-2" role="navigation" :aria-label="t('upload.upload_steps')">
      <div v-for="s in 3" :key="s" class="step-item flex-1 flex items-center gap-2" :class="{ active: step === s, completed: step > s }">
        <span class="step-number" :class="{ 'text-primary': step >= s, 'text-success': step > s }">{{ s }}</span>
        <span class="step-label text-sm" v-if="step >= s || step > s">
          {{ t(`upload.step_${s}`) }}
        </span>
      </div>
    </div>

    <!-- Step 1: Select/Create Project -->
    <section v-if="step === 1" class="card card-hover section">
      <h2 class="card-title">{{ t('upload.selectProject') }}</h2>

      <div class="grid gap-4">
        <div class="option-group p-4 rounded border" :class="projectMode === 'existing' ? 'border-primary bg-primary-soft' : 'border-border'" style="cursor: pointer;" @click="projectMode = 'existing'">
          <div class="flex items-center gap-3">
            <input type="radio" v-model="projectMode" value="existing" class="radio" style="accent-color: var(--color-primary);" />
            <label class="font-medium cursor-pointer flex-1">{{ t('upload.existingProject') }}</label>
          </div>
          <div v-if="projectMode === 'existing'" class="mt-3 ml-6">
            <select v-model="selectedProjectId" class="form-control" style="max-width: 300px;">
              <option :value="null" disabled>{{ t('upload.chooseProject') }}</option>
              <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.title }}</option>
            </select>
            <p v-if="projects.length === 0" class="text-muted text-sm mt-2">{{ t('upload.noProjects') }}</p>
          </div>
        </div>

        <div class="option-group p-4 rounded border" :class="projectMode === 'new' ? 'border-primary bg-primary-soft' : 'border-border'" style="cursor: pointer;" @click="projectMode = 'new'">
          <div class="flex items-center gap-3">
            <input type="radio" v-model="projectMode" value="new" class="radio" style="accent-color: var(--color-primary);" />
            <label class="font-medium cursor-pointer flex-1">{{ t('upload.newProject') }}</label>
          </div>
          <div v-if="projectMode === 'new'" class="mt-3 ml-6 grid gap-3" style="grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));">
            <div class="form-group">
              <label class="form-label">{{ t('upload.projectTitle') }}</label>
              <input v-model="newProject.title" type="text" class="form-control" :placeholder="t('upload.projectTitle')" />
            </div>
            <div class="form-group">
              <label class="form-label">{{ t('upload.author') }}</label>
              <input v-model="newProject.author" type="text" class="form-control" :placeholder="t('upload.author')" />
            </div>
            <div class="form-group">
              <label class="form-label">{{ t('upload.language') }}</label>
              <select v-model="newProject.language" class="form-control">
                <option value="zh">{{ t('upload.language_zh') }}</option>
                <option value="en">{{ t('upload.language_en') }}</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button class="btn btn-primary btn-lg" @click="goToStep2" :disabled="!canProceedStep1">
          {{ t('upload.next') }}
          <Icon icon="mdi:chevron-right" width="18" height="18" class="gap-2" />
        </button>
      </div>
    </section>

    <!-- Step 2: Upload File -->
    <section v-if="step === 2" class="card card-hover section">
      <h2 class="card-title">{{ t('upload.uploadFile') }}</h2>

      <div
        class="drop-zone"
        :class="{ active: isDragging, 'has-file': selectedFile }"
        @dragover.prevent="isDragging = true"
        @dragleave="isDragging = false"
        @drop.prevent="handleDrop"
        @click="triggerFileInput"
        style="border: 2px dashed var(--color-border); border-radius: var(--radius-lg); padding: 3rem 2rem; text-align: center; cursor: pointer; transition: all var(--transition); background: var(--color-bg);"
      >
        <input
          ref="fileInput"
          type="file"
          accept=".pdf,.epub,.docx,.txt"
          style="display: none"
          @change="handleFileSelect"
        />
        <div v-if="!selectedFile" class="drop-prompt">
          <Icon icon="mdi:file-upload-outline" width="48" height="48" class="text-primary mb-3" />
          <p class="text-lg font-medium">{{ t('upload.dragDrop') }}</p>
          <p class="text-muted text-sm mt-2">{{ t('upload.supportedFormats') }}</p>
          <p class="text-muted text-xs mt-1">{{ t('upload.clickToBrowse') }}</p>
        </div>
        <div v-else class="file-info flex items-center gap-4 p-4 text-left" style="background: var(--color-success-soft); border-radius: var(--radius); border: 1px solid var(--color-success);">
          <Icon icon="mdi:check-circle" width="24" height="24" class="text-success flex-shrink-0" />
          <div class="flex-1 min-w-0">
            <p class="font-medium truncate">{{ selectedFile.name }}</p>
            <p class="text-muted text-sm">{{ formatFileSize(selectedFile.size) }}</p>
          </div>
          <button class="btn btn-ghost btn-sm" @click.stop="clearFile">
            <Icon icon="mdi:close" width="18" height="18" />
          </button>
        </div>
      </div>

      <div class="flex justify-between gap-2 mt-4">
        <button class="btn btn-outline btn-lg" @click="step = 1">
          <Icon icon="mdi:chevron-left" width="18" height="18" class="gap-2" />
          {{ t('upload.back') }}
        </button>
        <button class="btn btn-primary btn-lg" @click="startUpload" :disabled="!selectedFile || uploading">
          <Icon v-if="uploading" icon="mdi:loading" width="18" height="18" class="spinner gap-2" style="border-color: rgba(255,255,255,.35); border-top-color: #fff" />
          <Icon v-else icon="mdi:upload" width="18" height="18" class="gap-2" />
          {{ uploading ? t('upload.uploading') : t('upload.startUpload') }}
        </button>
      </div>
    </section>

    <!-- Step 3: Upload Progress -->
    <section v-if="step === 3" class="card card-hover section">
      <h2 class="card-title">{{ t('upload.progress') }}</h2>

      <div class="progress-container mb-4">
        <div class="progress-bar" style="height: 8px; background: var(--color-border); border-radius: 4px; overflow: hidden;">
          <div class="progress-fill" :style="{ width: uploadProgress + '%' }" style="height: 100%; background: var(--color-primary); border-radius: 4px; transition: width 0.3s;"></div>
        </div>
        <span class="progress-text font-medium" style="min-width: 48px; text-align: right;">{{ uploadProgress }}%</span>
      </div>

      <div class="status-message p-3 rounded mb-4" :class="extractionStatus === 'error' ? 'alert alert-error' : 'alert alert-info'">
        <p>{{ statusMessage }}</p>
      </div>

      <div v-if="extractionStatus" class="extraction-status p-3 rounded mb-4" style="background: var(--color-bg-tertiary); border: 1px solid var(--color-border);">
        <p><strong>{{ t('upload.extractionStatus') }}:</strong> {{ extractionStatus }}</p>
      </div>

      <div v-if="uploadComplete" class="flex justify-end gap-2">
        <button class="btn btn-primary btn-lg" @click="goToProject">
          <Icon icon="mdi:book-open" width="18" height="18" class="gap-2" />
          {{ t('upload.viewProject') }}
        </button>
      </div>
    </section>
  </div>
</template>

