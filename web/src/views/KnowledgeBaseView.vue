<template>
  <div class="knowledge-view page-container">
    <div class="page-header">
      <h1>{{ t('knowledge.title') }}</h1>
      <button class="btn btn-primary" @click="showAdd = true" :aria-label="t('knowledge.add')">{{ t('knowledge.add') }}</button>
    </div>

    <div class="card section">
      <div class="card-header">
        <span class="card-title">{{ t('knowledge.entries') }}</span>
        <input
          v-model="topicFilter"
          class="form-control search-input"
          :placeholder="t('knowledge.searchTopic')"
          @change="load"
          :aria-label="t('knowledge.searchTopic')"
        />
      </div>
      <el-table :data="entries" v-loading="loading">
        <el-table-column prop="topic" :label="t('knowledge.topic')" min-width="160" />
        <el-table-column prop="source_agent" :label="t('knowledge.source')" width="120" />
        <el-table-column :label="t('knowledge.content')" min-width="220">
          <template #default="{ row }">
            <pre class="knowledge-json">{{ JSON.stringify(row?.knowledge ?? {}, null, 2) }}</pre>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" :label="t('knowledge.createdAt')" width="180" />
      </el-table>
      <el-empty v-if="!loading && entries.length === 0" :description="t('common.noData')" />
    </div>

    <el-dialog v-model="showAdd" :title="t('knowledge.add')" width="640px">
      <form class="knowledge-form" @submit.prevent="submit">
        <div class="form-group">
          <label class="form-label">{{ t('knowledge.topic') }}</label>
          <input v-model="form.topic" class="form-control" :aria-label="t('knowledge.topic')" />
        </div>
        <div class="form-group">
          <label class="form-label">{{ t('knowledge.content') }}</label>
          <textarea v-model="form.knowledgeJson" class="form-control knowledge-textarea" rows="8" placeholder="JSON" :aria-label="t('knowledge.content')"></textarea>
        </div>
      </form>
      <template #footer>
        <button class="btn btn-outline" @click="showAdd = false">{{ t('common.cancel') }}</button>
        <button class="btn btn-primary" :disabled="submitting" @click="submit" :aria-label="t('common.submit')">{{ t('common.submit') }}</button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useI18n } from '../i18n'
import { listKnowledge, addKnowledge, type KnowledgeEntry } from '../api'

const route = useRoute()
const { t } = useI18n()

const projectId = computed(() => Number(route.params.projectId || route.params.id))
const entries = ref<KnowledgeEntry[]>([])
const loading = ref(false)
const showAdd = ref(false)
const submitting = ref(false)
const topicFilter = ref('')
const form = ref({ topic: '', knowledgeJson: '' })

async function load() {
  loading.value = true
  try {
    const res = await listKnowledge(projectId.value, topicFilter.value || undefined)
    entries.value = res.knowledge ?? []
  } catch {
    entries.value = []
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (!form.value.topic.trim()) {
    ElMessage.warning(t('knowledge.topicRequired'))
    return
  }
  let knowledge: Record<string, unknown>
  try {
    knowledge = JSON.parse(form.value.knowledgeJson || '{}')
  } catch {
    ElMessage.error(t('knowledge.invalidJson'))
    return
  }
  submitting.value = true
  try {
    await addKnowledge(projectId.value, form.value.topic.trim(), knowledge)
    ElMessage.success(t('knowledge.added'))
    showAdd.value = false
    form.value = { topic: '', knowledgeJson: '' }
    await load()
  } catch (e: any) {
    ElMessage.error(e?.message ?? String(e))
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.knowledge-view {
  /* max-width & margin handled by .page-container */
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.search-input {
  width: 220px;
}

.knowledge-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.knowledge-json {
  margin: 0;
  max-height: 120px;
  overflow: auto;
  font-size: 12px;
  background: var(--color-bg-tertiary);
  padding: 8px;
  border-radius: var(--radius-sm);
}

.knowledge-textarea {
  min-height: 120px;
  resize: vertical;
  font-family: var(--font-mono);
}

@media (max-width: 767px) {
  .card-header {
    flex-direction: column;
    gap: 12px;
    align-items: stretch;
  }

  .search-input {
    width: 100%;
  }
}
</style>
