import { describe, it, expect } from 'vitest'
import {
  normalizeParagraphStatus,
  paragraphStatusIndex,
  normalizeChapterPipeline,
  computePipelineProgress,
  normalizeTimestamp,
  stageLabel,
  statusLabel,
} from '../normalize'
import type { NormalizeChapterInput, NormalizeParagraphInput } from '../../types/pipeline'

describe('normalize.ts', () => {
  describe('normalizeParagraphStatus', () => {
    it('应该返回有效状态', () => {
      expect(normalizeParagraphStatus('annotated')).toBe('annotated')
      expect(normalizeParagraphStatus('edited')).toBe('edited')
      expect(normalizeParagraphStatus('audio_processed')).toBe('audio_processed')
      expect(normalizeParagraphStatus('synthesized')).toBe('synthesized')
      expect(normalizeParagraphStatus('quality_checked')).toBe('quality_checked')
      expect(normalizeParagraphStatus('pending')).toBe('pending')
    })

    it('未知名品牌牌应归一为 pending', () => {
      expect(normalizeParagraphStatus('unknown')).toBe('pending')
      expect(normalizeParagraphStatus('')).toBe('pending')
      expect(normalizeParagraphStatus(null)).toBe('pending')
      expect(normalizeParagraphStatus(undefined)).toBe('pending')
      expect(normalizeParagraphStatus(123)).toBe('pending')
    })
  })

  describe('paragraphStatusIndex', () => {
    it('应该返回正确的索引', () => {
      expect(paragraphStatusIndex('pending')).toBe(0)
      expect(paragraphStatusIndex('annotated')).toBe(1)
      expect(paragraphStatusIndex('edited')).toBe(2)
      expect(paragraphStatusIndex('audio_processed')).toBe(3)
      expect(paragraphStatusIndex('synthesized')).toBe(4)
      expect(paragraphStatusIndex('quality_checked')).toBe(5)
    })

    it('未知状态返回 -1', () => {
      expect(paragraphStatusIndex('unknown' as any)).toBe(-1)
    })
  })

  describe('normalizeChapterPipeline', () => {
    const mockParagraphs: NormalizeParagraphInput[] = [
      { status: 'annotated' },
      { status: 'edited' },
      { status: 'audio_processed' },
      { status: 'pending' },
    ]

    it('Chapter 字段 completed 时应返回 completed', () => {
      const chapter: NormalizeChapterInput = {
        extract_status: 'completed',
        analyze_status: 'completed',
        annotate_status: 'pending', // 后端不写
        edit_status: 'pending',
        synthesize_status: 'pending',
        quality_status: 'pending',
      }

      const stages = normalizeChapterPipeline(chapter, mockParagraphs)

      const extract = stages.find((s) => s.stage === 'extract')
      const analyze = stages.find((s) => s.stage === 'analyze')
      expect(extract?.status).toBe('completed')
      expect(extract?.inferred_from).toBe('chapter_field')
      expect(analyze?.status).toBe('completed')
    })

    it('Chapter 字段 pending 时应回退到段落聚合推断', () => {
      const chapter: NormalizeChapterInput = {
        extract_status: 'completed',
        analyze_status: 'completed',
        annotate_status: 'pending', // 后端不写
        edit_status: 'pending',
        synthesize_status: 'pending',
        quality_status: 'pending',
      }

      const stages = normalizeChapterPipeline(chapter, mockParagraphs)

      const annotate = stages.find((s) => s.stage === 'annotate')
      const edit = stages.find((s) => s.stage === 'edit')
      const audioPost = stages.find((s) => s.stage === 'audio_postprocess')

      // 段落中有 annotated、edited、audio_processed
      expect(annotate?.status).toBe('completed')
      expect(annotate?.inferred_from).toBe('paragraph_agg')
      expect(edit?.status).toBe('completed')
      expect(audioPost?.status).toBe('completed')
    })

    it('无段落数据时默认 pending', () => {
      const chapter: NormalizeChapterInput = {
        extract_status: 'completed',
        analyze_status: 'completed',
        annotate_status: 'pending',
        edit_status: 'pending',
        synthesize_status: 'pending',
        quality_status: 'pending',
      }

      const stages = normalizeChapterPipeline(chapter, [])

      const annotate = stages.find((s) => s.stage === 'annotate')
      expect(annotate?.status).toBe('pending')
      expect(annotate?.inferred_from).toBe('default')
    })

    it('audio_postprocess 无独立字段，始终用段落聚合', () => {
      const chapter: NormalizeChapterInput = {
        extract_status: 'completed',
        analyze_status: 'completed',
        annotate_status: 'completed',
        edit_status: 'completed',
        synthesize_status: 'pending',
        quality_status: 'pending',
      }

      // 只有到 audio_processed 的段落
      const paragraphs: NormalizeParagraphInput[] = [
        { status: 'audio_processed' },
        { status: 'audio_processed' },
      ]

      const stages = normalizeChapterPipeline(chapter, paragraphs)
      const audioPost = stages.find((s) => s.stage === 'audio_postprocess')
      const synthesize = stages.find((s) => s.stage === 'synthesize')

      expect(audioPost?.status).toBe('completed')
      expect(synthesize?.status).toBe('pending')
    })

    it('应包含所有 7 个阶段', () => {
      const chapter: NormalizeChapterInput = {}
      const stages = normalizeChapterPipeline(chapter)

      expect(stages).toHaveLength(7)
      expect(stages.map((s) => s.stage)).toEqual([
        'extract',
        'analyze',
        'annotate',
        'edit',
        'audio_postprocess',
        'synthesize',
        'quality',
      ])
    })
  })

  describe('computePipelineProgress', () => {
    const stageOrder = [
      'extract',
      'analyze',
      'annotate',
      'edit',
      'audio_postprocess',
      'synthesize',
      'quality',
    ] as const

    it('全 completed 应为 100%', () => {
      const stages = stageOrder.map((stage) => ({
        stage,
        status: 'completed' as const,
        inferred_from: 'chapter_field' as const,
      }))
      expect(computePipelineProgress(stages)).toBe(1)
    })

    it('全 pending 应为 0%', () => {
      const stages = stageOrder.map((stage) => ({
        stage,
        status: 'pending' as const,
        inferred_from: 'default' as const,
      }))
      expect(computePipelineProgress(stages)).toBe(0)
    })

    it('混合状态应正确计算', () => {
      const stages = [
        { stage: 'extract' as const, status: 'completed' as const, inferred_from: 'chapter_field' as const },
        { stage: 'analyze' as const, status: 'completed' as const, inferred_from: 'chapter_field' as const },
        { stage: 'annotate' as const, status: 'running' as const, inferred_from: 'paragraph_agg' as const },
        { stage: 'edit' as const, status: 'pending' as const, inferred_from: 'default' as const },
        { stage: 'audio_postprocess' as const, status: 'pending' as const, inferred_from: 'default' as const },
        { stage: 'synthesize' as const, status: 'pending' as const, inferred_from: 'default' as const },
        { stage: 'quality' as const, status: 'pending' as const, inferred_from: 'default' as const },
      ]
      // 2 * 1 + 1 * 0.5 = 2.5 / 7 ≈ 0.357
      expect(computePipelineProgress(stages)).toBeCloseTo(2.5 / 7)
    })

    it('空数组应返回 0', () => {
      expect(computePipelineProgress([])).toBe(0)
    })
  })

  describe('normalizeTimestamp', () => {
    it('ISO 字符串原样返回', () => {
      const iso = '2026-06-30T10:00:00.000Z'
      expect(normalizeTimestamp(iso)).toBe(iso)
    })

    it('空字符串返回 null', () => {
      expect(normalizeTimestamp('')).toBeNull()
    })

    it('epoch 秒转 ISO', () => {
      // 测试转换逻辑，不依赖具体时区
      const seconds = 1782871200 // 2026-06-30T10:00:00Z in UTC
      const iso = normalizeTimestamp(seconds)
      expect(iso).not.toBeNull()
      expect(iso).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/)
    })

    it('epoch 毫秒转 ISO', () => {
      const milliseconds = 1782871200000 // 2026-06-30T10:00:00.000Z in UTC
      const iso = normalizeTimestamp(milliseconds)
      expect(iso).not.toBeNull()
      expect(iso).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/)
    })

    it('相对秒数（<1e9）返回 null', () => {
      expect(normalizeTimestamp(12345)).toBeNull()
      expect(normalizeTimestamp(0)).toBeNull()
    })

    it('null/undefined 返回 null', () => {
      expect(normalizeTimestamp(null)).toBeNull()
      expect(normalizeTimestamp(undefined)).toBeNull()
    })

    it('非数字非字符串返回 null', () => {
      expect(normalizeTimestamp({})).toBeNull()
      expect(normalizeTimestamp([])).toBeNull()
    })
  })

  describe('stageLabel', () => {
    it('中文标签', () => {
      expect(stageLabel('extract', 'zh')).toBe('文本提取')
      expect(stageLabel('analyze', 'zh')).toBe('结构分析')
      expect(stageLabel('annotate', 'zh')).toBe('段落标注')
      expect(stageLabel('edit', 'zh')).toBe('文本编辑')
      expect(stageLabel('audio_postprocess', 'zh')).toBe('声学参数')
      expect(stageLabel('synthesize', 'zh')).toBe('音频合成')
      expect(stageLabel('quality', 'zh')).toBe('质量检测')
    })

    it('英文标签', () => {
      expect(stageLabel('extract', 'en')).toBe('Extract')
      expect(stageLabel('analyze', 'en')).toBe('Analyze')
    })
  })

  describe('statusLabel', () => {
    it('中文标签', () => {
      expect(statusLabel('pending', 'zh')).toBe('待处理')
      expect(statusLabel('running', 'zh')).toBe('进行中')
      expect(statusLabel('completed', 'zh')).toBe('已完成')
      expect(statusLabel('failed', 'zh')).toBe('失败')
    })

    it('英文标签', () => {
      expect(statusLabel('pending', 'en')).toBe('pending')
      expect(statusLabel('running', 'en')).toBe('running')
    })
  })
})
