<template>
  <div class="promotions-view">
    <h1>{{ t('promotions.title') }}</h1>

    <el-row :gutter="16" class="stat-row">
      <el-col :span="6">
        <el-card><div class="stat-num">{{ gate?.promotion_passed_count ?? '—' }}</div><div class="stat-label">{{ t('promotions.passed') }}</div></el-card>
      </el-col>
      <el-col :span="6">
        <el-card><div class="stat-num">{{ canaries.length }}</div><div class="stat-label">{{ t('promotions.activeCanaries') }}</div></el-card>
      </el-col>
      <el-col :span="6">
        <el-card><div class="stat-num">{{ abTests.length }}</div><div class="stat-label">{{ t('promotions.abTests') }}</div></el-card>
      </el-col>
      <el-col :span="6">
        <el-card>
          <el-button type="primary" :loading="triggering" @click="onTrigger">{{ t('promotions.triggerIteration') }}</el-button>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="section">
      <template #header>{{ t('promotions.gateStatus') }}</template>
      <el-descriptions v-if="gate" :column="2" border>
        <el-descriptions-item v-for="(v, k) in gateSummary" :key="k" :label="String(k)">{{ v }}</el-descriptions-item>
      </el-descriptions>
      <el-empty v-else :description="t('common.noData')" />
    </el-card>

    <el-card class="section">
      <template #header>{{ t('promotions.canaries') }}</template>
      <el-table :data="canaries" v-loading="loading">
        <el-table-column prop="stage" :label="t('promotions.stage')" width="140" />
        <el-table-column prop="version" :label="t('promotions.version')" width="140" />
        <el-table-column prop="status" :label="t('promotions.status')" width="140">
          <template #default="{ row }">
            <el-tag :type="row.status === 'promoted' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="traffic_pct" :label="t('promotions.traffic')" width="120" />
        <el-table-column :label="t('common.actions')" width="200">
          <template #default="{ row }">
            <el-popconfirm :title="t('promotions.rollbackConfirm')" @confirm="onRollback(row)">
              <template #reference>
                <el-button size="small" type="danger" plain>{{ t('promotions.rollback') }}</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="section">
      <template #header>{{ t('promotions.abResults') }}</template>
      <el-table :data="abTests" v-loading="loading">
        <el-table-column prop="variant_a" :label="t('promotions.variantA')" width="130" />
        <el-table-column prop="variant_b" :label="t('promotions.variantB')" width="130" />
        <el-table-column prop="sample_count" :label="t('promotions.samples')" width="100" />
        <el-table-column prop="improvement_pct" :label="t('promotions.improvement')" width="120">
          <template #default="{ row }">{{ (row.improvement_pct ?? 0).toFixed(2) }}%</template>
        </el-table-column>
        <el-table-column prop="p_value" :label="t('promotions.pValue')" width="100">
          <template #default="{ row }">{{ row.p_value?.toFixed(4) ?? '—' }}</template>
        </el-table-column>
        <el-table-column prop="statistically_significant" :label="t('promotions.significant')" width="110">
          <template #default="{ row }">
            <el-tag :type="row.statistically_significant ? 'success' : 'info'">{{ row.statistically_significant ? '✓' : '—' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="winner" :label="t('promotions.winner')" width="110" />
      </el-table>
    </el-card>
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
.promotions-view { padding: 24px; }
.stat-row { margin-bottom: 16px; }
.stat-num { font-size: 28px; font-weight: 600; }
.stat-label { color: var(--el-text-color-secondary); }
.section { margin-bottom: 16px; }
</style>
