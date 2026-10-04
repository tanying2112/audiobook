import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '../i18n'
import { fetchProjects, createProject } from '../api'
import type { Project } from '../types'
import api from '../api'

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
          // Let the browser set `multipart/form-data; boundary=...`. An explicit header
          // without a boundary makes the server reject the upload (无法上传文件).
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

  function goBack() {
    router.push('/')
  }

  function clearFile() {
    selectedFile.value = null
    fileInput.value = null
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
    triggerFileInput,
    handleFileSelect,
    handleDrop,
    formatFileSize,
    goToStep2,
    startUpload,
    goToProject,
    goBack,
    clearFile,
  }
}
