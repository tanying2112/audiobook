<template>
  <div class="app-empty-state">
    <Icon v-if="icon" :icon="icon" width="48" height="48" class="empty-icon" />
    <h3 v-if="title" class="empty-title">{{ title }}</h3>
    <p v-if="description" class="empty-desc">{{ description }}</p>
    <slot />
  </div>
</template>

<script setup lang="ts">
import { Icon } from '@iconify/vue'

defineProps<{
  icon?: string
  title?: string
  description?: string
}>()
</script>

<style scoped>
.app-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 48px 24px;
  text-align: center;
  color: var(--color-text-secondary, #64748b);
}
.empty-icon {
  opacity: 0.6;
}
.empty-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--color-text, #1e293b);
}
.empty-desc {
  margin: 0;
  max-width: 420px;
  line-height: 1.6;
}
</style>
