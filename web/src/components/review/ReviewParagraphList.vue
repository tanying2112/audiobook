<template>
  <div class="review-paragraph-list">
    <p v-if="paragraphs.length === 0" class="text-secondary text-sm empty-hint">
      {{ t('review_gate.select_chapter_hint') }}
    </p>
    <div
      v-for="para in paragraphs"
      v-else
      :key="para.id"
      class="paragraph-item"
      :class="{ 'paragraph-item--active': para.id === selectedParagraphId }"
      role="button"
      tabindex="0"
      @click="$emit('select', para.id)"
      @keydown.enter="$emit('select', para.id)"
    >
      <div class="paragraph-item__head">
        <span class="paragraph-item__index">#{{ para.index }}</span>
        <span v-if="para.speaker_canonical_name" class="badge badge-secondary">
          {{ para.speaker_canonical_name }}
        </span>
        <span v-if="para.is_dialogue" class="badge badge-info">{{ t('review_gate.is_dialogue') }}</span>
        <span v-if="para.manual_voice_id || para.manual_engine" class="badge badge-warning">
          {{ t('review_gate.manual_override_badge') }}
        </span>
        <span v-if="previewOf(para)?.skipped" class="badge badge-secondary">
          {{ t('review_gate.skipped') }}
        </span>
      </div>

      <p class="paragraph-item__text">
        {{ displayText(para, previewOf(para)) }}
      </p>

      <div v-if="previewOf(para) && !previewOf(para)?.skipped" class="paragraph-item__routing">
        <span class="routing-chip">
          <Icon icon="mdi:engine" width="13" height="13" />
          {{ previewOf(para)!.engine_choice }}
        </span>
        <span class="routing-chip">
          <Icon icon="mdi:account-voice" width="13" height="13" />
          {{ previewOf(para)!.voice_id }}
        </span>
      </div>
      <div v-else-if="previewOf(para)?.skipped" class="paragraph-item__routing">
        <span class="routing-chip routing-chip--muted">
          {{ skipReasonLabel(previewOf(para)!.skip_reason) }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from '../../i18n'
import { Icon } from '@iconify/vue'
import type { ParagraphRoutingPreview } from '../../api'
import type { Paragraph } from '../../types'

interface Props {
  paragraphs: Paragraph[]
  previews: Map<number, ParagraphRoutingPreview>
  selectedParagraphId: number | null
}

const props = defineProps<Props>()

defineEmits<{
  select: [paragraphId: number]
}>()

const { t } = useI18n()

function previewOf(para: Paragraph): ParagraphRoutingPreview | undefined {
  return props.previews.get(para.id)
}

/** 优先显示合成将朗读的文本（预览的 effective_text），跳过段显示原文 */
function displayText(para: Paragraph, preview?: ParagraphRoutingPreview): string {
  const text = preview ? preview.effective_text : (para.edited_text ?? para.text)
  return text || t('review_gate.empty_text')
}

function skipReasonLabel(reason?: string | null): string {
  if (reason === 'empty_text') return t('review_gate.skip_reason_empty_text')
  if (reason === 'image_only') return t('review_gate.skip_reason_image_only')
  return t('review_gate.skipped')
}
</script>

<style scoped>
.review-paragraph-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  max-height: 100%;
  overflow-y: auto;
}

.paragraph-item {
  padding: 0.6rem 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.paragraph-item:hover {
  border-color: var(--color-primary, #4f6ef7);
}

.paragraph-item--active {
  border-color: var(--color-primary, #4f6ef7);
  background: rgba(79, 110, 247, 0.06);
}

.paragraph-item__head {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.3rem;
  flex-wrap: wrap;
}

.paragraph-item__index {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-secondary, #888);
}

.paragraph-item__text {
  margin: 0 0 0.3rem;
  font-size: 0.9rem;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.paragraph-item__routing {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.routing-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.75rem;
  padding: 0.1rem 0.5rem;
  border-radius: 999px;
  background: rgba(79, 110, 247, 0.08);
  color: var(--color-primary, #4f6ef7);
  font-family: monospace;
}

.routing-chip--muted {
  background: rgba(128, 128, 128, 0.1);
  color: var(--color-text-secondary, #888);
  font-family: inherit;
}

.empty-hint {
  padding: 1rem;
  text-align: center;
}
</style>
