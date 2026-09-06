<template>
  <div class="runs-view">
    <div class="header">
      <h1>{{ t('runs.title') }}</h1>
    </div>

    <el-card class="section">
      <template #header>{{ t('runs.manualRun') }}</template>
      <el-form :inline="true">
        <el-form-item :label="t('runs.stage')">
          <el-select v-model="stage" style="width: 180px">
            <el-option v-for="s in stages" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('runs.chapterId')">
          <el-input-number v-model="chapterId" :min="0" :controls="false" placeholder="-" style="width: 120px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="running" @click="runStage">{{ t('runs.run') }}</el-button>
        </el-form-item>
      </el-form>
      <el-alert
        v-if="runResult"
        :title="runResult.message"
        :type="runResult.status === 'completed' ? 'success' : runResult.status === 'failed' ? 'error' : 'info'"
        :closable="false"
      />
    </el-card>

    <el-card class="section" v-loading="loadingProduct">
      <template #header>
        <div class="card-header">
          <span>{{ t('runs.intermediate') }}</span>
          <el-button size="small" @click="loadProduct">{{ t('common.refresh') }}</el-button>
        </div>
      </template>
      <el-select v-model="viewStage" size="small" style="width: 160px; margin-bottom: 12px" @change="loadProduct">
        <el-option v-for="s in stages" :key="s" :label="s" :value="s" />
      </el-select>
      <pre v-if="product" class="product-json">{{ JSON.stringify(product, null, 2) }}</pre>
      <el-empty v-else-if="!loadingProduct" :description="t('common.noData')" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useI18n } from '../i18n'
import { runPipelineStage, fetchIntermediateProduct, type StageRunResponse } from '../api'

const route = useRoute()
const { t } = useI18n()

const projectId = computed(() => Number(route.params.projectId || route.params.id))
const stages = ['extract', 'analyze', 'annotate', 'edit', 'audio_postprocess', 'synthesize', 'quality']

const stage = ref('extract')
const chapterId = ref<number | undefined>(undefined)
const running = ref(false)
const runResult = ref<StageRunResponse | null>(null)

const viewStage = ref('extract')
const product = ref<Record<string, unknown> | null>(null)
const loadingProduct = ref(false)

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
.runs-view { padding: 24px; max-width: 1200px; margin: 0 auto; }
.header { margin-bottom: 16px; }
.section { margin-bottom: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.product-json {
  background: var(--el-fill-color-light);
  padding: 12px;
  border-radius: 4px;
  overflow: auto;
  max-height: 480px;
  font-size: 13px;
}
</style>
