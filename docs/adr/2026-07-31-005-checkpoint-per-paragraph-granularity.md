# ADR-005: Checkpoint 升级到 per-paragraph 粒度

## 状态
Accepted (2026-07-31, implemented pending — by human architect 选定方案 A)

## 背景

`CheckpointManager` (`src/audiobook_studio/pipeline/checkpoint.py`) 是 pipeline 的「断点续跑」真相源。当前 v2 结构按 `(stage, chapter_index)` 二元组跟踪 stage 完成状态：

```
{
  "version": 2,
  "chapters": {
    "1": {
      "stages_done": ["extract", "analyze", "annotate", "edit", ...],
      "paragraphs_done": [],
      "current_stage": null
    }
  }
}
```

`orchestrator.run_pipeline` 在 4 个位置基于 `checkpoint_manager.is_stage_done(stage, chapter_index)` 做 skip 决策（line 536/557/568/587），这三个参数完全没传 `paragraph_index`。

### 现象（commit `5d8682b` 端到端验证暴露）

`pipe_fix8.log` 末尾明确显示：每个 chapter 仅 paragraph 1 跑完了全部 stage，paragraph 2~15 全部「done (0 stages)」：

```
✅ Paragraph 1 done (3 stages)
✅ Paragraph 2 done (0 stages)   ← 跳过
...Paragraph 15 done (0 stages)
```

DB 印证：chapter 1 共 15 个段落，仅 idx=1 `status=quality_checked` 且有 audio_segment，其余 14 个全停在 `extracted`。

### 根因

Pipeline stages 实际有**两种粒度**：

| Stage | 粒度 | 处理单位 |
|-------|------|----------|
| `extract`, `analyze` | **chapter 级** | 整章一次 |
| `annotate`, `edit`, `audio_postprocess`, `synthesize`, `quality` | **paragraph 级** | 每段一次 |

但 CheckpointManager 的 `is_stage_done` / `mark_stage_done` 只接受 `(stage, chapter_index)`，导致：

1. paragraph 1 完成 `annotate` → checkpoint 标 `{chapter=1}.stages_done += ["annotate"]`
2. paragraph 2~15 调 `run_pipeline(stages=["annotate",...], chapter_index=1, paragraph_index=2)` → `is_stage_done("annotate", 1)` 返回 True → 整段跳过

`CheckpointManager` 内部其实已预留 `paragraphs_done` 字段和 `are_paragraphs_done` 方法，但 orchestrator 从未调用，且这套字段语义不够精确（只记「段落是否处理过」、不记「这个段落的哪个 stage 做完」）。

### 约束

- 红线 #4 ADR 闸门：调度主路径（checkpoint）变更必须先有 ADR
- 红线 #1 无隐式 Mock：不能跳过修复直接声明「端到端跑通」
- 现有 v2 持久化数据已不可信（含错误章级完成标记），升级时必须能干净处理旧数据
- 不可破坏 chapter 级 `extract`/`analyze` 的现有 checkpoint 语义

## 决策

**方案 A：把 CheckpointManager 的 stage 跟踪升级到 `(stage, chapter, paragraph)` 三元组**

per-paragraph 阶段（annotate/edit/audio_postprocess/synthesize/quality）按 `(stage, chapter, paragraph)` 三元组存；chapter 级阶段（extract/analyze/review）维持 `(stage, chapter)` 二元组。`paragraph_index` 作为可选参数贯穿 `is_stage_done` / `mark_stage_done` / `mark_stage_started`。

### 持久化结构 v3

```json
{
  "version": 3,
  "project_id": 4,
  "chapters": {
    "1": {
      "stages_done": ["extract", "analyze", "review"],
      "current_stage": null,
      "paragraphs": {
        "1": {"stages_done": ["annotate", "edit", "audio_postprocess", "synthesize", "quality"]},
        "2": {"stages_done": ["annotate"]},
        "3": {"stages_done": []}
      }
    }
  }
}
```

### API 变更

- `is_stage_done(stage, chapter_index, paragraph_index=None)` — paragraph_index 给定时查 `chapters[chapter].paragraphs[paragraph].stages_done`；不给定时查 `chapters[chapter].stages_done`
- `mark_stage_done(stage, chapter_index, paragraph_index=None)` — 对应写入
- `mark_stage_started(stage, chapter_index, paragraph_index=None)` — 对应写入
- 旧的 `paragraphs_done` / `are_paragraphs_done` / `mark_paragraph_done` 等 deprecated，新代码不再用

### v2→v3 兼容

旧 v2 文件中 `chapters[c].stages_done` 内含的 per-paragraph stage 名（`annotate`/`edit`/`audio_postprocess`/`synthesize`/`quality`）是不可信记录，加载时**全部丢弃**；只保留 chapter 级 stage（`extract`/`analyze`/`review`）。`paragraphs_done` 字段也丢弃（语义不明确）。

### orchestrator 配套修改

`orchestrator.run_pipeline` 4 处 checkpoint 调用全部传 `paragraph_index`：
- line 536 `is_stage_done` (early-exit 检查) → 传 paragraph_index
- line 557 `is_stage_done` (per-stage skip)
- line 568 `mark_stage_started`
- line 587 `mark_stage_done`

early-exit 逻辑 `all_done` 判定也要按 paragraph 粒度：若 paragraph_index 给定，遍历 stages 时全部按 `(stage, chapter, paragraph)` 查。

## 替代方案

| 方案 | 优势 | 劣势 | 判定 |
|------|------|------|------|
| **A — checkpoint 三元组** (选定) | 语义最干净，与 CheckpointManager 现有 `paragraphs_done` 设计意图一致；resume 能精确恢复到「某段某阶段」；改动局限在 checkpoint + orchestrator | 需持久化结构升级 v2→v3 + 旧数据兼容 | ✅ 人类架构师选 |
| **B — per-paragraph 改查 DB Paragraph.status** | 改动最小（只动 orchestrator）；DB status 本就是 ground truth | 需逐 stage 对齐 persist 是否推进 status；resume 粒度仍只为整段，不能恢复中断在某段落某 stage 中间的状态 | ❌ resume 粒度不够 |
| **C — 完全废弃 CheckpointManager，全押 DB 状态机** | 单一真相源 | 大重构，违反红线 #4 外科手术；DB 状态机尚未规整（如 synthesize 失败时段落 status 推进了吗？） | ❌ 过度设计 |

## 后果

### 正面
- 端到端章节级 pipeline 真正可跑通（不是只跑段 1）
- resume 粒度精确到 (chapter, paragraph, stage)，崩溃恢复更可靠
- CheckpointManager 现有 `paragraphs_done` 字段概念被正确的 per-paragraph stage tracking 替代

### 负面
- 持久化结构 v2→v3 升级需迁移代码（虽然简单，但旧 checkpoint JSON 含的「已完成 stages」中 per-paragraph 的部分会丢，需重跑这些 stage — 但这些原本就是被错误标记的）
- 多增加一层 `paragraph_index` 参数贯穿，API 变复杂

### 后续行动
- 写 ADR 后立即实施：checkpoint.py v3 + orchestrator 调用改造
- 写回归测试：paragraph 1 完成 annotate 不影响 paragraph 2 的 `is_stage_done` 结果
- 跑完整 pipeline 重验证：test_story ch1 全 15 段都到 quality_checked

## 关联
- Implementation: `src/audiobook_studio/pipeline/checkpoint.py`, `src/audiobook_studio/pipeline/orchestrator.py`
- 触发 bug 的提交: `5d8682b` (fix(pipeline): unblock end-to-end production pipeline)
- 相关证据日志: `storage/books/4/logs/pipe_fix8.log`
