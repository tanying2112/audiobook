import { describe, it, expect } from 'vitest'
import {
  PIPELINE_STAGE_ORDER,
  PARAGRAPH_STATUS_FLOW,
  type InlineChatAnchor,
  type ChatSuggestion,
  type ChatMessage,
  type ChatEditRequest,
} from '../pipeline'

describe('Pipeline Types', () => {
  describe('PIPELINE_STAGE_ORDER', () => {
    it('should have correct stage order', () => {
      expect(PIPELINE_STAGE_ORDER).toEqual([
        'extract',
        'analyze',
        'annotate',
        'edit',
        'audio_postprocess',
        'synthesize',
        'quality',
      ])
    })

    it('should have 7 stages', () => {
      expect(PIPELINE_STAGE_ORDER.length).toBe(7)
    })
  })

  describe('PARAGRAPH_STATUS_FLOW', () => {
    it('should have correct status flow order', () => {
      expect(PARAGRAPH_STATUS_FLOW).toEqual([
        'pending',
        'annotated',
        'edited',
        'audio_processed',
        'synthesized',
        'quality_checked',
      ])
    })

    it('should have 6 statuses', () => {
      expect(PARAGRAPH_STATUS_FLOW.length).toBe(6)
    })
  })

  describe('InlineChatAnchor type', () => {
    it('should accept text_selection kind', () => {
      const anchor: InlineChatAnchor = {
        kind: 'text_selection',
        paragraph_id: 1,
        selected_text: '测试文本',
        selection_start: 0,
        selection_end: 4,
        rect: { x: 100, y: 200, width: 50, height: 20 },
      }
      expect(anchor.kind).toBe('text_selection')
      expect(anchor.selected_text).toBe('测试文本')
    })

    it('should accept param_control kind', () => {
      const anchor: InlineChatAnchor = {
        kind: 'param_control',
        paragraph_id: 2,
        param_field: 'emotion',
        param_value: 'angry',
        rect: { x: 150, y: 250, width: 80, height: 30 },
      }
      expect(anchor.kind).toBe('param_control')
      expect(anchor.param_field).toBe('emotion')
      expect(anchor.param_value).toBe('angry')
    })

    it('should accept paragraph kind', () => {
      const anchor: InlineChatAnchor = {
        kind: 'paragraph',
        paragraph_id: 3,
        rect: { x: 50, y: 100, width: 200, height: 150 },
      }
      expect(anchor.kind).toBe('paragraph')
      expect(anchor.paragraph_id).toBe(3)
    })
  })

  describe('ChatSuggestion type', () => {
    it('should accept valid suggestion structure', () => {
      const suggestion: ChatSuggestion = {
        kind: 'text_edit',
        paragraph_id: '1_ch1_p0',
        before: { text: '原文' },
        after: { text: '新文本' },
        changes_made: ['口语化', '简化'],
        confidence: 0.9,
        rationale: '更自然',
      }
      expect(suggestion.kind).toBe('text_edit')
      expect(suggestion.confidence).toBe(0.9)
      expect(suggestion.changes_made).toHaveLength(2)
    })
  })

  describe('ChatMessage type', () => {
    it('should accept user message', () => {
      const msg: ChatMessage = {
        id: 'msg_1',
        role: 'user',
        content: '请口语化',
        timestamp: new Date().toISOString(),
      }
      expect(msg.role).toBe('user')
      expect(msg.content).toBe('请口语化')
    })

    it('should accept assistant message with suggestion', () => {
      const msg: ChatMessage = {
        id: 'msg_2',
        role: 'assistant',
        content: '已口语化',
        timestamp: new Date().toISOString(),
        suggestion: {
          kind: 'text_edit',
          paragraph_id: '1_ch1_p0',
          before: { text: '原文' },
          after: { text: '新文本' },
          changes_made: ['口语化'],
          confidence: 0.9,
          rationale: '更自然',
        },
        adoption: 'pending',
      }
      expect(msg.role).toBe('assistant')
      expect(msg.suggestion).toBeDefined()
      expect(msg.adoption).toBe('pending')
    })
  })

  describe('ChatEditRequest type', () => {
    it('should accept valid request', () => {
      const req: ChatEditRequest = {
        project_id: 1,
        chapter_index: 1,
        paragraph_index: 0,
        target_stage: 'edit',
        intent: '口语化',
        conversation_history: [],
        annotation_context: { selected_text: '测试' },
        shortcut: 'colloquialize',
      }
      expect(req.project_id).toBe(1)
      expect(req.target_stage).toBe('edit')
      expect(req.shortcut).toBe('colloquialize')
    })
  })
})
