<template>
  <div v-if="projectId" class="project-tabs">
    <div class="project-context">
      <span class="crumb-label">{{ t('common.project') }}</span>
      <el-select
        :model-value="Number(projectId)"
        size="small"
        class="project-switcher"
        @change="switchProject"
      >
        <el-option
          v-for="p in projectOptions"
          :key="p.id"
          :label="p.title || `#${p.id}`"
          :value="p.id"
        />
      </el-select>
      <span v-if="currentProjectTitle" class="project-title">{{ currentProjectTitle }}</span>
    </div>
    <el-tabs :model-value="activeTab" @tab-click="onTabClick">
      <el-tab-pane
        v-for="tab in tabs"
        :key="tab.name"
        :label="t(tab.label)"
        :name="tab.name"
      />
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '../i18n'
import { useProjectStore } from '../stores/projects'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const store = useProjectStore()

const projectId = computed(() => String(route.params.id || route.params.projectId || ''))

const projectOptions = computed(() => {
  const list = Array.isArray(store.projects) ? store.projects : []
  return list.map((p) => ({ id: p.id, title: p.title || `#${p.id}` }))
})

const currentProjectTitle = computed(() => {
  const id = Number(projectId.value)
  const current = store.currentProject?.id === id ? store.currentProject : store.projects.find((p) => p.id === id)
  return current?.title || ''
})

async function ensureProjectContext() {
  const id = Number(projectId.value)
  if (!id) return
  if (!store.projects.length) {
    await store.loadProjects()
  }
  if (!store.currentProject || store.currentProject.id !== id) {
    await store.loadProject(id)
  }
}

function switchProject(id: number) {
  const path = route.path
  const next = path.replace(/^\/projects\/\d+/, `/projects/${id}`)
  if (next !== path) router.push(next)
}

const tabs = [
  { name: 'overview', label: 'overview.links.tabs.overview', path: 'overview' },
  { name: 'characters', label: 'overview.links.characters', path: 'characters' },
  { name: 'quality', label: 'overview.links.quality', path: 'quality' },
  { name: 'translation', label: 'overview.links.translation', path: 'translation' },
  { name: 'voice-clone', label: 'overview.links.voiceClone', path: 'voice-clone' },
  { name: 'auto-run', label: 'overview.links.autoRun', path: 'auto-run' },
  { name: 'review', label: 'overview.links.reviewGate', path: 'review' },
  { name: 'runs', label: 'overview.links.runs', path: 'runs' },
  { name: 'knowledge', label: 'overview.links.knowledge', path: 'knowledge' },
  { name: 'dashboard', label: 'overview.links.dashboard', path: 'dashboard' },
  { name: 'audio-segments', label: 'overview.links.audioSegments', path: 'audio-segments' },
  { name: 'tts-edit', label: 'project_detail.edit_for_tts', path: 'tts-edit' },
  { name: 'export', label: 'overview.links.export', path: 'export' },
  { name: 'publish', label: 'overview.links.publish', path: 'publish' },
]

const activeTab = computed(() => {
  const seg = route.path.split('/').filter(Boolean)
  const sub = seg[2] || ''
  if (sub === 'chapters') return 'overview'
  const hit = tabs.find((tb) => tb.path === sub)
  return hit ? hit.name : 'overview'
})

function onTabClick(pane: { paneName?: string | number }) {
  const name = String(pane.paneName || '')
  const tab = tabs.find((tb) => tb.name === name)
  if (tab && projectId.value) {
    router.push('/projects/' + projectId.value + '/' + tab.path)
  }
}

onMounted(ensureProjectContext)
</script>

<style scoped>
.project-tabs {
  padding: 8px 24px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}
.project-context {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 8px;
}
.crumb-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.project-switcher {
  width: 180px;
}
.project-title {
  font-weight: 600;
  font-size: 13px;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.project-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}
.project-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}
</style>
