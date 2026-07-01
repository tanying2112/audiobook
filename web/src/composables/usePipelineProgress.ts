import { ref, onUnmounted } from 'vue'
import { streamPipelineEvents, type PipelineEventCallbacks } from '../api/sse'
import type { PipelineStage } from '../types/pipeline'

export interface PipelineProgressState {
  /** 当前活动阶段 */
  currentStage: PipelineStage | null
  /** 当前处理的章节 ID */
  currentChapterId: number | null
  /** 当前阶段进度 0-1 */
  stageProgress: number
  /** 已完成的阶段列表 */
  completedStages: PipelineStage[]
  /** 管线是否正在运行 */
  isRunning: boolean
  /** 管线是否暂停 */
  isPaused: boolean
  /** 错误信息 */
  error: string | null
  /** 最后更新时间 */
  lastUpdate: Date | null
}

export interface UsePipelineProgressOptions {
  projectId: number
  /** 是否自动连接 */
  autoConnect?: boolean
  /** 连接成功回调 */
  onConnected?: () => void
  /** 章节完成回调 */
  onChapterComplete?: (chapterId: number) => void
  /** 段落完成回调 */
  onParagraphComplete?: (chapterId: number, paragraphIndex: number) => void
}

/**
 * 管线进度订阅 Composable
 *
 * 通过 WebSocket 实时接收管线阶段进度事件:
 * - stage_enter: 阶段开始
 * - stage_progress: 阶段进度更新
 * - stage_exit: 阶段结束
 * - chapter_complete: 章节完成
 * - paragraph_complete: 段落完成
 * - completed: 管线完成
 * - paused/resumed: 暂停/恢复
 * - error: 错误
 */
export function usePipelineProgress(options: UsePipelineProgressOptions) {
  const {
    projectId,
    autoConnect = true,
    onChapterComplete,
    onParagraphComplete,
  } = options

  const state = ref<PipelineProgressState>({
    currentStage: null,
    currentChapterId: null,
    stageProgress: 0,
    completedStages: [],
    isRunning: false,
    isPaused: false,
    error: null,
    lastUpdate: null,
  })

  let unsubscribe: (() => void) | null = null

  const callbacks: PipelineEventCallbacks = {
    onStageEnter: (stage, chapterId) => {
      state.value.currentStage = stage as PipelineStage
      state.value.currentChapterId = chapterId
      state.value.stageProgress = 0
      state.value.isRunning = true
      state.value.error = null
      state.value.lastUpdate = new Date()
    },
    onStageProgress: (stage, chapterId, progress) => {
      if (state.value.currentStage === stage && state.value.currentChapterId === chapterId) {
        state.value.stageProgress = Math.max(0, Math.min(1, progress))
        state.value.lastUpdate = new Date()
      }
    },
    onStageExit: (stage, chapterId) => {
      if (state.value.currentStage === stage && state.value.currentChapterId === chapterId) {
        const completedStages = [...state.value.completedStages]
        if (!completedStages.includes(stage as PipelineStage)) {
          completedStages.push(stage as PipelineStage)
        }
        state.value.completedStages = completedStages
        state.value.stageProgress = 1
        state.value.lastUpdate = new Date()
      }
    },
    onChapterComplete: (chapterId) => {
      state.value.currentChapterId = null
      state.value.stageProgress = 0
      state.value.lastUpdate = new Date()
      onChapterComplete?.(chapterId)
    },
    onParagraphComplete: (chapterId, paragraphIndex) => {
      state.value.lastUpdate = new Date()
      onParagraphComplete?.(chapterId, paragraphIndex)
    },
    onPipelineEnd: (_projectId) => {
      state.value.isRunning = false
      state.value.currentStage = null
      state.value.currentChapterId = null
      state.value.stageProgress = 1
      state.value.lastUpdate = new Date()
    },
    onPaused: () => {
      state.value.isPaused = true
      state.value.lastUpdate = new Date()
    },
    onResumed: () => {
      state.value.isPaused = false
      state.value.lastUpdate = new Date()
    },
    onError: (message) => {
      state.value.error = message
      state.value.isRunning = false
      state.value.lastUpdate = new Date()
    },
  }

  /** 连接 WebSocket */
  function connect(): void {
    if (unsubscribe) return
    unsubscribe = streamPipelineEvents(projectId, callbacks)
  }

  /** 断开连接 */
  function disconnect(): void {
    if (unsubscribe) {
      unsubscribe()
      unsubscribe = null
    }
    state.value.isRunning = false
  }

  /** 重置状态 */
  function reset(): void {
    disconnect()
    state.value = {
      currentStage: null,
      currentChapterId: null,
      stageProgress: 0,
      completedStages: [],
      isRunning: false,
      isPaused: false,
      error: null,
      lastUpdate: null,
    }
  }

  /** 获取整体进度 (0-1) */
  function getOverallProgress(): number {
    const completedCount = state.value.completedStages.length
    const currentStage = state.value.currentStage
    const totalStages = 7

    if (currentStage) {
      return (completedCount + state.value.stageProgress) / totalStages
    }
    return completedCount / totalStages
  }

  /** 检查阶段是否已完成 */
  function isStageCompleted(stage: PipelineStage): boolean {
    return state.value.completedStages.includes(stage)
  }

  /** 检查阶段是否正在进行 */
  function isStageActive(stage: PipelineStage): boolean {
    return state.value.currentStage === stage
  }

  // 自动连接
  if (autoConnect) {
    connect()
  }

  // 组件卸载时断开
  onUnmounted(disconnect)

  return {
    // 状态
    state,
    // 计算属性
    getOverallProgress,
    isStageCompleted,
    isStageActive,
    // 方法
    connect,
    disconnect,
    reset,
  }
}