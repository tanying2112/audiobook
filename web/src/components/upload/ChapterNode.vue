<template>
  <div class="chapter-node">
    <div
      class="node-header"
      :class="{ expanded, selected, match: hasMatch }"
      @click="toggleExpand"
    >
      <el-icon class="expand-icon" :class="{ rotated: expanded }">
        <ArrowRight />
      </el-icon>

      <el-checkbox
        :model-value="isSelected"
        @update:modelValue="onCheckboxChange"
        @change.stop
      />

      <div class="chapter-title-wrapper" @click.stop="toggleExpand">
        <span class="chapter-index">{{ t('upload.chapter') }} {{ chapter.index }}</span>
        <span class="chapter-title" :class="{ 'has-match': hasMatch }">
          <span v-if="hasMatch" class="highlight">{{ highlightedTitle }}</span>
          <span v-else>{{ chapter.title }}</span>
        </span>
        <el-tag :type="getStatusType(chapter.status)" size="small" class="status-tag">
          {{ getStatusLabel(chapter.status) }}
        </el-tag>
      </div>

      <div class="node-meta">
        <span class="para-count">{{ chapter.paragraph_count }} {{ t('upload.paragraphs_short') }}</span>
      </div>
    </div>

    <div class="node-children" v-show="expanded" style="overflow: hidden;">
      <transition name="slide">
        <div class="paragraphs-list" v-if="showParagraphs && chapter.id === selectedChapterId">
          <ParagraphNode
            v-for="para in chapterParagraphs"
            :key="para.id"
            :paragraph="para"
            :search-query="searchQuery"
          />
        </div>
      </transition>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { ElCheckbox, ElTag } from 'element-plus'
import { ArrowRight } from '@element-plus/icons-vue'
import ParagraphNode from './ParagraphNode.vue'

interface ChapterData {
  id: number
  index: number
  title: string
  raw_text: string
  paragraph_count: number
  status: string
  selected: boolean
}

const props = defineProps<{
  chapter: ChapterData
  selected: boolean
  searchQuery: string
}>()

const emit = defineEmits<{
  'toggle': [chapterId: number]
  'paragraph-select': [paragraph: { id: number; chapter_id: number; index: number; text: string }]
}>()

const { t } = useI18n()

const expanded = ref(false)
const isSelected = ref(props.selected)
const showParagraphs = ref(false)
const selectedChapterId = ref<number | null>(null)
const chapterParagraphs = ref<Array<{
  id: number
  chapter_id: number
  index: number
  text: string
  preview_text: string
  character: string | null
  emotion: string | null
}>>([])

const hasMatch = computed(() => {
  if (!props.searchQuery) return false
  const query = props.searchQuery.toLowerCase()
  return props.chapter.title.toLowerCase().includes(query) ||
         props.chapter.raw_text.toLowerCase().includes(query)
})

const highlightedTitle = computed(() => {
  if (!props.searchQuery) return props.chapter.title
  const query = props.searchQuery
  const regex = new RegExp(`(${query})`, 'gi')
  return props.chapter.title.replace(regex, '<mark>$1</mark>')
})

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
    completed: '完成',
    current: '进行中',
    awaiting_confirm: '待确认',
    failed: '失败',
    pending: '待处理',
  }
  return labels[status] || status
}

const toggleExpand = () => {
  expanded.value = !expanded.value
  if (expanded.value && !showParagraphs.value) {
    loadParagraphs()
  }
}

const loadParagraphs = async () => {
  // In a real implementation, this would fetch from the API
  // For now, we'll emit an event to load paragraphs
  // The parent can handle the actual loading
  showParagraphs.value = true
}

const onCheckboxChange = (value: string | number | boolean) => {
  isSelected.value = value === true
  emit('toggle', props.chapter.id)
}

watch(() => props.selected, (val) => {
  isSelected.value = val
})
</script>

<style scoped>
.chapter-node {
  border: 1px solid transparent;
  border-radius: 6px;
  margin: 2px 0;
  transition: background 0.15s;
}
.chapter-node:hover {
  background: var(--bg-tertiary, #f5f5f5);
}
.chapter-node.selected {
  background: var(--color-primary-light, #e6f7ff);
  border-color: var(--color-primary, #409eff);
}

.node-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
}

.expand-icon {
  font-size: 12px;
  color: var(--text-tertiary, #bbb);
  transition: transform 0.2s;
  flex-shrink: 0;
  width: 20px;
  text-align: center;
}
.expand-icon.rotated {
  transform: rotate(90deg);
}

.chapter-title-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  cursor: pointer;
}

.chapter-index {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-primary, #409eff);
  background: var(--color-primary-light, #e6f7ff);
  padding: 1px 6px;
  border-radius: 4px;
  white-space: nowrap;
}

.chapter-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary, #333);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}
.chapter-title.has-match {
  color: var(--color-primary, #409eff);
}
.chapter-title mark {
  background: var(--color-warning-light, #fdf6ec);
  color: var(--color-warning, #e6a23c);
  padding: 0 2px;
  border-radius: 2px;
}

.status-tag {
  flex-shrink: 0;
}

.node-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-tertiary, #bbb);
  font-size: 11px;
}

.para-count {
  background: var(--bg-tertiary, #f0f0f0);
  padding: 1px 6px;
  border-radius: 4px;
}

.node-children {
  padding-left: 36px;
  border-left: 2px solid var(--border-color, #e8e8e8);
  margin-left: 10px;
}

.paragraphs-list {
  padding-top: 8px;
  animation: slideDown 0.2s ease-out;
}
@keyframes slideDown {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 600px) {
  .node-children {
    padding-left: 24px;
  }
}
</style>