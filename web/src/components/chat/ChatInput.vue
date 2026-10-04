<template>
  <div class="input-area">
    <div class="input-wrapper">
      <textarea
        ref="messageInput"
        :value="modelValue"
        :placeholder="placeholder"
        @input="onInput"
        @keydown.enter.exact="$emit('send')"
        @keydown.enter.shift="$emit('newline')"
        rows="1"
        class="message-input"
      ></textarea>
      <div class="input-actions">
        <button class="icon-btn" @click="$emit('attach')" :title="t('agentChat.attachFile')">
          <Icon icon="mdi:paperclip" width="20" height="20" />
        </button>
        <button
          class="icon-btn send-btn"
          @click="$emit('send')"
          :disabled="!modelValue.trim() || loading"
          :title="t('agentChat.send')"
        >
          <Icon icon="mdi:send" width="20" height="20" />
        </button>
      </div>
    </div>
    <div class="input-hints">
      <span>{{ t('agentChat.enterToSend') }}</span>
      <span>{{ t('agentChat.shiftEnterForNewline') }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useI18n } from '../../i18n'
import { Icon } from '@iconify/vue'

interface Props {
  modelValue: string
  loading: boolean
  placeholder: string
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  send: []
  attach: []
  newline: []
}>()

const { t } = useI18n()

const messageInput = ref<HTMLTextAreaElement>()

const onInput = (event: Event) => {
  emit('update:modelValue', (event.target as HTMLTextAreaElement).value)
}

watch(() => props.modelValue, () => {
  nextTick(() => {
    if (messageInput.value) {
      messageInput.value.style.height = 'auto'
      messageInput.value.style.height = `${Math.min(messageInput.value.scrollHeight, 150)}px`
    }
  })
})
</script>

<style scoped>
.input-area {
  padding: 16px 20px;
  background: var(--bg-secondary, #f8f9fa);
  border-top: 1px solid var(--border-color, #e9ecef);
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  background: var(--bg-primary, #ffffff);
  border: 1px solid var(--border-color, #e9ecef);
  border-radius: 12px;
  padding: 8px 12px;
  transition: border-color 0.2s;

  &:focus-within {
    border-color: #667eea;
    box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
  }
}

.message-input {
  flex: 1;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  font-size: 14px;
  line-height: 1.5;
  font-family: inherit;
  color: var(--text-primary, #1f2937);
  min-height: 24px;
  max-height: 150px;
  padding: 4px 0;

  &::placeholder {
    color: var(--text-tertiary, #9ca3af);
  }
}

.input-actions {
  display: flex;
  gap: 4px;
  align-items: center;
}

.send-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s, opacity 0.2s;

  &:hover:not(:disabled) {
    transform: scale(1.05);
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
}

.input-hints {
  display: flex;
  gap: 16px;
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-tertiary, #9ca3af);
}
</style>
