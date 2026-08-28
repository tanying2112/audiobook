<template>
  <div class="publish-view">
    <div class="header">
      <h1>{{ t('publish.title') }}</h1>
      <p class="subtitle">{{ t('publish.subtitle') }}</p>
    </div>

    <!-- Project Info -->
    <section class="card" v-if="project">
      <h2>{{ project.title }}</h2>
      <p class="meta">
        <span v-if="project.author">{{ project.author }}</span>
        <span class="status-badge" :class="project.status">{{ project.status }}</span>
        <span v-if="project.status !== 'completed'" class="hint">{{ t('publish.notCompletedHint') }}</span>
      </p>
    </section>

    <!-- Destination Selection -->
    <section class="card">
      <h2>{{ t('publish.destinations') }}</h2>

      <label class="checkbox-label">
        <input type="checkbox" :value="'audiobookshelf'" v-model="destinations" />
        <span class="dest-name">Audiobookshelf</span>
        <span class="dest-desc">{{ t('publish.audiobookshelfDesc') }}</span>
      </label>
      <label class="checkbox-label">
        <input type="checkbox" :value="'podcast_rss'" v-model="destinations" />
        <span class="dest-name">{{ t('publish.rss') }}</span>
        <span class="dest-desc">{{ t('publish.rssDesc') }}</span>
      </label>
    </section>

    <!-- Audiobookshelf Config -->
    <section class="card" v-if="destinations.includes('audiobookshelf')">
      <h2>Audiobookshelf</h2>
      <div class="form-group">
        <label>{{ t('publish.serverUrl') }}</label>
        <input
          v-model="absConfig.server_url"
          type="text"
          class="input"
          :placeholder="'https://abs.example.com'"
        />
      </div>
      <div class="form-group">
        <label>{{ t('publish.apiKey') }}</label>
        <input
          v-model="absConfig.api_key"
          type="password"
          class="input"
          :placeholder="'••••••••'"
        />
      </div>
      <div class="form-group">
        <label>{{ t('publish.libraryId') }}</label>
        <input v-model="absConfig.library_id" type="text" class="input" />
      </div>
    </section>

    <!-- Podcast RSS Config -->
    <section class="card" v-if="destinations.includes('podcast_rss')">
      <h2>Podcast RSS</h2>
      <div class="form-group">
        <label>{{ t('publish.feedTitle') }}</label>
        <input v-model="rssConfig.feed_title" type="text" class="input" />
      </div>
      <div class="form-group">
        <label>{{ t('publish.feedDescription') }}</label>
        <textarea v-model="rssConfig.feed_description" class="input textarea" rows="2"></textarea>
      </div>
      <div class="form-group">
        <label>{{ t('publish.feedLink') }}</label>
        <input v-model="rssConfig.feed_link" type="text" class="input" />
      </div>
      <div class="form-group">
        <label>{{ t('publish.author') }}</label>
        <input v-model="rssConfig.author" type="text" class="input" />
      </div>
      <div class="form-group">
        <label>{{ t('publish.ownerEmail') }}</label>
        <input v-model="rssConfig.owner_email" type="email" class="input" />
      </div>
      <div class="form-group">
        <label>{{ t('publish.feedLanguage') }}</label>
        <input v-model="rssConfig.feed_language" type="text" class="input short" />
      </div>
    </section>

    <!-- Actions -->
    <section class="card">
      <div class="actions">
        <button
          class="btn primary"
          @click="startPublish"
          :disabled="destinations.length === 0 || publishing || project?.status !== 'completed'"
        >
          {{ publishing ? t('publish.publishing') : t('publish.startPublish') }}
        </button>
      </div>

      <div v-if="publishResult" class="result" :class="publishResult.status">
        <h3 v-if="publishResult.status === 'completed'">{{ t('publish.success') }}</h3>
        <h3 v-else-if="publishResult.status === 'failed'">{{ t('publish.failed') }}</h3>
        <h3 v-else>{{ t('publish.status') }}: {{ publishResult.status }}</h3>
        <p v-if="publishResult.error">{{ publishResult.error }}</p>
        <pre v-if="publishResult.results && Object.keys(publishResult.results).length" class="results-json">{{
          JSON.stringify(publishResult.results, null, 2)
        }}</pre>
      </div>
    </section>

    <!-- Live Job Status (S3-1: durable job + polling) -->
    <section class="card" v-if="jobId">
      <h2>发布状态</h2>
      <div class="job-status">
        <span class="status-badge" :class="String(jobStatus).toLowerCase()">{{ jobStatus || '—' }}</span>
        <span v-if="jobProgress != null" class="progress-text">{{ Math.round(jobProgress * 100) }}%</span>
      </div>
      <div class="progress-bar" v-if="jobProgress != null && jobStatus !== 'FAILED'">
        <div class="progress-fill" :style="{ width: (jobProgress * 100) + '%' }"></div>
      </div>
      <p v-if="jobError" class="error">{{ jobError }}</p>
      <pre v-if="jobResult" class="results-json">{{ JSON.stringify(jobResult, null, 2) }}</pre>
    </section>

    <!-- History -->
    <section class="card" v-if="history.length">
      <h2>{{ t('publish.history') }}</h2>
      <table class="history-table">
        <thead>
          <tr>
            <th>{{ t('publish.historyJob') }}</th>
            <th>{{ t('publish.historyStatus') }}</th>
            <th>{{ t('publish.historyDest') }}</th>
            <th>{{ t('publish.historyTime') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="job in history" :key="job.job_id">
            <td class="mono">{{ job.job_id.slice(0, 8) }}</td>
            <td><span class="status-badge" :class="job.status">{{ job.status }}</span></td>
            <td>{{ (job.destinations || []).join(', ') }}</td>
            <td>{{ job.created_at }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from '../i18n'
import { fetchProject } from '../api'
import type { Project } from '../types'
import api from '../api'

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
      rssConfig.value.feed_title = `${project.value.title} - 有声书`
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
</script>

<style scoped>
.publish-view {
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
.hint {
  color: #b8860b;
  font-size: 0.85rem;
}
.status-badge {
  padding: 0.2rem 0.6rem;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: 500;
  background: #eee;
}
.status-badge.completed {
  background: #e6f7e6;
  color: #2e7d32;
}
.status-badge.failed {
  background: #fff2f0;
  color: #d32f2f;
}
.status-badge.publishing,
.status-badge.pending {
  background: #fff8e1;
  color: #b8860b;
}
.form-group {
  margin-bottom: 1rem;
}
.form-group > label:first-child {
  display: block;
  font-weight: 600;
  margin-bottom: 0.5rem;
}
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  padding: 0.4rem 0;
}
.dest-name {
  font-weight: 500;
}
.dest-desc {
  color: var(--color-text-secondary, #888);
  font-size: 0.85rem;
}
.input {
  width: 100%;
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--color-border, #ccc);
  border-radius: 6px;
  font-size: 0.95rem;
  box-sizing: border-box;
}
.input.short {
  width: 140px;
}
.textarea {
  resize: vertical;
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
.result {
  padding: 1rem;
  border-radius: 8px;
  margin-top: 0.5rem;
}
.result.completed {
  background: #e6f7e6;
  border: 1px solid #b7eb8f;
}
.result.failed {
  background: #fff2f0;
  border: 1px solid #ffccc7;
}
.results-json {
  background: #f5f5f5;
  border-radius: 6px;
  padding: 0.8rem;
  font-size: 0.8rem;
  max-height: 200px;
  overflow: auto;
}
.history-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}
.history-table th,
.history-table td {
  text-align: left;
  padding: 0.5rem;
  border-bottom: 1px solid var(--color-border, #eee);
}
.mono {
  font-family: monospace;
}
.job-status {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 0.75rem;
}
.progress-text {
  font-weight: 600;
  color: var(--color-text-secondary, #888);
}
.progress-bar {
  width: 100%;
  height: 10px;
  background: #eee;
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 0.75rem;
}
.progress-fill {
  height: 100%;
  background: var(--color-primary, #4a90d9);
  transition: width 0.4s ease;
}
.error {
  color: #d32f2f;
  margin-top: 0.5rem;
}
</style>