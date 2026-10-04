<template>
  <div class="connection-status" :class="connectionStatus">
    <Icon :icon="connectionStatus === 'connected' ? 'mdi:wifi' : 'mdi:wifi-off'" width="14" height="14" />
    <span>{{ connectionStatusText }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '../../i18n'
import { Icon } from '@iconify/vue'

interface Props {
  connectionStatus: 'connected' | 'connecting' | 'disconnected'
}

const props = defineProps<Props>()

const { t } = useI18n()

const connectionStatusText = computed(() => {
  if (props.connectionStatus === 'connected') return t('agentChat.wsConnected')
  if (props.connectionStatus === 'connecting') return t('agentChat.wsConnecting')
  return t('agentChat.wsDisconnected')
})
</script>

<style scoped>
.connection-status {
  position: absolute;
  bottom: 12px;
  left: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 11px;
  z-index: 5;
  background: var(--bg-primary, #ffffff);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);

  &.connected {
    color: #166534;
    background: #dcfce7;

    svg { color: #22c55e; }
  }
  &.connecting {
    color: #92400e;
    background: #fef3c7;

    svg { color: #f59e0b; }
  }
  &.disconnected {
    color: #6b7280;
    background: #f3f4f6;

    svg { color: #9ca3af; }
  }
}
</style>
