<template>
  <div v-if="projectId" class="project-tabs">
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
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '../i18n'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const projectId = computed(() => String(route.params.id || route.params.projectId || ''))

const tabs = [
  { name: 'overview', label: 'overview.links.tabs.overview', path: 'overview' },
  { name: 'characters', label: 'overview.links.characters', path: 'characters' },
  { name: 'quality', label: 'overview.links.quality', path: 'quality' },
  { name: 'translation', label: 'overview.links.translation', path: 'translation' },
  { name: 'voice-clone', label: 'overview.links.voiceClone', path: 'voice-clone' },
  { name: 'auto-run', label: 'overview.links.autoRun', path: 'auto-run' },
  { name: 'dashboard', label: 'overview.links.dashboard', path: 'dashboard' },
  { name: 'audio-segments', label: 'overview.links.audioSegments', path: 'audio-segments' },
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
</script>

<style scoped>
.project-tabs {
  padding: 8px 24px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}
.project-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}
.project-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}
</style>
