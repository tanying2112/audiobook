/**
 * useSopCorrection — SOP 修正捕获 Composable
 *
 * 核心功能：
 * - WebSocket 实时连接 ws://host/sop/corrections/ws
 * - 心跳保活 (30s ping/pong)
 * - 指数退避自动重连 (1s, 2s, 4s, 8s... max 30s, 最多 10 次)
 * - 连接状态机: connecting | connected | disconnected | reconnecting
 * - 防抖队列: 按 project_id 聚合，500ms 刷新，同段落/字段保留最新
 * - HTTP 静默回退: WS 彻底失败后自动切换 POST /api/sop/corrections
 * - 无 UI 阻塞，回退对用户透明
 *
 * 集成点：
 * - ParagraphEditor.vue: emotion/speech_rate 保存时调用 sendCorrection
 * - CharacterManager.vue: voice binding 变更时调用 sendCorrection
 */

import { ref, onUnmounted, type Ref } from 'vue'
import {
  createSopCorrectionClient,
  type SopCorrectionWebSocketClient,
  type SopCorrectionMessage,
  type SopConnectionState,
  type SopCorrectionCallbacks,
} from '../api/sopCorrection'
import type { BookGenre } from '../types'

// ── Debounce Queue ─────────────────────────────────────────────────────────

interface QueuedCorrection {
  correction: SopCorrectionMessage
  timestamp: number
  resolve: (sent: boolean) => void
}

interface DebounceQueueOptions {
  /** 队列刷新间隔(ms)，默认 500ms */
  flushIntervalMs?: number
  /** 合并键：用于判断同一段落/字段的最新修正 */
  getMergeKey?: (correction: SopCorrectionMessage) => string
}

const DEFAULT_FLUSH_INTERVAL = 500

/**
 * 防抖队列管理器：聚合同项目的修正，定期刷新，保留最新值
 */
class SopCorrectionDebounceQueue {
  private projectQueues = new Map<number, Map<string, QueuedCorrection>>() // projectId -> queue
  private flushTimer: ReturnType<typeof setInterval> | null = null
  private readonly options: Required<DebounceQueueOptions>
  private readonly sendFn: (correction: SopCorrectionMessage) => boolean

  constructor(
    sendFn: (correction: SopCorrectionMessage) => boolean,
    options: DebounceQueueOptions = {},
  ) {
    this.sendFn = sendFn
    this.options = {
      flushIntervalMs: options.flushIntervalMs ?? DEFAULT_FLUSH_INTERVAL,
      getMergeKey: options.getMergeKey ?? ((c) => `${c.chapter_index}-${c.paragraph_index}-${c.field}`),
    }
    this.startFlushTimer()
  }

  /** 添加修正到队列 */
  enqueue(correction: SopCorrectionMessage): Promise<boolean> {
    return new Promise((resolve) => {
      const projectId = correction.project_id
      const mergeKey = this.options.getMergeKey(correction)

      let projectQueue = this.projectQueues.get(projectId)
      if (!projectQueue) {
        projectQueue = new Map()
        this.projectQueues.set(projectId, projectQueue)
      }

      // 同一 mergeKey 保留最新
      projectQueue.set(mergeKey, {
        correction,
        timestamp: Date.now(),
        resolve,
      })
    })
  }

  /** 刷新所有队列 */
  flush(): void {
    for (const [_projectId, projectQueue] of this.projectQueues) {
      if (projectQueue.size === 0) continue

      // 取每个 mergeKey 的最新值发送
      for (const [, queued] of projectQueue) {
        const sent = this.sendFn(queued.correction)
        queued.resolve(sent)
      }
      projectQueue.clear()
    }
  }

  /** 获取指定项目的待发送数量 */
  getPendingCount(projectId: number): number {
    return this.projectQueues.get(projectId)?.size ?? 0
  }

  /** 获取所有待发送总数 */
  getTotalPendingCount(): number {
    let total = 0
    for (const queue of this.projectQueues.values()) {
      total += queue.size
    }
    return total
  }

  /** 启动定时刷新 */
  private startFlushTimer(): void {
    this.flushTimer = setInterval(() => this.flush(), this.options.flushIntervalMs)
  }

  /** 停止并清理 */
  destroy(): void {
    if (this.flushTimer) {
      clearInterval(this.flushTimer)
      this.flushTimer = null
    }
    // 刷新剩余
    this.flush()
    this.projectQueues.clear()
  }
}

// ── Composable Types ───────────────────────────────────────────────────────

export interface UseSopCorrectionOptions {
  /** 项目 ID */
  projectId: number
  /** 书籍体裁 */
  genre: BookGenre
  /** 是否自动连接，默认 true */
  autoConnect?: boolean
  /** 防抖刷新间隔(ms)，默认 500ms */
  debounceFlushIntervalMs?: number
  /** 自定义合并键生成器 */
  getMergeKey?: (correction: SopCorrectionMessage) => string
  /** 连接成功回调 */
  onConnected?: () => void
  /** 连接关闭回调 */
  onDisconnected?: (code: number, reason: string) => void
  /** 错误回调 */
  onError?: (error: Error) => void
  /** 收到修正回调（可用于本地状态同步） */
  onCorrectionReceived?: (correction: SopCorrectionMessage) => void
  /** 确认回调 */
  onAckReceived?: (ack: { correction_id: string; status: string }) => void
  /** 回退到 HTTP 模式回调 */
  onFallback?: (reason: string) => void
  /** 连接状态变化回调 */
  onStateChange?: (state: SopConnectionState) => void
}

export interface UseSopCorrectionReturn {
  /** 连接状态 */
  connectionState: Ref<SopConnectionState>
  /** 是否正在使用 HTTP 回退 */
  isUsingFallback: Ref<boolean>
  /** 待发送队列长度 */
  pendingCount: Ref<number>
  /** 发送修正 */
  sendCorrection: (
    field: string,
    originalValue: string,
    correctedValue: string,
    paragraphIndex: number,
    chapterIndex: number,
    context?: string,
  ) => Promise<boolean>
  /** 手动连接 */
  connect: () => void
  /** 手动断开 */
  disconnect: () => void
  /** 重置并重连 */
  reset: () => void
}

// ── Composable ─────────────────────────────────────────────────────────────

export function useSopCorrection(options: UseSopCorrectionOptions): UseSopCorrectionReturn {
  const {
    projectId,
    genre,
    autoConnect = true,
    debounceFlushIntervalMs = DEFAULT_FLUSH_INTERVAL,
    getMergeKey,
    onConnected,
    onDisconnected,
    onError,
    onCorrectionReceived,
    onAckReceived,
    onFallback,
    onStateChange,
  } = options

  // ── 响应式状态 ───────────────────────────────────────────────────────────
  const connectionState = ref<SopConnectionState>('disconnected')
  const isUsingFallback = ref<boolean>(false)
  const pendingCount = ref<number>(0)

  // ── 内部实例 ─────────────────────────────────────────────────────────────
  let client: SopCorrectionWebSocketClient | null = null
  let debounceQueue: SopCorrectionDebounceQueue | null = null

  // ── 回调处理 ─────────────────────────────────────────────────────────────
  const callbacks: SopCorrectionCallbacks = {
    onOpen: () => {
      connectionState.value = 'connected'
      onConnected?.()
    },
    onClose: (code, reason) => {
      connectionState.value = 'disconnected'
      onDisconnected?.(code, reason)
    },
    onError: (error) => {
      onError?.(error)
    },
    onCorrection: (correction) => {
      onCorrectionReceived?.(correction)
    },
    onAck: (ack) => {
      onAckReceived?.({ correction_id: ack.correction_id, status: ack.status })
    },
    onStateChange: (state) => {
      connectionState.value = state
      onStateChange?.(state)
    },
    onFallback: (reason) => {
      isUsingFallback.value = true
      onFallback?.(reason)
    },
  }

  // ── 初始化客户端与队列 ──────────────────────────────────────────────────
  function initClient(): void {
    if (client) return

    client = createSopCorrectionClient({
      projectId,
      genre,
      callbacks,
    })

    debounceQueue = new SopCorrectionDebounceQueue(
      (correction) => client!.sendCorrection(correction),
      {
        flushIntervalMs: debounceFlushIntervalMs,
        getMergeKey: getMergeKey ?? ((c) => `${c.chapter_index}-${c.paragraph_index}-${c.field}`),
      },
    )

    // 同步 pendingCount
    const syncPendingCount = () => {
      if (debounceQueue) {
        pendingCount.value = debounceQueue.getPendingCount(projectId)
      }
    }

    // 定期同步队列长度（每 200ms）
    const syncTimer = setInterval(syncPendingCount, 200)

    // 监听连接状态变化，连接时刷新队列
    const originalOnOpen = callbacks.onOpen
    callbacks.onOpen = () => {
      originalOnOpen?.()
      debounceQueue?.flush()
    }

    // 存储定时器以便清理
    ;(client as any)._syncTimer = syncTimer
  }

  // ── 公共方法 ─────────────────────────────────────────────────────────────

  /** 发送 SOP 修正 */
  async function sendCorrection(
    field: string,
    originalValue: string,
    correctedValue: string,
    paragraphIndex: number,
    chapterIndex: number,
    context?: string,
  ): Promise<boolean> {
    if (!client || !debounceQueue) {
      initClient()
    }

    const correction: SopCorrectionMessage = {
      type: 'correction',
      project_id: projectId,
      chapter_index: chapterIndex,
      paragraph_index: paragraphIndex,
      field,
      original_value: originalValue,
      corrected_value: correctedValue,
      genre,
      context,
      timestamp: new Date().toISOString(),
    }

    // 通过防抖队列发送
    return debounceQueue!.enqueue(correction)
  }

  /** 手动连接 */
  function connect(): void {
    if (!client) initClient()
    client!.connect()
  }

  /** 手动断开 */
  function disconnect(): void {
    client?.disconnect()
  }

  /** 重置并重连 */
  function reset(): void {
    isUsingFallback.value = false
    client?.reset()
  }

  // ── 自动连接 ─────────────────────────────────────────────────────────────
  if (autoConnect) {
    // 延迟初始化，避免在组件创建时立即连接
    queueMicrotask(() => {
      initClient()
      connect()
    })
  }

  // ── 组件卸载清理 ─────────────────────────────────────────────────────────
  onUnmounted(() => {
    if (client) {
      const syncTimer = (client as any)._syncTimer
      if (syncTimer) clearInterval(syncTimer)
      client.disconnect()
      client = null
    }
    debounceQueue?.destroy()
    debounceQueue = null
  })

  // ── 派生状态：监听 projectId/genre 变化重新初始化 ────────────────────────
  // 注意：当前设计假设 projectId/genre 在 composable 生命周期内不变
  // 如需支持动态切换，可在此添加 watch 逻辑

  return {
    // 状态
    connectionState,
    isUsingFallback,
    pendingCount,
    // 方法
    sendCorrection,
    connect,
    disconnect,
    reset,
  }
}

// ── 辅助导出 ────────────────────────────────────────────────────────────────

/** 创建修正消息的工厂函数（供调用方构建自定义 payload） */
export function createSopCorrectionMessage(
  projectId: number,
  genre: BookGenre,
  field: string,
  originalValue: string,
  correctedValue: string,
  paragraphIndex: number,
  chapterIndex: number,
  context?: string,
): SopCorrectionMessage {
  return {
    type: 'correction',
    project_id: projectId,
    chapter_index: chapterIndex,
    paragraph_index: paragraphIndex,
    field,
    original_value: originalValue,
    corrected_value: correctedValue,
    genre,
    context,
    timestamp: new Date().toISOString(),
  }
}