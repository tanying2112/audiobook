"""Paragraph schemas — 环节③ 段落标注契约 (HARNESS §2.2.7).

包含：
- ParagraphAnnotationInput: 环节③输入 (单段文本 + 上帝视角上下文)
- ParagraphAnnotation: 环节③输出 (单段语义标注，声学参数由 AudioPostProcessor 生成)

Hard Rules (违反即解析失败):
1. speaker_canonical_name 必须命中 character_voice_map 或为 "_narrator_"
2. canonical_name 全本唯一
3. emotion 仅能从 14 枚举中选取
4. confidence < 0.6 需 UI 高亮提示人工复核

Schema v2 (极简重构):
- 仅保留语义层参数：speaker, emotion, is_dialogue, confidence, difficulty, notes
- 声学参数由 AudioPostProcessor 基于 Voice Design 动态生成
- 兼容 v1: 保留声学字段作为可选字段，供迁移期使用
"""

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, confloat, conint
from typing_extensions import TypedDict

from .book import BookMeta, CharacterVoiceBinding, EmotionSnapshot

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
EmotionIntensity = Annotated[float, Field(ge=0.0, le=1.0)]
DifficultyLevel = Literal["A", "B", "C"]

# v1 兼容字段（可选，用于迁移期）
SpeechRate = Annotated[float, Field(ge=0.7, le=1.3)]
PitchShift = Annotated[int, Field(ge=-5, le=5)]
PauseMs = Annotated[int, Field(ge=0, le=2000)]


class ParagraphAnnotationInput(BaseModel):
    """环节③输入：单段文本 + 注入的上帝视角上下文."""

    paragraph_text: str = Field(
        ..., min_length=10, max_length=2000, description="段落文本"
    )
    paragraph_index: int = Field(..., ge=0, description="段落索引")
    chapter_index: int = Field(..., ge=1, description="章节索引")

    # 注入的"上帝视角"上下文 (来自 BookAnalysisOutput)
    book_meta: BookMeta = Field(..., description="书籍元信息")
    character_voice_map: list[CharacterVoiceBinding] = Field(
        ..., min_length=1, description="角色声音绑定表"
    )
    emotion_snapshot: EmotionSnapshot = Field(..., description="当前章节情感快照")
    story_line_summary: str = Field(
        ..., min_length=100, max_length=500, description="故事主线摘要"
    )
    global_style_notes: str = Field(..., description="全局文风备注")
    contract_version: int = Field(default=2, description="契约版本号 v2: 极简语义标注")


class ParagraphAnnotation(BaseModel):
    """环节③输出：单段语义标注 (v2 极简版).

    仅保留语义层参数，声学参数由 AudioPostProcessor 动态生成。
    v1 声学字段保留为可选，兼容迁移期代码。
    """

    paragraph_id: Optional[int] = Field(default=None, description="段落数据库主键 ID")
    chapter_id: Optional[int] = Field(default=None, description="章节数据库主键 ID")
    paragraph_index: int = Field(..., ge=0, description="段落索引")
    text: str = Field(default="", description="段落文本内容")
    speaker_canonical_name: str = Field(
        ...,
        min_length=1,
        description="说话人规范名 (必须命中 character_voice_map 或 _narrator_)",
    )
    is_dialogue: bool = Field(..., description="是否为对话")
    emotion: Literal[
        "neutral",
        "happy",
        "sad",
        "angry",
        "fearful",
        "surprised",
        "disgusted",
        "tense",
        "tender",
        "contemplative",
        "whisper",
        "cold_laugh",
        "sigh",
        "sarcastic",
    ] = Field(..., description="情感标签 (14 枚举)")
    emotion_intensity: EmotionIntensity = Field(..., description="情感强度 0-1")
    confidence: Confidence = Field(..., description="置信度 0-1")
    difficulty: DifficultyLevel = Field(
        default="B", description="段落难度等级 A/B/C，用于成本预估和质量阈值"
    )
    notes: str | None = Field(default=None, description="备注/不确定性说明")
    contract_version: int = Field(default=2, description="契约版本号 v2: 极简语义标注")

    # v1 兼容字段 (可选，迁移期保留)
    speech_rate: Optional[SpeechRate] = Field(
        default=None, description="语速 (7 档离散值) - v1 兼容"
    )
    pitch_shift_semitones: Optional[PitchShift] = Field(
        default=None, description="音高偏移 半音 -5 到 +5 - v1 兼容"
    )
    needs_sfx: Optional[bool] = Field(
        default=None, description="是否需要场景音效 - v1 兼容"
    )
    sfx_tags: Optional[list[str]] = Field(
        default=None, description="音效标签列表 - v1 兼容"
    )
    pause_before_ms: Optional[PauseMs] = Field(
        default=None, description="前停顿毫秒 - v1 兼容"
    )
    pause_after_ms: Optional[PauseMs] = Field(
        default=None, description="后停顿毫秒 - v1 兼容"
    )

    model_config = {"from_attributes": True, "extra": "forbid"}


class Paragraph(BaseModel):
    """Simple Paragraph schema for CRUD API."""

    id: int | None = Field(default=None, description="Database primary key")
    book_id: int = Field(..., description="Foreign key to Book")
    index: int = Field(..., description="Paragraph index")
    text: str = Field(..., description="Paragraph text")
    speaker: str | None = Field(default=None, description="Speaker name")

    model_config = {"from_attributes": True}
