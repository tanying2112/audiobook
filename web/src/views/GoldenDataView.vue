<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h1>{{ t('golden.title') }}</h1>
      </div>
      <div class="header-actions">
        <button class="btn btn-outline btn-sm" :disabled="regressing" @click="onRunRegression">
          <span v-if="regressing" class="spinner"></span>
          {{ t('golden.runRegression') }}
        </button>
        <button class="btn btn-primary btn-sm" @click="contributeVisible = true">
          {{ t('golden.contribute') }}
        </button>
      </div>
    </div>

    <div class="card section">
      <div class="filters">
        <select v-model="stageFilter" class="form-control filter-select" @change="load">
          <option value="">{{ t('golden.stage') }}</option>
          <option v-for="s in stages" :key="s" :value="s">{{ s }}</option>
        </select>
      </div>

      <div class="table-responsive">
        <table class="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>{{ t('golden.stage') }}</th>
              <th>{{ t('golden.status') }}</th>
              <th>{{ t('golden.createdAt') }}</th>
              <th>{{ t('common.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in samples" :key="row.id">
              <td class="cell-id">{{ row.id }}</td>
              <td>{{ row.stage }}</td>
              <td>
                <span
                  class="badge"
                  :class="row.status === 'approved' ? 'badge-success' : row.status === 'rejected' ? 'badge-danger' : 'badge-muted'"
                >
                  {{ row.status || 'pending' }}
                </span>
              </td>
              <td>{{ row.created_at }}</td>
              <td class="cell-actions">
                <button class="btn btn-sm btn-action-success" @click="onApprove(row)">
                  {{ t('golden.approve') }}
                </button>
                <button class="btn btn-sm btn-action-danger" @click="onReject(row)">
                  {{ t('golden.reject') }}
                </button>
              </td>
            </tr>
            <tr v-if="!loading && samples.length === 0">
              <td colspan="5" class="empty-cell">{{ t('golden.empty') }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="loading" class="loading-state">
        <div class="spinner"></div>
      </div>
    </div>

    <!-- Contribute dialog -->
    <div v-if="contributeVisible" class="dialog-overlay" @click.self="contributeVisible = false">
      <div class="dialog" role="dialog" aria-modal="true" :aria-label="t('golden.contribute')">
        <div class="dialog-header">
          <h2>{{ t('golden.contribute') }}</h2>
          <button class="dialog-close" @click="contributeVisible = false" aria-label="Close">&times;</button>
        </div>
        <div class="dialog-body">
          <div class="form-group">
            <label>{{ t('golden.stage') }}</label>
            <select v-model="form.stage" class="form-control">
              <option v-for="s in stages" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>
          <div class="form-group">
            <label>{{ t('golden.input') }}</label>
            <textarea v-model="form.input" class="form-control" rows="5" placeholder="JSON"></textarea>
          </div>
          <div class="form-group">
            <label>{{ t('golden.expected') }}</label>
            <textarea v-model="form.expected" class="form-control" rows="5" placeholder="JSON"></textarea>
          </div>
        </div>
        <div class="dialog-footer">
          <button class="btn btn-outline btn-sm" @click="contributeVisible = false">{{ t('common.cancel') }}</button>
          <button class="btn btn-primary btn-sm" :disabled="submitting" @click="onContribute">
            <span v-if="submitting" class="spinner"></span>
            {{ t('common.submit') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from '../i18n'
import {
  fetchGoldenSamples,
  approveGoldenSample,
  rejectGoldenSample,
  contributeGoldenSample,
  runGoldenRegression,
  type GoldenSample,
} from '../api/golden'

const { t } = useI18n()
const stages = ['extract', 'analyze', 'annotate', 'edit', 'translate', 'judge', 'quality']
const samples = ref<GoldenSample[]>([])
const loading = ref(false)
const regressing = ref(false)
const submitting = ref(false)
const stageFilter = ref('')
const contributeVisible = ref(false)
const form = ref({ stage: 'extract', input: '', expected: '' })

async function load() {
  loading.value = true
  try {
    const data = await fetchGoldenSamples(stageFilter.value ? { stage: stageFilter.value } : undefined)
    samples.value = data.samples ?? []
  } catch {
    samples.value = []
  } finally {
    loading.value = false
  }
}

async function onApprove(row: GoldenSample) {
  await approveGoldenSample(row.id)
  ElMessage.success(t('golden.approved'))
  await load()
}

async function onReject(row: GoldenSample) {
  await rejectGoldenSample(row.id)
  ElMessage.success(t('golden.rejected'))
  await load()
}

async function onContribute() {
  submitting.value = true
  try {
    await contributeGoldenSample({
      stage: form.value.stage,
      input: JSON.parse(form.value.input),
      expected: JSON.parse(form.value.expected),
    })
    ElMessage.success(t('golden.contributed'))
    contributeVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message ?? String(e))
  } finally {
    submitting.value = false
  }
}

async function onRunRegression() {
  regressing.value = true
  try {
    await runGoldenRegression()
    ElMessage.success(t('golden.regressionDone'))
  } finally {
    regressing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.filters { margin-bottom: 12px; }
.filter-select { width: 200px; max-width: 100%; }
.cell-id { font-family: var(--font-mono); font-size: 13px; max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cell-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.empty-cell { text-align: center; color: var(--color-text-muted); padding: 32px 12px; }
.btn-action-success { color: var(--color-success); }
.btn-action-success:hover { background: var(--color-success-soft); }
.btn-action-danger { color: var(--color-danger); }
.btn-action-danger:hover { background: var(--color-danger-soft); }

/* Dialog */
.dialog-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; padding: 16px; }
.dialog { background: var(--color-surface); border-radius: var(--radius-lg); box-shadow: var(--shadow-lg); width: 100%; max-width: 640px; max-height: calc(100vh - 32px); overflow-y: auto; }
.dialog-header { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--color-border); }
.dialog-header h2 { margin: 0; font-size: 17px; font-weight: 600; }
.dialog-close { background: none; border: none; font-size: 22px; color: var(--color-text-muted); cursor: pointer; padding: 0 4px; line-height: 1; }
.dialog-close:hover { color: var(--color-text); }
.dialog-body { padding: 20px; display: flex; flex-direction: column; gap: 16px; }
.dialog-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 20px; border-top: 1px solid var(--color-border); }

@media (max-width: 767px) {
  .page-header { flex-direction: column; align-items: stretch; }
  .header-actions { justify-content: flex-end; }
  .filter-select { width: 100%; }
  .dialog { margin: 0; border-radius: var(--radius); }
}
</style>
