<template>
  <div class="segments-view">
    <div class="header">
      <h1>{{ t('segments.title') }}</h1>
      <div class="actions">
        <el-button type="primary" :disabled="selected.length < 2" :loading="merging" @click="onMerge">
          {{ t('segments.mergeSelected', { n: selected.length }) }}
        </el-button>
        <el-button :loading="loading" @click="load">{{ t('common.refresh') }}</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" />
    <el-empty v-if="!loading && segments.length === 0" :description="t('segments.empty')" />

    <el-table v-else v-loading="loading" :data="segments" @selection-change="onSelectionChange">
      <el-table-column type="selection" width="45" />
      <el-table-column type="index" :label="t('segments.order')" width="70" />
      <el-table-column prop="id" :label="t('segments.id')" min-width="180" show-overflow-tooltip />
      <el-table-column :label="t('segments.duration')" width="110">
        <template #default="scope">{{ formatDuration(scope.row.duration_ms) }}</template>
      </el-table-column>
      <el-table-column :label="t('segments.speaker')" width="120">
        <template #default="scope">{{ scope.row.speaker || '—' }}</template>
      </el-table-column>
      <el-table-column prop="paragraph_index" :label="t('segments.paragraph')" width="90" />
      <el-table-column :label="t('common.actions')" width="260">
        <template #default="scope">
          <el-button size="small" text @click="openTrim(scope.row)">{{ t('segments.trim') }}</el-button>
          <el-button size="small" text :disabled="scope.$index === 0" @click="move(scope.$index, -1)">↑</el-button>
          <el-button size="small" text :disabled="scope.$index === segments.length - 1" @click="move(scope.$index, 1)">↓</el-button>
          <el-popconfirm :title="t('segments.deleteConfirm')" @confirm="onDelete(scope.row)">
            <template #reference>
              <el-button size="small" text type="danger">{{ t('common.delete') }}</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="dirty" class="footer">
      <el-button type="primary" :loading="savingOrder" @click="saveOrder">{{ t('segments.saveOrder') }}</el-button>
      <el-button @click="load">{{ t('common.cancel') }}</el-button>
    </div>

    <el-dialog v-model="trimDialog" :title="t('segments.trimTitle')" width="420px">
      <el-form label-width="110px">
        <el-form-item :label="t('segments.startMs')">
          <el-input-number v-model="trimForm.start_ms" :min="0" :max="trimForm.end_ms - 1" />
        </el-form-item>
        <el-form-item :label="t('segments.endMs')">
          <el-input-number v-model="trimForm.end_ms" :min="trimForm.start_ms + 1" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="trimDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="trimming" @click="submitTrim">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useI18n } from '../i18n'
import {
  fetchAudioSegments,
  trimAudioSegment,
  mergeAudioSegments,
  reorderAudioSegments,
  deleteAudioSegment,
  type AudioSegment,
} from '../api/audioSegments'

const route = useRoute()
const { t } = useI18n()

const bookId = String(route.params.id)
const segments = ref<AudioSegment[]>([])
const selected = ref<AudioSegment[]>([])
const loading = ref(false)
const merging = ref(false)
const trimming = ref(false)
const savingOrder = ref(false)
const dirty = ref(false)
const error = ref('')

const trimDialog = ref(false)
const trimTarget = ref<AudioSegment | null>(null)
const trimForm = ref({ start_ms: 0, end_ms: 0 })

function formatDuration(ms: number): string {
  const s = Math.round(ms / 1000)
  const m = Math.floor(s / 60)
  const r = String(s % 60).padStart(2, '0')
  return m + ':' + r
}

function onSelectionChange(rows: AudioSegment[]) {
  selected.value = rows
}

async function load() {
  loading.value = true
  error.value = ''
  dirty.value = false
  try {
    segments.value = await fetchAudioSegments(bookId)
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function move(index: number, delta: number) {
  const arr = [...segments.value]
  const removed = arr.splice(index, 1)[0]
  arr.splice(index + delta, 0, removed)
  segments.value = arr
  dirty.value = true
}

async function saveOrder() {
  if (segments.value.length === 0) return
  savingOrder.value = true
  try {
    await reorderAudioSegments(segments.value[0].id, segments.value.map((s) => s.id), 50, bookId)
    dirty.value = false
    ElMessage.success(t('segments.orderSaved'))
  } catch {
    ElMessage.error(t('segments.actionFailed'))
  } finally {
    savingOrder.value = false
  }
}

function openTrim(seg: AudioSegment) {
  trimTarget.value = seg
  trimForm.value = { start_ms: 0, end_ms: seg.duration_ms }
  trimDialog.value = true
}

async function submitTrim() {
  if (!trimTarget.value) return
  trimming.value = true
  try {
    await trimAudioSegment(trimTarget.value.id, trimForm.value, bookId)
    ElMessage.success(t('segments.trimmed'))
    trimDialog.value = false
    await load()
  } catch {
    ElMessage.error(t('segments.actionFailed'))
  } finally {
    trimming.value = false
  }
}

async function onMerge() {
  merging.value = true
  try {
    await mergeAudioSegments(selected.value.map((s) => s.id), bookId)
    ElMessage.success(t('segments.merged'))
    await load()
  } catch {
    ElMessage.error(t('segments.actionFailed'))
  } finally {
    merging.value = false
  }
}

async function onDelete(seg: AudioSegment) {
  try {
    await deleteAudioSegment(seg.id, bookId)
    segments.value = segments.value.filter((s) => s.id !== seg.id)
    ElMessage.success(t('common.deleted'))
  } catch {
    ElMessage.error(t('segments.actionFailed'))
  }
}

onMounted(load)
</script>

<style scoped>
.segments-view { padding: 24px; max-width: 1200px; margin: 0 auto; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.footer { margin-top: 16px; display: flex; gap: 8px; }
.mb { margin-bottom: 12px; }
</style>
