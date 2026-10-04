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
      <h2>{{ t('publish.jobStatus') }}</h2>
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
import './PublishView.css'
import { usePublish } from '../composables/usePublish'

const {
  t,
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
} = usePublish()
</script>


