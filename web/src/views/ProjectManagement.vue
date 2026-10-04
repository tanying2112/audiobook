<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '../stores/projects'
import { useI18n } from '../i18n'
import { Icon } from '@iconify/vue'

const router = useRouter()
const store = useProjectStore()
const { t } = useI18n()
const searchQuery = ref('')

// 7 阶段流程（与 AutoRunView / ChapterTimeline 一致）
const STAGE_ORDER = [
  'extract', 'analyze', 'annotate', 'edit',
  'audio_postprocess', 'synthesize', 'quality',
] as const

function stageLabel(stage: string): string {
  const map: Record<string, string> = {
    extract: t('pipeline.stages.extract'),
    analyze: t('pipeline.stages.analyze'),
    annotate: t('pipeline.stages.annotate'),
    edit: t('pipeline.stages.edit'),
    audio_postprocess: t('pipeline.stages.audio_postprocess'),
    synthesize: t('pipeline.stages.synthesize'),
    quality: t('pipeline.stages.quality'),
  }
  return map[stage] || stage
}

// 后端 current_stage 取值：'pending' / 阶段名（extract|analyze|...）/ 'completed'
function currentStageIndex(stage?: string): number {
  if (!stage || stage === 'pending') return -1
  if (stage === 'completed') return STAGE_ORDER.length // 全部完成
  return STAGE_ORDER.indexOf(stage as any)
}

function stageProgress(project: any): number {
  // 后端 progress 为 0-100 浮点；归一化到 0-1
  if (typeof project.progress === 'number') {
    const p = project.progress > 1 ? project.progress / 100 : project.progress
    return Math.max(0, Math.min(1, p))
  }
  const idx = currentStageIndex(project.current_stage)
  if (idx < 0) return 0
  if (idx >= STAGE_ORDER.length) return 1
  return (idx + 1) / STAGE_ORDER.length
}

onMounted(() => store.loadProjects())

const filteredProjects = computed(() => {
  const q = searchQuery.value.toLowerCase()
  const list = Array.isArray(store.projects) ? store.projects : []
  if (!q) return list
  return list.filter(
    (p) =>
      (p.title || '').toLowerCase().includes(q) ||
      (p.author || '').toLowerCase().includes(q) ||
      (p.genre || '').toLowerCase().includes(q),
  )
})

function openDetail(id: number) {
  router.push(`/projects/${id}`)
}

function openAutoRun(id: number) {
  router.push(`/projects/${id}/auto-run`)
}

function exportAudio(id: number) {
  router.push(`/projects/${id}/export`)
}

function openQuality(id: number) {
  router.push(`/projects/${id}/quality`)
}

function openCharacters(id: number) {
  router.push(`/projects/${id}/characters`)
}

function openTranslation(id: number) {
  router.push(`/projects/${id}/translation`)
}
</script>

<template>
  <div class="page-container project-management">
    <header class="page-header">
      <div>
        <h1>{{ t('project_mgmt.title') }}</h1>
        <p class="page-subtitle">{{ t('project_mgmt.subtitle') }}</p>
      </div>
    </header>

    <div class="search-bar section">
      <Icon icon="mdi:magnify" width="18" height="18" class="search-icon" />
      <input
        v-model="searchQuery"
        type="text"
        :placeholder="t('projects.search_placeholder')"
        class="form-control search-input"
      />
    </div>

    <p class="manage-hint text-muted text-sm" style="margin: 0 0 16px;">{{ t('project_mgmt.manage_hint') }}</p>

    <div v-if="store.loading" class="loading-section">
      <div class="spinner"></div>
      <p>{{ t('projects.loading') }}</p>
    </div>
    <div v-else-if="store.error" class="alert alert-error">
      {{ t('common.error') }}: {{ store.error }}
    </div>
    <div v-else-if="filteredProjects.length === 0" class="empty-state">
      {{ searchQuery ? t('projects.no_results') : t('projects.empty_state') }}
    </div>

    <div v-else class="mgmt-list">
      <div
        v-for="project in filteredProjects"
        :key="project.id"
        class="card card-hover mgmt-card"
        @click="openDetail(project.id)"
      >
        <div class="mgmt-card-header">
          <div class="mgmt-title">
            <h3 class="card-title">{{ project.title || t('projects.unnamed_project') }}</h3>
            <span v-if="project.author" class="meta">{{ project.author }}</span>
            <span v-if="project.genre" class="badge badge-muted">{{ project.genre }}</span>
          </div>
          <span class="badge" :class="project.status === 'completed' ? 'badge-success' : project.status === 'running' ? 'badge-info' : 'badge-muted'">
            {{ project.status || 'draft' }}
          </span>
        </div>

        <!-- 7 阶段流程状态 -->
        <div class="stage-strip">
          <div
            v-for="(stage, si) in STAGE_ORDER"
            :key="stage"
            class="stage-node"
            :class="{
              done: currentStageIndex(project.current_stage) > si,
              active: currentStageIndex(project.current_stage) === si,
            }"
            :title="stageLabel(stage)"
          >
            <span class="stage-node-dot">
              <Icon v-if="currentStageIndex(project.current_stage) > si" icon="mdi:check" width="12" height="12" />
              <span v-else-if="currentStageIndex(project.current_stage) === si" class="stage-node-pulse"></span>
            </span>
            <span class="stage-node-label">{{ stageLabel(stage) }}</span>
          </div>
        </div>

        <div class="stage-progress-bar">
          <div class="stage-progress-fill" :style="{ width: `${Math.round(stageProgress(project) * 100)}%` }"></div>
        </div>
        <div class="stage-progress-meta">
          <span class="text-sm text-muted">{{ t('project_mgmt.stage_progress') }}:</span>
          <span class="stage-current">{{ project.current_stage ? stageLabel(project.current_stage) : t('projects.not_started') }}</span>
          <span class="stage-percent">{{ Math.round(stageProgress(project) * 100) }}%</span>
        </div>

        <!-- 管理操作 -->
        <div class="mgmt-actions">
          <button class="btn btn-ghost btn-sm touch-target-sm" @click.stop="openDetail(project.id)">
            <Icon icon="mdi:open-in-new" width="16" height="16" />
            <span>{{ t('project_mgmt.open_detail') }}</span>
          </button>
          <button class="btn btn-primary btn-sm touch-target-sm" @click.stop="openAutoRun(project.id)">
            <Icon icon="mdi:play-circle-outline" width="16" height="16" />
            <span>{{ t('project_mgmt.auto_run') }}</span>
          </button>
          <button class="btn btn-outline btn-sm touch-target-sm" @click.stop="exportAudio(project.id)">
            <Icon icon="mdi:download" width="16" height="16" />
            <span>{{ t('project_mgmt.export_audio') }}</span>
          </button>
          <button class="btn btn-ghost btn-sm touch-target-sm" @click.stop="openQuality(project.id)">
            <Icon icon="mdi:chart-bar" width="16" height="16" />
            <span>{{ t('project_mgmt.quality_report') }}</span>
          </button>
          <button class="btn btn-ghost btn-sm touch-target-sm" @click.stop="openCharacters(project.id)">
            <Icon icon="mdi:account-group" width="16" height="16" />
            <span>{{ t('project_detail.characters') }}</span>
          </button>
          <button class="btn btn-ghost btn-sm touch-target-sm" @click.stop="openTranslation(project.id)">
            <Icon icon="mdi:translate" width="16" height="16" />
            <span>{{ t('translation.title') }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.project-management {
  max-width: 1100px;
}

.search-bar {
  position: relative;
}
.search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-muted);
  pointer-events: none;
}
.search-input {
  padding-left: 40px !important;
}

.loading-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 48px 24px;
  color: var(--color-text-secondary);
  text-align: center;
}

.mgmt-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.mgmt-card {
  cursor: pointer;
  padding: 20px;
}

.mgmt-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}
.mgmt-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.mgmt-title .card-title {
  margin: 0;
  font-size: 18px;
}

/* 7 阶段节点条 */
.stage-strip {
  display: flex;
  align-items: center;
  gap: 0;
  margin-bottom: 12px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.stage-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  flex: 1;
  min-width: 64px;
  position: relative;
}
.stage-node:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 11px;
  left: 50%;
  width: 100%;
  height: 2px;
  background: var(--color-border);
  z-index: 0;
}
.stage-node.done:not(:last-child)::after {
  background: var(--color-success);
}
.stage-node-dot {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--color-border);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  z-index: 1;
}
.stage-node.done .stage-node-dot {
  background: var(--color-success);
}
.stage-node.active .stage-node-dot {
  background: var(--color-primary);
}
.stage-node-pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #fff;
  animation: pulse 1.2s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
.stage-node-label {
  font-size: 10px;
  color: var(--color-text-muted);
  text-align: center;
  white-space: nowrap;
}
.stage-node.done .stage-node-label,
.stage-node.active .stage-node-label {
  color: var(--color-text);
  font-weight: 500;
}

.stage-progress-bar {
  height: 6px;
  background: var(--color-border);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 6px;
}
.stage-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary), var(--color-success));
  border-radius: 3px;
  transition: width 0.3s ease;
}
.stage-progress-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}
.stage-current {
  font-weight: 500;
  color: var(--color-primary);
}
.stage-percent {
  font-variant-numeric: tabular-nums;
  color: var(--color-text-muted);
}

.mgmt-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  border-top: 1px solid var(--color-border);
  padding-top: 12px;
}
</style>