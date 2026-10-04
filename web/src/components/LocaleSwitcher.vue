<script setup lang="ts">
import { computed } from 'vue'
import { Icon } from '@iconify/vue'
import { useI18n, SUPPORTED_LOCALES } from '../i18n'
import type { SupportedLocale } from '../types'

const { locale, setLocale, t } = useI18n()

// 当前已启用的语言列表（按 SUPPORTED_LOCALES 顺序）
const localeOptions = computed(() =>
  Object.entries(SUPPORTED_LOCALES).map(([code, label]) => ({ code, label }))
)

function onChange(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  if (value) setLocale(value as SupportedLocale)
}
</script>

<template>
  <div class="locale-switcher">
    <Icon icon="mdi:translate" width="18" height="18" class="locale-icon" />
    <label class="visually-hidden" for="locale-select">{{ t('settings.language') }}</label>
    <select
      id="locale-select"
      class="locale-select"
      :value="locale"
      @change="onChange"
      :aria-label="t('settings.language')"
    >
      <option v-for="opt in localeOptions" :key="opt.code" :value="opt.code">
        {{ opt.label }}
      </option>
    </select>
  </div>
</template>

<style scoped>
.locale-switcher {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 12px 8px;
}
.locale-icon {
  color: #94a3b8;
  flex-shrink: 0;
}
.locale-select {
  flex: 1;
  min-width: 0;
  height: 36px;
  padding: 0 8px;
  border: 1px solid #334155;
  border-radius: 8px;
  background: #1e293b;
  color: #e2e8f0;
  font-size: 13px;
  cursor: pointer;
}
.locale-select:hover {
  border-color: #475569;
}
.locale-select:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
