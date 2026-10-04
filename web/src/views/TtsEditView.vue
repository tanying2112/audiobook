<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '../i18n'
import { useChapterStore } from '../stores/chapters'
import { useProjectStore } from '../stores/projects'
import { updateParagraph } from '../api'
import type { Paragraph } from '../types'
import ParagraphEditor from '../components/ParagraphEditor.vue'
import { Icon } from '@iconify/vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const chapterStore = useChapterStore()
const projectStore = useProjectStore()

const projectId = Number(route.params.id)

const searchText = ref('')
const showOnlyUnedited = ref(false)
const currentChapter = ref<number | null>(null)
const editingParagraph = ref<Paragraph | null>(null)

const paragraphs = computed(() => chapterStore.paragraphs || [])

const filteredParagraphs = computed(() => {
  let result = paragraphs.value
  if (currentChapter.value) result = result.filter(p => p.chapter_id === currentChapter.value)
  if (searchText.value) {
    const q = searchText.value.toLowerCase()
    result = result.filter(p => p.text.toLowerCase().includes(q) || (p.edited_text && p.edited_text.toLowerCase().includes(q)))
  }
  if (showOnlyUnedited.value) result = result.filter(p => p.text !== (p.edited_text || ''))
  return result
})

const chapters = computed(() => chapterStore.chapters || [])

async function loadData() {
  await projectStore.loadProject(projectId)
  await chapterStore.loadChapters(projectId)
  if (chapters.value.length > 0 && !currentChapter.value) {
    currentChapter.value = chapters.value[0].id
    await chapterStore.loadParagraphs(projectId, currentChapter.value)
  }
}

onMounted(loadData)

async function handleChapterChange(chapterId: number) {
  currentChapter.value = chapterId
  await chapterStore.loadParagraphs(projectId, chapterId)
}

async function handleSave(paragraphId: number, payload: Partial<Paragraph>) {
  if (!currentChapter.value) return
  try {
    await updateParagraph(projectId, currentChapter.value, paragraphId, payload)
    await chapterStore.loadParagraphs(projectId, currentChapter.value)
    editingParagraph.value = null
  } catch (e: any) {
    alert(t('common.save_failed') + (e.message || e))
  }
}

function handleClose() { editingParagraph.value = null }
function goBack() { router.push('/projects/' + projectId + '/overview') }
function openEditor(para: Paragraph) { editingParagraph.value = para }

function getStatusBadgeClass(status?: string): string {
  const map: Record<string, string> = { quality_checked: 'badge-success', edited: 'badge-info', annotated: 'badge-warning', pending: 'badge-muted' }
  const key = status?.toLowerCase()
  return key && map[key] ? map[key] : 'badge-muted'
}

function formatStatus(status?: string): string {
  const map: Record<string, string> = { quality_checked: '质检通过', edited: '已编辑', annotated: '已标注', pending: '待处理' }
  const key = status?.toLowerCase()
  return key && map[key] ? map[key] : (status || '未知')
}

function hasEdits(para: Paragraph): boolean {
  return para.text !== (para.edited_text || '')
}
</script>

<template>
  <div class="page-container tts-edit-view">
    <header class="page-header">
      <button class="btn btn-ghost touch-target" :aria-label="t('common.back')" @click="goBack">
        <Icon icon="mdi:arrow-left" width="18" height="18" />
        <span class="hidden-mobile">{{ t('common.back') }}</span>
      </button>
      <div class="header-text">
        <h1>{{ t('project_detail.edit_for_tts') }}</h1>
        <p class="page-subtitle">{{ t('tts_edit.subtitle') }}</p>
      </div>
    </header>

    <div v-if="chapterStore.loading" class="loading-state">
      <div class="spinner"></div>
      <span>{{ t('common.loading') }}</span>
    </div>

    <div v-else>
      <!-- Filter Bar -->
      <div class="card card-hover section filter-bar">
        <div class="filter-row">
          <div class="filter-col">
            <label class="form-label">{{ t('tts_edit.chapter') }}</label>
            <el-select v-model="currentChapter" :placeholder="t('tts_edit.select_chapter')" class="w-full" :aria-label="t('tts_edit.chapter')" @change="handleChapterChange">
              <el-option v-for="ch in chapters" :key="ch.id" :label="ch.title || t('chapter_timeline.chapter_fallback', { id: ch.id })" :value="ch.id" />
            </el-select>
          </div>
          <div class="filter-col">
            <label class="form-label">{{ t('tts_edit.search') }}</label>
            <el-input v-model="searchText" :placeholder="t('tts_edit.search_placeholder')" :aria-label="t('tts_edit.search')" clearable size="default">
              <template #prefix>
                <Icon icon="mdi:magnify" width="18" height="18" class="text-secondary" />
              </template>
            </el-input>
          </div>
          <div class="flex items-center gap-2">
            <el-checkbox v-model="showOnlyUnedited" :label="t('tts_edit.only_unedited')" />
          </div>
          <div class="flex items-center gap-4 filter-stats">
            <span>{{ t('tts_edit.total_paragraphs', { count: paragraphs.length }) }}</span>
            <span class="text-info">{{ t('tts_edit.edited_count', { count: paragraphs.filter(hasEdits).length }) }}</span>
            <span class="text-warning">{{ t('tts_edit.pending_count', { count: paragraphs.filter(p => !hasEdits(p)).length }) }}</span>
          </div>
        </div>
      </div>

      <!-- Paragraph List -->
      <div class="card card-hover section">
        <h2 class="card-title mb-4">{{ t('tts_edit.paragraph_list') }}</h2>

        <div v-if="filteredParagraphs.length === 0" class="empty-state">
          <Icon icon="mdi:file-document-outline" width="48" height="48" class="icon-faded" />
          <p>{{ t('tts_edit.no_paragraphs') }}</p>
        </div>

        <div v-else class="paragraph-list">
          <div v-for="para in filteredParagraphs" :key="para.id" class="paragraph-row" :class="{ 'has-edits': hasEdits(para) }">
            <div class="para-index">#{{ para.index }}</div>
            <div class="para-content">
              <div class="para-text" :title="para.text">{{ para.text }}</div>
              <div v-if="para.edited_text" class="para-text para-edited" :title="para.edited_text">
                {{ t('tts_edit.edited_prefix') }}{{ para.edited_text }}
              </div>
              <div v-else class="para-text para-no-edit">{{ t('tts_edit.not_edited') }}</div>
            </div>
            <div class="meta-col">
              <span :class="getStatusBadgeClass(para.status)">{{ formatStatus(para.status) }}</span>
              <span class="text-xs text-secondary" v-if="para.speaker_canonical_name">{{ para.speaker_canonical_name }}</span>
              <span class="text-xs text-secondary" v-if="para.emotion">{{ para.emotion }} ({{ para.emotion_intensity }})</span>
            </div>
            <div class="para-actions">
              <el-button size="small" type="primary" :aria-label="t('tts_edit.edit')" :icon="hasEdits(para) ? 'mdi:file-document-edit' : 'mdi:file-document-edit-outline'" @click="openEditor(para)">
                {{ t('tts_edit.edit') }}
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- Pagination -->
      <div v-if="filteredParagraphs.length > 20" class="mt-4 flex justify-center">
        <el-pagination :page-size="20" :total="filteredParagraphs.length" layout="prev, pager, next" background />
      </div>
    </div>

    <ParagraphEditor v-if="editingParagraph" class="section" :paragraph="editingParagraph" :project-id="projectId" :chapter-id="currentChapter || 0" @save="handleSave" @close="handleClose" />
  </div>
</template>

<style scoped>
.tts-edit-view { max-width: 1200px; }
.header-text { flex: 1; min-width: 0; }
.filter-bar { padding: 16px; }
.filter-row { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 16px; }
.filter-col { flex: 1; min-width: 200px; }
.filter-stats { font-size: 14px; color: var(--color-text-secondary); }
.text-xs { font-size: 12px; }
.text-info { color: var(--color-info); }
.justify-center { justify-content: center; }
.icon-faded { opacity: 0.4; }

.para-text {
  font-size: 13px; white-space: pre-wrap; word-break: break-word;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.para-no-edit { color: var(--color-text-muted); font-style: italic; font-weight: 400; }
.para-edited { color: var(--color-primary); font-weight: 500; }

.paragraph-list { max-height: 60vh; overflow-y: auto; }
.paragraph-row {
  display: flex; align-items: center; gap: 16px; padding: 16px;
  border-bottom: 1px solid var(--color-border); transition: background-color 0.15s;
}
.paragraph-row:last-child { border-bottom: none; }
.paragraph-row:hover { background-color: var(--color-surface-raised); }

.para-index {
  flex-shrink: 0; width: 48px; font-size: 13px; color: var(--color-text-secondary); font-variant-numeric: tabular-nums;
}
.para-content { flex: 1; min-width: 0; }
.meta-col {
  flex-shrink: 0; display: flex; flex-direction: column; align-items: flex-end; gap: 4px;
  min-width: 100px; font-size: 11px; text-align: right;
}
.para-actions { flex-shrink: 0; }
.has-edits { background-color: var(--color-success-soft); }

@media (max-width: 600px) {
  .filter-col { min-width: 0; width: 100%; }
  .paragraph-row { flex-wrap: wrap; }
  .meta-col { min-width: 0; width: 100%; align-items: flex-start; text-align: left; }
}
</style>
