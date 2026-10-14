/**
 * InlineChatPopup.vue — 内联对话小窗渲染层测试。
 *
 * 红线主路径真实性：不 mock useInlineChat —— 用真实 composable 实例挂载，
 * mock 的只有网络层（api/sse.ts 的 streamChatEdit），断言：
 *  ① open() 后弹窗渲染、消息与流式文本逐条出现；
 *  ② 发送按钮调用 streamChatEdit（真实 send 路径）；
 *  ③ suggestion 到达后渲染采纳/拒绝按钮，采纳回调 onAccept 被调用；
 *  ④ 关闭按钮关窗。
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

// ── Mock 网络层（保留真实 composable + 组件行为）───────────────────────────
let capturedCallbacks: Record<string, ((...args: unknown[]) => void) | undefined> = {}
vi.mock('../../api/sse', () => ({
  streamChatEdit: vi.fn((_req, callbacks) => {
    capturedCallbacks = callbacks
    return new AbortController()
  }),
}))

import InlineChatPopup from '../chat/InlineChatPopup.vue'
import { useInlineChat } from '../../composables/useInlineChat'
import { streamChatEdit } from '../../api/sse'

function mountPopup() {
  const chat = useInlineChat({ projectId: () => 7, chapterIndex: () => 3 })
  const anchorEl = document.createElement('textarea')
  document.body.appendChild(anchorEl)
  chat.open(anchorEl, {
    kind: 'text_selection',
    paragraph_id: 9,
    selected_text: '原始正文文本在这里。',
    param_field: 'edited_text',
  })
  const wrapper = mount(InlineChatPopup, { props: { chat }, attachTo: document.body })
  return { wrapper, chat, anchorEl }
}

describe('InlineChatPopup.vue', () => {
  beforeEach(() => {
    // useInlineChat 依赖 Pinia context store
    setActivePinia(createPinia())
    capturedCallbacks = {}
    vi.mocked(streamChatEdit).mockClear()
  })
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('open() 后渲染弹窗：标题、输入框与提示', () => {
    const { wrapper } = mountPopup()
    const popup = wrapper.find('.inline-chat-popup')
    expect(popup.exists()).toBe(true)
    expect(wrapper.find('.popup-title').text()).toContain('edited_text')
    expect(wrapper.find('.popup-input').exists()).toBe(true)
  })

  it('发送消息 → 调用 streamChatEdit（真实 send 路径）并渲染用户消息', async () => {
    const { wrapper } = mountPopup()
    const input = wrapper.find('.popup-input')
    await input.setValue('更口语化')
    await wrapper.find('.popup-btn.primary').trigger('click')
    await flushPromises()

    expect(streamChatEdit).toHaveBeenCalledTimes(1)
    const req = vi.mocked(streamChatEdit).mock.calls[0][0]
    expect(req.intent).toBe('更口语化')
    expect(req.project_id).toBe(7)
    expect(req.paragraph_index).toBe(9)
    // 用户消息渲染
    const msgs = wrapper.findAll('.popup-msg')
    expect(msgs.length).toBe(1)
    expect(msgs[0].text()).toContain('更口语化')
  })

  it('suggestion 事件 → 渲染采纳/拒绝，采纳调用 onAccept', async () => {
    const onAccept = vi.fn()
    const chat = useInlineChat({ projectId: () => 7, chapterIndex: () => 3, onAccept })
    const anchorEl = document.createElement('textarea')
    document.body.appendChild(anchorEl)
    chat.open(anchorEl, { kind: 'text_selection', paragraph_id: 9, selected_text: '原文' })
    const wrapper = mount(InlineChatPopup, { props: { chat }, attachTo: document.body })

    // setValue 会等 nextTick，按钮从禁用态刷新为可点击（真实用户路径）
    const input = wrapper.find('.popup-input')
    await input.setValue('改一下')
    await wrapper.find('.popup-btn.primary').trigger('click')
    await flushPromises()
    expect(streamChatEdit).toHaveBeenCalledTimes(1)

    const cbs = capturedCallbacks
    cbs.onSuggestion?.(
      {
        kind: 'text_edit',
        paragraph_id: '9',
        before: {},
        after: { edited_text: '改后的文本' },
        changes_made: ['改写'],
        confidence: 0.9,
        rationale: '更自然',
      },
      'msg_1',
    )
    await flushPromises()

    const actionBtns = wrapper.findAll('.msg-actions .popup-btn')
    expect(actionBtns.length).toBe(2)
    // 采纳按钮是第一个（primary 样式；测试环境 i18n 可能是 en-US，不断言文案）
    expect(actionBtns[0].classes()).toContain('primary')
    await actionBtns[0].trigger('click')
    await flushPromises()
    expect(onAccept).toHaveBeenCalledTimes(1)
    expect(onAccept.mock.calls[0][0].after.edited_text).toBe('改后的文本')
  })

  it('关闭按钮 → 弹窗消失', async () => {
    const { wrapper, chat } = mountPopup()
    expect(wrapper.find('.inline-chat-popup').exists()).toBe(true)
    await wrapper.find('.popup-close').trigger('click')
    await flushPromises()
    expect(chat.active.value).toBe(false)
    // active=false 后 Teleport 内容不再渲染弹窗节点
    expect(document.querySelector('.inline-chat-popup')).toBeNull()
  })

  it('stop 后保留已接收文本并展示', async () => {
    const { wrapper, chat } = mountPopup()
    const input = wrapper.find('.popup-input')
    await input.setValue('改一下')
    await wrapper.find('.popup-btn.primary').trigger('click')
    await flushPromises()
    expect(streamChatEdit).toHaveBeenCalledTimes(1)

    capturedCallbacks.onToken?.('部分流式文本', 'msg_1')
    await flushPromises()
    await wrapper.find('.popup-btn.danger').trigger('click')
    await flushPromises()

    expect(chat.loading.value).toBe(false)
    expect(wrapper.text()).toContain('部分流式文本 [已停止]')
  })
})
