"""Feedback schemas — 反馈数据契约 (HARNESS §3.4.4).

FeedbackRecord: 统一的反馈记录，捕获人工编辑、质量检测、用户评分等所有反馈来源。
用于：
1. 黄金数据集增量增长
2. 差异分析 Agent 提取 pattern_tags
3. 提示词版本迭代 (Promotion Gate 评估)
4. A/B 测试对比

反馈流向:
人工编辑/质量检测/用户评分 → FeedbackRecord 存储 → 批处理差异分析 → pattern_tags → 新版本 Prompt → 回归测试 → Promotion Gate → 升级/回滚
"""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field
from typing_extensions import Annotated


class FeedbackRecord(BaseModel):
    """统一反馈记录契约."""

    id: str = Field(..., description="唯一反馈 ID (UUID)")
    timestamp: datetime = Field(default_factory=datetime.now(timezone.utc), description="反馈时间戳")
    source: Literal["human_edit", "quality_judge", "user_rating"] = Field(..., description="反馈来源")
    stage: Literal[
        "extract",
        "analyze_structure",
        "annotate_paragraph",
        "edit_for_tts",
        "tts_routing",
        "quality_judge",
        "synthesize",
        "audio_postprocess",
    ] = Field(..., description="发生反馈的环节")
    book_id: str = Field(..., description="书籍 ID")
    paragraph_index: int | None = Field(default=None, description="段落索引 (如适用)")
    chapter_index: int | None = Field(default=None, description="章节索引 (如适用)")

    # 快照数据
    input_snapshot: dict[str, Any] = Field(..., description="当时的输入数据完整快照")
    llm_output: dict[str, Any] = Field(..., description="当时 LLM 的输出")
    corrected_output: dict[str, Any] = Field(..., description="人工/期望的修正输出")

    # 核心：修改理由 (必填，用于差异分析)
    rationale: str = Field(..., min_length=10, description="修改理由 (必填，供 Agent 学习)")

    # Agent 自动生成
    diff_summary: str = Field(default="", description="差异摘要 (Agent 自动生成)")
    pattern_tags: list[str] = Field(
        default_factory=list,
        description="模式标签 (如: missed_dialogue_attribution, emotion_too_mild)",
    )
    contract_version: int = Field(default=1, description="契约版本号，用于追踪 schema 变更")

    model_config = {"from_attributes": True, "extra": "forbid"}
