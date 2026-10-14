<template>
  <div class="paragraph-node" :class="{ 'has-match': hasMatch }">
    <div class="para-content" v-html="highlightedPreview"></div>
    <div class="para-meta">
      <span v-if="paragraph.character" class="meta-item">
        <User class="meta-icon" />{{ paragraph.character }}
      </span>
      <span v-if="paragraph.emotion" class="meta-item">
        <Star class="meta-icon" />{{ paragraph.emotion }}
      </span>
      <span class="meta-item index">
        #{{ paragraph.index + 1 }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { User, Star } from '@element-plus/icons-vue'

const props = defineProps<{
  paragraph: {
    id: number
    chapter_id: number
    index: number
    text: string
    preview_text: string
    character: string | null
    emotion: string | null
  }
  searchQuery: string
}>()

const hasMatch = computed(() => {
  if (!props.searchQuery) return false
  const query = props.searchQuery.toLowerCase()
  return props.paragraph.text.toLowerCase().includes(query) ||
         (props.paragraph.character?.toLowerCase().includes(query)) ||
         (props.paragraph.emotion?.toLowerCase().includes(query))
})

const highlightedPreview = computed(() => {
  if (!props.searchQuery) return props.paragraph.preview_text
  const query = props.searchQuery
  const regex = new RegExp(`(${query})`, 'gi')
  return props.paragraph.preview_text.replace(regex, '<mark>$1</mark>')
})
</script>

<style scoped>
.paragraph-node {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 12px;
  background: var(--bg-secondary, #fafafa);
  border-radius: 4px;
  margin: 4px 0;
  border: 1px solid var(--border-color, #e8e8e8);
  font-size: 12px;
}
.paragraph-node.has-match {
  border-color: var(--color-primary, #409eff);
  background: var(--color-primary-light, #e6f7ff);
}

.para-content {
  line-height: 1.6;
  color: var(--text-primary, #333);
}
.para-content mark {
  background: var(--color-warning-light, #fdf6ec);
  color: var(--color-warning, #e6a23c);
  padding: 0 2px;
  border-radius: 2px;
}

.para-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
  color: var(--text-tertiary, #bbb);
  font-size: 11px;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.meta-icon {
  font-size: 11px;
}
.index {
  margin-left: auto;
  color: var(--color-primary, #409eff);
  font-weight: 500;
}
</style>