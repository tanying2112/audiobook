/**
 * 全局上下文 Store（Pinia）
 *
 * 无论路由到哪个页面，此 store 实时维护"当前用户在关注什么"。
 * 服务于：
 *   - P0-AI-7 全局智能助手浮层（自动感知当前页面/项目/选中文本）
 *   - P0-AI-8 Cursor 风格内联小窗（追踪当前选区/参数锚点）
 *   - 任何需要跨组件读取"当前上下文"的场景
 *
 * 路由相关字段（route/projectId/chapterIndex/paragraphIndex）由 main.ts 的
 * router.afterEach 钩子自动更新；selection/anchor 由具体编辑组件主动 set。
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { InlineChatAnchor } from '../types/pipeline'

export const useContextStore = defineStore('context', () => {
  // ── 路由上下文（router.afterEach 自动维护）─────────────────────────────
  const route = ref<string>('/')
  const projectId = ref<number | null>(null)
  const chapterIndex = ref<number | null>(null)
  const paragraphIndex = ref<number | null>(null)

  // ── 用户操作上下文（编辑组件主动维护）─────────────────────────────────

  /** 用户当前选中的文本（全局助手用） */
  const selectedText = ref<string | null>(null)
  /** 当前活跃的内联小窗锚点（Cursor 风格小窗用） */
  const activeAnchor = ref<InlineChatAnchor | null>(null)

  // ── 派生 ─────────────────────────────────────────────────────────────
  const isInlineChatActive = computed(() => activeAnchor.value !== null)
  const hasSelection = computed(() => (selectedText.value ?? '').length > 0)

  // ── Actions ──────────────────────────────────────────────────────────

  /** 从路由 path + params 同步路由上下文（由 router.afterEach 调用） */
  function syncFromRoute(path: string, params: Record<string, string>) {
    route.value = path
    projectId.value = params.projectId != null ? Number(params.projectId) : null
    chapterIndex.value = params.chapterId != null ? Number(params.chapterId) : null
    paragraphIndex.value = params.paragraphId != null ? Number(params.paragraphId) : null
    // 切换路由时清掉易失效的操作上下文
    selectedText.value = null
    activeAnchor.value = null
  }

  function setSelectedText(text: string | null) {
    selectedText.value = text
  }

  /** 设置内联小窗锚点（激活小窗） */
  function openInlineChat(anchor: InlineChatAnchor) {
    activeAnchor.value = anchor
  }

  /** 关闭内联小窗 */
  function closeInlineChat() {
    activeAnchor.value = null
  }

  function clear() {
    selectedText.value = null
    activeAnchor.value = null
  }

  return {
    // state
    route,
    projectId,
    chapterIndex,
    paragraphIndex,
    selectedText,
    activeAnchor,
    // getters
    isInlineChatActive,
    hasSelection,
    // actions
    syncFromRoute,
    setSelectedText,
    openInlineChat,
    closeInlineChat,
    clear,
  }
})
