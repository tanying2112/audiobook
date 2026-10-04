<template>
  <div class="knowledge-view">
    <div class="header">
      <h1>{{ t('knowledge.title') }}</h1>
      <el-button type="primary" @click="showAdd = true">{{ t('knowledge.add') }}</el-button>
    </div>

    <el-card class="section">
      <template #header>
        <div class="card-header">
          <span>{{ t('knowledge.entries') }}</span>
          <el-input
            v-model="topicFilter"
            :placeholder="t('knowledge.searchTopic')"
            clearable
            size="small"
            style="width: 220px"
            @change="load"
          />
        </div>
      </template>
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
    </el-card>

    <el-dialog v-model="showAdd" :title="t('knowledge.add')" width="640px">
      <el-form label-width="100px">
        <el-form-item :label="t('knowledge.topic')">
          <el-input v-model="form.topic" />
        </el-form-item>
        <el-form-item :label="t('knowledge.content')">
          <el-input v-model="form.knowledgeJson" type="textarea" :rows="8" placeholder="JSON" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAdd = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">{{ t('common.submit') }}</el-button>
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
.knowledge-view { padding: 24px; max-width: 1200px; margin: 0 auto; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.section { margin-bottom: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.knowledge-json {
  margin: 0;
  max-height: 120px;
  overflow: auto;
  font-size: 12px;
  background: var(--el-fill-color-light);
  padding: 8px;
  border-radius: 4px;
}
</style>
