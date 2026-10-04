<script setup lang="ts">
import './DashboardView.css'
import { useDashboard } from '../composables/useDashboard'

const {
  t,
  selectedProjectId,
  chapterIndex,
  loading,
  error,
  metrics,
  history,
  projects,
  refresh,
  costChartRef,
  latencyChartRef,
  providerCostChartRef,
  rtfChartRef,
  historyChartRef,
} = useDashboard()

void costChartRef
void latencyChartRef
void providerCostChartRef
void rtfChartRef
void historyChartRef
</script>


<template>
  <div class="page-container dashboard-view">
    <header class="page-header">
      <div class="flex items-center gap-4">
        <h1>{{ t('dashboard.title') }}</h1>
        <span class="badge badge-muted">{{ t('dashboard.project') }} #{{ selectedProjectId }}</span>
        <span v-if="chapterIndex !== undefined" class="badge badge-info">{{ t('dashboard.chapter_filter') }} #{{ chapterIndex }}</span>
      </div>
    </header>

    <div v-if="loading" class="loading-state section">
      <div class="spinner"></div>
      <span>{{ t('dashboard.loading') }}</span>
    </div>

    <div v-else-if="error" class="alert alert-error section">{{ error }}</div>

    <template v-else>
      <!-- KPI Cards -->
      <section class="kpi-section section">
        <div class="card card-hover kpi-card">
          <div class="kpi-icon text-primary"><Icon icon="mdi:currency-usd" width="24" height="24" /></div>
          <div class="kpi-value font-bold" style="font-size: 24px;">${{ (metrics?.cost_accounting?.total_cost_usd || 0).toFixed(4) }}</div>
          <div class="kpi-label text-muted">{{ t('dashboard.total_cost') }}</div>
        </div>
        <div class="card card-hover kpi-card">
          <div class="kpi-icon text-success"><Icon icon="mdi:timer" width="24" height="24" /></div>
          <div class="kpi-value font-bold" style="font-size: 24px;">{{ (metrics?.latency_profiles?.real_time_factor || 0).toFixed(2) }}x</div>
          <div class="kpi-label text-muted">{{ t('dashboard.avg_rtf') }}</div>
        </div>
        <div class="card card-hover kpi-card">
          <div class="kpi-icon text-warning"><Icon icon="mdi:clock" width="24" height="24" /></div>
          <div class="kpi-value font-bold" style="font-size: 24px;">{{ Object.values(metrics?.latency_profiles?.stage_wall_times_ms || {}).reduce((sum, s) => sum + s.duration_ms, 0) }}ms</div>
          <div class="kpi-label text-muted">{{ t('dashboard.total_latency') }}</div>
        </div>
        <div class="card card-hover kpi-card">
          <div class="kpi-icon text-info"><Icon icon="mdi:chart-line" width="24" height="24" /></div>
          <div class="kpi-value font-bold" style="font-size: 24px;">{{ history.length }}</div>
          <div class="kpi-label text-muted">{{ t('dashboard.history_days') }}</div>
        </div>
      </section>

      <!-- Chart Row 1: Cost Distribution + Latency Leaderboard -->
      <div class="chart-row section">
        <div class="card card-hover" style="min-height: 320px;">
          <div ref="costChartRef" style="width: 100%; height: 100%; min-height: 300px;"></div>
        </div>
        <div class="card card-hover" style="min-height: 320px;">
          <div ref="latencyChartRef" style="width: 100%; height: 100%; min-height: 300px;"></div>
        </div>
      </div>

      <!-- Chart Row 2: Provider Cost Breakdown + RTF Gauge -->
      <div class="chart-row section">
        <div class="card card-hover" style="min-height: 320px;">
          <div ref="providerCostChartRef" style="width: 100%; height: 100%; min-height: 300px;"></div>
        </div>
        <div class="card card-hover" style="min-height: 320px;">
          <div ref="rtfChartRef" style="width: 100%; height: 100%; min-height: 300px;"></div>
        </div>
      </div>

      <!-- History Chart -->
      <section class="card card-hover section" style="min-height: 320px;">
        <div ref="historyChartRef" style="width: 100%; height: 100%; min-height: 300px;"></div>
      </section>

      <!-- Project Selector -->
      <section class="card card-hover section">
        <h2 class="card-title">{{ t('dashboard.select_project') }}</h2>
        <div class="flex items-center gap-4 flex-wrap">
          <div class="flex-1" style="min-width: 200px;">
            <select v-model="selectedProjectId" class="form-control" @change="refresh">
              <option v-for="p in projects" :key="p.project_id" :value="p.project_id">
                {{ p.title }} ({{ t('dashboard.total_cost') }}: ${{ p.total_cost_usd?.toFixed(4) || 0 }})
              </option>
            </select>
          </div>
          <div style="min-width: 200px;">
            <select v-model="chapterIndex" class="form-control" @change="refresh" style="min-width: 200px;">
              <option :value="null">{{ t('dashboard.latest_all_chapters') }}</option>
              <option v-for="i in 10" :key="i" :value="i">
                {{ t('dashboard.chapter', { num: i }) }}
              </option>
            </select>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
