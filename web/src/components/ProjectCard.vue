<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { useI18n } from '../i18n'
import type { Project } from '../types'

const { t, formatRelativeTime } = useI18n()

const props = defineProps<{
  project: Project
  editing: boolean
  draftTitle: string
}>()

const emit = defineEmits<{
  (e: 'open', id: number): void
  (e: 'delete', id: number, title: string): void
  (e: 'edit-title', id: number, title: string): void
  (e: 'save-edit', id: number): void
  (e: 'cancel-edit'): void
  (e: 'update:draft', val: string): void
  (e: 'export', id: number): void
  (e: 'auto-run', id: number): void
  (e: 'characters', id: number): void
  (e: 'quality', id: number): void
  (e: 'translation', id: number): void
}>()

// ── 7 阶段 ──────────────────────────────────────────────────
const PIPELINE_STAGES = [
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

function currentStageIndex(stage?: string): number {
  if (!stage || stage === 'pending') return -1
  if (stage === 'completed') return PIPELINE_STAGES.length
  return PIPELINE_STAGES.indexOf(stage as any)
}

function progressRatio(project: { progress?: number }): number {
  const p = project.progress ?? 0
  const ratio = p > 1 ? p / 100 : p
  return Math.max(0, Math.min(1, ratio))
}

// ── 标签颜色 ─────────────────────────────────────────────────
function genreColor(genre?: string): string {
  if (!genre) return 'secondary'
  if (genre.includes('古典') || genre.includes('历史')) return 'warning'
  if (genre.includes('科幻') || genre.includes('奇幻')) return 'primary'
  if (genre.includes('悬疑')) return 'danger'
  if (genre.includes('言情') || genre.includes('青春')) return 'success'
  return 'info'
}

function languageLabel(lang?: string): string {
  const map: Record<string, string> = { zh: '中文', en: 'English', ja: '日本語' }
  return map[lang || ''] || lang || ''
}

function difficultyLabel(d?: string): string {
  if (!d) return ''
  const map: Record<string, string> = { easy: '初级', medium: '中级', hard: '高级', advanced: '高级' }
  return map[d] || d
}

function difficultyColor(d?: string): string {
  if (d === 'easy') return 'success'
  if (d === 'medium') return 'warning'
  if (d === 'hard' || d === 'advanced') return 'danger'
  return 'secondary'
}
</script>

<template>
  <div class="card project-card" @click="emit('open', project.id)">
    <div class="card-body">
      <!-- 编辑标题模式 -->
      <template v-if="editing">
        <input
          :value="draftTitle"
          class="form-control"
          :placeholder="t('projects.enter_project_name')"
          @click.stop
          @input="emit('update:draft', ($event.target as HTMLInputElement).value)"
          @keyup.enter="emit('save-edit', project.id)"
          @keyup.esc="emit('cancel-edit')"
        />
        <div class="edit-actions">
          <button class="btn btn-primary btn-sm touch-target-sm" :title="t('common.save')" @click.stop="emit('save-edit', project.id)">
            <Icon icon="mdi:check" width="18" height="18" />
          </button>
          <button class="btn btn-ghost btn-sm touch-target-sm" :title="t('common.cancel')" @click.stop="emit('cancel-edit')">
            <Icon icon="mdi:close" width="18" height="18" />
          </button>
        </div>
      </template>

      <!-- 正常展示模式 -->
      <template v-else>
        <h3 class="card-title project-card__title">
          {{ project.title || t('projects.unnamed_project') }}
        </h3>
        <p v-if="project.description" class="project-card__desc">{{ project.description }}</p>

        <!-- 标签行: 作者 / 类型 / 语言 / 难度 -->
        <div class="project-card__tags">
          <span v-if="project.author" class="tag tag--secondary">
            <Icon icon="mdi:account-outline" width="12" height="12" />
            {{ project.author }}
          </span>
          <span v-if="project.genre" class="tag" :class="`tag--${genreColor(project.genre)}`">
            {{ project.genre }}
          </span>
          <span v-if="project.language" class="tag tag--secondary">
            {{ languageLabel(project.language) }}
          </span>
          <span v-if="project.difficulty" class="tag" :class="`tag--${difficultyColor(project.difficulty)}`">
            {{ difficultyLabel(project.difficulty) }}
          </span>
        </div>

        <!-- 更新时间 -->
        <span v-if="project.updated_at" class="project-card__meta">
          <Icon icon="mdi:clock-outline" width="12" height="12" />
          {{ formatRelativeTime(project.updated_at) }}
        </span>

        <!-- 7 阶段进度 -->
        <div class="project-card__progress">
          <div class="progress-steps">
            <span
              v-for="(stage, si) in PIPELINE_STAGES"
              :key="stage"
              class="progress-dot"
              :class="{
                done: currentStageIndex(project.current_stage) > si,
                active: currentStageIndex(project.current_stage) === si,
              }"
              :title="stageLabel(stage)"
            ></span>
          </div>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: `${Math.round(progressRatio(project) * 100)}%` }"></div>
          </div>
          <div class="progress-meta">
            <span class="progress-stage-label">
              {{ project.current_stage ? stageLabel(project.current_stage) : t('projects.not_started') }}
            </span>
            <span class="progress-pct">{{ Math.round(progressRatio(project) * 100) }}%</span>
          </div>
        </div>
      </template>
    </div>

    <!-- 操作按钮 -->
    <div class="card-actions">
      <button class="btn btn-ghost btn-sm touch-target-sm" :title="t('projects.delete_tooltip')" aria-label="Delete project"
        @click.stop="emit('delete', project.id, project.title || '')">
        <Icon icon="mdi:delete-outline" width="18" height="18" />
      </button>
      <button v-if="!editing" class="btn btn-ghost btn-sm touch-target-sm" :title="t('common.edit')" aria-label="Edit project title"
        @click.stop="emit('edit-title', project.id, project.title || '')">
        <Icon icon="mdi:pencil-outline" width="18" height="18" />
      </button>
      <button class="btn btn-ghost btn-sm touch-target-sm" :title="t('common.export')" aria-label="Export project"
        @click.stop="emit('export', project.id)">
        <Icon icon="mdi:export" width="18" height="18" />
      </button>
    </div>

    <!-- 快捷入口 -->
    <div class="card-quicklinks">
      <button class="btn btn-primary btn-sm touch-target-sm" @click.stop="emit('auto-run', project.id)">
        <Icon icon="mdi:play-circle-outline" width="16" height="16" />
        <span>{{ t('auto_run.title') }}</span>
      </button>
      <button class="btn btn-ghost btn-sm touch-target-sm" @click.stop="emit('characters', project.id)">
        <Icon icon="mdi:account-group" width="16" height="16" />
        <span>{{ t('project_detail.characters') }}</span>
      </button>
      <button class="btn btn-ghost btn-sm touch-target-sm" @click.stop="emit('quality', project.id)">
        <Icon icon="mdi:chart-bar" width="16" height="16" />
        <span>{{ t('project_detail.quality_report') }}</span>
      </button>
      <button class="btn btn-ghost btn-sm touch-target-sm" @click.stop="emit('translation', project.id)">
        <Icon icon="mdi:translate" width="16" height="16" />
        <span>{{ t('translation.title') }}</span>
      </button>
      <button class="btn btn-outline btn-sm touch-target-sm" @click.stop="emit('export', project.id)">
        <Icon icon="mdi:download" width="16" height="16" />
        <span>{{ t('projects.export_audio') }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.project-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  cursor: pointer;
  transition: box-shadow var(--transition), transform var(--transition-fast);
}
.project-card:hover { box-shadow: var(--shadow-md); transform: translateY(-2px); }
.project-card:active { transform: translateY(0); }
.project-card__title { font-size: 17px; margin: 0; }
.project-card__desc {
  margin: 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.project-card__meta {
  display: inline-flex; align-items: center; gap: 4px;
  color: var(--color-text-muted); font-size: 12px;
}
.project-card__tags { display: flex; flex-wrap: wrap; gap: 6px; }
.tag {
  display: inline-flex; align-items: center; gap: 3px; padding: 2px 8px;
  border-radius: var(--radius-full); font-size: 12px; font-weight: 500;
  line-height: 1.4; white-space: nowrap;
}
.tag--secondary { background: var(--color-bg-tertiary); color: var(--color-text-secondary); }
.tag--primary { background: var(--color-primary-soft); color: var(--color-primary); }
.tag--success { background: var(--color-success-soft); color: var(--color-success); }
.tag--warning { background: var(--color-warning-soft); color: var(--color-warning); }
.tag--danger { background: var(--color-danger-soft); color: var(--color-danger); }
.tag--info { background: var(--color-info-soft); color: var(--color-info); }

.project-card__progress { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
.progress-steps { display: flex; gap: 4px; }
.progress-dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--color-border);
  transition: background var(--transition-fast), transform var(--transition-fast);
}
.progress-dot.done { background: var(--color-success); }
.progress-dot.active {
  background: var(--color-primary); transform: scale(1.25);
  box-shadow: 0 0 0 3px var(--color-primary-alpha);
}
.progress-bar {
  height: 4px; background: var(--color-bg-tertiary);
  border-radius: var(--radius-full); overflow: hidden;
}
.progress-fill {
  height: 100%; border-radius: var(--radius-full);
  background: linear-gradient(90deg, var(--color-primary), var(--color-success));
  transition: width 0.4s ease;
}
.progress-meta { display: flex; justify-content: space-between; align-items: center; font-size: 12px; }
.progress-stage-label { color: var(--color-text-secondary); }
.progress-pct { font-weight: 600; color: var(--color-primary); font-variant-numeric: tabular-nums; }

.edit-actions { display: flex; gap: 8px; margin-top: 8px; }
.card-actions { margin-top: 12px; display: flex; justify-content: flex-end; }
.card-quicklinks { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-start; }
</style>
