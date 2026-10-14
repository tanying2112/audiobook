<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '../../i18n'
import type { Chapter } from '../../types'

const props = defineProps<{
  chapters: Chapter[]
  projectId: number
}>()

const { t } = useI18n()

const emit = defineEmits<{
  navigate: [path: string]
}>()

const recentChapters = computed(() => {
  // Show the last 8 chapters sorted by index descending (most recent first)
  return [...props.chapters]
    .sort((a, b) => (b.index ?? 0) - (a.index ?? 0))
    .slice(0, 8)
})

function chapterStatusInfo(chapter: Chapter) {
  const stages = [
    chapter.extract_status,
    chapter.analyze_status,
    chapter.annotate_status,
    chapter.edit_status,
    chapter.synthesize_status,
    chapter.quality_status,
  ]
  const completed = stages.filter((s) => s === 'completed').length
  const total = stages.length
  const anyFailed = stages.some((s) => s === 'failed')
  const anyRunning = stages.some((s) => s === 'running')

  if (anyFailed) return { label: t('common.failed'), color: 'var(--color-danger)', bg: 'var(--color-danger-soft)' }
  if (anyRunning) return { label: t('common.running'), color: 'var(--color-primary)', bg: 'var(--color-primary-soft)' }
  if (completed === total) return { label: t('common.completed'), color: 'var(--color-success)', bg: 'var(--color-success-soft)' }
  if (completed > 0) return { label: `${completed}/${total}`, color: 'var(--color-warning)', bg: 'var(--color-warning-soft)' }
  return { label: t('common.pending'), color: 'var(--color-text-muted)', bg: 'var(--color-bg-tertiary)' }
}

function goToChapter(chapterId: number) {
  emit('navigate', `/projects/${props.projectId}/chapters/${chapterId}`)
}
</script>

<template>
  <div class="chapter-list">
    <div
      v-for="ch in recentChapters"
      :key="ch.id"
      class="chapter-row"
      @click="goToChapter(ch.id)"
      role="button"
      tabindex="0"
      :aria-label="`Chapter ${ch.index}: ${ch.title || t('common.chapter')} ${ch.index}`"
      @keydown.enter="goToChapter(ch.id)"
    >
      <div class="ch-index">{{ ch.index }}</div>
      <div class="ch-info">
        <span class="ch-title">{{ ch.title || `${t('common.chapter')} ${ch.index}` }}</span>
      </div>
      <span
        class="ch-badge"
        :style="{
          color: chapterStatusInfo(ch).color,
          background: chapterStatusInfo(ch).bg,
        }"
      >
        {{ chapterStatusInfo(ch).label }}
      </span>
    </div>

    <div v-if="chapters.length === 0" class="empty-state">
      {{ t('common.no_data') || 'No chapters yet' }}
    </div>
  </div>
</template>

<style scoped>
.chapter-list {
  display: flex;
  flex-direction: column;
}

.chapter-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--color-border);
  cursor: pointer;
  transition: background var(--transition-fast);
  border-radius: var(--radius-sm);
}

.chapter-row:last-child {
  border-bottom: none;
}

.chapter-row:hover {
  background: var(--color-bg);
}

.chapter-row:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.ch-index {
  width: 28px;
  height: 28px;
  border-radius: var(--radius);
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.ch-info {
  flex: 1;
  min-width: 0;
}

.ch-title {
  font-size: 13px;
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ch-badge {
  font-size: 11px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: var(--radius-full);
  white-space: nowrap;
  flex-shrink: 0;
}

.empty-state {
  padding: 24px;
  text-align: center;
  color: var(--color-text-muted);
  font-size: 13px;
}
</style>
