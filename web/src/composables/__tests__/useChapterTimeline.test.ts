import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'

// Mock the chapter store
const mockParagraphsData: any[] = [
  { id: 1, project_id: 1, chapter_id: 1, index: 0, text: 'Test paragraph 1', emotion: 'neutral' },
  { id: 2, project_id: 1, chapter_id: 1, index: 1, text: 'Test paragraph 2', emotion: 'happy' },
]

const mockStore = {
  currentChapter: { id: 1, project_id: 1, index: 1 },
  paragraphs: mockParagraphsData,
  loadChapter: vi.fn().mockResolvedValue(undefined),
  loadParagraphs: vi.fn().mockResolvedValue(undefined),
  loadAudioSegments: vi.fn(),
  loadQuality: vi.fn(),
}

vi.mock('@/stores/chapters', () => ({
  useChapterStore: () => mockStore,
}))

// Mock useWaveSurfer
vi.mock('@/composables/useWaveSurfer', () => ({
  useWaveSurfer: () => ({
    isPlaying: ref(false),
    currentTime: ref(0),
    duration: ref(0),
    error: ref(null),
    load: vi.fn(),
    playPause: vi.fn(),
    skip: vi.fn(),
    zoom: vi.fn(),
    cleanup: vi.fn(),
  }),
}))

// Mock usePipelineProgress
vi.mock('@/composables/usePipelineProgress', () => ({
  usePipelineProgress: () => ({
    state: ref({
      isRunning: false,
      completedStages: [],
      currentStage: null,
      stageProgress: 0,
    }),
    getOverallProgress: () => 0,
    isStageCompleted: () => false,
    isStageActive: () => false,
  }),
}))

// Mock i18n
vi.mock('@/i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}))

// Mock normalize
vi.mock('@/utils/normalize', () => ({
  normalizeChapterPipeline: () => [],
}))

// Mock API
const mockFetchParagraphDetail = vi.fn()
vi.mock('@/api', () => ({
  fetchParagraphDetail: mockFetchParagraphDetail,
}))

// Mock router
vi.mock('vue-router', () => ({
  useRoute: () => ({
    params: { projectId: '1', chapterId: '1' },
  }),
  useRouter: () => ({
    push: vi.fn(),
  }),
}))

describe('useChapterTimeline - fetchParagraphDetail integration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockParagraphsData.length = 0
    mockParagraphsData.push(
      { id: 1, project_id: 1, chapter_id: 1, index: 0, text: 'Test paragraph 1', emotion: 'neutral' },
      { id: 2, project_id: 1, chapter_id: 1, index: 1, text: 'Test paragraph 2', emotion: 'happy' },
    )
    mockStore.currentChapter = { id: 1, project_id: 1, index: 1 }
  })

  it('calls fetchParagraphDetail when paragraph is selected', async () => {
    const { useChapterTimeline } = await import('@/composables/useChapterTimeline')
    const timeline = useChapterTimeline()

    const detailResponse = {
      id: 1,
      project_id: 1,
      chapter_id: 1,
      index: 0,
      text: 'Test paragraph 1',
      emotion: 'neutral',
      tts_edit_history: [{ edit: 'test', timestamp: '2024-01-01' }],
      quality_records: [{ score: 0.9, timestamp: '2024-01-01' }],
      routing_decision: { engine: 'edge', voice: 'zh-CN-XiaoxiaoNeural' },
      annotations_full: { speaker: 'narrator', notes: 'test' },
    }

    mockFetchParagraphDetail.mockResolvedValue(detailResponse)

    // Call selectParagraph which should trigger fetchParagraphDetail
    timeline.selectParagraph(1)

    // Wait for async operations
    await new Promise(resolve => setTimeout(resolve, 0))

    // Verify fetchParagraphDetail was called with correct params
    expect(mockFetchParagraphDetail).toHaveBeenCalledWith(1, 1, 1)

    // Wait for the promise to resolve and store to be updated
    await new Promise(resolve => setTimeout(resolve, 10))

    // Verify the paragraph in store was updated with detail data
    const updatedPara = mockParagraphsData.find(p => p.id === 1)
    expect(updatedPara).toBeDefined()
    expect(updatedPara?.tts_edit_history).toEqual([{ edit: 'test', timestamp: '2024-01-01' }])
    expect(updatedPara?.quality_records).toEqual([{ score: 0.9, timestamp: '2024-01-01' }])
    expect(updatedPara?.routing_decision).toEqual({ engine: 'edge', voice: 'zh-CN-XiaoxiaoNeural' })
    expect(updatedPara?.annotations_full).toEqual({ speaker: 'narrator', notes: 'test' })
  })

  it('handles fetchParagraphDetail error gracefully', async () => {
    const { useChapterTimeline } = await import('@/composables/useChapterTimeline')
    const timeline = useChapterTimeline()

    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetchParagraphDetail.mockRejectedValue(new Error('Network error'))

    timeline.selectParagraph(1)

    await new Promise(resolve => setTimeout(resolve, 0))
    await new Promise(resolve => setTimeout(resolve, 10))

    // Should not throw, just log error
    expect(consoleError).toHaveBeenCalledWith('Failed to fetch paragraph detail:', expect.any(Error))

    consoleError.mockRestore()
  })

  it('does not call fetchParagraphDetail when paragraph not found in store', async () => {
    const { useChapterTimeline } = await import('@/composables/useChapterTimeline')
    const timeline = useChapterTimeline()

    // Select non-existent paragraph
    timeline.selectParagraph(999)

    await new Promise(resolve => setTimeout(resolve, 0))

    // Should not call fetchParagraphDetail
    expect(mockFetchParagraphDetail).not.toHaveBeenCalled()
  })

  it('updates existing paragraph with detail data preserving original fields', async () => {
    const { useChapterTimeline } = await import('@/composables/useChapterTimeline')
    const timeline = useChapterTimeline()

    const detailResponse = {
      id: 1,
      project_id: 1,
      chapter_id: 1,
      index: 0,
      text: 'Test paragraph 1 updated',
      emotion: 'excited',
      tts_edit_history: [{ edit: 'test', timestamp: '2024-01-01' }],
      quality_records: [],
      routing_decision: null,
      annotations_full: null,
    }

    mockFetchParagraphDetail.mockResolvedValue(detailResponse)

    timeline.selectParagraph(1)

    await new Promise(resolve => setTimeout(resolve, 0))
    await new Promise(resolve => setTimeout(resolve, 10))

    const updatedPara = mockParagraphsData.find(p => p.id === 1)
    expect(updatedPara).toBeDefined()
    // Original fields should be preserved or updated
    expect(updatedPara?.id).toBe(1)
    expect(updatedPara?.project_id).toBe(1)
    expect(updatedPara?.chapter_id).toBe(1)
    // New fields should be added
    expect(updatedPara?.tts_edit_history).toEqual([{ edit: 'test', timestamp: '2024-01-01' }])
  })
})