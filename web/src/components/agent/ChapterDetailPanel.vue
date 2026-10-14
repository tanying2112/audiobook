<template>
  <div class="chapter-detail-panel" :class="{ 'fsm-mode': fsmMode }">
    <div class="panel-header">
      <h3 v-if="currentChapter">
        {{ currentChapter.title || t('agentChat.fsm.chapter_default', { index: currentChapter.index }) }}
        <el-tag :type="getStatusType(currentChapter.status)" size="small" style="margin-left: 8px;">
          {{ getStatusLabel(currentChapter.status) }}
        </el-tag>
      </h3>
      <h3 v-else>{{ t('agentChat.fsm.select_chapter') }}</h3>
      <div class="header-actions" v-if="currentChapter">
        <el-button size="small" @click="copyOriginalText" :disabled="!chapterDetail?.original_text">
          <CopyDocument /><span style="margin-left: 4px;">{{ t('agentChat.fsm.copy_original') }}</span>
        </el-button>
        <el-button size="small" @click="copyEditedText" :disabled="!chapterDetail?.edited_text">
          <DocumentCopy /><span style="margin-left: 4px;">{{ t('agentChat.fsm.copy_edited') }}</span>
        </el-button>
      </div>
    </div>

    <div class="panel-content" v-if="currentChapter && chapterDetail">
      <el-tabs v-model="activeTab" class="detail-tabs">
        <el-tab-pane :label="t('agentChat.fsm.original_text')" name="original">
          <div class="text-content" v-html="formatText(chapterDetail.original_text)"></div>
        </el-tab-pane>
        <el-tab-pane :label="t('agentChat.fsm.edited_text')" name="edited">
          <div class="text-content" v-html="formatText(chapterDetail.edited_text || chapterDetail.original_text)"></div>
        </el-tab-pane>
        <el-tab-pane :label="t('agentChat.fsm.annotations')" name="annotations">
          <div class="annotations-list" v-if="chapterDetail.annotations?.length">
            <div class="annotations-container">
              <el-tag
                v-for="ann in chapterDetail.annotations"
                :key="ann.id"
                :type="getTypeColor(ann.type)"
                effect="plain"
                size="small"
                class="annotation-chip"
                @click="onAnnotationClick(ann)"
              >
                <component :is="getTypeIcon(ann.type)" class="chip-icon" />
                <span class="chip-label">{{ ann.label }}</span>
                <span class="chip-value">{{ ann.value }}</span>
                <span v-if="ann.confidence !== undefined" class="chip-confidence">{{ Math.round(ann.confidence * 100) }}%</span>
                <span class="chip-para">{{ t('agentChat.fsm.paragraph') }} {{ ann.paragraph_index + 1 }}</span>
              </el-tag>
            </div>
          </div>
          <div v-else class="empty-state">
            <el-icon><Edit /></el-icon>
            <p>{{ t('agentChat.fsm.no_annotations') }}</p>
          </div>
        </el-tab-pane>
        <el-tab-pane :label="t('agentChat.fsm.routing')" name="routing" v-if="chapterDetail.routing_decision">
          <div class="routing-card">
            <div class="routing-row">
              <span class="routing-label">{{ t('agentChat.fsm.engine') }}</span>
              <span class="routing-value">{{ chapterDetail.routing_decision.engine }}</span>
            </div>
            <div class="routing-row">
              <span class="routing-label">{{ t('agentChat.fsm.voice') }}</span>
              <span class="routing-value">{{ chapterDetail.routing_decision.voice }}</span>
            </div>
            <div class="routing-row">
              <span class="routing-label">{{ t('agentChat.fsm.confidence') }}</span>
              <el-progress
                :percentage="Math.round(chapterDetail.routing_decision.confidence * 100)"
                :stroke-width="8"
                :show-text="true"
                :status="getConfidenceStatus(chapterDetail.routing_decision.confidence)"
              />
            </div>
            <div class="routing-reason">
              <span class="routing-label">{{ t('agentChat.fsm.reason') }}</span>
              <p>{{ chapterDetail.routing_decision.reason }}</p>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <div v-else-if="currentChapter && !chapterDetail" class="loading-state">
      <el-icon class="loading-spinner"><Loading /></el-icon>
      <p>{{ t('agentChat.fsm.loading_detail') }}</p>
    </div>

    <div v-else class="empty-state">
      <el-icon><Document /></el-icon>
      <p>{{ t('agentChat.fsm.select_chapter_hint') }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from '@/i18n'
import { ElTabs, ElTabPane, ElButton, ElTag, ElProgress, ElMessage } from 'element-plus'
import { CopyDocument, DocumentCopy, Edit, Loading, User, Star, Mic, Timer, Microphone } from '@element-plus/icons-vue'

const props = defineProps<{
  currentChapter: {
    id: number
    index: number
    title: string
    status: string
  } | null
  chapterDetail: {
    original_text: string
    edited_text: string
    annotations: Array<{
      id: string
      type: 'character' | 'emotion' | 'voice' | 'pause' | 'sfx'
      label: string
      value: string
      confidence?: number
      paragraph_index: number
      offset_start?: number
      offset_end?: number
    }>
    routing_decision?: {
      engine: string
      voice: string
      reason: string
      confidence: number
    } | null
  } | null
  fsmMode: boolean
}>()

const emit = defineEmits<{
  'annotation-click': [annotation: { id: string; type: string; label: string; value: string }]
}>()

const { t } = useI18n()
const activeTab = ref<'original' | 'edited' | 'annotations' | 'routing'>('original')

const getStatusType = (status: string) => {
  switch (status) {
    case 'completed': return 'success'
    case 'current': return 'primary'
    case 'awaiting_confirm': return 'warning'
    case 'failed': return 'danger'
    default: return 'info'
  }
}

const getStatusLabel = (status: string) => {
  const labels: Record<string, string> = {
    completed: '已完成',
    current: '进行中',
    awaiting_confirm: '待确认',
    failed: '失败',
    pending: '待处理',
  }
  return labels[status] || status
}

const formatText = (text: string) => {
  if (!text) return ''
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>')
}

const copyOriginalText = () => {
  if (props.chapterDetail?.original_text) {
    navigator.clipboard.writeText(props.chapterDetail.original_text)
    ElMessage.success(t('agentChat.fsm.copied'))
  }
}

const copyEditedText = () => {
  if (props.chapterDetail?.edited_text) {
    navigator.clipboard.writeText(props.chapterDetail.edited_text)
    ElMessage.success(t('agentChat.fsm.copied'))
  }
}

const onAnnotationClick = (annotation: { id: string; type: string; label: string; value: string }) => {
  emit('annotation-click', annotation)
}

const getTypeColor = (type: string) => {
  switch (type) {
    case 'character': return 'primary'
    case 'emotion': return 'success'
    case 'voice': return 'warning'
    case 'pause': return 'info'
    case 'sfx': return 'danger'
    default: return 'info'
  }
}

const getTypeIcon = (type: string) => {
  switch (type) {
    case 'character': return User
    case 'emotion': return Star
    case 'voice': return Mic
    case 'pause': return Timer
    case 'sfx': return Microphone
    default: return Edit
  }
}

const getConfidenceStatus = (confidence: number) => {
  if (confidence > 0.8) return 'success'
  if (confidence > 0.5) return 'warning'
  return 'exception'
}
</script>

<style scoped>
.chapter-detail-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary, #fff);
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color, #e8e8e8);
  background: var(--bg-secondary, #fafafa);
}

.panel-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary, #333);
  display: flex;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 8px;
}
.header-actions .el-button {
  display: flex;
  align-items: center;
}

.panel-content {
  flex: 1;
  overflow: hidden;
}

.detail-tabs :deep(.el-tabs__content) {
  height: calc(100% - 48px);
  overflow-y: auto;
  padding: 16px;
}

.text-content {
  line-height: 1.8;
  font-size: 14px;
  color: var(--text-primary, #333);
  white-space: pre-wrap;
  word-break: break-word;
}
.text-content code {
  background: var(--bg-tertiary, #f0f0f0);
  padding: 2px 4px;
  border-radius: 4px;
  font-family: monospace;
}
.text-content strong { font-weight: 600; }
.text-content em { font-style: italic; }

.annotations-list {
  max-height: 100%;
  overflow-y: auto;
}

.annotations-container {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.annotation-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  transition: transform 0.15s;
}
.annotation-chip:hover {
  transform: translateY(-1px);
}
.chip-icon { font-size: 12px; }
.chip-label { font-weight: 500; }
.chip-value { color: var(--text-secondary, #999); }
.chip-confidence {
  font-size: 10px;
  color: var(--color-success, #67c23a);
}
.chip-para {
  font-size: 10px;
  color: var(--text-tertiary, #bbb);
}

.routing-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  background: var(--bg-secondary, #fafafa);
  border-radius: 8px;
  border: 1px solid var(--border-color, #e8e8e8);
}
.routing-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.routing-label {
  min-width: 80px;
  font-size: 13px;
  color: var(--text-secondary, #999);
}
.routing-value {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary, #333);
}
.routing-reason {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.routing-reason p {
  margin: 0;
  font-size: 13px;
  color: var(--text-primary, #333);
  line-height: 1.6;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  color: var(--text-tertiary, #bbb);
}
.loading-spinner {
  font-size: 32px;
  color: var(--color-primary, #409eff);
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  color: var(--text-tertiary, #bbb);
  padding: 24px;
  text-align: center;
}
.empty-state .el-icon {
  font-size: 48px;
  margin-bottom: 12px;
  opacity: 0.3;
}
</style>