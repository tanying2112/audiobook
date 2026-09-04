<template>
  <div class="overview-view" v-loading="loading">
    <template v-if="project">
      <div class="header">
        <div>
          <h1>{{ project.title }}</h1>
          <span class="sub">{{ t('overview.projectId') }}: {{ projectId }}</span>
        </div>
        <div class="actions">
          <el-button type="primary" @click="go('auto-run')">{{ t('overview.runPipeline') }}</el-button>
          <el-button @click="go('export')">{{ t('overview.export') }}</el-button>
          <el-button @click="go('publish')">{{ t('overview.publish') }}</el-button>
        </div>
      </div>

      <el-row :gutter="16" class="stat-row">
        <el-col :span="6">
          <el-card><div class="stat-num">{{ chapters.length }}</div><div class="stat-label">{{ t('overview.chapters') }}</div></el-card>
        </el-col>
        <el-col :span="6">
          <el-card><div class="stat-num">{{ paragraphCount }}</div><div class="stat-label">{{ t('overview.paragraphs') }}</div></el-card>
        </el-col>
        <el-col :span="6">
          <el-card><div class="stat-num">{{ characters.length }}</div><div class="stat-label">{{ t('overview.characters') }}</div></el-card>
        </el-col>
        <el-col :span="6">
          <el-card>
            <div class="stat-num">
              <el-tag :type="runStatusTag">{{ autoRun?.status || t('overview.notStarted') }}</el-tag>
            </div>
            <div class="stat-label">{{ t('overview.pipelineStatus') }}</div>
          </el-card>
        </el-col>
      </el-row>

      <el-card class="section">
        <template #header>{{ t('overview.stageProgress') }}</template>
        <el-steps :active="activeStage" align-center finish-status="success">
          <el-step v-for="s in stageNames" :key="s" :title="t('stages.' + s)" />
        </el-steps>
        <div v-if="autoRun?.current_stage" class="current-stage">
          {{ t('overview.currentStage') }}: <b>{{ autoRun.current_stage }}</b>
          <el-progress :percentage="Math.round((autoRun.progress ?? 0) * 100)" style="margin-top: 8px" />
        </div>
      </el-card>

      <el-card class="section">
        <template #header>{{ t('overview.quickLinks') }}</template>
        <div class="quick-links">
          <el-button text type="primary" @click="go('characters')">{{ t('overview.links.characters') }}</el-button>
          <el-button text type="primary" @click="go('chapters')">{{ t('overview.links.chapters') }}</el-button>
          <el-button text type="primary" @click="go('quality')">{{ t('overview.links.quality') }}</el-button>
          <el-button text type="primary" @click="go('translation')">{{ t('overview.links.translation') }}</el-button>
          <el-button text type="primary" @click="go('voice-clone')">{{ t('overview.links.voiceClone') }}</el-button>
          <el-button text type="primary" @click="go('dashboard')">{{ t('overview.links.dashboard') }}</el-button>
        </div>
      </el-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '../i18n'
import {
  fetchProject,
  fetchChapters,
  fetchCharacters,
  getAutoRunStatus,
  type AutoRunStatusResponse,
} from '../api'
import type { Project, Chapter, Character } from '../types'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const projectId = Number(route.params.id)
const project = ref<Project | null>(null)
const chapters = ref<Chapter[]>([])
const characters = ref<Character[]>([])
const autoRun = ref<AutoRunStatusResponse | null>(null)
const paragraphCount = ref(0)
const loading = ref(false)

const stageNames = ['extract', 'analyze', 'annotate', 'edit', 'synthesize', 'quality', 'export']
const STAGE_ORDER = stageNames

const activeStage = computed(() => {
  const cur = (autoRun.value as any)?.current_stage as string | undefined
  if (!cur) return 0
  const idx = STAGE_ORDER.indexOf(cur)
  return idx >= 0 ? idx + 1 : 0
})

const runStatusTag = computed(() => {
  const s = autoRun.value?.status
  if (s === 'running') return 'warning'
  if (s === 'completed') return 'success'
  if (s === 'failed') return 'danger'
  return 'info'
})

function go(target: string) {
  const map: Record<string, string> = {
    'auto-run': `/projects/${projectId}/auto-run`,
    export: `/projects/${projectId}/export`,
    publish: `/projects/${projectId}/publish`,
    characters: `/projects/${projectId}/characters`,
    chapters: `/projects/${projectId}/chapters/${chapters.value[0]?.id ?? 1}`,
    quality: `/projects/${projectId}/quality`,
    translation: `/projects/${projectId}/translation`,
    'voice-clone': `/projects/${projectId}/voice-clone`,
    dashboard: `/projects/${projectId}/dashboard`,
  }
  if (map[target]) router.push(map[target])
}

async function load() {
  loading.value = true
  try {
    const [p, ch, chars, ar] = await Promise.all([
      fetchProject(projectId).catch(() => null),
      fetchChapters(projectId).catch(() => [] as Chapter[]),
      fetchCharacters(projectId).catch(() => [] as Character[]),
      getAutoRunStatus(projectId).catch(() => null),
    ])
    project.value = p
    chapters.value = ch
    characters.value = chars
    autoRun.value = ar
    paragraphCount.value = ch.reduce((sum: number, c: any) => sum + (c.paragraph_count ?? 0), 0)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.overview-view { padding: 24px; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.sub { color: var(--el-text-color-secondary); }
.stat-row { margin-bottom: 16px; }
.stat-num { font-size: 26px; font-weight: 600; }
.stat-label { color: var(--el-text-color-secondary); }
.section { margin-bottom: 16px; }
.current-stage { margin-top: 12px; }
.quick-links { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
