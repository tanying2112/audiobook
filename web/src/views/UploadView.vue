<script setup lang="ts">
import './UploadView.css'
import { useUpload } from '../composables/useUpload'
import { Icon } from '@iconify/vue'
import ChapterTree from '../components/upload/ChapterTree.vue'
import UploadActionBar from '../components/upload/UploadActionBar.vue'

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
  canProceedStep1,
  canProceedStep3,
  triggerFileInput,
  handleFileSelect,
  handleDrop,
  formatFileSize,
  goToStep2,
  startUpload,
  goBack,
  clearFile,
  extractionResult,
  selectedChapterIds,
  extractionLoading,
  extractionJobId,
  startPipelineLoading,
  fetchExtractionResultData,
  startPipeline,
  toggleChapterSelection,
  toggleSelectAll,
} = useUpload()

const handleSaveDraft = () => {
  console.log('Save draft clicked')
  alert(t('upload.saveDraftNotImplemented'))
}
</script>

<template>
  <div class="page-container upload-view">
    <header class="page-header section">
      <button class="btn btn-ghost touch-target" @click="goBack">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        <span class="hidden-mobile">{{ t('common.back') }}</span>
      </button>
      <div class="header-text">
        <h1>{{ t('upload.title') }}</h1>
        <p class="page-subtitle">{{ t('upload.subtitle') }}</p>
      </div>
    </header>

    <!-- Step indicator -->
    <div class="step-indicator section" role="navigation" :aria-label="t('upload.upload_steps')">
      <div v-for="s in 3" :key="s" class="step-item" :class="{ active: step === s, completed: step > s }">
        <span class="step-number">{{ s }}</span>
        <span class="step-label" v-if="step >= s || step > s">
          {{ t(`upload.step_${s}`) }}
        </span>
      </div>
    </div>

    <!-- Step 1: Select/Create Project -->
    <section v-if="step === 1" class="card card-hover section">
      <h2 class="card-title">{{ t('upload.selectProject') }}</h2>

      <div class="option-list">
        <div
          class="option-group"
          :class="{ 'option-selected': projectMode === 'existing' }"
          @click="projectMode = 'existing'"
        >
          <div class="option-row">
            <input type="radio" v-model="projectMode" value="existing" class="radio" />
            <label class="option-label">{{ t('upload.existingProject') }}</label>
          </div>
          <div v-if="projectMode === 'existing'" class="option-content">
            <select v-model="selectedProjectId" class="form-control project-select">
              <option :value="null" disabled>{{ t('upload.chooseProject') }}</option>
              <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.title }}</option>
            </select>
            <p v-if="projects.length === 0" class="hint-sm">{{ t('upload.noProjects') }}</p>
          </div>
        </div>

        <div
          class="option-group"
          :class="{ 'option-selected': projectMode === 'new' }"
          @click="projectMode = 'new'"
        >
          <div class="option-row">
            <input type="radio" v-model="projectMode" value="new" class="radio" />
            <label class="option-label">{{ t('upload.newProject') }}</label>
          </div>
          <div v-if="projectMode === 'new'" class="project-fields">
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

      <div class="step-actions">
        <button class="btn btn-primary btn-lg" @click="goToStep2" :disabled="!canProceedStep1">
          {{ t('upload.next') }}
          <Icon icon="mdi:chevron-right" width="18" height="18" />
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
      >
        <input
          ref="fileInput"
          type="file"
          accept=".pdf,.epub,.docx,.txt"
          class="file-input-hidden"
          @change="handleFileSelect"
        />
        <div v-if="!selectedFile" class="drop-prompt">
          <Icon icon="mdi:file-upload-outline" width="48" height="48" class="text-primary" />
          <p class="drop-prompt-title">{{ t('upload.dragDrop') }}</p>
          <p class="drop-prompt-hint">{{ t('upload.supportedFormats') }}</p>
          <p class="drop-prompt-hint-xs">{{ t('upload.clickToBrowse') }}</p>
        </div>
        <div v-else class="file-info">
          <Icon icon="mdi:check-circle" width="24" height="24" class="text-success file-icon" />
          <div class="file-text">
            <p class="file-name">{{ selectedFile.name }}</p>
            <p class="file-size">{{ formatFileSize(selectedFile.size) }}</p>
          </div>
          <button class="btn btn-ghost btn-sm" @click.stop="clearFile" :aria-label="t('common.remove')">
            <Icon icon="mdi:close" width="18" height="18" />
          </button>
        </div>
      </div>

      <div class="step-actions-between">
        <button class="btn btn-outline btn-lg" @click="step = 1">
          <Icon icon="mdi:chevron-left" width="18" height="18" />
          {{ t('upload.back') }}
        </button>
        <button class="btn btn-primary btn-lg" @click="startUpload" :disabled="!selectedFile || uploading">
          <Icon v-if="uploading" icon="mdi:loading" width="18" height="18" class="spinner" />
          <Icon v-else icon="mdi:upload" width="18" height="18" />
          {{ uploading ? t('upload.uploading') : t('upload.startUpload') }}
        </button>
      </div>
    </section>

    <!-- Step 3: Extraction Result & Chapter Selection -->
    <section v-if="step === 3" class="card card-hover section">
      <h2 class="card-title">{{ t('upload.step_3') }}</h2>

      <div v-if="uploading" class="progress-container">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: uploadProgress + '%' }"></div>
        </div>
        <span class="progress-text">{{ uploadProgress }}%</span>
      </div>

      <div v-if="!uploadComplete" class="status-msg" :class="extractionStatus === 'error' ? 'alert alert-error' : 'alert alert-info'">
        <p>{{ statusMessage }}</p>
      </div>

      <div v-else class="extraction-content">
        <div class="extraction-chapter-tree">
          <ChapterTree
            :extraction-result="extractionResult"
            :selected-chapter-ids="selectedChapterIds"
            :extraction-loading="extractionLoading"
            :extraction-job-id="extractionJobId"
            @toggle="toggleChapterSelection"
            @refresh="fetchExtractionResultData"
            @select-all="toggleSelectAll"
          />
        </div>

        <UploadActionBar
          :extraction-result="extractionResult"
          :selected-chapter-ids="selectedChapterIds"
          :start-pipeline-loading="startPipelineLoading"
          :extraction-loading="extractionLoading"
          :can-start-pipeline="canProceedStep3"
          @start-pipeline="startPipeline"
          @back-to-edit="step = 2"
          @save-draft="handleSaveDraft"
        />
      </div>
    </section>
  </div>
</template>
