"""Book schemas — 环节② 结构分析契约 (HARNESS §2.2.7).

包含：
- BookAnalysisInput: 环节②输入 (原始文本 + 提示)
- BookMeta: 书籍元信息
- CharacterVoiceBinding: 角色声音绑定
- EmotionSnapshot: 章节情感快照
- BookAnalysisOutput: 环节②输出 (上帝视角完整档案)
"""

from typing import Literal

from pydantic import BaseModel, Field, confloat, conint


class BookAnalysisInput(BaseModel):
    """环节②输入：原始文本 + 可选提示."""

    raw_text: str = Field(..., max_length=200_000, description="原始文本内容")
    title_hint: str | None = Field(default=None, description="标题提示")
    author_hint: str | None = Field(default=None, description="作者提示")
    target_difficulty: Literal["A", "B", "C", "D"] = Field(default="B", description="目标难度等级")
    contract_version: int = Field(default=1, description="契约版本号，用于追踪 schema 变更")


class BookMeta(BaseModel):
    """书籍元信息."""

    title: str = Field(..., description="书名")
    author: str | None = Field(default=None, description="作者")
    genre: Literal["小说", "散文", "诗歌", "历史", "科普", "童话", "其他"] = Field(..., description="体裁")
    difficulty: Literal["A", "B", "C", "D"] = Field(..., description="难度等级")
    language: str = Field(..., description="ISO 639-1 语言代码")
    era: str | None = Field(default=None, description="时代背景")
    total_chapters_estimated: int = Field(..., ge=1, description="预估总章节数")
    contract_version: int = Field(default=1, description="契约版本号，用于追踪 schema 变更")


class CharacterVoiceBinding(BaseModel):
    """角色声音绑定 (全本唯一 canonical_name)."""

    canonical_name: str = Field(..., min_length=1, description="规范角色名 (全本唯一)")
    aliases: list[str] = Field(default_factory=list, description="别名列表")
    gender: Literal["male", "female", "neutral", "unknown"] = Field(default="unknown", description="性别")
    age_range: Literal["child", "young", "adult", "elderly", "unknown"] = Field(default="unknown", description="年龄段")
    suggested_voice_id: str | None = Field(default=None, description="建议声音 ID (TTS 引擎特定)")
    sample_quote: str = Field(..., description="用于声音克隆的样本引用文本")
    contract_version: int = Field(default=1, description="契约版本号，用于追踪 schema 变更")


class EmotionSnapshot(BaseModel):
    """章节情感快照."""

    chapter: int = Field(..., ge=1, description="章节号")
    dominant_emotion: Literal[
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
    ] = Field(..., description="主导情感")
    intensity: confloat(ge=0.0, le=1.0) = Field(..., description="情感强度 0-1")
    notes: str = Field(default="", description="备注")
    contract_version: int = Field(default=1, description="契约版本号，用于追踪 schema 变更")


class BookAnalysisOutput(BaseModel):
    """环节②输出：完整的上帝视角剧本档案.

    此输出将注入后续所有环节作为上下文，确保角色一致性。
    """

    book_meta: BookMeta = Field(..., description="书籍元信息")
    character_voice_map: list[CharacterVoiceBinding] = Field(..., min_length=1, description="角色声音绑定表")
    emotion_snapshots: list[EmotionSnapshot] = Field(..., min_length=1, description="每章情感快照")
    story_line_summary: str = Field(..., min_length=100, max_length=500, description="故事主线摘要 100-500 字")
    global_style_notes: str = Field(..., description="全局文风与特殊处理建议")
    contract_version: int = Field(default=1, description="契约版本号，用于追踪 schema 变更")

    model_config = {"from_attributes": True, "extra": "forbid"}


class Book(BaseModel):
    """Simple Book schema for CRUD API."""

    id: int | None = Field(default=None, description="Database primary key")
    title: str = Field(..., description="Book title")
    author: str | None = Field(default=None, description="Book author")
    language: str = Field(..., description="ISO 639-1 language code")
    isbn: str | None = Field(default=None, description="ISBN identifier")

    model_config = {"from_attributes": True}
