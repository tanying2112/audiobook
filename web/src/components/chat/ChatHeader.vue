<template>
  <div class="chat-header">
    <div class="header-left">
      <div class="avatar" :class="statusClass">
        <Icon icon="mdi:robot" width="24" height="24" />
      </div>
      <div class="header-info">
        <h3>{{ t('agentChat.title') }}</h3>
        <span class="status-badge" :class="statusClass">
          {{ statusText }}
        </span>
      </div>
    </div>
    <div class="header-actions">
      <button class="icon-btn" @click="$emit('history')" :title="t('agentChat.history')">
        <Icon icon="mdi:history" width="20" height="20" />
      </button>
      <button class="icon-btn" @click="$emit('settings')" :title="t('agentChat.settings')">
        <Icon icon="mdi:cog" width="20" height="20" />
      </button>
      <button class="icon-btn" @click="$emit('close')" v-if="closable" :title="t('common.close')">
        <Icon icon="mdi:close" width="20" height="20" />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '../../i18n'
import { Icon } from '@iconify/vue'

interface Props {
  connectionStatus: 'connected' | 'connecting' | 'disconnected'
  closable?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  closable: false,
})

defineEmits<{
  history: []
  settings: []
  close: []
}>()

const { t } = useI18n()

const statusClass = computed(() => {
  if (props.connectionStatus === 'connected') return 'online'
  if (props.connectionStatus === 'connecting') return 'connecting'
  return 'offline'
})

const statusText = computed(() => {
  if (props.connectionStatus === 'connected') return t('status.online')
  if (props.connectionStatus === 'connecting') return t('status.connecting')
  return t('status.offline')
})
</script>

<style scoped>
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  background: var(--bg-secondary, #f8f9fa);
  border-bottom: 1px solid var(--border-color, #e9ecef);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  font-size: 18px;

  &.online {
    box-shadow: 0 0 0 2px #22c55e;
  }
  &.connecting {
    box-shadow: 0 0 0 2px #f59e0b;
  }
  &.offline {
    box-shadow: 0 0 0 2px #9ca3af;
  }
}

.header-info h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary, #1f2937);
}

.status-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 500;

  &.online {
    background: #dcfce7;
    color: #166534;
  }
  &.connecting {
    background: #fef3c7;
    color: #92400e;
  }
  &.offline {
    background: #f3f4f6;
    color: #6b7280;
  }
}

.header-actions {
  display: flex;
  gap: 8px;
}

.icon-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary, #6b7280);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;

  &:hover {
    background: var(--bg-tertiary, #e9ecef);
    color: var(--text-primary, #1f2937);
  }

  &.danger:hover {
    background: #fee2e2;
    color: #dc2626;
  }
}
</style>
