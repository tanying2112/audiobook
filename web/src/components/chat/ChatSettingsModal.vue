<template>
  <div class="modal-overlay" v-if="show" @click.self="$emit('close')">
    <div class="modal settings-modal">
      <div class="modal-header">
        <h4>{{ t('agentChat.settings') }}</h4>
        <button class="icon-btn" @click="$emit('close')">
          <Icon icon="mdi:close" width="20" height="20" />
        </button>
      </div>
      <div class="modal-body">
        <div class="setting-group">
          <label>{{ t('agentChat.agentPersonality') }}</label>
          <select v-model="settings.personality" class="setting-select">
            <option value="general">{{ t('agentChat.personality.general') }}</option>
            <option value="expert">{{ t('agentChat.personality.expert') }}</option>
            <option value="creative">{{ t('agentChat.personality.creative') }}</option>
            <option value="concise">{{ t('agentChat.personality.concise') }}</option>
          </select>
        </div>
        <div class="setting-group">
          <label>{{ t('agentChat.responseLength') }}</label>
          <select v-model="settings.responseLength" class="setting-select">
            <option value="short">{{ t('agentChat.length.short') }}</option>
            <option value="medium">{{ t('agentChat.length.medium') }}</option>
            <option value="long">{{ t('agentChat.length.long') }}</option>
          </select>
        </div>
        <div class="setting-group">
          <label class="checkbox-label">
            <input type="checkbox" v-model="settings.autoScroll" />
            <span>{{ t('agentChat.autoScroll') }}</span>
          </label>
        </div>
        <div class="setting-group">
          <label class="checkbox-label">
            <input type="checkbox" v-model="settings.showTimestamps" />
            <span>{{ t('agentChat.showTimestamps') }}</span>
          </label>
        </div>
        <div class="setting-group danger-zone">
          <h5>{{ t('agentChat.dangerZone') }}</h5>
          <button class="btn danger" @click="$emit('clear-history')">
            {{ t('agentChat.clearAllHistory') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from '../../i18n'
import { Icon } from '@iconify/vue'

interface Settings {
  personality: 'general' | 'expert' | 'creative' | 'concise'
  responseLength: 'short' | 'medium' | 'long'
  autoScroll: boolean
  showTimestamps: boolean
}

interface Props {
  show: boolean
  settings: Settings
}

defineProps<Props>()

defineEmits<{
  close: []
  'clear-history': []
}>()

const { t } = useI18n()
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 20px;
}

.settings-modal {
  width: 100%;
  max-width: 400px;
  background: var(--bg-primary, #ffffff);
  border-radius: 16px;
  overflow: hidden;
  animation: scaleIn 0.2s ease;
}

@keyframes scaleIn {
  from { transform: scale(0.95); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color, #e9ecef);

  h4 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }
}

.modal-body {
  padding: 20px;
}

.setting-group {
  margin-bottom: 20px;

  label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary, #1f2937);
    margin-bottom: 8px;
  }
}

.setting-select {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border-color, #e9ecef);
  border-radius: 8px;
  background: var(--bg-primary, #ffffff);
  font-size: 13px;
  color: var(--text-primary, #1f2937);
  cursor: pointer;

  &:focus {
    outline: none;
    border-color: #667eea;
    box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
  }
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-primary, #1f2937);

  input {
    width: 18px;
    height: 18px;
    accent-color: #667eea;
  }
}

.danger-zone {
  padding-top: 20px;
  border-top: 1px solid var(--border-color, #e9ecef);

  h5 {
    margin: 0 0 12px;
    font-size: 13px;
    font-weight: 600;
    color: #dc2626;
  }
}

.btn {
  padding: 10px 16px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;

  &.danger {
    background: #fee2e2;
    color: #dc2626;
    width: 100%;

    &:hover {
      background: #fecaca;
    }
  }
}
</style>
