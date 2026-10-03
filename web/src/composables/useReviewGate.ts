import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from '../i18n'
import {
  fetchReviewGateSummary,
  fetchRoutingPreview,
  fetchParagraphs,
  fetchTTSVoices,
  approveChapter,
  resetChapterApproval,
  approveAllChapters,
  reviewEditParagraph,
  type ReviewGateSummary,
  type RoutingPreviewResponse,
  type ReviewParagraphEditPayload,
  type ReviewEditResponse,
  type TTSVoicesResponse,
} from '../api'
import type { Paragraph } from '../types'

/**
 * 人工终审门工作台逻辑（ReviewGateView.vue 抽离）。
 *
 * review 模式的流水线在合成前暂停于此。工作台让客户在放行合成前：
 * - 逐章查看路由预览（每段将用什么引擎/音色/韵律 —— 与合成同一份代码）
 * - 逐段编辑标注文本、韵律参数、人工覆盖 voice/engine（客户最终控制）
 * - 逐章/整书确认（approve）；已确认章节被再次编辑会自动打回待审
 */
export function useReviewGate() {
  const route = useRoute()
  const { t } = useI18n()

  const projectId = Number(route.params.projectId)

  // ── State ─────────────────────────────────────────────────────────────
  const loading = ref(false)
  const summary = ref<ReviewGateSummary | null>(null)
  const selectedChapterId = ref<number | null>(null)
  const paragraphs = ref<Paragraph[]>([])
  const paragraphsLoading = ref(false)
  const routingPreview = ref<RoutingPreviewResponse | null>(null)
  const selectedParagraphId = ref<number | null>(null)
  const saving = ref(false)
  const error = ref<string | null>(null)
  /** 上一次保存结果提示（changes_made 摘要 / 打回待审提示） */
  const lastSaveMessage = ref<string | null>(null)
  const ttsVoices = ref<TTSVoicesResponse | null>(null)

  // ── Computed ─────────────────────────────────────────────────────────
  /** 终审门是否激活（流水线正等确认） */
  const isGateActive = computed(() => summary.value?.run_status === 'awaiting_review')
  const chapters = computed(() => summary.value?.chapters || [])
  const selectedChapter = computed(
    () => chapters.value.find((c) => c.chapter_id === selectedChapterId.value) || null,
  )
  const selectedParagraph = computed(
    () => paragraphs.value.find((p) => p.id === selectedParagraphId.value) || null,
  )
  /** 预览按 paragraph_id 索引，供段落列表直接显示引擎/音色 */
  const previewByParagraphId = computed(() => {
    const map = new Map<number, RoutingPreviewResponse['previews'][number]>()
    for (const p of routingPreview.value?.previews || []) {
      map.set(p.paragraph_id, p)
    }
    return map
  })

  // ── Actions ──────────────────────────────────────────────────────────
  async function loadSummary(): Promise<void> {
    try {
      summary.value = await fetchReviewGateSummary(projectId)
    } catch (e: unknown) {
      error.value = (e as Error).message
    }
  }

  async function loadVoices(): Promise<void> {
    try {
      ttsVoices.value = await fetchTTSVoices(true)
    } catch {
      // 音色表加载失败不阻断工作台 —— 覆盖输入退化为自由文本
      ttsVoices.value = null
    }
  }

  /** 选中章节：拉取段落列表 + 路由预览（保持之前选中的段落尽量不丢） */
  async function selectChapter(chapterId: number): Promise<void> {
    selectedChapterId.value = chapterId
    paragraphsLoading.value = true
    error.value = null
    try {
      const [paras, preview] = await Promise.all([
        fetchParagraphs(projectId, chapterId),
        fetchRoutingPreview(projectId, chapterId),
      ])
      paragraphs.value = paras
      routingPreview.value = preview
      if (!paras.some((p) => p.id === selectedParagraphId.value)) {
        selectedParagraphId.value = paras[0]?.id ?? null
      }
    } catch (e: unknown) {
      error.value = (e as Error).message
      paragraphs.value = []
      routingPreview.value = null
    } finally {
      paragraphsLoading.value = false
    }
  }

  async function handleApprove(chapterId: number): Promise<void> {
    try {
      summary.value = await approveChapter(projectId, chapterId)
    } catch (e: unknown) {
      error.value = (e as Error).message
    }
  }

  async function handleReset(chapterId: number): Promise<void> {
    try {
      summary.value = await resetChapterApproval(projectId, chapterId)
    } catch (e: unknown) {
      error.value = (e as Error).message
    }
  }

  async function handleApproveAll(): Promise<void> {
    if (!confirm(t('review_gate.confirm_approve_all'))) return
    try {
      summary.value = await approveAllChapters(projectId)
    } catch (e: unknown) {
      error.value = (e as Error).message
    }
  }

  /**
   * 保存人工编辑。后端每次有效编辑写一条 TTSEdit 人工版本；
   * 已确认章节被编辑会自动打回 pending_review（chapter_review_reset）。
   */
  async function saveParagraphEdit(payload: ReviewParagraphEditPayload): Promise<boolean> {
    if (!selectedChapterId.value || !selectedParagraphId.value) return false
    saving.value = true
    error.value = null
    lastSaveMessage.value = null
    try {
      const resp: ReviewEditResponse = await reviewEditParagraph(
        projectId,
        selectedChapterId.value,
        selectedParagraphId.value,
        payload,
      )
      // 用返回的段落就地更新列表（含 manual_* 回显）
      const idx = paragraphs.value.findIndex((p) => p.id === resp.paragraph.id)
      if (idx >= 0) paragraphs.value[idx] = resp.paragraph
      // 章节确认状态可能被打回 → 刷新汇总
      await loadSummary()
      if (resp.chapter_review_reset) {
        lastSaveMessage.value = t('review_gate.chapter_review_reset')
      } else if (resp.changes_made.length > 0) {
        lastSaveMessage.value = t('review_gate.saved_changes', {
          count: resp.changes_made.length,
        })
      } else {
        lastSaveMessage.value = t('review_gate.no_changes')
      }
      // 编辑改变了路由依据 → 刷新预览保持所见即所合成
      routingPreview.value = await fetchRoutingPreview(projectId, selectedChapterId.value)
      return true
    } catch (e: unknown) {
      error.value = (e as Error).message
      return false
    } finally {
      saving.value = false
    }
  }

  // 轮询兜底（WS 断连/未触发时也能看到 run_status 变化）
  let pollTimer: ReturnType<typeof setInterval> | null = null

  onMounted(async () => {
    loading.value = true
    try {
      await Promise.all([loadSummary(), loadVoices()])
      // 默认选中第一章
      const first = chapters.value[0]
      if (first) await selectChapter(first.chapter_id)
    } finally {
      loading.value = false
    }
    pollTimer = setInterval(loadSummary, 5000)
  })

  onUnmounted(() => {
    if (pollTimer) clearInterval(pollTimer)
  })

  return {
    // state
    loading,
    summary,
    chapters,
    selectedChapterId,
    selectedChapter,
    paragraphs,
    paragraphsLoading,
    routingPreview,
    previewByParagraphId,
    selectedParagraphId,
    selectedParagraph,
    saving,
    error,
    lastSaveMessage,
    ttsVoices,
    isGateActive,
    // actions
    projectId,
    loadSummary,
    selectChapter,
    handleApprove,
    handleReset,
    handleApproveAll,
    saveParagraphEdit,
  }
}
