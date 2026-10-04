import { setActivePinia, createPinia } from 'pinia'
import { describe, it, expect, beforeEach } from 'vitest'
import { useContextStore } from '../context'

describe('useContextStore', () => {
  let store: ReturnType<typeof useContextStore>

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useContextStore()
  })

  describe('initial state', () => {
    it('should have correct default values', () => {
      expect(store.route).toBe('/')
      expect(store.projectId).toBeNull()
      expect(store.chapterIndex).toBeNull()
      expect(store.paragraphIndex).toBeNull()
      expect(store.selectedText).toBeNull()
      expect(store.activeAnchor).toBeNull()
      expect(store.isInlineChatActive).toBe(false)
      expect(store.hasSelection).toBe(false)
    })
  })

  describe('syncFromRoute', () => {
    it('should sync route params correctly', () => {
      store.syncFromRoute('/projects/1/chapters/2', {
        projectId: '1',
        chapterId: '2',
      })

      expect(store.route).toBe('/projects/1/chapters/2')
      expect(store.projectId).toBe(1)
      expect(store.chapterIndex).toBe(2)
      expect(store.paragraphIndex).toBeNull()
    })

    it('should handle missing chapterId param', () => {
      store.syncFromRoute('/projects/1', {
        projectId: '1',
      })

      expect(store.projectId).toBe(1)
      expect(store.chapterIndex).toBeNull()
    })

    it('should clear selection and anchor on route change', () => {
      store.setSelectedText('选中文本')
      store.openInlineChat({
        kind: 'text_selection',
        paragraph_id: 0,
        selected_text: '选中',
        selection_start: 0,
        selection_end: 2,
        rect: { x: 0, y: 0, width: 10, height: 20 },
      })

      store.syncFromRoute('/projects/2', { projectId: '2' })

      expect(store.selectedText).toBeNull()
      expect(store.activeAnchor).toBeNull()
    })
  })

  describe('setSelectedText', () => {
    it('should set selected text', () => {
      store.setSelectedText('选中的文本')
      expect(store.selectedText).toBe('选中的文本')
      expect(store.hasSelection).toBe(true)
    })

    it('should clear when set to null', () => {
      store.setSelectedText('文本')
      store.setSelectedText(null)
      expect(store.selectedText).toBeNull()
      expect(store.hasSelection).toBe(false)
    })
  })

  describe('openInlineChat / closeInlineChat', () => {
    const mockAnchor = {
      kind: 'text_selection' as const,
      paragraph_id: 0,
      selected_text: '测试',
      selection_start: 0,
      selection_end: 2,
      rect: { x: 100, y: 100, width: 50, height: 20 },
    }

    it('should open inline chat and set active anchor', () => {
      store.openInlineChat(mockAnchor)

      expect(store.activeAnchor).toEqual(mockAnchor)
      expect(store.isInlineChatActive).toBe(true)
    })

    it('should close inline chat', () => {
      store.openInlineChat(mockAnchor)
      store.closeInlineChat()

      expect(store.activeAnchor).toBeNull()
      expect(store.isInlineChatActive).toBe(false)
    })

    it('should replace anchor when opening again', () => {
      store.openInlineChat(mockAnchor)

      const newAnchor = {
        ...mockAnchor,
        kind: 'param_control' as const,
        param_field: 'emotion',
        param_value: 'happy',
      }
      store.openInlineChat(newAnchor)

      expect(store.activeAnchor).toEqual(newAnchor)
      expect(store.activeAnchor?.kind).toBe('param_control')
    })
  })

  describe('clear', () => {
    it('should clear all operation context', () => {
      store.setSelectedText('文本')
      store.openInlineChat({
        kind: 'paragraph',
        paragraph_id: 1,
        rect: { x: 0, y: 0, width: 10, height: 10 },
      })

      store.clear()

      expect(store.selectedText).toBeNull()
      expect(store.activeAnchor).toBeNull()
    })
  })

  describe('anchor kinds', () => {
    it('should support text_selection kind', () => {
      const anchor = {
        kind: 'text_selection' as const,
        paragraph_id: 0,
        selected_text: '选中',
        selection_start: 0,
        selection_end: 2,
        rect: { x: 0, y: 0, width: 20, height: 20 },
      }
      store.openInlineChat(anchor)
      expect(store.activeAnchor?.kind).toBe('text_selection')
    })

    it('should support param_control kind', () => {
      const anchor = {
        kind: 'param_control' as const,
        paragraph_id: 0,
        param_field: 'emotion',
        param_value: 'angry',
        rect: { x: 0, y: 0, width: 30, height: 30 },
      }
      store.openInlineChat(anchor)
      expect(store.activeAnchor?.kind).toBe('param_control')
      expect(store.activeAnchor?.param_field).toBe('emotion')
    })

    it('should support paragraph kind', () => {
      const anchor = {
        kind: 'paragraph' as const,
        paragraph_id: 1,
        rect: { x: 0, y: 0, width: 100, height: 50 },
      }
      store.openInlineChat(anchor)
      expect(store.activeAnchor?.kind).toBe('paragraph')
      expect(store.activeAnchor?.paragraph_id).toBe(1)
    })
  })
})
