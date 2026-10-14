<template>
  <div class="page-container runs-view">
    <header class="page-header">
      <div>
        <h1>{{ t('runs.title') }}</h1>
        <p class="page-subtitle">Manual stage execution &amp; intermediate products</p>
      </div>
    </header>

    <!-- Manual Run -->
    <div class="card card-hover section">
      <h2 class="card-title">{{ t('runs.manualRun') }}</h2>
      <div class="manual-run-form">
        <div class="form-group">
          <label class="form-label">{{ t('runs.stage') }}</label>
          <select v-model="stage" class="form-control stage-select">
            <option v-for="s in stages" :key="s" :label="s" :value="s" />
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">{{ t('runs.chapterId') }}</label>
          <input
            type="number"
            v-model.number="chapterId"
            min="0"
            placeholder="-"
            class="form-control chapter-input"
          />
        </div>
        <div class="form-group run-btn-group">
          <button
            class="btn btn-primary run-btn"
            :disabled="running"
            @click="runStage"
            :aria-label="running ? 'Running...' : t('runs.run')"
          >
            <Icon v-if="running" icon="mdi:loading" width="16" height="16" class="spinner" />
            <Icon v-else icon="mdi:play" width="16" height="16" />
            {{ running ? 'Running...' : t('runs.run') }}
          </button>
        </div>
      </div>
      <div v-if="runResult" class="result-alert" :class="resultAlertClass">
        <Icon :icon="resultIcon" width="16" height="16" />
        <span>{{ runResult.message }}</span>
      </div>
    </div>

    <!-- Intermediate Products -->
    <div class="card card-hover section">
      <div class="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h2 class="card-title card-title--compact">{{ t('runs.intermediate') }}</h2>
        <button class="btn btn-outline btn-sm" @click="loadProduct" :aria-label="t('common.refresh')">
          <Icon icon="mdi:refresh" width="14" height="14" />
          {{ t('common.refresh') }}
        </button>
      </div>
      <div class="form-group mb-4">
        <label class="form-label">{{ t('runs.stage') }}</label>
        <select v-model="viewStage" class="form-control view-stage-select" @change="loadProduct">
          <option v-for="s in stages" :key="s" :label="s" :value="s" />
        </select>
      </div>
      <div v-if="loadingProduct" class="loading-state">
        <span class="spinner spinner-lg"></span>
        <span>Loading...</span>
      </div>
      <pre v-else-if="product" class="product-json">{{ JSON.stringify(product, null, 2) }}</pre>
      <div v-else class="empty-state">
        <Icon icon="mdi:file-document-outline" width="32" height="32" />
        <span>{{ t('common.noData') }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Icon } from '@iconify/vue'
import { useI18n } from '../i18n'
import { runPipelineStage, fetchIntermediateProduct, type StageRunResponse } from '../api'

const route = useRoute()
const { t } = useI18n()

const projectId = computed(() => Number(route.params.projectId || route.params.id))
const stages = ['extract', 'analyze', 'annotate', 'edit', 'audio_postprocess', 'synthesize', 'quality']

const queryStage = (route.query as { stage?: unknown } | undefined)?.stage
const stage = ref(stages.includes(String(queryStage)) ? String(queryStage) : 'extract')
const chapterId = ref<number | undefined>(undefined)
const running = ref(false)
const runResult = ref<StageRunResponse | null>(null)

const viewStage = ref('extract')
const product = ref<Record<string, unknown> | null>(null)
const loadingProduct = ref(false)

const resultAlertClass = computed(() => {
  if (!runResult.value) return ''
  return runResult.value.status === 'completed' ? 'result-alert--success'
    : runResult.value.status === 'failed' ? 'result-alert--danger'
    : 'result-alert--info'
})

const resultIcon = computed(() => {
  if (!runResult.value) return 'mdi:information'
  return runResult.value.status === 'completed' ? 'mdi:check-circle'
    : runResult.value.status === 'failed' ? 'mdi:alert-circle'
    : 'mdi:information'
})

async function runStage() {
  running.value = true
  runResult.value = null
  try {
    const result = await runPipelineStage(projectId.value, {
      stage: stage.value,
      ...(chapterId.value ? { chapter_id: chapterId.value } : {}),
    })
    runResult.value = result
    if (result.status === 'completed') {
      await loadProduct()
    }
  } catch (e: any) {
    ElMessage.error(e?.message ?? String(e))
  } finally {
    running.value = false
  }
}

async function loadProduct() {
  loadingProduct.value = true
  try {
    product.value = await fetchIntermediateProduct(projectId.value, viewStage.value, chapterId.value || undefined)
  } catch (e: any) {
    product.value = null
    ElMessage.warning(e?.message ?? String(e))
  } finally {
    loadingProduct.value = false
  }
}

onMounted(loadProduct)
</script>

<style scoped>
.runs-view {
  max-width: 960px;
}

/* ── Manual run form ──────────────────────────────────────── */
.manual-run-form {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  flex-wrap: wrap;
}
.stage-select {
  width: 180px;
}
.chapter-input {
  width: 120px;
}
.run-btn-group {
  display: flex;
  align-items: flex-end;
}
.run-btn {
  min-width: 120px;
}

/* ── Result alert ─────────────────────────────────────────── */
.result-alert {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: var(--radius);
  font-size: 13px;
  margin-top: 16px;
}
.result-alert--success {
  background: var(--color-success-soft);
  color: var(--color-success);
  border: 1px solid var(--color-success);
  border-color: rgba(5, 150, 105, 0.2);
}
.result-alert--danger {
  background: var(--color-danger-soft);
  color: var(--color-danger);
  border: 1px solid rgba(220, 38, 38, 0.2);
}
.result-alert--info {
  background: var(--color-info-soft);
  color: var(--color-info);
  border: 1px solid rgba(2, 132, 199, 0.2);
}

/* ── View stage select ────────────────────────────────────── */
.view-stage-select {
  width: 200px;
}

/* ── Product JSON ─────────────────────────────────────────── */
.product-json {
  background: var(--color-bg-tertiary);
  color: var(--color-text);
  padding: 12px;
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
  overflow: auto;
  max-height: 480px;
  font-size: 13px;
  font-family: var(--font-mono);
  margin: 0;
}

/* ── Mobile ───────────────────────────────────────────────── */
@media (max-width: 767px) {
  .manual-run-form {
    flex-direction: column;
    align-items: stretch;
  }
  .stage-select,
  .chapter-input,
  .view-stage-select {
    width: 100%;
  }
  .run-btn {
    width: 100%;
  }
}


/* ── Compact card title ─────────────────────────────────────── */
.card-title--compact {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

/* ── Mobile improvements ────────────────────────────────────── */
@media (max-width: 767px) {
  .result-alert {
    font-size: 12px;
    padding: 8px 12px;
  }
}
</style>
