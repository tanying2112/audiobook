<template>
  <div class="monitoring-dashboard">
    <header class="dashboard-header">
      <h1>{{ t('monitoring.title') }}</h1>
      <div class="header-controls">
        <select v-model="selectedProjectId" @change="fetchMetrics" class="project-select">
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.title }} (ID: {{ p.id }})</option>
        </select>
        <button @click="refreshData" :disabled="loading" class="btn btn-primary">
          {{ loading ? t('monitoring.refreshing') : t('monitoring.refresh') }}
        </button>
      </div>
    </header>

    <div v-if="loading" class="loading-overlay">
      <div class="spinner"></div>
      <p>{{ t('monitoring.loading') }}</p>
    </div>

    <div v-else-if="!metrics" class="empty-state">
      <p>{{ t('monitoring.empty') }}</p>
    </div>

    <div v-else class="dashboard-grid">
      <!-- Cost Analysis Pie Chart -->
      <section class="chart-card">
        <h2>{{ t('monitoring.cost_pie') }}</h2>
        <div class="chart-container">
          <canvas ref="costChart"></canvas>
        </div>
        <div class="chart-legend" v-if="costChartData.labels.length > 0">
          <div v-for="(label, i) in costChartData.labels" :key="label" class="legend-item">
            <span class="legend-color" :style="{ backgroundColor: costChartData.datasets[0].backgroundColor[i] }"></span>
            <span class="legend-label">{{ label }}</span>
            <span class="legend-value">${{ costChartData.datasets[0].data[i].toFixed(4) }}</span>
            <span class="legend-pct">({{ ((costChartData.datasets[0].data[i] / costTotal) * 100).toFixed(1) }}%)</span>
          </div>
          <div class="legend-total">
            <strong>{{ t('monitoring.cost_total', { total: costTotal.toFixed(4) }) }}</strong>
          </div>
        </div>
        <div v-if="costChartData.labels.length === 0" class="no-data">{{ t('monitoring.no_cost_data') }}</div>
      </section>

      <!-- Stage Latency Leaderboard -->
      <section class="chart-card">
        <h2>{{ t('monitoring.latency_leaderboard') }}</h2>
        <div class="chart-container">
          <canvas ref="latencyChart"></canvas>
        </div>
        <div class="leaderboard-table" v-if="latencyChartData.labels.length > 0">
          <table>
            <thead>
              <tr>
                <th>{{ t('monitoring.rank') }}</th>
                <th>{{ t('monitoring.stage') }}</th>
                <th>{{ t('monitoring.latency_ms') }}</th>
                <th>{{ t('monitoring.status') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(stage, i) in sortedStages" :key="stage.name" :class="stage.success ? 'success' : 'failed'">
                <td class="rank">{{ i + 1 }}</td>
                <td class="stage-name">{{ stage.name }}</td>
                <td class="latency">{{ stage.duration.toFixed(0) }} ms</td>
                <td class="status">{{ stage.success ? t('monitoring.success') : t('monitoring.failed') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="latencyChartData.labels.length === 0" class="no-data">{{ t('monitoring.no_latency_data') }}</div>
      </section>

      <!-- Resilience Metrics -->
      <section class="metrics-card">
        <h2>{{ t('monitoring.resilience') }}</h2>
        <div class="metrics-grid">
          <div class="metric-box">
            <span class="metric-label">{{ t('monitoring.llm_total_calls') }}</span>
            <span class="metric-value">{{ resilience.llm.total_calls }}</span>
          </div>
          <div class="metric-box">
            <span class="metric-label">{{ t('monitoring.llm_retries') }}</span>
            <span class="metric-value warn">{{ resilience.llm.total_retries }}</span>
          </div>
          <div class="metric-box">
            <span class="metric-label">{{ t('monitoring.llm_fallbacks') }}</span>
            <span class="metric-value danger">{{ resilience.llm.total_fallbacks }}</span>
          </div>
          <div class="metric-box">
            <span class="metric-label">{{ t('monitoring.tts_segments') }}</span>
            <span class="metric-value">{{ resilience.tts.total_segments }}</span>
          </div>
          <div class="metric-box">
            <span class="metric-label">{{ t('monitoring.tts_success_rate') }}</span>
            <span class="metric-value success">{{ (resilience.tts.total_segments > 0 ? (resilience.tts.successful_segments / resilience.tts.total_segments * 100).toFixed(1) : 0) }}%</span>
          </div>
          <div class="metric-box">
            <span class="metric-label">{{ t('monitoring.synthesis_rate_ratio') }}</span>
            <span class="metric-value">{{ latency.synthesis_rate_ratio.toFixed(2) }}</span>
          </div>
          <div class="metric-box">
            <span class="metric-label">{{ t('monitoring.real_time_factor') }}</span>
            <span class="metric-value">{{ latency.real_time_factor.toFixed(2) }}</span>
          </div>
          <div class="metric-box">
            <span class="metric-label">{{ t('monitoring.total_audio_duration') }}</span>
            <span class="metric-value">{{ t('monitoring.seconds', { n: (latency.total_audio_duration_ms / 1000).toFixed(1) }) }}</span>
          </div>
        </div>
      </section>

      <!-- Provider Cost Breakdown -->
      <section class="metrics-card">
        <h2>{{ t('monitoring.provider_cost') }}</h2>
        <div class="provider-table" v-if="providerBreakdown.length > 0">
          <table>
            <thead>
              <tr>
                <th>{{ t('monitoring.provider') }}</th>
                <th>{{ t('monitoring.model') }}</th>
                <th>{{ t('monitoring.prompt_tokens') }}</th>
                <th>{{ t('monitoring.completion_tokens') }}</th>
                <th>{{ t('monitoring.cost_usd') }}</th>
                <th>{{ t('monitoring.call_count') }}</th>
                <th>{{ t('monitoring.avg_latency') }}</th>
                <th>{{ t('monitoring.success_rate') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in providerBreakdown" :key="p.key">
                <td>{{ p.provider }}</td>
                <td>{{ p.model }}</td>
                <td>{{ p.prompt_tokens.toLocaleString() }}</td>
                <td>{{ p.completion_tokens.toLocaleString() }}</td>
                <td class="cost">${{ p.cost_usd.toFixed(6) }}</td>
                <td>{{ p.call_count }}</td>
                <td>{{ p.avg_latency_ms.toFixed(0) }} ms</td>
                <td :class="p.success_rate >= 0.95 ? 'success' : (p.success_rate >= 0.8 ? 'warn' : 'danger')">
                  {{ (p.success_rate * 100).toFixed(1) }}%
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="no-data">{{ t('monitoring.no_provider_data') }}</div>
      </section>
    </div>

    <!-- Pipeline Metadata -->
    <section class="metadata-section" v-if="metrics?.metadata">
      <h2>{{ t('monitoring.pipeline_metadata') }}</h2>
      <div class="metadata-grid">
        <div><strong>{{ t('monitoring.project_id') }}</strong> {{ metrics.metadata.project_id }}</div>
        <div><strong>{{ t('monitoring.pipeline_id') }}</strong> {{ metrics.metadata.pipeline_id }}</div>
        <div><strong>{{ t('monitoring.started_at') }}</strong> {{ formatDate(metrics.metadata.started_at) }}</div>
        <div><strong>{{ t('monitoring.ended_at') }}</strong> {{ metrics.metadata.ended_at ? formatDate(metrics.metadata.ended_at) : t('monitoring.in_progress') }}</div>
        <div><strong>{{ t('monitoring.duration') }}</strong> {{ metrics.metadata.duration_ms.toFixed(0) }} ms</div>
        <div><strong>{{ t('monitoring.status') }}</strong> <span :class="metrics.metadata.success ? 'success' : 'danger'">{{ metrics.metadata.success ? t('monitoring.success') : t('monitoring.failed') }}</span></div>
        <div v-if="metrics.metadata.error"><strong>{{ t('monitoring.error') }}</strong> {{ metrics.metadata.error }}</div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { useMonitoringDashboard } from '../composables/useMonitoringDashboard'
import './MonitoringDashboard.css'

const {
  t,
  selectedProjectId,
  projects,
  metrics,
  loading,
  fetchMetrics,
  refreshData,
  costChartData,
  costTotal,
  latencyChartData,
  sortedStages,
  resilience,
  latency,
  providerBreakdown,
  formatDate,
} = useMonitoringDashboard()
</script>
