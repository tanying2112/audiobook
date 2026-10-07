<script setup lang="ts">
/**
 * InlineChatPopup — Cursor 风格内联小窗（P0-AI-8 的渲染层）。
 *
 * 消费父组件持有的 useInlineChat 实例（状态与操作共享同一份），
 * 通过 useInlineChatPosition 锚定在触发元素旁，滚动/缩放实时跟随。
 */
import { computed } from 'vue'
import { useI18n } from '../../i18n'
import { useInlineChatPosition } from '../../composables/useInlineChatPosition'
import type { useInlineChat } from '../../composables/useInlineChat'

type InlineChatInstance = ReturnType<typeof useInlineChat>

const props = defineProps<{ chat: InlineChatInstance }>()

const { t } = useI18n()

// chat 实例由父组件创建一次并保持稳定；解构捕获的是 ref 对象本身，保持响应式
const {
  messages,
  streamingText,
  loading,
  error,
  currentSuggestion,
  inputText,
  active,
  anchor,
  anchorEl,
  canSend,
  canStop,
  close,
  send,
  stop,
  accept,
  reject,
} = props.chat

const { position } = useInlineChatPosition(anchorEl, {
  active,
  popoverSize: { width: 380, height: 460 },
})

const anchorTitle = computed(() => {
  const a = anchor.value
  if (!a) return t('inline_chat.selection')
  if (a.param_field) return a.param_field
  const sel = (a.selected_text ?? '').trim()
  return sel.length > 24 ? sel.slice(0, 24) + '…' : sel || t('inline_chat.selection')
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="active"
      class="inline-chat-popup"
      :style="position.style"
      :data-placement="position.placement"
    >
      <header class="popup-header">
        <span class="popup-title">{{ anchorTitle }}</span>
        <button class="popup-close" :aria-label="t('common.cancel')" @click="close">×</button>
      </header>

      <div class="popup-messages">
        <div v-for="m in messages" :key="m.id" class="popup-msg" :class="m.role">
          <span class="msg-role">{{ m.role === 'user' ? t('inline_chat.you') : t('inline_chat.ai') }}</span>
          <p class="msg-content">{{ m.content }}</p>
          <div
            v-if="m.suggestion && m.adoption === 'pending' && currentSuggestion === m.suggestion"
            class="msg-actions"
          >
            <button class="popup-btn primary" @click="accept">{{ t('inline_chat.accept') }}</button>
            <button class="popup-btn" @click="reject">{{ t('inline_chat.reject') }}</button>
          </div>
        </div>
        <p v-if="streamingText" class="popup-msg assistant streaming">
          {{ streamingText }}<span class="cursor">▍</span>
        </p>
        <p v-if="loading && !streamingText && messages.length <= 1" class="popup-hint">
          {{ t('inline_chat.hint') }}
        </p>
      </div>

      <p v-if="error" class="popup-error">{{ error }}</p>

      <footer class="popup-footer">
        <textarea
          v-model="inputText"
          class="popup-input"
          rows="2"
          :placeholder="t('inline_chat.input_placeholder')"
          @keydown.enter.exact.prevent="send"
        ></textarea>
        <button v-if="!canStop" class="popup-btn primary" :disabled="!canSend" @click="send">
          {{ t('inline_chat.send') }}
        </button>
        <button v-else class="popup-btn danger" @click="stop">{{ t('inline_chat.stop') }}</button>
      </footer>
    </div>
  </Teleport>
</template>

<style scoped>
.inline-chat-popup {
  position: fixed;
  z-index: 3000;
  display: flex;
  flex-direction: column;
  width: 380px;
  max-height: 460px;
  background: #fff;
  border: 1px solid #dbe3ee;
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(15, 23, 42, 0.18);
  overflow: hidden;
}

.popup-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid #eef2f7;
  background: #f8fafc;
}
.popup-title {
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.popup-close {
  border: none;
  background: none;
  font-size: 16px;
  line-height: 1;
  color: #94a3b8;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 6px;
}
.popup-close:hover { color: #475569; background: #eef2f7; }

.popup-messages {
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.popup-msg { font-size: 13px; line-height: 1.6; }
.popup-msg.user { text-align: right; }
.msg-role {
  display: inline-block;
  font-size: 11px;
  color: #94a3b8;
  margin-bottom: 2px;
}
.msg-content {
  margin: 2px 0 0;
  padding: 6px 10px;
  border-radius: 10px;
  background: #f1f5f9;
  color: #1e293b;
  white-space: pre-wrap;
  text-align: left;
}
.popup-msg.user .msg-content { background: #dbeafe; }
.popup-msg.streaming { color: #334155; }
.cursor { animation: blink 1s step-start infinite; }
@keyframes blink { 50% { opacity: 0; } }
.popup-hint { margin: 0; font-size: 12px; color: #94a3b8; }

.msg-actions { display: flex; gap: 6px; margin-top: 6px; }

.popup-error {
  margin: 0;
  padding: 6px 12px;
  font-size: 12px;
  color: #b91c1c;
  background: #fef2f2;
}

.popup-footer {
  display: flex;
  gap: 8px;
  padding: 8px 12px;
  border-top: 1px solid #eef2f7;
  align-items: flex-end;
}
.popup-input {
  flex: 1;
  resize: none;
  padding: 6px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 13px;
  font-family: inherit;
  color: #1e293b;
}
.popup-input:focus { outline: none; border-color: #3b82f6; }

.popup-btn {
  border: 1px solid #e2e8f0;
  background: #fff;
  color: #475569;
  font-size: 12px;
  padding: 5px 12px;
  border-radius: 8px;
  cursor: pointer;
}
.popup-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.popup-btn.primary { background: #2563eb; border-color: #2563eb; color: #fff; }
.popup-btn.primary:hover:not(:disabled) { background: #1d4ed8; }
.popup-btn.danger { background: #dc2626; border-color: #dc2626; color: #fff; }
</style>
