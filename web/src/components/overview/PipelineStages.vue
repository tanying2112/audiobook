<script setup lang="ts">
import { computed } from 'vue'
import { Icon } from '@iconify/vue'
import { useI18n } from '../../i18n'
import { PIPELINE_STAGE_ORDER, type PipelineStage } from '../../types/pipeline'
import type { AutoRunStatusResponse } from '../../api'

const props = defineProps<{
  /** Auto-run status response from API */
  autoRun: AutoRunStatusResponse | null
}>()

const { t } = useI18n()

/** Per-stage status: completed | running | pending */
interface StageInfo {
  stage: PipelineStage
  label: string
  status: 'completed' | 'running' | 'pending'
}

const stages = computed<StageInfo[]>(() => {
  const currentStage = props.autoRun?.current_stage
  const completed = props.autoRun?.completed_stages ?? []

  return PIPELINE_STAGE_ORDER.map((stage) => {
    let status: 'completed' | 'running' | 'pending' = 'pending'
    if (completed.includes(stage)) {
      status = 'completed'
    } else if (currentStage === stage) {
      status = 'running'
    }
    return { stage, label: t('stages.' + stage), status }
  })
})

const overallProgress = computed(() => {
  return Math.round((props.autoRun?.progress ?? 0) * 100)
})

const hasProgress = computed(() => {
  const s = props.autoRun?.status
  return s === 'running' || s === 'completed'
})

const statusIcon: Record<string, string> = {
  completed: 'mdi:check-circle',
  running: 'mdi:loading',
  pending: 'mdi:circle-outline',
}

const statusIconColor: Record<string, string> = {
  completed: 'var(--color-success)',
  running: 'var(--color-primary)',
  pending: 'var(--color-text-muted)',
}
</script>

<template>
  <div class="pipeline-stages">
    <!-- Horizontal stage ribbon -->
    <div class="stage-ribbon">
      <div
        v-for="(s, i) in stages"
        :key="s.stage"
        class="stage-node"
      >
        <!-- Connector line (before every node except the first) -->
        <div v-if="i > 0" class="connector" :class="s.status === 'completed' || s.status === 'running' ? 'filled' : ''"></div>
        <div class="node" :class="s.status">
          <Icon :icon="statusIcon[s.status]" width="18" height="18" :style="{ color: statusIconColor[s.status] }" />
        </div>
        <span class="stage-label" :class="s.status">{{ s.label }}</span>
      </div>
    </div>

    <!-- Overall progress bar -->
    <div v-if="hasProgress" class="progress-row">
      <div class="progress-track">
        <div class="progress-fill" :style="{ width: overallProgress + '%' }"></div>
      </div>
      <span class="progress-pct">{{ overallProgress }}%</span>
    </div>
  </div>
</template>

<style scoped>
.pipeline-stages {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ── Horizontal ribbon ───────────────────────────────── */

.stage-ribbon {
  display: flex;
  align-items: flex-start;
  gap: 0;
  overflow-x: auto;
  padding: 8px 0 4px;
}

.stage-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  min-width: 60px;
  position: relative;
}

/* Connector line between nodes */
.connector {
  position: absolute;
  top: 9px;
  right: 50%;
  width: 100%;
  height: 2px;
  background: var(--color-border);
  z-index: 0;
  transition: background var(--transition);
}

.connector.filled {
  background: var(--color-success);
}

/* Status node circle */
.node {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-full);
  background: var(--color-bg);
  border: 2px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  z-index: 1;
  transition: border-color var(--transition), background var(--transition);
  flex-shrink: 0;
}

.node.completed {
  border-color: var(--color-success);
  background: var(--color-success-soft);
}

.node.running {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
}

.node.pending {
  border-color: var(--color-border);
  background: var(--color-bg);
}

/* Stage label below node */
.stage-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-text-muted);
  text-align: center;
  margin-top: 6px;
  white-space: nowrap;
}

.stage-label.completed {
  color: var(--color-success);
}

.stage-label.running {
  color: var(--color-primary);
  font-weight: 600;
}

/* ── Progress bar ─────────────────────────────────────── */

.progress-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.progress-track {
  flex: 1;
  height: 6px;
  border-radius: var(--radius-full);
  background: var(--color-bg-tertiary);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: var(--radius-full);
  background: var(--color-primary);
  transition: width 0.4s ease;
}

.progress-pct {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-primary);
  min-width: 40px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
</style>
