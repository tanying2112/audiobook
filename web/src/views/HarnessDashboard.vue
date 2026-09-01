<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '../i18n'
import {
  fetchHarnessDashboard,
  triggerIteration,
  type HarnessDashboardResponse,

} from '../api'

const router = useRouter()
const { t } = useI18n()

// ── State ─────────────────────────────────────────────────────────────────
const dashboard = ref<HarnessDashboardResponse | null>(null)
const loading = ref(true)
const error = ref('')
const triggering = ref(false)
const triggerMessage = ref('')
const triggerError = ref(false)
const lastRefresh = ref<string>('')
let refreshTimer: ReturnType<typeof setInterval> | null = null

// ── Load Data ─────────────────────────────────────────────────────────────
async function loadDashboard() {
  try {
    loading.value = true
    error.value = ''
    dashboard.value = await fetchHarnessDashboard()
    lastRefresh.value = new Date().toLocaleTimeString()
  } catch (e: any) {
    error.value = t('harness_dashboard.load_failed', { error: e.response?.data?.detail || e.message })
  } finally {
    loading.value = false
  }
}

async function handleTrigger() {
  try {
    triggering.value = true
    triggerMessage.value = ''
    triggerError.value = false
    const result = await triggerIteration()
    triggerMessage.value = result.message
    await loadDashboard()
  } catch (e: any) {
    triggerError.value = true
    triggerMessage.value = t('harness_dashboard.trigger_failed', { error: e.response?.data?.detail || e.message })
  } finally {
    triggering.value = false
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────
function statusColor(status: string): string {
  switch (status) {
    case 'running': return '#22c55e'
    case 'paused': return 'var(--color-warning)'
    case 'completed': return 'var(--color-primary)'
    case 'failed': return '#ef4444'
    case 'rolled_back': return '#9333ea'
    default: return '#94a3b8'
  }
}

function gateBarWidth(rate: number, threshold: number): string {
  const pct = Math.min((rate / threshold) * 100, 100)
  return `${pct}%`
}

function gateBarColor(rate: number, threshold: number): string {
  return rate >= threshold ? '#22c55e' : '#ef4444'
}

function verdictColor(verdict: string): string {
  switch (verdict) {
    case 'accept': return '#22c55e'
    case 'reject': return '#ef4444'
    case 'needs_revision': return 'var(--color-warning)'
    default: return '#94a3b8'
  }
}

function patternBarWidth(count: number, maxCount: number): string {
  if (maxCount === 0) return '0%'
  return `${(count / maxCount) * 100}%`
}

// ── Lifecycle ─────────────────────────────────────────────────────────────
onMounted(async () => {
  await loadDashboard()
  // Auto-refresh every 30s
  refreshTimer = setInterval(loadDashboard, 30000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
  <div class="page-container harness-dashboard">
    <!-- Header -->
    <div class="page-header">
      <button class="btn btn-ghost touch-target" @click="router.push('/')">
        ← <span class="hidden-mobile">{{ t('common.back') }}</span>
      </button>
      <h1>{{ t('harness_dashboard.title') }}</h1>
      <div class="header-actions flex items-center gap-2">
        <button
          class="btn btn-primary touch-target"
          @click="handleTrigger"
          :disabled="triggering"
        >
          {{ triggering ? t('harness_dashboard.triggering') : t('harness_dashboard.trigger_iteration') }}
        </button>
        <button class="btn btn-outline touch-target" @click="loadDashboard" :disabled="loading">
          <span class="hidden-mobile">{{ t('common.refresh') }}</span>
          <span class="visible-mobile">↻</span>
        </button>
      </div>
    </div>

    <!-- Status bar -->
    <div class="status-bar" v-if="lastRefresh">
      <span>{{ t('harness_dashboard.last_refresh', { time: lastRefresh }) }}</span>
      <span v-if="triggerMessage" :class="['trigger-msg', triggerError ? 'error' : 'success']">
        {{ triggerMessage }}
      </span>
    </div>

    <!-- Error -->
    <div v-if="error" class="error-banner">{{ error }}</div>

    <!-- Loading -->
    <div v-if="loading && !dashboard" class="loading">{{ t('common.loading') }}</div>

    <!-- Dashboard Content -->
    <template v-if="dashboard">
      <!-- Row 1: Iteration Status + Feedback Funnel -->
      <div class="grid grid-2">
        <!-- Iteration Status -->
        <section class="card">
          <h2>{{ t('harness_dashboard.self_iteration_status') }}</h2>
          <div class="stat-row">
            <div class="stat-item">
              <span class="stat-label">{{ t('harness_dashboard.running_status') }}</span>
              <span :class="['stat-badge', dashboard.iteration_status.running ? 'active' : 'inactive']">
                {{ dashboard.iteration_status.running ? t('harness_dashboard.running') : t('harness_dashboard.stopped') }}
              </span>
            </div>
            <div class="stat-item">
              <span class="stat-label">{{ t('harness_dashboard.iteration_count') }}</span>
              <span class="stat-value">{{ dashboard.iteration_status.iteration_count }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">{{ t('harness_dashboard.unprocessed_feedback') }}</span>
              <span class="stat-value">{{ dashboard.iteration_status.unprocessed_feedback_count }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">{{ t('harness_dashboard.trigger_threshold') }}</span>
              <span class="stat-value">{{ dashboard.iteration_status.min_feedback_threshold }}</span>
            </div>
          </div>
          <div v-if="dashboard.iteration_status.last_iteration_time" class="stat-row">
            <div class="stat-item">
              <span class="stat-label">{{ t('harness_dashboard.last_iteration') }}</span>
              <span class="stat-value small">{{ dashboard.iteration_status.last_iteration_time }}</span>
            </div>
          </div>
        </section>

        <!-- Feedback Funnel -->
        <section class="card">
          <h2>{{ t('harness_dashboard.feedback_funnel') }}</h2>
          <div class="funnel">
            <div class="funnel-step" v-for="(step, idx) in [
              { label: 'harness_dashboard.total_feedback', value: dashboard.feedback_funnel.total_feedback },
              { label: 'harness_dashboard.analyzed', value: dashboard.feedback_funnel.analyzed_count },
              { label: 'harness_dashboard.triggered_upgrade', value: dashboard.feedback_funnel.triggered_upgrade_count },
              { label: 'harness_dashboard.promotion_passed', value: dashboard.feedback_funnel.promotion_passed_count },
              { label: 'harness_dashboard.published', value: dashboard.feedback_funnel.published_count },
            ]" :key="idx">
              <span class="funnel-label">{{ t(step.label) }}</span>
              <div class="funnel-bar-wrapper">
                <div
                  class="funnel-bar"
                  :style="{
                    width: dashboard.feedback_funnel.total_feedback > 0
                      ? (step.value / dashboard.feedback_funnel.total_feedback * 100) + '%'
                      : '0%'
                  }"
                />
              </div>
              <span class="funnel-value">{{ step.value }}</span>
            </div>
          </div>
        </section>
      </div>

      <!-- Row 2: Pattern Heatmap + Promotion Gate -->
      <div class="grid grid-2">
        <!-- Pattern Heatmap -->
        <section class="card">
          <h2>{{ t('harness_dashboard.pattern_heatmap') }}</h2>
          <div v-if="dashboard.pattern_heatmap.top_patterns.length > 0" class="top-patterns">
            <span class="tag" v-for="p in dashboard.pattern_heatmap.top_patterns" :key="p">{{ p }}</span>
          </div>
          <div v-if="dashboard.pattern_heatmap.patterns.length > 0" class="pattern-bars">
            <template v-for="pat in dashboard.pattern_heatmap.patterns.slice(0, 12)" :key="pat.tag">
              <div class="pattern-row">
                <span class="pattern-tag">{{ pat.tag }}</span>
                <div class="pattern-bar-wrapper">
                  <div
                    class="pattern-bar"
                    :style="{ width: patternBarWidth(pat.count, dashboard.pattern_heatmap.patterns[0]?.count || 1) }"
                  />
                </div>
                <span class="pattern-count">{{ pat.count }}</span>
                <span class="pattern-stage">{{ pat.stage }}</span>
              </div>
            </template>
          </div>
          <div v-else class="empty-state">{{ t('common.no_data') }}</div>
        </section>

        <!-- Promotion Gate -->
        <section class="card">
          <h2>{{ t('harness_dashboard.promotion_gate') }}</h2>
          <div :class="['gate-status', dashboard.promotion_gate.overall_pass ? 'pass' : 'fail']">
            {{ dashboard.promotion_gate.overall_pass ? t('harness_dashboard.all_passed') : t('harness_dashboard.not_all_passed') }}
          </div>
          <div class="gate-list">
            <div class="gate-item" v-for="(item, idx) in [
              { label: 'harness_dashboard.format_compliance_rate', value: dashboard.promotion_gate.format_compliance_rate, threshold: dashboard.promotion_gate.thresholds.format_compliance || 0.99 },
              { label: 'harness_dashboard.golden_pass_rate', value: dashboard.promotion_gate.golden_pass_rate, threshold: dashboard.promotion_gate.thresholds.golden_pass || 0.95 },
              { label: 'harness_dashboard.quality_score_ratio', value: dashboard.promotion_gate.quality_score_ratio, threshold: dashboard.promotion_gate.thresholds.quality_ratio || 1.02 },
              { label: 'harness_dashboard.human_preference_rate', value: dashboard.promotion_gate.human_preference_rate, threshold: dashboard.promotion_gate.thresholds.human_preference || 0.80 },
            ]" :key="idx">
              <span class="gate-label">{{ t(item.label) }}</span>
              <div class="gate-bar-wrapper">
                <div
                  class="gate-bar"
                  :style="{
                    width: gateBarWidth(item.value, item.threshold),
                    backgroundColor: gateBarColor(item.value, item.threshold)
                  }"
                />
              </div>
              <span class="gate-value">
                {{ (item.value * 100).toFixed(1) }}%
                <span class="gate-threshold">/ {{ (item.threshold * 100).toFixed(0) }}%</span>
              </span>
            </div>
          </div>
        </section>
      </div>

      <!-- Row 3: Canary + A/B Tests + Critics -->
      <div class="grid grid-3">
        <!-- Canary Releases -->
        <section class="card">
          <h2>{{ t('harness_dashboard.canary_releases') }}</h2>
          <div v-if="dashboard.canary_dashboard.active_canaries.length > 0">
            <div
              v-for="canary in dashboard.canary_dashboard.active_canaries"
              :key="canary.canary_id"
              class="canary-item"
            >
              <div class="canary-header">
                <span class="canary-stage">{{ t('harness_dashboard.stage', { stage: canary.stage }) }}</span>
                <span :class="['canary-status', canary.status]" :style="{ color: statusColor(canary.status) }">
                  {{ t('harness_dashboard.status.' + canary.status) }}
                </span>
              </div>
              <div class="canary-detail">{{ t('harness_dashboard.traffic', { pct: (canary.traffic_pct * 100).toFixed(0) }) }}</div>
              <div class="canary-detail">{{ t('harness_dashboard.samples_collected', { count: canary.samples_collected }) }}</div>
              <div class="canary-detail">{{ t('harness_dashboard.quality_ratio', { ratio: canary.quality_ratio.toFixed(3) }) }}</div>
              <div v-if="canary.auto_rollback_triggered" class="canary-alert">{{ t('harness_dashboard.auto_rollback_triggered') }}</div>
            </div>
          </div>
          <div v-else class="empty-state">{{ t('harness_dashboard.no_active_canaries') }}</div>
        </section>

        <!-- A/B Tests -->
        <section class="card">
          <h2>{{ t('harness_dashboard.ab_tests') }}</h2>
          <div v-if="dashboard.ab_tests.tests.length > 0">
            <div
              v-for="test in dashboard.ab_tests.tests"
              :key="test.test_id"
              class="ab-test-item"
            >
              <div class="ab-header">
                <span>{{ test.variant_a }} vs {{ test.variant_b }}</span>
                <span v-if="test.winner" class="ab-winner">🏆 {{ test.winner }}</span>
              </div>
              <div class="ab-detail">{{ t('harness_dashboard.samples', { count: test.sample_count }) }} | {{ t('harness_dashboard.improvement', { pct: test.improvement_pct.toFixed(1) }) }}</div>
              <div class="ab-detail">
                p={{ test.p_value.toFixed(4) }}
                <span :class="['ab-significance', test.statistically_significant ? 'significant' : 'not-significant']">
                  {{ test.statistically_significant ? t('harness_dashboard.significant') : t('harness_dashboard.not_significant') }}
                </span>
              </div>
            </div>
          </div>
          <div v-else class="empty-state">{{ t('harness_dashboard.no_ab_tests') }}</div>
        </section>

        <!-- Critics Ensemble -->
        <section class="card">
          <h2>{{ t('harness_dashboard.critics_ensemble') }}</h2>
          <div v-if="dashboard.critics_latest.verdicts.length > 0">
            <div class="critics-summary">
              <span class="critics-verdict" :style="{ color: verdictColor(dashboard.critics_latest.weighted_verdict) }">
                {{ t('harness_dashboard.verdict.' + dashboard.critics_latest.weighted_verdict) }}
              </span>
              <span class="critics-score">{{ t('harness_dashboard.combined_score', { score: (dashboard.critics_latest.weighted_score * 100).toFixed(1) }) }}</span>
            </div>
            <div
              v-for="v in dashboard.critics_latest.verdicts"
              :key="v.critic_type"
              class="critic-item"
            >
              <span class="critic-type">{{ t('harness_dashboard.critic_type.' + v.critic_type.toLowerCase()) }}</span>
              <span :class="['critic-verdict', v.verdict]" :style="{ color: verdictColor(v.verdict) }">
                {{ t('harness_dashboard.verdict.' + v.verdict) }}
              </span>
              <span class="critic-score">{{ (v.score * 100).toFixed(0) }}%</span>
            </div>
          </div>
          <div v-else class="empty-state">{{ t('harness_dashboard.no_critics_data') }}</div>
        </section>
      </div>

      <!-- Row 4: Prompt Timeline -->
      <section class="card full-width" v-if="Object.keys(dashboard.prompt_timeline.stages).length > 0">
        <h2>{{ t('harness_dashboard.prompt_timeline') }}</h2>
        <div class="timeline-grid">
          <div v-for="(items, stage) in dashboard.prompt_timeline.stages" :key="stage" class="timeline-stage">
            <h3>{{ t('harness_dashboard.stage', { stage }) }}</h3>
            <div class="timeline-items">
              <div v-for="item in items" :key="item.version" class="timeline-item">
                <span :class="['tl-badge', item.status]">{{ t('harness_dashboard.status.' + item.status) }}</span>
                <span class="tl-version">{{ item.version }}</span>
                <span class="tl-date">{{ item.created_at }}</span>
                <span v-if="item.golden_score !== null" class="tl-score">
                  {{ t('harness_dashboard.golden_score', { score: (item.golden_score * 100).toFixed(0) }) }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.harness-dashboard {
  max-width: 1200px;
  margin: 0 auto;
}

/* Header */
.page-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.page-header h1 { margin: 0; font-size: 22px; flex: 1; }
.header-actions { display: flex; gap: 8px; }
.header-actions .btn { white-space: nowrap; }

.btn {
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  cursor: pointer;
  font-size: 14px;
  transition: all 0.15s;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: var(--color-primary); color: #fff; border-color: var(--color-primary); }
.btn-primary:hover:not(:disabled) { background: var(--color-primary-hover); }
.btn-outline { background: var(--color-card-bg); color: var(--color-text-secondary); }
.btn-outline:hover:not(:disabled) { background: var(--color-bg-tertiary); }
.btn-ghost { background: none; border: none; color: var(--color-text-secondary); }
.btn-ghost:hover { color: var(--color-text); }

/* Status bar */
.status-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: var(--color-bg-tertiary);
  border-radius: 8px;
  font-size: 13px;
  color: var(--color-text-secondary);
  margin-bottom: 16px;
}
.trigger-msg.success { color: var(--color-success); }
.trigger-msg.error { color: var(--color-danger); }

.error-banner {
  padding: 12px 16px;
  background: var(--color-danger-soft);
  color: var(--color-danger);
  border-radius: 8px;
  margin-bottom: 16px;
}

.loading {
  text-align: center;
  padding: 60px;
  color: var(--color-text-secondary);
}

/* Grid */
.grid { display: grid; gap: 16px; margin-bottom: 16px; }
.grid-2 { grid-template-columns: 1fr 1fr; }
.grid-3 { grid-template-columns: 1fr 1fr 1fr; }
.full-width { margin-bottom: 16px; }

@media (max-width: 900px) {
  .grid-2, .grid-3 { grid-template-columns: 1fr; }
}

/* Card */
.card {
  background: var(--color-card-bg);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  padding: 20px;
}
.card h2 {
  margin: 0 0 16px;
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text);
}

/* Stat row */
.stat-row { display: flex; gap: 16px; flex-wrap: wrap; }
.stat-item { display: flex; flex-direction: column; gap: 4px; }
.stat-label { font-size: 12px; color: var(--color-text-muted); }
.stat-value { font-size: 20px; font-weight: 600; color: var(--color-text); }
.stat-value.small { font-size: 13px; font-weight: 400; }
.stat-badge {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 99px;
  font-weight: 500;
}
.stat-badge.active { background: var(--color-success-soft); color: var(--color-success); }
.stat-badge.inactive { background: var(--color-bg-tertiary); color: var(--color-text-secondary); }

/* Funnel */
.funnel { display: flex; flex-direction: column; gap: 10px; }
.funnel-step { display: flex; align-items: center; gap: 12px; }
.funnel-label { width: 80px; font-size: 13px; color: var(--color-text-secondary); text-align: right; }
.funnel-bar-wrapper { flex: 1; height: 20px; background: var(--color-bg-tertiary); border-radius: 4px; overflow: hidden; }
.funnel-bar { height: 100%; background: var(--color-primary); border-radius: 4px; transition: width 0.5s; }
.funnel-value { width: 40px; font-size: 14px; font-weight: 600; text-align: right; }

/* Pattern heatmap */
.top-patterns { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.tag {
  font-size: 11px;
  padding: 2px 8px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  border-radius: 4px;
}
.pattern-bars { display: flex; flex-direction: column; gap: 6px; }
.pattern-row { display: flex; align-items: center; gap: 8px; }
.pattern-tag { width: 140px; font-size: 12px; color: var(--color-text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pattern-bar-wrapper { flex: 1; height: 14px; background: var(--color-bg-tertiary); border-radius: 3px; overflow: hidden; }
.pattern-bar { height: 100%; background: var(--color-warning); border-radius: 3px; }
.pattern-count { width: 30px; font-size: 12px; font-weight: 600; text-align: right; }
.pattern-stage { font-size: 11px; color: var(--color-text-muted); width: 100px; }

/* Promotion gate */
.gate-status {
  padding: 8px 12px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 16px;
  text-align: center;
}
.gate-status.pass { background: var(--color-success-soft); color: var(--color-success); }
.gate-status.fail { background: var(--color-danger-soft); color: var(--color-danger); }
.gate-list { display: flex; flex-direction: column; gap: 12px; }
.gate-item { display: flex; align-items: center; gap: 12px; }
.gate-label { width: 120px; font-size: 13px; color: var(--color-text-secondary); text-align: right; }
.gate-bar-wrapper { flex: 1; height: 18px; background: var(--color-bg-tertiary); border-radius: 4px; overflow: hidden; }
.gate-bar { height: 100%; border-radius: 4px; transition: width 0.5s; }
.gate-value { width: 110px; font-size: 13px; font-weight: 500; text-align: right; }
.gate-threshold { color: var(--color-text-muted); font-weight: 400; }

/* Canary */
.canary-item { padding: 10px; background: var(--color-bg-tertiary); border-radius: 8px; margin-bottom: 8px; }
.canary-header { display: flex; justify-content: space-between; margin-bottom: 4px; }
.canary-stage { font-weight: 600; font-size: 14px; }
.canary-status { font-size: 12px; text-transform: capitalize; }
.canary-detail { font-size: 13px; color: var(--color-text-secondary); }
.canary-alert { font-size: 12px; color: var(--color-warning); margin-top: 4px; }

/* A/B Test */
.ab-test-item { padding: 10px; background: var(--color-bg-tertiary); border-radius: 8px; margin-bottom: 8px; }
.ab-header { display: flex; justify-content: space-between; margin-bottom: 4px; font-weight: 500; font-size: 13px; }
.ab-winner { font-size: 12px; }
.ab-detail { font-size: 12px; color: var(--color-text-secondary); }
.ab-significance { margin-left: 4px; }
.ab-significance.significant { color: var(--color-success); }
.ab-significance.not-significant { color: var(--color-text-muted); }

/* Critics */
.critics-summary { display: flex; gap: 12px; align-items: center; margin-bottom: 12px; }
.critics-verdict { font-size: 18px; font-weight: 700; text-transform: uppercase; }
.critics-score { font-size: 14px; color: var(--color-text-secondary); }
.critic-item { display: flex; gap: 12px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--color-bg-tertiary); }
.critic-type { width: 100px; font-size: 13px; font-weight: 500; }
.critic-verdict { width: 100px; font-size: 13px; }
.critic-score { font-size: 13px; color: var(--color-text-secondary); }

/* Empty state */
.empty-state {
  text-align: center;
  padding: 20px;
  color: var(--color-text-muted);
  font-size: 14px;
}

/* Timeline */
.timeline-grid { display: flex; gap: 20px; flex-wrap: wrap; }
.timeline-stage { flex: 1; min-width: 250px; }
.timeline-stage h3 { font-size: 14px; margin: 0 0 8px; color: var(--color-text-secondary); }

/* ── Mobile Responsive ─────────────────────────────────────── */
@media (max-width: 900px) {
  .stat-row { gap: 12px; }
  .funnel-label { width: 70px; font-size: 12px; }
  .pattern-tag { width: 110px; }
  .pattern-stage { width: 70px; }
  .gate-label { width: 90px; }
  .gate-value { width: 90px; font-size: 12px; }
  .critic-type, .critic-verdict { width: 80px; }
}

@media (max-width: 600px) {
  .page-header { flex-direction: column; align-items: flex-start; gap: 12px; }
  .header-actions { width: 100%; flex-wrap: wrap; }
  .header-actions .btn { flex: 1; justify-content: center; }

  .stat-row { flex-direction: column; gap: 8px; }

  /* Stack funnel rows on narrow screens */
  .funnel-label { width: auto; flex-basis: 100%; text-align: left; margin-bottom: 2px; }
  .funnel-step { flex-wrap: wrap; }

  /* Timeline stages stack vertically */
  .timeline-stage { min-width: 100%; }

  /* Status bar wraps */
  .status-bar { flex-direction: column; gap: 8px; align-items: flex-start; }

  .canary-header, .ab-header { flex-direction: column; gap: 4px; }
}
.timeline-items { display: flex; flex-direction: column; gap: 6px; }
.timeline-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--color-bg-tertiary);
  border-radius: 6px;
  font-size: 13px;
}
.tl-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
  text-transform: uppercase;
}
.tl-badge.draft { background: var(--color-bg-tertiary); color: var(--color-text-secondary); }
.tl-badge.canary { background: var(--color-warning-soft); color: var(--color-warning); }
.tl-badge.promoted { background: var(--color-success-soft); color: var(--color-success); }
.tl-badge.rolled_back { background: var(--color-danger-soft); color: var(--color-danger); }
.tl-version { font-weight: 500; }
.tl-date { color: var(--color-text-muted); }
.tl-score { color: var(--color-primary); }
</style>
