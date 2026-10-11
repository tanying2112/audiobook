<template>
  <div class="chapter-tree" ref="treeRef">
    <div class="tree-header">
      <h3>{{ t('upload.chapters') }}</h3>
      <div class="header-actions">
        <el-button size="small" @click="toggleSelectAll" :disabled="extractionLoading">
          <Check v-if="allSelected" /><Minus v-else />
          <span>{{ allSelected ? t('upload.deselect_all') : t('upload.select_all') }}</span>
        </el-button>
        <el-button size="small" @click="refreshTree" :loading="extractionLoading" :disabled="extractionLoading">
          <Refresh />
        </el-button>
      </div>
    </div>

    <div class="tree-content" v-if="!extractionLoading">
      <ChapterNode
        v-for="chapter in filteredChapters"
        :key="chapter.id"
        :chapter="chapter"
        :selected="selectedChapterIds.includes(chapter.id)"
        :search-query="searchQuery"
        @toggle="toggleChapter"
      />

      <div v-if="filteredChapters.length === 0 && searchQuery" class="no-results">
        <el-icon><Search /></el-icon>
        <p>{{ t('upload.no_chapters_match') }}</p>
      </div>
    </div>

    <div v-else class="loading-state">
      <el-icon class="spin"><Loading /></el-icon>
      <p>{{ t('upload.loading_chapters') }}</p>
    </div>

    <div class="tree-footer" v-if="extractionResult">
      <span class="stats">
        {{ t('upload.selected_count', { count: selectedChapterIds.length, total: extractionResult.total_chapters }) }}
      </span>
      <span class="paragraphs">
        {{ t('upload.total_paragraphs', { count: extractionResult.total_paragraphs }) }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/i18n'
import { ElButton } from 'element-plus'
import { Refresh, Search, Check, Minus, Loading } from '@element-plus/icons-vue'
import ChapterNode from './ChapterNode.vue'

interface ChapterData {
  id: number
  index: number
  title: string
  raw_text: string
  paragraph_count: number
  status: string
  selected: boolean
}

interface ExtractionResult {
  chapters: ChapterData[]
  total_chapters: number
  total_paragraphs: number
}

const props = defineProps<{
  extractionResult: ExtractionResult | null
  selectedChapterIds: number[]
  extractionLoading: boolean
  extractionJobId: string | null
}>()

const emit = defineEmits<{
  'toggle': [chapterId: number]
  'refresh': []
  'select-all': []
}>()

const { t } = useI18n()
const searchQuery = ref('')

const filteredChapters = computed(() => {
  if (!props.extractionResult) return []
  const chapters = props.extractionResult.chapters
  if (!searchQuery.value) return chapters
  const query = searchQuery.value.toLowerCase()
  return chapters.filter(c =>
    c.title.toLowerCase().includes(query) ||
    c.raw_text.toLowerCase().includes(query)
  )
})

const allSelected = computed(() => {
  if (!props.extractionResult) return false
  return props.selectedChapterIds.length === props.extractionResult.chapters.length &&
         props.extractionResult.chapters.length > 0
})

const toggleChapter = (chapterId: number) => {
  emit('toggle', chapterId)
}

const toggleSelectAll = () => {
  emit('select-all')
}

const refreshTree = () => {
  emit('refresh')
}

watch(() => props.extractionJobId, (jobId) => {
  if (jobId) {
    emit('refresh')
  }
})
</script>

<style scoped>
.chapter-tree {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary, #fff);
  border: 1px solid var(--border-color, #e8e8e8);
  border-radius: 8px;
  overflow: hidden;
}

.tree-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color, #e8e8e8);
  background: var(--bg-secondary, #fafafa);
}

.tree-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #333);
}

.header-actions {
  display: flex;
  gap: 8px;
}

.tree-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  max-height: 400px;
}

.no-results, .loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px;
  color: var(--text-tertiary, #bbb);
  text-align: center;
}
.loading-state .spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.tree-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-top: 1px solid var(--border-color, #e8e8e8);
  background: var(--bg-secondary, #fafafa);
  font-size: 12px;
  color: var(--text-secondary, #999);
}

.stats, .paragraphs {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>