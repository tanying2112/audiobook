/**
 * WebSocket 客户端 - 管线实时进度推送
 *
 * 连接 /ws/pipeline/{project_id} 接收实时阶段事件:
 * - stage_enter: 阶段开始
 * - stage_progress: 阶段进度更新
 * - stage_exit: 阶段结束
 * - chapter_complete: 章节完成
 * - paragraph_complete: 段落完成
 * - error: 错误事件
 * - paused/resumed: 暂停/恢复
 * - completed: 管线完成
 * - keepalive: 心跳
 */

import type { PipelineStage } from '../types/pipeline'

export interface PipelineEvent {
  type: string
  project_id: number
  timestamp: string
  stage?: PipelineStage
  chapter_id?: number
  paragraph_index?: number
  progress?: number
  data?: Record<string, unknown>
}

export interface PipelineEventCallbacks {
  onStageEnter?: (stage: PipelineStage, chapterId: number) => void
  onStageProgress?: (stage: PipelineStage, chapterId: number, progress: number) => void
  onStageExit?: (stage: PipelineStage, chapterId: number) => void
  onChapterComplete?: (chapterId: number) => void
  onParagraphComplete?: (chapterId: number, paragraphIndex: number) => void
  onPipelineEnd?: (projectId: number) => void
  onPaused?: () => void
  onResumed?: () => void
  onError?: (message: string) => void
  onConnected?: () => void
  onKeepalive?: () => void
}

export interface WebSocketClientOptions {
  projectId: number
  callbacks: PipelineEventCallbacks
  autoReconnect?: boolean
  reconnectIntervalMs?: number
  maxReconnectAttempts?: number
}

type WebSocketState = 'connecting' | 'connected' | 'disconnected' | 'reconnecting'

export class PipelineWebSocketClient {
  private ws: WebSocket | null = null
  private readonly options: Required<WebSocketClientOptions>
  private state: WebSocketState = 'disconnected'
  private reconnectAttempts = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private keepaliveTimer: ReturnType<typeof setTimeout> | null = null

  constructor(options: WebSocketClientOptions) {
    this.options = {
      projectId: options.projectId,
      callbacks: options.callbacks,
      autoReconnect: options.autoReconnect ?? true,
      reconnectIntervalMs: options.reconnectIntervalMs ?? 3000,
      maxReconnectAttempts: options.maxReconnectAttempts ?? 10,
    }
  }

  /** 获取 WebSocket URL (支持 Vite proxy / 生产环境) */
  private getWsUrl(): string {
    const base = import.meta.env.VITE_API_BASE || ''
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = base ? new URL(base, window.location.origin).host : window.location.host
    return `${protocol}//${host}/api/ws/pipeline/${this.options.projectId}`
  }

  /** 建立连接 */
  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) {
      return
    }

    this.state = 'connecting'
    const url = this.getWsUrl()

    try {
      this.ws = new WebSocket(url)
    } catch (err) {
      this.handleError(`创建 WebSocket 失败: ${err}`)
      this.scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      this.state = 'connected'
      this.reconnectAttempts = 0
      this.startKeepalive()
      this.options.callbacks.onConnected?.()
    }

    this.ws.onmessage = (event) => {
      this.handleMessage(event.data)
    }

    this.ws.onclose = () => {
      this.state = 'disconnected'
      this.stopKeepalive()
      if (this.options.autoReconnect) {
        this.scheduleReconnect()
      }
    }

    this.ws.onerror = (err) => {
      this.handleError(`WebSocket 错误: ${err}`)
    }
  }

  /** 处理接收到的消息 */
  private handleMessage(data: string): void {
    try {
      const event: PipelineEvent = JSON.parse(data)
      this.dispatchEvent(event)
    } catch {
      // 忽略非 JSON 消息
    }
  }

  /** 分发事件到对应回调 */
  private dispatchEvent(event: PipelineEvent): void {
    const { type, stage, chapter_id, paragraph_index, progress } = event

    switch (type) {
      case 'stage_enter':
        if (stage && chapter_id !== undefined) {
          this.options.callbacks.onStageEnter?.(stage, chapter_id)
        }
        break
      case 'stage_progress':
        if (stage && chapter_id !== undefined && progress !== undefined) {
          this.options.callbacks.onStageProgress?.(stage, chapter_id, progress)
        }
        break
      case 'stage_exit':
        if (stage && chapter_id !== undefined) {
          this.options.callbacks.onStageExit?.(stage, chapter_id)
        }
        break
      case 'chapter_complete':
        if (chapter_id !== undefined) {
          this.options.callbacks.onChapterComplete?.(chapter_id)
        }
        break
      case 'paragraph_complete':
        if (chapter_id !== undefined && paragraph_index !== undefined) {
          this.options.callbacks.onParagraphComplete?.(chapter_id, paragraph_index)
        }
        break
      case 'completed':
        this.options.callbacks.onPipelineEnd?.(event.project_id)
        break
      case 'paused':
        this.options.callbacks.onPaused?.()
        break
      case 'resumed':
        this.options.callbacks.onResumed?.()
        break
      case 'error':
        this.options.callbacks.onError?.(event.data?.message as string ?? '未知错误')
        break
      case 'keepalive':
        this.options.callbacks.onKeepalive?.()
        break
    }
  }

  /** 发送消息 */
  send(type: string, payload?: Record<string, unknown>): boolean {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, ...payload }))
      return true
    }
    return false
  }

  /** 请求暂停管线 */
  pause(): boolean {
    return this.send('pause')
  }

  /** 请求恢复管线 */
  resume(): boolean {
    return this.send('resume')
  }

  /** 请求状态 */
  requestStatus(): boolean {
    return this.send('status')
  }

  /** 断开连接 */
  disconnect(): void {
    this.options.autoReconnect = false
    this.stopKeepalive()
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    this.state = 'disconnected'
  }

  /** 获取连接状态 */
  getState(): WebSocketState {
    return this.state
  }

  /** 是否已连接 */
  isConnected(): boolean {
    return this.state === 'connected' && this.ws?.readyState === WebSocket.OPEN
  }

  /** 启动心跳检测 */
  private startKeepalive(): void {
    this.stopKeepalive()
    this.keepaliveTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }))
      }
    }, 25000)
  }

  /** 停止心跳检测 */
  private stopKeepalive(): void {
    if (this.keepaliveTimer) {
      clearInterval(this.keepaliveTimer)
      this.keepaliveTimer = null
    }
  }

  /** 处理错误 */
  private handleError(message: string): void {
    this.options.callbacks.onError?.(message)
  }

  /** 调度重连 */
  private scheduleReconnect(): void {
    if (!this.options.autoReconnect) return
    if (this.reconnectAttempts >= this.options.maxReconnectAttempts) {
      this.handleError('达到最大重连次数，放弃重连')
      return
    }

    this.state = 'reconnecting'
    this.reconnectAttempts++

    this.reconnectTimer = setTimeout(() => {
      this.connect()
    }, this.options.reconnectIntervalMs)
  }
}

/** 创建 WebSocket 客户端的工厂函数 */
export function createPipelineWebSocketClient(
  options: WebSocketClientOptions,
): PipelineWebSocketClient {
  return new PipelineWebSocketClient(options)
}