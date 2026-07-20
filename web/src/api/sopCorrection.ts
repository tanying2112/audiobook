/**
 * SOP Correction WebSocket Client & HTTP Fallback
 *
 * Connects to ws://host/sop/corrections/ws for real-time SOP correction streaming
 * with heartbeat, auto-reconnect (exponential backoff), and HTTP fallback.
 */

import type { BookGenre } from '../types'

export type { BookGenre }

// ── Message Types ──────────────────────────────────────────────────────────

export interface SopCorrectionMessage {
  type: 'correction'
  project_id: number
  chapter_index: number
  paragraph_index: number
  field: string
  original_value: string
  corrected_value: string
  genre: BookGenre
  context?: string
  timestamp: string
}

export interface SopPingMessage {
  type: 'ping'
  timestamp: string
}

export interface SopPongMessage {
  type: 'pong'
  timestamp: string
}

export interface SopAckMessage {
  type: 'ack'
  correction_id: string
  status: 'accepted' | 'rejected'
  message?: string
}

export interface SopErrorMessage {
  type: 'error'
  code: string
  message: string
}

export type SopWsMessage =
  | SopCorrectionMessage
  | SopPingMessage
  | SopPongMessage
  | SopAckMessage
  | SopErrorMessage

// ── HTTP Fallback Types ────────────────────────────────────────────────────

export interface SopCorrectionRequest {
  project_id: number
  chapter_index: number
  paragraph_index: number
  field: string
  original_value: string
  corrected_value: string
  genre: BookGenre
  context?: string
}

export interface SopCorrectionResponse {
  correction_id: string
  status: 'accepted' | 'rejected'
  message?: string
}

// ── Connection State ───────────────────────────────────────────────────────

export type SopConnectionState = 'connecting' | 'connected' | 'disconnected' | 'reconnecting'

export interface SopCorrectionCallbacks {
  onOpen?: () => void
  onClose?: (code: number, reason: string) => void
  onError?: (error: Error) => void
  onCorrection?: (correction: SopCorrectionMessage) => void
  onAck?: (ack: SopAckMessage) => void
  onStateChange?: (state: SopConnectionState) => void
  onFallback?: (reason: string) => void
}

// ── WebSocket Client ───────────────────────────────────────────────────────

interface SopWebSocketClientOptions {
  projectId: number
  genre: BookGenre
  callbacks: SopCorrectionCallbacks
  /** 心跳间隔(ms)，默认 30s */
  heartbeatIntervalMs?: number
  /** 最大重连次数，默认 10 */
  maxReconnectAttempts?: number
  /** 重连基础间隔(ms)，指数退避，默认 1000ms */
  baseReconnectIntervalMs?: number
  /** 最大重连间隔(ms)，默认 30000ms */
  maxReconnectIntervalMs?: number
  /** WebSocket URL（可选，默认自动构建） */
  wsUrl?: string
  /** HTTP 回退端点 */
  httpFallbackUrl?: string
}

const DEFAULT_HEARTBEAT_INTERVAL = 30_000
const DEFAULT_MAX_RECONNECT_ATTEMPTS = 10
const DEFAULT_BASE_RECONNECT_INTERVAL = 1_000
const DEFAULT_MAX_RECONNECT_INTERVAL = 30_000

export class SopCorrectionWebSocketClient {
  private ws: WebSocket | null = null
  private readonly options: Required<SopWebSocketClientOptions>
  private state: SopConnectionState = 'disconnected'
  private reconnectAttempts = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private isIntentionallyClosed = false
  private pendingQueue: SopCorrectionMessage[] = []
  private isUsingFallback = false

  constructor(options: SopWebSocketClientOptions) {
    this.options = {
      projectId: options.projectId,
      genre: options.genre,
      callbacks: options.callbacks,
      heartbeatIntervalMs: options.heartbeatIntervalMs ?? DEFAULT_HEARTBEAT_INTERVAL,
      maxReconnectAttempts: options.maxReconnectAttempts ?? DEFAULT_MAX_RECONNECT_ATTEMPTS,
      baseReconnectIntervalMs: options.baseReconnectIntervalMs ?? DEFAULT_BASE_RECONNECT_INTERVAL,
      maxReconnectIntervalMs: options.maxReconnectIntervalMs ?? DEFAULT_MAX_RECONNECT_INTERVAL,
      wsUrl: options.wsUrl ?? this.buildDefaultWsUrl(options.projectId),
      httpFallbackUrl: options.httpFallbackUrl ?? this.buildDefaultHttpUrl(options.projectId),
    }
  }

  /** 构建默认 WebSocket URL */
  private buildDefaultWsUrl(projectId: number): string {
    const base = import.meta.env.VITE_API_BASE || ''
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = base ? new URL(base, window.location.origin).host : window.location.host
    return `${protocol}//${host}/api/sop/corrections/ws/${projectId}`
  }

  /** 构建默认 HTTP 回退 URL */
  private buildDefaultHttpUrl(projectId: number): string {
    const base = import.meta.env.VITE_API_BASE || ''
    return `${base}/api/sop/corrections/${projectId}`
  }

  /** 获取当前连接状态 */
  getState(): SopConnectionState {
    return this.state
  }

  /** 是否正在使用 HTTP 回退 */
  getIsUsingFallback(): boolean {
    return this.isUsingFallback
  }

  /** 设置连接状态并通知回调 */
  private setState(state: SopConnectionState): void {
    if (this.state !== state) {
      this.state = state
      this.options.callbacks.onStateChange?.(state)
    }
  }

  /** 发送心跳 ping */
  private sendPing(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      const ping: SopPingMessage = {
        type: 'ping',
        timestamp: new Date().toISOString(),
      }
      this.ws.send(JSON.stringify(ping))
    }
  }

  /** 启动心跳定时器 */
  private startHeartbeat(): void {
    this.stopHeartbeat()
    this.heartbeatTimer = setInterval(() => this.sendPing(), this.options.heartbeatIntervalMs)
  }

  /** 停止心跳定时器 */
  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  /** 建立 WebSocket 连接 */
  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) {
      return
    }

    this.isIntentionallyClosed = false
    this.setState('connecting')

    try {
      this.ws = new WebSocket(this.options.wsUrl)
    } catch (err) {
      this.handleError(err instanceof Error ? err : new Error(String(err)))
      this.scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      this.setState('connected')
      this.reconnectAttempts = 0
      this.startHeartbeat()
      this.options.callbacks.onOpen?.()
      this.flushPendingQueue()
    }

    this.ws.onmessage = (event) => {
      this.handleMessage(event.data)
    }

    this.ws.onclose = (event) => {
      this.stopHeartbeat()
      this.setState('disconnected')
      this.options.callbacks.onClose?.(event.code, event.reason)

      if (!this.isIntentionallyClosed && this.options.callbacks.onFallback) {
        if (this.reconnectAttempts < this.options.maxReconnectAttempts) {
          this.scheduleReconnect()
        } else {
          this.enableHttpFallback('达到最大重连次数，切换到 HTTP 回退模式')
        }
      }
    }

    this.ws.onerror = (event) => {
      const error = new Error(`WebSocket 错误: ${event.type}`)
      this.handleError(error)
    }
  }

  /** 处理接收到的消息 */
  private handleMessage(data: string): void {
    try {
      const message: SopWsMessage = JSON.parse(data)

      switch (message.type) {
        case 'pong':
          // 心跳响应，无需处理
          break
        case 'correction':
          this.options.callbacks.onCorrection?.(message)
          // 发送确认
          this.sendAck(message)
          break
        case 'ack':
          this.options.callbacks.onAck?.(message)
          break
        case 'error':
          this.options.callbacks.onError?.(new Error(message.message))
          break
      }
    } catch {
      // 忽略非 JSON 消息
    }
  }

  /** 发送确认消息 */
  private sendAck(correction: SopCorrectionMessage): void {
    const ack: SopAckMessage = {
      type: 'ack',
      correction_id: `${correction.project_id}-${correction.chapter_index}-${correction.paragraph_index}-${correction.field}-${Date.now()}`,
      status: 'accepted',
    }
    this.send(ack)
  }

  /** 处理错误 */
  private handleError(error: Error): void {
    this.options.callbacks.onError?.(error)
  }

  /** 调度重连（指数退避） */
  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.options.maxReconnectAttempts) {
      this.enableHttpFallback('达到最大重连次数')
      return
    }

    this.setState('reconnecting')
    this.reconnectAttempts++

    // 指数退避：1s, 2s, 4s, 8s... 最大 30s
    const delay = Math.min(
      this.options.baseReconnectIntervalMs * 2 ** (this.reconnectAttempts - 1),
      this.options.maxReconnectIntervalMs,
    )

    this.reconnectTimer = setTimeout(() => {
      this.connect()
    }, delay)
  }

  /** 启用 HTTP 回退模式 */
  private enableHttpFallback(reason: string): void {
    if (!this.isUsingFallback) {
      this.isUsingFallback = true
      this.options.callbacks.onFallback?.(reason)
    }
  }

  /** 发送消息 */
  send(message: SopWsMessage | SopCorrectionMessage): boolean {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message))
      return true
    }

    // 连接未建立或已断开，加入待发送队列
    if (message.type === 'correction') {
      this.pendingQueue.push(message as SopCorrectionMessage)
    }
    return false
  }

  /** 刷新待发送队列 */
  private flushPendingQueue(): void {
    while (this.pendingQueue.length > 0) {
      const msg = this.pendingQueue.shift()
      if (msg) this.send(msg)
    }
  }

  /** 发送 SOP 修正（核心方法） */
  sendCorrection(correction: SopCorrectionMessage): boolean {
    // 如果正在使用 HTTP 回退，直接发 HTTP
    if (this.isUsingFallback) {
      this.sendHttpFallback(correction)
      return true
    }

    // 尝试 WebSocket 发送
    const sent = this.send(correction)

    // 发送失败且未在队列中，尝试 HTTP 回退
    if (!sent && !this.pendingQueue.some((m) => m.field === correction.field && m.paragraph_index === correction.paragraph_index)) {
      this.sendHttpFallback(correction)
    }

    return true
  }

  /** HTTP 回退发送 */
  private async sendHttpFallback(correction: SopCorrectionMessage): Promise<void> {
    try {
      const payload: SopCorrectionRequest = {
        project_id: correction.project_id,
        chapter_index: correction.chapter_index,
        paragraph_index: correction.paragraph_index,
        field: correction.field,
        original_value: correction.original_value,
        corrected_value: correction.corrected_value,
        genre: correction.genre,
        context: correction.context,
      }

      await fetch(this.options.httpFallbackUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
    } catch (err) {
      this.options.callbacks.onError?.(err instanceof Error ? err : new Error(String(err)))
    }
  }

  /** 断开连接 */
  disconnect(): void {
    this.isIntentionallyClosed = true
    this.stopHeartbeat()

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    if (this.ws) {
      this.ws.close(1000, 'Client disconnect')
      this.ws = null
    }

    this.setState('disconnected')
  }

  /** 重置客户端（重新连接） */
  reset(): void {
    this.disconnect()
    this.isUsingFallback = false
    this.reconnectAttempts = 0
    this.pendingQueue = []
    this.connect()
  }
}

/** 创建 SOP 修正 WebSocket 客户端工厂函数 */
export function createSopCorrectionClient(options: SopWebSocketClientOptions): SopCorrectionWebSocketClient {
  return new SopCorrectionWebSocketClient(options)
}

/** 创建 SOP 修正消息工厂函数（供测试和外部构建 payload 使用） */
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