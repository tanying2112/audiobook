<template>
  <div class="chapter-list-panel" :class="{ 'fsm-mode': fsmMode }">
    <div class="panel-header">
      <h3>{{ t('agentChat.fsm.chapters') }}</h3>
      <el-tooltip :content="t('agentChat.fsm.chapter_list_tooltip')" placement="bottom">
        <el-icon class="refresh-btn" @click="refreshChapters" :class="{ spinning: fsmLoading }">
          <Refresh />
        </el-icon>
      </el-tooltip>
    </div>

    <div class="chapter-list" ref="listRef">
      <div
        v-for="chapter in fsmChapters"
        :key="chapter.id"
        class="chapter-item"
        :class="[
          chapter.status,
          { active: currentChapter?.id === chapter.id, selected: currentChapter?.id === chapter.id },
        ]"
        @click="selectChapter(chapter)"
      >
        <div class="chapter-main">
          <div class="chapter-status-icon">
            <component :is="getStatusIcon(chapter.status)" class="status-icon" />
          </div>
          <div class="chapter-info">
            <div class="chapter-title">{{ chapter.title || t('agentChat.fsm.chapter_default', { index: chapter.index }) }}</div>
            <div class="chapter-meta">
              <span class="chapter-index">{{ t('agentChat.fsm.chapter_index', { index: chapter.index }) }}</span>
              <span v-if="chapter.current_stage" class="current-stage">
                {{ getStageLabel(chapter.current_stage) }}
              </span>
            </div>
          </div>
        </div>
        <div class="chapter-progress" v-if="chapter.status === 'current' || chapter.status === 'awaiting_confirm'">
          <el-progress
            :percentage="Math.round(chapter.progress * 100)"
            :stroke-width="4"
            :show-text="false"
            :status="chapter.status === 'awaiting_confirm' ? 'warning' : ''"
          />
        </div>
        <div class="chapter-actions" v-if="chapter.status === 'awaiting_confirm'">
          <el-tag size="small" type="warning" effect="plain">{{ t('agentChat.fsm.awaiting_confirm') }}</el-tag>
        </div>
      </div>

      <div v-if="fsmChapters.length === 0" class="empty-state">
        <el-icon><Document /></el-icon>
        <p>{{ t('agentChat.fsm.no_chapters') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from '@/i18n'
import { ElProgress, ElTag, ElTooltip } from 'element-plus'
import { Refresh, Document, CircleCheck, CircleClose, Clock, Warning } from '@element-plus/icons-vue'

interface FsmChapter {
  id: number
  index: number
  title: string
  status: string
  current_stage?: string
  progress: number
}

interface ChapterListProps {
  fsmChapters: FsmChapter[]
  currentChapter: { id: number } | null
  fsmLoading: boolean
  fsmMode: boolean
}

const props = defineProps<ChapterListProps>()

const emit = defineEmits<{
  'chapter-select': [chapter: FsmChapter]
  'refresh': []
}>()

const { t } = useI18n()
const listRef = ref<HTMLElement>()

const getStatusIcon = (status: string) => {
  switch (status) {
    case 'completed': return CircleCheck
    case 'current': return CircleClose
    case 'awaiting_confirm': return Warning
    case 'failed': return CircleClose
    default: return Clock
  }
}

const getStageLabel = (stage: string) => {
  const labels: Record<string, string> = {
    extracting: t('pipeline.stages.extract'),
    analyzing: t('pipeline.stages.analyze'),
    annotating: t('pipeline.stages.annotate'),
    pending_human_confirm: t('agentChat.fsm.pending_confirm'),
    audio_postprocessing: t('pipeline.stages.audio_postprocess'),
    synthesizing: t('pipeline.stages.synthesize'),
    quality_check: t('pipeline.stages.quality'),
    exporting: t('pipeline.stages.export'),
  }
  return labels[stage] || stage
}

const selectChapter = (chapter: typeof props.fsmChapters[0]) => {
  emit('chapter-select', chapter)
}

const refreshChapters = () => {
  emit('refresh')
}

// Auto-scroll to current chapter
watch(() => props.currentChapter, (chapter) => {
  if (chapter && listRef.value) {
    const item = listRef.value.querySelector(`.chapter-item.active`)
    item?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }
}, { immediate: true })
</script>

<style scoped>
.chapter-list-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-secondary, #fafafa);
  border-right: 1px solid var(--border-color, #e8e8e8);
  overflow: hidden;
}

.chapter-list-panel.fsm-mode {
  min-width: 280px;
  max-width: 350px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color, #e8e8e8);
  background: var(--bg-primary, #fff);
}

.panel-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #333);
}

.refresh-btn {
  cursor: pointer;
  color: var(--text-secondary, #999);
  transition: color 0.2s;
}
.refresh-btn:hover {
  color: var(--color-primary, #409eff);
}
.refresh-btn.spinning {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.chapter-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.chapter-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
  border: 1px solid transparent;
}
.chapter-item:hover {
  background: var(--bg-tertiary, #f0f0f0);
}
.chapter-item.active {
  background: var(--color-primary-light, #e6f7ff);
  border-color: var(--color-primary, #409eff);
}

.chapter-status-icon {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.status-icon {
  width: 18px;
  height: 18px;
}
.chapter-item.completed .status-icon { color: var(--color-success, #67c23a); }
.chapter-item.current .status-icon { color: var(--color-primary, #409eff); animation: pulse 1.5s infinite; }
.chapter-item.awaiting_confirm .status-icon { color: var(--color-warning, #e6a23c); }
.chapter-item.failed .status-icon { color: var(--color-danger, #f56c6c); }
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.chapter-info {
  flex: 1;
  min-width: 0;
}
.chapter-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary, #333);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.chapter-meta {
  display: flex;
  gap: 8px;
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-tertiary, #bbb);
}
.current-stage {
  color: var(--color-primary, #409eff);
  font-weight: 500;
}

.chapter-progress {
  flex-shrink: 0;
  width: 80px;
  height: 6px;
}

.chapter-actions {
  flex-shrink: 0;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-tertiary, #bbb);
  padding: 24px;
  text-align: center;
}
.empty-state .el-icon {
  font-size: 32px;
  margin-bottom: 8px;
  opacity: 0.5;
}
</style>