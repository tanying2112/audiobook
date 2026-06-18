"""Quality schemas — 环节⑥ 质量检测契约 (HARNESS §2.5.7).

包含：
- QualityJudgment: 环节⑥输出 (多维度评分 + 问题列表 + 修复建议 + 是否需重合成)
- FixSuggestion: 结构化修复建议模型

检测维度与 Judge 契约:
| 维度 | 评估方法 | 阈值 |
|------|---------|------|
| 角色一致性 | LLM Judge 比对 speaker_canonical_name 与音频声纹 | ≥ 0.85 |
| 情感对齐 | LLM Judge 听音频描述情绪 vs paragraph_annotation.emotion | 一致/不一致 |
| 无声/卡顿/截断 | 音频规则脚本 (pydub + numpy) | 0 个错误 |
| 敏感内容 | 关键词规则 + LLM 复核 | 0 命中 |
| 节奏合理性 | 句间停顿 vs pause_before_ms/pause_after_ms | 误差 < 200ms |

反馈回路触发条件:
- 任何维度 < 0.7 → needs_regeneration = true
- 连续 3 段同一角色 wrong_speaker → 触发角色声音绑定重新评估
- 情感不匹配占比 > 20% → 触发提示词版本升级评估
"""

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, confloat

Score = Annotated[float, Field(ge=0.0, le=1.0)]


class FixSuggestion(BaseModel):
    """结构化修复建议，用于指导LLM进行具体改进."""

    suggestion_type: Literal[
        "voice_adjustment",
        "emotion_adjustment",
        "pacing_adjustment",
        "content_edit",
        "emphasis_change",
        "pause_insertion",
        "prosody_correction",
    ] = Field(..., description="修改类型")

    target_text: str = Field(..., description="需要修改的目标文本片段")

    current_value: Optional[str] = Field(
        None, description="当前值（如当前语速、情感强度等）"
    )

    suggested_value: str = Field(..., description="建议的新值")

    confidence: Score = Field(default=0.8, description="建议的置信度 0-1")

    rationale: str = Field(default="", description="修改建议的理由或依据")

    priority: Literal["low", "medium", "high"] = Field(
        default="medium", description="优先级别"
    )


class QualityJudgment(BaseModel):
    """环节⑥输出：音频片段质量判定."""

    segment_id: str = Field(..., description="音频片段 ID")
    speaker_clarity: Score = Field(..., description="角色识别准确度 0-1")
    emotion_match: Score = Field(..., description="情感匹配度 0-1")
    prosody_naturalness: Score = Field(..., description="韵律自然度 0-1")
    text_audio_alignment: Score = Field(..., description="文本-音频一致性 0-1")
    overall_score: Score = Field(..., description="综合得分 0-1")

    issues: list[
        Literal[
            "wrong_speaker",
            "emotion_mismatch",
            "silent_segment",
            "stuttering",
            "truncation",
            "sensitive_content",
            "wrong_speed",
            "wrong_pitch",
        ]
    ] = Field(default_factory=list, description="检出的问题列表")

    fix_suggestions: list[FixSuggestion] = Field(
        default_factory=list, description="结构化修复建议列表，提供具体的改进指导"
    )
    needs_regeneration: bool = Field(
        ..., description="是否需重新合成 (任一维度<0.7 或致命问题)"
    )
    contract_version: int = Field(
        default=1, description="契约版本号，用于追踪 schema 变更"
    )
    judge_model: Optional[str] = Field(default=None, description="评判使用的模型名称")
    judge_prompt_version: Optional[str] = Field(
        default=None, description="评判提示词版本"
    )

    model_config = {"from_attributes": True, "extra": "forbid"}


class Quality(BaseModel):
    """Simple Quality schema for CRUD API."""

    id: int | None = Field(default=None, description="Database primary key")
    tts_edit_id: int = Field(..., description="Foreign key to TTSEdit")
    score: float = Field(..., description="Quality score")
    comments: str | None = Field(default=None, description="Comments")

    model_config = {"from_attributes": True}
