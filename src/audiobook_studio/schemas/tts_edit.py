"""TTS Edit schemas — 环节④ 文本编辑契约 (HARNESS §2.3.7).

包含：
- TtsEditInput: 环节④输入 (段落文本 + 标注 + 难度 + 编辑锁)
- TtsEditOutput: 环节④输出 (编辑后文本 + 变更记录 + 理由)

马具规则:
1. 难度锁: difficulty ≤ A 或 forbid_edit=true → 直接返回原文，changes_made 为空
2. 数字归一化: 阿拉伯数字 vs 中文数字统一 (推荐阿拉伯数字)
3. 断句: 长句 > 50 字必须拆分，每句 ≤ 30 字
4. 标点处理: 删除朗读无意义符号 (· ※ 等)，保留逗号句号
5. 禁止删改对话主体: dialogue 文本必须 1:1 保留，只调整标点
"""

from typing import Literal

from pydantic import BaseModel, Field, confloat
from typing_extensions import Annotated

from .paragraph import ParagraphAnnotation

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class TtsEditInput(BaseModel):
    """环节④输入：待编辑文本 + 上下文参数."""

    paragraph_text: str = Field(..., description="原始段落文本")
    paragraph_annotation: ParagraphAnnotation = Field(..., description="段落标注参数")
    difficulty: Literal["A", "B", "C", "D"] = Field(..., description="难度等级")
    forbid_edit: bool = Field(
        default=False, description="难度≤A 或人工标记原文锁定时为 true"
    )
    contract_version: int = Field(
        default=1, description="契约版本号，用于追踪 schema 变更"
    )


class TtsEditOutput(BaseModel):
    """环节④输出：编辑后文本 + 变更记录 + 理由."""

    edited_text: str = Field(..., description="编辑后用于 TTS 的文本")
    changes_made: list[str] = Field(
        default_factory=list, description="所做变更列表 (如: '数字归一化', '长句拆分')"
    )
    forbidden_content_removed: list[str] = Field(
        default_factory=list, description="被移除的禁用内容 (练习页、版权页等)"
    )
    confidence: Confidence = Field(..., description="编辑置信度 0-1")
    rationale: str = Field(..., description="编辑理由 (用于反馈学习)")

    model_config = {"from_attributes": True, "extra": "forbid"}


class TTSEdit(BaseModel):
    """Simple TTSEdit schema for CRUD API."""

    id: int | None = Field(default=None, description="Database primary key")
    paragraph_id: int = Field(..., description="Foreign key to Paragraph")
    edited_text: str = Field(..., description="Edited text for TTS")
    voice: str = Field(..., description="Voice identifier")

    model_config = {"from_attributes": True}
