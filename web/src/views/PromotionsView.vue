<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h1>{{ t('promotions.title') }}</h1>
      </div>
    </div>

    <!-- KPI row -->
    <div class="kpi-row">
      <div class="card kpi-card">
        <div class="stat-value">{{ gate?.promotion_passed_count ?? '—' }}</div>
        <div class="stat-label">{{ t('promotions.passed') }}</div>
      </div>
      <div class="card kpi-card">
        <div class="stat-value">{{ canaries.length }}</div>
        <div class="stat-label">{{ t('promotions.activeCanaries') }}</div>
      </div>
      <div class="card kpi-card">
        <div class="stat-value">{{ abTests.length }}</div>
        <div class="stat-label">{{ t('promotions.abTests') }}</div>
      </div>
      <div class="card kpi-card kpi-action">
        <button class="btn btn-primary btn-sm" :disabled="triggering" @click="onTrigger">
          <span v-if="triggering" class="spinner"></span>
          {{ t('promotions.triggerIteration') }}
        </button>
      </div>
    </div>

    <!-- Gate status -->
    <div class="card section">
      <div class="card-title">{{ t('promotions.gateStatus') }}</div>
      <div v-if="gate" class="gate-grid">
        <div v-for="(v, k) in gateSummary" :key="k" class="gate-item">
          <span class="gate-label">{{ k }}</span>
          <span class="gate-value">{{ v }}</span>
        </div>
      </div>
      <div v-else class="empty-state">{{ t('common.noData') }}</div>
    </div>

    <!-- Canaries -->
    <div class="card section">
      <div class="card-title">{{ t('promotions.canaries') }}</div>
      <div class="table-responsive">
        <table class="table" v-loading="loading">
          <thead>
            <tr>
              <th>{{ t('promotions.stage') }}</th>
              <th>{{ t('promotions.version') }}</th>
              <th>{{ t('promotions.status') }}</th>
              <th>{{ t('promotions.traffic') }}</th>
              <th>{{ t('common.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in canaries" :key="row.version + row.stage">
              <td>{{ row.stage }}</td>
              <td>{{ row.version }}</td>
              <td>
                <span
                  class="badge"
                  :class="row.status === 'promoted' ? 'badge-success' : row.status === 'failed' ? 'badge-danger' : 'badge-warning'"
                >
                  {{ row.status }}
                </span>
              </td>
              <td>{{ row.traffic_pct }}</td>
              <td>
                <button class="btn btn-sm btn-action-danger" @click="onRollback(row)">
                  {{ t('promotions.rollback') }}
                </button>
              </td>
            </tr>
            <tr v-if="canaries.length === 0">
              <td colspan="5" class="empty-cell">{{ t('common.noData') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- AB tests -->
    <div class="card section">
      <div class="card-title">{{ t('promotions.abResults') }}</div>
      <div class="table-responsive">
        <table class="table" v-loading="loading">
          <thead>
            <tr>
              <th>{{ t('promotions.variantA') }}</th>
              <th>{{ t('promotions.variantB') }}</th>
              <th>{{ t('promotions.samples') }}</th>
              <th>{{ t('promotions.improvement') }}</th>
              <th>{{ t('promotions.pValue') }}</th>
              <th>{{ t('promotions.significant') }}</th>
              <th>{{ t('promotions.winner') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in abTests" :key="i">
              <td>{{ row.variant_a }}</td>
              <td>{{ row.variant_b }}</td>
              <td>{{ row.sample_count }}</td>
              <td>{{ (row.improvement_pct ?? 0).toFixed(2) }}%</td>
              <td>{{ row.p_value?.toFixed(4) ?? '—' }}</td>
              <td>
                <span
                  class="badge"
                  :class="row.statistically_significant ? 'badge-success' : 'badge-muted'"
                >
                  {{ row.statistically_significant ? '✓' : '—' }}
                </span>
              </td>
              <td>{{ row.winner }}</td>
            </tr>
            <tr v-if="abTests.length === 0">
              <td colspan="7" class="empty-cell">{{ t('common.noData') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from '../i18n'
import {
  fetchPromotionGate,
  fetchCanaries,
  fetchABTests,
  triggerIteration,
  rollbackVersion,
} from '../api'

const { t } = useI18n()
const gate = ref<any>(null)
const canaries = ref<any[]>([])
const abTests = ref<any[]>([])
const loading = ref(false)
const triggering = ref(false)

const gateSummary = computed(() => {
  if (!gate.value) return {}
  const { stage, current_version, candidate_version, decision, reasons } = gate.value as any
  return { stage, current_version, candidate_version, decision, reasons: Array.isArray(reasons) ? reasons.join('; ') : reasons }
})

async function load() {
  loading.value = true
  try {
    const [g, c, a] = await Promise.all([
      fetchPromotionGate().catch(() => null),
      fetchCanaries().catch(() => ({ canaries: [] })),
      fetchABTests().catch(() => ({ ab_tests: [] })),
    ])
    gate.value = g
    canaries.value = (c as any)?.active_canaries ?? (c as any)?.canaries ?? []
    abTests.value = (a as any)?.tests ?? []
  } finally {
    loading.value = false
  }
}

async function onTrigger() {
  triggering.value = true
  try {
    await triggerIteration()
    await load()
  } finally {
    triggering.value = false
  }
}

async function onRollback(row: any) {
  await rollbackVersion(row.stage, row.version)
  await load()
}

onMounted(load)
</script>

<style scoped>
.kpi-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.kpi-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 20px 12px;
  text-align: center;
  min-height: 80px;
}

.kpi-action {
  display: flex;
  align-items: center;
  justify-content: center;
}

.stat-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-muted);
}

.gate-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.gate-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius);
}

.gate-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-muted);
  text-transform: capitalize;
}

.gate-value {
  font-size: 14px;
  color: var(--color-text);
  word-break: break-word;
}

.empty-cell {
  text-align: center;
  color: var(--color-text-muted);
  padding: 32px 12px;
}
.btn-action-danger { color: var(--color-danger); }
.btn-action-danger:hover { background: var(--color-danger-soft); }

@media (max-width: 767px) {
  .kpi-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .gate-grid {
    grid-template-columns: 1fr;
  }
}
</style>
