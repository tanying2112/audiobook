"""ChapterSource schema — 章节源数据契约 (HARNESS §2.1.8).

定义统一的章节级数据源契约，用于：
1. 人工标注黄金数据集的标准格式
2. 跨阶段的数据传递与校验
3. A/B 测试样本构建的输入源
"""

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, confloat, conint
from typing_extensions import Annotated as AnnotatedExt

from .book import BookMeta, CharacterVoiceBinding, EmotionSnapshot
from .paragraph import ParagraphAnnotation

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
Score = Annotated[float, Field(ge=0.0, le=1.0)]


class ChapterSourceParagraph(BaseModel):
    """章节内单段落的完整标注数据."""

    paragraph_index: int = Field(..., ge=0, description="段落在章节内的索引")
    text: str = Field(..., min_length=1, max_length=2000, description="段落原始文本")
    annotation: ParagraphAnnotation = Field(..., description="段落标注参数")
    # 人工标注字段
    human_verified: bool = Field(default=False, description="是否经过人工复核")
    human_notes: str = Field(default="", description="人工标注备注")
    # 质量评分（用于黄金数据集评分）
    quality_score: Score = Field(default=1.0, description="该段落质量分 0-1")


class ChapterSource(BaseModel):
    """章节源数据契约 - 完整的章节级标注数据集.

    包含：
    - 书籍元信息 + 角色声音表 + 章节情感快照
    - 该章节所有段落的完整标注
    - 人工标注验证状态
    - 用于黄金数据集构建和 A/B 测试
    """

    # 章节标识
    book_id: str = Field(..., description="书籍唯一标识")
    chapter_index: int = Field(..., ge=1, description="章节号 (从1开始)")
    chapter_title: str = Field(default="", description="章节标题")

    # 上帝视角上下文 (来自 BookAnalysisOutput)
    book_meta: BookMeta = Field(..., description="书籍元信息")
    character_voice_map: list[CharacterVoiceBinding] = Field(
        ..., min_length=1, description="角色声音绑定表"
    )
    emotion_snapshot: EmotionSnapshot = Field(..., description="当前章节情感快照")
    story_line_summary: str = Field(
        ..., min_length=100, max_length=500, description="故事主线摘要"
    )
    global_style_notes: str = Field(..., description="全局文风备注")

    # 段落标注列表
    paragraphs: list[ChapterSourceParagraph] = Field(
        ..., min_length=1, description="章节内所有段落标注"
    )

    # 人工标注元数据
    annotated_by: str = Field(default="", description="标注人员/来源")
    annotated_at: str = Field(default="", description="标注时间 ISO 8601")
    annotation_version: str = Field(default="v0.1", description="标注版本")
    total_paragraphs: int = Field(..., ge=1, description="段落总数")
    verified_paragraphs: int = Field(default=0, description="已验证段落数")
    overall_quality_score: Score = Field(default=1.0, description="章节整体质量分")

    # 契约版本
    contract_version: int = Field(
        default=1, description="契约版本号，用于追踪 schema 变更"
    )

    model_config = {"from_attributes": True, "extra": "forbid"}

    @property
    def verification_rate(self) -> float:
        """已验证段落占比."""
        return self.verified_paragraphs / max(self.total_paragraphs, 1)

    def get_golden_samples(self, min_quality: float = 0.8) -> list[ChapterSourceParagraph]:
        """获取符合质量阈值的黄金样本."""
        return [p for p in self.paragraphs if p.quality_score >= min_quality and p.human_verified]


class ChapterSourceCollection(BaseModel):
    """章节源数据集合 - 多章节的黄金数据集."""

    book_id: str = Field(..., description="书籍唯一标识")
    book_title: str = Field(..., description="书名")
    chapters: list[ChapterSource] = Field(..., min_length=1, description="章节列表")
    collection_version: str = Field(default="v0.1", description="数据集版本")
    created_at: str = Field(default="", description="创建时间")
    total_chapters: int = Field(..., ge=1, description="章节总数")
    total_paragraphs: int = Field(..., ge=1, description="段落总数")
    verified_paragraphs: int = Field(default=0, description="已验证段落总数")

    model_config = {"from_attributes": True, "extra": "forbid"}

    @property
    def verification_rate(self) -> float:
        return self.verified_paragraphs / max(self.total_paragraphs, 1)
