<template>
  <div class="review-chapter-list">
    <div
      v-for="chapter in chapters"
      :key="chapter.chapter_id"
      class="chapter-item"
      :class="{
        'chapter-item--active': chapter.chapter_id === selectedChapterId,
        'chapter-item--approved': chapter.review_status === 'approved',
      }"
      role="button"
      tabindex="0"
      @click="$emit('select', chapter.chapter_id)"
      @keydown.enter="$emit('select', chapter.chapter_id)"
    >
      <div class="chapter-item__main">
        <span class="chapter-item__index">{{ chapter.index }}</span>
        <span class="chapter-item__title">{{ chapter.title || `#${chapter.index}` }}</span>
        <span class="badge" :class="statusBadgeClass(chapter.review_status)">
          {{ statusLabel(chapter.review_status) }}
        </span>
      </div>
      <div class="chapter-item__footer">
        <span class="text-secondary text-sm">
          {{ t('review_gate.paragraph_count', { count: chapter.paragraph_count }) }}
        </span>
        <span class="chapter-item__actions" @click.stop>
          <button
            v-if="chapter.review_status !== 'approved'"
            class="btn btn-sm btn-primary"
            @click="$emit('approve', chapter.chapter_id)"
          >
            <Icon icon="mdi:check" width="14" height="14" />
            {{ t('review_gate.approve') }}
          </button>
          <button
            v-else
            class="btn btn-sm btn-outline"
            @click="$emit('reset', chapter.chapter_id)"
          >
            <Icon icon="mdi:undo" width="14" height="14" />
            {{ t('review_gate.reset') }}
          </button>
        </span>
      </div>
    </div>
    <p v-if="chapters.length === 0" class="text-secondary text-sm empty-hint">
      {{ t('review_gate.select_chapter_hint') }}
    </p>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from '../../i18n'
import { Icon } from '@iconify/vue'
import type { ReviewGateChapterStatus } from '../../api'

interface Props {
  chapters: ReviewGateChapterStatus[]
  selectedChapterId: number | null
}

defineProps<Props>()

defineEmits<{
  select: [chapterId: number]
  approve: [chapterId: number]
  reset: [chapterId: number]
}>()

const { t } = useI18n()

function statusLabel(status: string | null): string {
  if (status === 'approved') return t('review_gate.approved')
  if (status === 'pending_review') return t('review_gate.pending_review')
  return t('review_gate.not_in_review')
}

function statusBadgeClass(status: string | null): string {
  if (status === 'approved') return 'badge-success'
  if (status === 'pending_review') return 'badge-warning'
  return 'badge-secondary'
}
</script>

<style scoped>
.review-chapter-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.chapter-item {
  padding: 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.chapter-item:hover {
  border-color: var(--color-primary, #4f6ef7);
}

.chapter-item--active {
  border-color: var(--color-primary, #4f6ef7);
  background: rgba(79, 110, 247, 0.06);
}

.chapter-item--approved {
  border-left: 3px solid var(--color-success, #22a06b);
}

.chapter-item__main {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.chapter-item__index {
  min-width: 1.5rem;
  text-align: center;
  font-weight: 600;
  color: var(--color-text-secondary, #888);
}

.chapter-item__title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}

.chapter-item__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 0.4rem;
  padding-left: 2rem;
}

.chapter-item__actions {
  display: flex;
  gap: 0.4rem;
}

.empty-hint {
  padding: 1rem;
  text-align: center;
}
</style>
