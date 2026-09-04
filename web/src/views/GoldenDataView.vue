<template>
  <div class="golden-view">
    <div class="header">
      <h1>{{ t('golden.title') }}</h1>
      <div>
        <el-button :loading="regressing" @click="onRunRegression">{{ t('golden.runRegression') }}</el-button>
        <el-button type="primary" @click="contributeVisible = true">{{ t('golden.contribute') }}</el-button>
      </div>
    </div>

    <el-card class="section">
      <div class="filters">
        <el-select v-model="stageFilter" :placeholder="t('golden.stage')" clearable style="width: 180px" @change="load">
          <el-option v-for="s in stages" :key="s" :label="s" :value="s" />
        </el-select>
      </div>
      <el-table :data="samples" v-loading="loading">
        <el-table-column prop="id" label="ID" width="220" show-overflow-tooltip />
        <el-table-column prop="stage" :label="t('golden.stage')" width="120" />
        <el-table-column prop="status" :label="t('golden.status')" width="120">
          <template #default="{ row }">
            <el-tag :type="row.status === 'approved' ? 'success' : row.status === 'rejected' ? 'danger' : 'info'">
              {{ row.status || 'pending' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" :label="t('golden.createdAt')" width="180" />
        <el-table-column :label="t('common.actions')" width="200">
          <template #default="{ row }">
            <el-button size="small" type="success" plain @click="onApprove(row)">{{ t('golden.approve') }}</el-button>
            <el-button size="small" type="danger" plain @click="onReject(row)">{{ t('golden.reject') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && samples.length === 0" :description="t('golden.empty')" />
    </el-card>

    <el-dialog v-model="contributeVisible" :title="t('golden.contribute')" width="640px">
      <el-form label-width="100px">
        <el-form-item :label="t('golden.stage')">
          <el-select v-model="form.stage" style="width: 100%">
            <el-option v-for="s in stages" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('golden.input')">
          <el-input v-model="form.input" type="textarea" :rows="5" placeholder="JSON" />
        </el-form-item>
        <el-form-item :label="t('golden.expected')">
          <el-input v-model="form.expected" type="textarea" :rows="5" placeholder="JSON" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="contributeVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="submitting" @click="onContribute">{{ t('common.submit') }}</el-button>
      </template>
    </el-dialog>
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
.golden-view { padding: 24px; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.section { margin-bottom: 16px; }
.filters { margin-bottom: 12px; }
</style>
