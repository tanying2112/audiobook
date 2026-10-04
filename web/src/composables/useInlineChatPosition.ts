/**
 * useInlineChatPosition — Cursor 风格内联小窗定位算法
 *
 * 解决当前 SseDemo.vue 的 4 个定位缺陷：
 *   1. 一次性 rect 快照 → 页面滚动/缩放后小窗飘移
 *   2. 无边界检测 → 选区在右侧边缘时溢出视口
 *   3. 无翻转逻辑 → 选区在底部时小窗被推到视口外
 *   4. 无锚点跟随 → 滚动时锚点已移走但小窗不动
 *
 * 核心思路：
 *   - 用 requestAnimationFrame 循环实时读取锚点元素位置（而非快照）
 *   - 计算理想位置后做视口边界碰撞检测，自动翻转/夹紧
 *   - 监听 scroll/resize 事件（含捕获模式，捕获内层滚动容器）
 *   - 锚点元素不可见（滚出视口）时自动隐藏小窗，滚回时恢复
 */

import { ref, computed, watch, onUnmounted, type Ref, type ComputedRef } from 'vue'

/** 小窗尺寸假设（用于翻转判定；实际可用 ref 测量真实高度） */
export interface PopoverSize {
  width: number
  height: number
}

/** 定位结果 */
export interface PopoverPosition {
  /** 应用到 popover 的 CSS style 对象 */
  style: Record<string, string>
  /** 当前放置方向（用于渲染箭头指向） */
  placement: 'right' | 'left' | 'bottom' | 'top'
  /** 锚点是否仍在视口内（false 时应隐藏小窗） */
  anchorVisible: boolean
}

export interface UseInlineChatPositionOptions {
  /** 小窗预估尺寸（翻转判定用） */
  popoverSize?: Ref<PopoverSize> | ComputedRef<PopoverSize> | PopoverSize
  /** 与锚点的间距（px） */
  gap?: number
  /** 距视口边缘的安全间距（px） */
  viewportMargin?: number
  /** 偏好方向优先级（默认右 > 左 > 下 > 上） */
  preferredPlacements?: Array<'right' | 'left' | 'bottom' | 'top'>
  /** 锚点元素是否激活（false 时不计算，停止 rAF） */
  active: Ref<boolean> | ComputedRef<boolean>
  /** 是否在锚点滚出视口时隐藏小窗（默认 true） */
  hideWhenAnchorOffscreen?: boolean
}

/** 默认偏好方向：右侧优先（Cursor 风格），不够空间依次回退 */
const DEFAULT_PREFERRED: Array<'right' | 'left' | 'bottom' | 'top'> = [
  'right',
  'left',
  'bottom',
  'top',
]

export function useInlineChatPosition(
  /** 锚点元素 ref（getBoundingClientRect 的真实来源） */
  anchorEl: Ref<HTMLElement | null>,
  options: UseInlineChatPositionOptions,
) {
  const gap = options.gap ?? 8
  const viewportMargin = options.viewportMargin ?? 12
  const preferred = options.preferredPlacements ?? DEFAULT_PREFERRED
  const hideWhenOffscreen = options.hideWhenAnchorOffscreen ?? true

  /** 当前计算出的定位 */
  const position = ref<PopoverPosition>({
    style: { display: 'none' },
    placement: 'right',
    anchorVisible: true,
  })

  let rafId: number | null = null

  /** 解析 popover 尺寸（支持 ref / computed / 字面量） */
  function resolveSize(): PopoverSize {
    const s = options.popoverSize
    if (!s) return { width: 380, height: 420 }
    if (isRefLike(s)) return (s as Ref<PopoverSize>).value
    return s as PopoverSize
  }

  function isRefLike(v: unknown): v is { value: unknown } {
    return v !== null && typeof v === 'object' && 'value' in v
  }

  /**
   * 核心定位计算：基于锚点 rect + 视口边界，选择最优 placement。
   */
  function compute(anchorRect: DOMRect, popover: PopoverSize): PopoverPosition {
    const vw = window.innerWidth
    const vh = window.innerHeight

    // 锚点是否在视口内（含一定容差）
    const anchorVisible =
      anchorRect.bottom > 0 &&
      anchorRect.top < vh &&
      anchorRect.right > 0 &&
      anchorRect.left < vw

    if (!anchorVisible && hideWhenOffscreen) {
      return { style: { display: 'none' }, placement: 'right', anchorVisible: false }
    }

    // 候选位置计算 + 边界检测
    for (const placement of preferred) {
      const candidate = computeCandidate(anchorRect, placement, popover, vw, vh)
      if (candidate.fits) {
        return {
          style: candidate.style,
          placement,
          anchorVisible: true,
        }
      }
    }

    // 所有方向都不完全放下 → 用首选方向，但夹紧到视口内
    const fallback = computeCandidate(anchorRect, preferred[0], popover, vw, vh)
    return {
      style: clampToViewport(fallback.style, popover, vw, vh),
      placement: preferred[0],
      anchorVisible: true,
    }
  }

  /** 计算单个 placement 方向的候选位置，返回是否完全放入视口 */
  function computeCandidate(
    anchorRect: DOMRect,
    placement: 'right' | 'left' | 'bottom' | 'top',
    popover: PopoverSize,
    vw: number,
    vh: number,
  ): { style: Record<string, string>; fits: boolean } {
    let top: number
    let left: number
    let fits = true

    switch (placement) {
      case 'right':
        left = anchorRect.right + gap
        top = anchorRect.top
        if (left + popover.width > vw - viewportMargin) fits = false
        break
      case 'left':
        left = anchorRect.left - gap - popover.width
        top = anchorRect.top
        if (left < viewportMargin) fits = false
        break
      case 'bottom':
        left = anchorRect.left
        top = anchorRect.bottom + gap
        if (top + popover.height > vh - viewportMargin) fits = false
        break
      case 'top':
        left = anchorRect.left
        top = anchorRect.top - gap - popover.height
        if (top < viewportMargin) fits = false
        break
    }

    // 垂直方向：超出底部时夹紧（但不改变 fits 判定，仅优化）
    if (top + popover.height > vh - viewportMargin) {
      top = Math.max(viewportMargin, vh - viewportMargin - popover.height)
    }
    if (top < viewportMargin) top = viewportMargin

    return {
      style: {
        position: 'fixed',
        left: `${Math.round(left)}px`,
        top: `${Math.round(top)}px`,
      },
      fits,
    }
  }

  /** 将位置夹紧到视口内（所有方向都不放下时的兜底） */
  function clampToViewport(
    style: Record<string, string>,
    popover: PopoverSize,
    vw: number,
    vh: number,
  ): Record<string, string> {
    let left = parseFloat(style.left) || 0
    let top = parseFloat(style.top) || 0
    left = Math.max(viewportMargin, Math.min(left, vw - viewportMargin - popover.width))
    top = Math.max(viewportMargin, Math.min(top, vh - viewportMargin - popover.height))
    return {
      position: 'fixed',
      left: `${Math.round(left)}px`,
      top: `${Math.round(top)}px`,
    }
  }

  /** rAF 循环：每帧重新读取锚点位置并重算定位 */
  function tick() {
    if (rafId !== null) cancelAnimationFrame(rafId)
    rafId = requestAnimationFrame(() => {
      const el = anchorEl.value
      if (!el) {
        position.value = { style: { display: 'none' }, placement: 'right', anchorVisible: false }
        rafId = null
        return
      }
      const rect = el.getBoundingClientRect()
      // 零尺寸（display:none / 已卸载）→ 隐藏
      if (rect.width === 0 && rect.height === 0) {
        position.value = { style: { display: 'none' }, placement: 'right', anchorVisible: false }
        rafId = null
        return
      }
      position.value = compute(rect, resolveSize())
      // 激活期间持续循环
      if (isActive()) {
        tick()
      } else {
        rafId = null
      }
    })
  }

  function isActive(): boolean {
    return options.active && (options.active as Ref<boolean>).value === true
  }

  // 激活状态变化时启动/停止 rAF
  if (isRefLike(options.active)) {
    watch(
      options.active as Ref<boolean>,
      (active) => {
        if (active) {
          tick()
        } else if (rafId !== null) {
          cancelAnimationFrame(rafId)
          rafId = null
        }
      },
      { immediate: true },
    )
  }

  // 监听 scroll（捕获模式，捕获所有内层滚动容器）和 resize
  function onScrollCapture() {
    if (isActive() && rafId === null) tick()
  }
  function onResize() {
    if (isActive()) tick()
  }

  if (typeof window !== 'undefined') {
    window.addEventListener('scroll', onScrollCapture, true)
    window.addEventListener('resize', onResize)
  }

  onUnmounted(() => {
    if (rafId !== null) cancelAnimationFrame(rafId)
    if (typeof window !== 'undefined') {
      window.removeEventListener('scroll', onScrollCapture, true)
      window.removeEventListener('resize', onResize)
    }
  })

  /** 暴露给模板的响应式 style（直接 :style="popoverStyle"） */
  const popoverStyle = computed(() => position.value.style)
  const placement = computed(() => position.value.placement)
  const anchorVisible = computed(() => position.value.anchorVisible)

  return {
    position,
    popoverStyle,
    placement,
    anchorVisible,
    /** 手动触发一次重算（如小窗内容高度变化后） */
    recalculate: tick,
  }
}
