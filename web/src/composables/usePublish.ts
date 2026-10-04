import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from '../i18n'
import { fetchProject } from '../api'
import type { Project } from '../types'
import api from '../api'

export function usePublish() {
  const route = useRoute()
  const { t } = useI18n()

  const projectId = Number(route.params.projectId || route.params.id)
  const project = ref<Project | null>(null)

  const destinations = ref<string[]>(['podcast_rss'])
  const absConfig = ref({
    server_url: '',
    api_key: '',
    library_id: '',
  })
  const rssConfig = ref({
    feed_title: '',
    feed_description: '',
    feed_link: '',
    author: '',
    owner_email: '',
    feed_language: 'zh-CN',
  })

  const publishing = ref(false)
  const publishResult = ref<any>(null)
  const history = ref<any[]>([])

  // S3-1: durable publish job + live status polling
  const jobId = ref<string | null>(null)
  const jobStatus = ref<string>('')
  const jobProgress = ref<number | null>(null)
  const jobError = ref<string | null>(null)
  const jobResult = ref<any>(null)
  let pollTimer: ReturnType<typeof setInterval> | null = null

  const TERMINAL_STATES = new Set(['SUCCESS', 'FAILED'])

  function stopPoll() {
    if (pollTimer !== null) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  async function pollStatus() {
    if (!jobId.value) return
    try {
      const { data } = await api.get(`/api/publish/${jobId.value}/status`)
      jobStatus.value = data.status
      if (typeof data.progress === 'number') jobProgress.value = data.progress
      if (data.error_log) jobError.value = data.error_log
      if (data.result) jobResult.value = data.result
      if (TERMINAL_STATES.has(String(data.status).toUpperCase())) {
        stopPoll()
      }
    } catch (e: any) {
      // 404 = job record not persisted yet (best-effort); keep polling.
      if (e?.response?.status !== 404) {
        stopPoll()
        jobError.value = e?.response?.data?.detail || e?.message || 'Failed to poll status'
      }
    }
  }

  function startPoll() {
    stopPoll()
    void pollStatus()
    pollTimer = setInterval(pollStatus, 1500)
  }

  onMounted(async () => {
    try {
      project.value = await fetchProject(projectId)
      // Prefill RSS from project metadata
      if (project.value) {
        rssConfig.value.feed_title = t('publish.defaultFeedTitle', { title: project.value.title })
        if (project.value.genre) rssConfig.value.author = project.value.genre
      }
      await loadHistory()
    } catch (e) {
      console.error('Failed to load project:', e)
    }
  })

  onUnmounted(stopPoll)

  async function loadHistory() {
    try {
      const { data } = await api.get(`/api/projects/${projectId}/publish/history`)
      history.value = data
    } catch (e) {
      // History endpoint may be empty on first run — not fatal.
      console.warn('No publish history:', e)
    }
  }

  async function startPublish() {
    publishing.value = true
    publishResult.value = null
    jobId.value = null
    jobStatus.value = ''
    jobProgress.value = null
    jobError.value = null
    jobResult.value = null
    stopPoll()

    const payload: Record<string, unknown> = {
      project_id: projectId,
      destinations: destinations.value,
    }
    if (destinations.value.includes('audiobookshelf')) {
      payload.audiobookshelf_config = { ...absConfig.value }
    }
    if (destinations.value.includes('podcast_rss')) {
      payload.podcast_config = {
        ...rssConfig.value,
        categories: [],
        explicit: false,
        chapter_as_episode: true,
      }
    }

    try {
      // S3-1: start a durable publish job, then poll its live status.
      const { data } = await api.post(`/api/publish/start`, payload)
      jobId.value = data.job_id
      jobStatus.value = data.status
      publishResult.value = data
      startPoll()
      await loadHistory()
    } catch (e: any) {
      jobError.value = e?.response?.data?.detail || e?.message || 'Publish failed'
      publishResult.value = { status: 'failed', error: jobError.value }
    } finally {
      publishing.value = false
    }
  }

  return {
    t,
    projectId,
    project,
    destinations,
    absConfig,
    rssConfig,
    publishing,
    publishResult,
    history,
    jobId,
    jobStatus,
    jobProgress,
    jobError,
    jobResult,
    startPublish,
  }
}
