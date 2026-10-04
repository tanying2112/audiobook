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

<script setup lang="ts">
import { useHarnessDashboard } from '../composables/useHarnessDashboard'
import './HarnessDashboard.css'

const {
  t,
  router,
  dashboard,
  loading,
  error,
  triggering,
  triggerMessage,
  triggerError,
  lastRefresh,
  loadDashboard,
  handleTrigger,
  statusColor,
  gateBarWidth,
  gateBarColor,
  verdictColor,
  patternBarWidth,
} = useHarnessDashboard()
</script>
