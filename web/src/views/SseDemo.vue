<!--
  SseDemo.vue — 临时验证页（验证通过后删除）

  验证三项基建：
    1. SSE 打字机流式接收（api/sse.ts）
    2. Cursor 风格内联小窗定位 + 对话（useInlineChat.ts + context store）
    3. normalize 数据清洗（normalize.ts）

  访问方式：临时路由 /sse-demo（已在 router 中添加，验证后移除）
  依赖后端：uvicorn src.audiobook_studio.main:app --port 8000
-->
<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useInlineChat } from '../composables/useInlineChat'
import { useInlineChatPosition } from '../composables/useInlineChatPosition'
import {
  normalizeChapterPipeline,
  computePipelineProgress,
  stageLabel,
} from '../utils/normalize'

// ── 1. 内联小窗 ──────────────────────────────────────────────────────
const {
  messages,
  streamingText,
  loading,
  error,
  currentSuggestion,
  inputText,
  active,
  anchor,
  anchorEl,
  canSend,
  canStop,
  open,
  close,
  send,
  stop,
  accept,
  reject,
} = useInlineChat({
  projectId: () => 1,
  chapterIndex: () => 1,
  targetStage: 'edit',
  useMock: true,
  onAccept: (s) => {
    console.log('[demo] accepted suggestion:', s)
    if (s.after && typeof s.after.text === 'string') {
      appliedEdits.value.push(s.after.text)
    }
  },
})

// ── 2. 智能定位（防飘移核心）──────────────────────────────────────────
// 实时读取 anchorEl 位置 + 视口边界检测 + 智能翻转，页面滚动/缩放时小窗始终跟随锚点。
const { popoverStyle, placement, anchorVisible } = useInlineChatPosition(
  anchorEl,
  {
    active,
    gap: 8,
    viewportMargin: 12,
    popoverSize: { width: 380, height: 420 },
    preferredPlacements: ['right', 'left', 'bottom', 'top'],
    hideWhenAnchorOffscreen: true,
  },
)

// ── 3. 模拟文本区 + 选区触发 ─────────────────────────────────────────
const sampleText = ref(
  '他对此表示非常愤怒，并表示绝对不会接受这样的安排。这事儿太离谱了，我真的不想再说了。他在1985年花了贰佰叁拾元买了3本书。',
)
const appliedEdits = ref<string[]>([])

/** 选中文本后触发内联小窗 */
function openInlineFromSelection(e: MouseEvent) {
  const sel = window.getSelection()
  const selected = sel?.toString().trim() ?? ''
  if (!selected) return

  // 用触发元素定位小窗（保留元素引用，定位 composable 实时跟随）
  const el = e.currentTarget as HTMLElement
  open(el, {
    kind: 'text_selection',
    paragraph_id: 0,
    selected_text: selected,
    selection_start: 0,
    selection_end: selected.length,
  })
}

/** 快捷指令按钮 */
function quickIntent(intent: string) {
  inputText.value = intent
  send()
}

// ── 4. normalize 演示 ─────────────────────────────────────────────────
const normalizeResult = ref('')
function runNormalizeDemo() {
  // 模拟一个 Chapter（extract/analyze 已完成，其余恒 pending）
  const fakeChapter = {
    extract_status: 'completed',
    analyze_status: 'completed',
    annotate_status: 'pending',
    edit_status: 'pending',
    route_status: 'pending',
    synthesize_status: 'pending',
    quality_status: 'pending',
  }
  // 模拟该章节的段落（部分已标注/编辑）
  const fakeParagraphs = [
    { status: 'annotated' },
    { status: 'annotated' },
    { status: 'edited' },
    { status: 'pending' },
  ]
  const stages = normalizeChapterPipeline(fakeChapter, fakeParagraphs)
  const progress = computePipelineProgress(stages)
  const lines = stages.map(
    (s) =>
      `  ${stageLabel(s.stage).padEnd(8)} | ${s.status.padEnd(9)} | from: ${s.inferred_from}`,
  )
  normalizeResult.value = [
    `整体进度: ${(progress * 100).toFixed(0)}%`,
    '阶段明细:',
    ...lines,
  ].join('\n')
}

// ── 5. 点击外部关闭小窗 ───────────────────────────────────────────────
function onDocClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (active.value && !target.closest('[data-inline-chat]') && !target.closest('button')) {
    close()
  }
}
onMounted(() => {
  document.addEventListener('click', onDocClick)
  runNormalizeDemo()
})
onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  close()
})
</script>

<template>
  <div class="sse-demo">
    <h1>SSE + 内联小窗 + Normalize 验证</h1>
    <p class="hint">
      1. 在下方文本中选中一段 → 自动弹出内联小窗<br />
      2. 输入意图（如"口语化"、"拆分长句"）或点快捷按钮 → 观察打字机效果<br />
      3. 流结束后查看 diff 卡片，可采纳
    </p>

    <!-- 文本区 -->
    <p
      class="sample-text"
      @mouseup="openInlineFromSelection"
    >
      {{ sampleText }}
    </p>

    <div v-if="appliedEdits.length" class="applied">
      <h3>已采纳的编辑：</h3>
      <ol>
        <li v-for="(t, i) in appliedEdits" :key="i">{{ t }}</li>
      </ol>
    </div>

    <!-- normalize 演示 -->
    <pre class="normalize-output">{{ normalizeResult }}</pre>

    <!-- 防飘移验证区：选中上方文本后，滚动此区域，小窗应始终跟随锚点 -->
    <div class="scroll-test">
      <h3>⬇ 滚动验证区</h3>
      <p class="hint">
        1. 先选中上方任一文本 → 弹出小窗<br />
        2. 上下滚动此区域 → 小窗应跟随锚点移动，不飘移<br />
        3. 把锚点滚出视口 → 小窗显示"锚点已滚出视口"<br />
        4. 缩小浏览器窗口 → 选区在右侧时小窗自动翻转到左侧（📍badge 变化）
      </p>
      <p v-for="i in 30" :key="i" class="filler-line">填充行 #{{ i }}：用于制造足够长的可滚动内容，验证内联小窗在页面滚动时的绝对定位跟随效果。</p>
    </div>

    <!-- 内联小窗（Teleport 到 body 避免被父级 overflow 裁切） -->
    <Teleport to="body">
      <div
        v-if="active"
        data-inline-chat
        class="inline-chat-popover"
        :class="[`placement-${placement}`, { 'anchor-hidden': !anchorVisible }]"
        :style="popoverStyle"
        @click.stop
      >
        <div class="icp-header">
          <span class="icp-title">💬 就地编辑</span>
          <!-- 定位指示器（验证翻转逻辑用）-->
          <span class="icp-placement-badge" :title="'当前放置方向：' + placement">
            📍{{ placement }}
          </span>
          <button class="icp-close" @click="close">✕</button>
        </div>
        <!-- 锚点滚出视口提示 -->
        <div v-if="!anchorVisible" class="icp-offscreen-hint">
          ⤓ 锚点已滚出视口，滚动回来可恢复
        </div>

        <div class="icp-context" v-if="anchor?.selected_text">
          选中："{{ anchor.selected_text.length > 30
            ? anchor.selected_text.slice(0, 30) + '...'
            : anchor.selected_text }}"
        </div>

        <!-- 消息列表 -->
        <div class="icp-messages">
          <div
            v-for="m in messages"
            :key="m.id"
            :class="['icp-msg', `icp-msg-${m.role}`]"
          >
            <span class="icp-msg-role">{{ m.role === 'user' ? '🧑' : '🤖' }}</span>
            <span class="icp-msg-content">{{ m.content }}</span>
          </div>
          <!-- 打字机 -->
          <div v-if="streamingText" class="icp-msg icp-msg-assistant">
            <span class="icp-msg-role">🤖</span>
            <span class="icp-msg-content">{{ streamingText }}<span class="cursor">▋</span></span>
          </div>
          <!-- thinking 占位 -->
          <div v-if="loading && !streamingText" class="icp-thinking">思考中...</div>
          <div v-if="error" class="icp-error">⚠ {{ error }}</div>
        </div>

        <!-- suggestion diff 卡片 -->
        <div v-if="currentSuggestion" class="icp-suggestion">
          <div class="icp-diff">
            <div class="icp-diff-before">
              <del>{{ currentSuggestion.before?.text }}</del>
            </div>
            <div class="icp-diff-after">
              <ins>{{ currentSuggestion.after?.text }}</ins>
            </div>
          </div>
          <div class="icp-changes">
            <span v-for="c in currentSuggestion.changes_made" :key="c" class="icp-tag">{{ c }}</span>
            <span class="icp-confidence">置信度 {{ (currentSuggestion.confidence * 100).toFixed(0) }}%</span>
          </div>
          <div class="icp-actions">
            <button class="btn-accept" @click="accept()">✅ 采纳</button>
            <button class="btn-reject" @click="reject()">❌ 拒绝</button>
          </div>
        </div>

        <!-- 输入区 -->
        <div class="icp-input-area">
          <div class="icp-shortcuts">
            <button @click="quickIntent('口语化')">口语化</button>
            <button @click="quickIntent('拆分长句')">拆分长句</button>
            <button @click="quickIntent('数字归一化')">数字归一化</button>
          </div>
          <div class="icp-input-row">
            <input
              v-model="inputText"
              class="icp-input"
              placeholder="描述你想要的修改..."
              @keyup.enter="send()"
              :disabled="loading"
            />
            <button v-if="canStop" class="btn-stop" @click="stop()">⏹</button>
            <button v-else class="btn-send" :disabled="!canSend" @click="send()">➤</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.sse-demo {
  max-width: 900px;
  margin: 20px auto;
  padding: 20px;
  font-family: system-ui, sans-serif;
}
.sse-demo h1 {
  font-size: 18px;
  margin-bottom: 8px;
}
.hint {
  font-size: 13px;
  color: #666;
  background: #f5f5f5;
  padding: 8px 12px;
  border-radius: 6px;
  margin-bottom: 16px;
}
.sample-text {
  line-height: 1.8;
  padding: 16px;
  background: #fffbe6;
  border: 1px dashed #d4b106;
  border-radius: 6px;
  cursor: text;
  user-select: text;
}
.applied {
  margin-top: 16px;
  padding: 12px;
  background: #f0f9eb;
  border-radius: 6px;
}
.applied h3 {
  font-size: 13px;
  margin: 0 0 8px;
}
.normalize-output {
  margin-top: 16px;
  padding: 12px;
  background: #1e1e1e;
  color: #0f0;
  border-radius: 6px;
  font-size: 12px;
  font-family: 'Menlo', monospace;
}

/* 内联小窗 */
.inline-chat-popover {
  position: fixed;
  width: 360px;
  max-height: 480px;
  background: #fff;
  border: 1px solid #d9d9d9;
  border-radius: 10px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.18);
  display: flex;
  flex-direction: column;
  z-index: 9999;
}
.icp-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  border-bottom: 1px solid #f0f0f0;
}
.icp-title {
  font-weight: 600;
  font-size: 13px;
}
.icp-close {
  border: none;
  background: none;
  cursor: pointer;
  font-size: 14px;
  color: #999;
}
.icp-context {
  padding: 6px 12px;
  font-size: 11px;
  color: #888;
  background: #fafafa;
  border-bottom: 1px solid #f0f0f0;
}
.icp-messages {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
  max-height: 200px;
}
.icp-msg {
  margin-bottom: 8px;
  font-size: 13px;
  line-height: 1.5;
}
.icp-msg-user {
  text-align: right;
}
.icp-msg-role {
  margin-right: 4px;
}
.icp-thinking {
  font-size: 12px;
  color: #999;
  font-style: italic;
}
.icp-error {
  font-size: 12px;
  color: #d4380d;
}
.cursor {
  animation: blink 1s infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
.icp-suggestion {
  padding: 8px 12px;
  border-top: 1px solid #f0f0f0;
  background: #fafcff;
}
.icp-diff {
  font-size: 12px;
  line-height: 1.6;
}
.icp-diff-before {
  color: #999;
}
.icp-diff-before del {
  color: #d4380d;
  text-decoration: line-through;
}
.icp-diff-after ins {
  color: #389e0d;
  text-decoration: none;
  font-weight: 500;
}
.icp-changes {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}
.icp-tag {
  font-size: 10px;
  background: #e6f4ff;
  color: #0958d9;
  padding: 1px 6px;
  border-radius: 8px;
}
.icp-confidence {
  font-size: 10px;
  color: #888;
  margin-left: auto;
}
.icp-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}
.btn-accept,
.btn-reject {
  flex: 1;
  padding: 4px;
  border: 1px solid #d9d9d9;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}
.btn-accept {
  background: #f6ffed;
  border-color: #b7eb8f;
}
.btn-reject {
  background: #fff2f0;
  border-color: #ffccc7;
}
.icp-input-area {
  padding: 8px 12px;
  border-top: 1px solid #f0f0f0;
}
.icp-shortcuts {
  display: flex;
  gap: 4px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.icp-shortcuts button {
  font-size: 10px;
  padding: 2px 8px;
  border: 1px solid #d9d9d9;
  border-radius: 10px;
  background: #fafafa;
  cursor: pointer;
}
.icp-input-row {
  display: flex;
  gap: 6px;
}
.icp-input {
  flex: 1;
  padding: 6px 8px;
  border: 1px solid #d9d9d9;
  border-radius: 4px;
  font-size: 13px;
}
.btn-send,
.btn-stop {
  border: none;
  border-radius: 4px;
  padding: 0 12px;
  cursor: pointer;
}
.btn-send {
  background: #1677ff;
  color: #fff;
}
.btn-send:disabled {
  background: #d9d9d9;
}
.btn-stop {
  background: #ff4d4f;
  color: #fff;
}

/* ── 定位指示 badge（验证翻转逻辑用）── */
.icp-placement-badge {
  margin-left: auto;
  margin-right: 8px;
  font-size: 10px;
  color: #888;
  background: #f0f0f0;
  padding: 1px 6px;
  border-radius: 8px;
  font-family: 'Menlo', monospace;
}
/* 锚点滚出视口时小窗整体变暗 */
.inline-chat-popover.anchor-hidden {
  opacity: 0.45;
}
.icp-offscreen-hint {
  padding: 6px 12px;
  font-size: 11px;
  color: #d48806;
  background: #fffbe6;
  border-bottom: 1px solid #ffe58f;
}

/* ── 滚动验证区 ── */
.scroll-test {
  margin-top: 20px;
  padding: 16px;
  background: #f6f8fa;
  border: 1px solid #d0d7de;
  border-radius: 8px;
}
.scroll-test h3 {
  font-size: 14px;
  margin: 0 0 8px;
  color: #0969da;
}
.filler-line {
  margin: 4px 0;
  font-size: 13px;
  color: #57606a;
  line-height: 1.8;
  border-bottom: 1px dashed #d0d7de;
  padding-bottom: 4px;
}
</style>
