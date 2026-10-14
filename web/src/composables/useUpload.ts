import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '../i18n'
import { fetchProjects, createProject, fetchExtractionResult, startPipelineWithChapters } from '../api'
import type { Project } from '../types'
import api from '../api'
import type { ExtractionDetailResponse } from '../types/pipeline'

export function useUpload() {
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

  // Phase 3: Extraction result & chapter selection
  const extractionResult = ref<ExtractionDetailResponse | null>(null)
  const selectedChapterIds = ref<number[]>([])
  const extractionLoading = ref(false)
  const extractionJobId = ref<string | null>(null)
  const startPipelineLoading = ref(false)

  const canProceedStep1 = computed(() => {
    if (projectMode.value === 'existing') return selectedProjectId.value !== null
    return newProject.value.title.trim().length > 0
  })

  const canProceedStep3 = computed(() => {
    return extractionResult.value !== null && selectedChapterIds.value.length > 0
  })

  // SessionStorage persistence for chapter selection
  const STORAGE_KEY = 'upload_chapter_selection'

  const loadSelectionFromStorage = () => {
    try {
      const stored = sessionStorage.getItem(STORAGE_KEY)
      if (stored) {
        const parsed = JSON.parse(stored)
        if (parsed.projectId === createdProjectId.value) {
          selectedChapterIds.value = parsed.chapterIds || []
        }
      }
    } catch (e) {
      console.error('Failed to load selection from storage:', e)
    }
  }

  const saveSelectionToStorage = () => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
        projectId: createdProjectId.value,
        chapterIds: selectedChapterIds.value,
      }))
    } catch (e) {
      console.error('Failed to save selection to storage:', e)
    }
  }

  watch(selectedChapterIds, saveSelectionToStorage, { deep: true })

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
          headers: { 'Content-Type': undefined },
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
      extractionJobId.value = response.data.extraction_job_id || null
      uploadComplete.value = true

      // Phase 3: Fetch extraction result when job completes
      if (extractionJobId.value) {
        await fetchExtractionResultData()
      }
    } catch (e: any) {
      statusMessage.value = t('upload.uploadFailed') + ': ' + (e.message || 'Unknown error')
      extractionStatus.value = 'error'
    } finally {
      uploading.value = false
    }
  }

  async function fetchExtractionResultData() {
    if (!extractionJobId.value || !createdProjectId.value) return

    extractionLoading.value = true
    try {
      const result = await fetchExtractionResult(createdProjectId.value, extractionJobId.value)
      extractionResult.value = result

      // Auto-select all chapters by default
      selectedChapterIds.value = result.chapters.map(c => c.id)
      loadSelectionFromStorage() // Override with stored selection if exists
    } catch (e) {
      console.error('Failed to fetch extraction result:', e)
    } finally {
      extractionLoading.value = false
    }
  }

  async function startPipeline() {
    if (!createdProjectId.value || selectedChapterIds.value.length === 0) return

    startPipelineLoading.value = true
    try {
      await startPipelineWithChapters(createdProjectId.value, selectedChapterIds.value)
      router.push({ name: 'auto-run', params: { projectId: createdProjectId.value } })
    } catch (e: any) {
      console.error('Failed to start pipeline:', e)
      alert(t('upload.startPipelineFailed') + ': ' + (e.message || 'Unknown error'))
    } finally {
      startPipelineLoading.value = false
    }
  }

  function goToProject() {
    if (createdProjectId.value) {
      router.push({ name: 'project-detail', params: { id: createdProjectId.value } })
    }
  }

  function goBack() {
    router.push('/')
  }

  function clearFile() {
    selectedFile.value = null
    fileInput.value = null
  }

  function toggleChapterSelection(chapterId: number) {
    const idx = selectedChapterIds.value.indexOf(chapterId)
    if (idx === -1) {
      selectedChapterIds.value.push(chapterId)
    } else {
      selectedChapterIds.value.splice(idx, 1)
    }
  }

  function toggleSelectAll() {
    if (!extractionResult.value) return
    if (selectedChapterIds.value.length === extractionResult.value.chapters.length) {
      selectedChapterIds.value = []
    } else {
      selectedChapterIds.value = extractionResult.value.chapters.map(c => c.id)
    }
  }

  return {
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
    canProceedStep3,
    triggerFileInput,
    handleFileSelect,
    handleDrop,
    formatFileSize,
    goToStep2,
    startUpload,
    goToProject,
    goBack,
    clearFile,
    // Phase 3 exports
    extractionResult,
    selectedChapterIds,
    extractionLoading,
    extractionJobId,
    startPipelineLoading,
    fetchExtractionResultData,
    startPipeline,
    toggleChapterSelection,
    toggleSelectAll,
  }
}
