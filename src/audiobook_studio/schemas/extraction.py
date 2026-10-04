"""Extraction schemas — 文本提取环节契约 (HARNESS §2.1.7).

对应环节①：多模态 LLM 流式提取 + 结构语义工程清洗。
输入：ExtractionInput (文件路径、MIME 类型、语言检测开关)
输出：ExtractionResult (原始文本、语言、页数、OCR 统计、警告)
"""

from typing import Literal

from pydantic import BaseModel, Field


class VisualElement(BaseModel):
    """多模态视觉理解产出的单个图/元素描述 (Task 4).

    对应图文混排书籍里的一个视觉元素：插图、图表、地图、照片，或纯文字图。
    供下游朗读 (extracted_text) 与语义理解 (caption) 使用。
    """

    kind: Literal["text", "figure", "table", "map", "photo", "other"] = "other"
    caption: str = Field(default="", description="一段中文描述该图的内容/意图")
    extracted_text: str = Field(default="", description="图内可读文字（供朗读/转录）")


class ExtractionInput(BaseModel):
    """文本提取环节输入参数."""

    file_path: str = Field(..., description="源文件路径")
    mime_type: Literal[
        "application/pdf",
        "application/epub+zip",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/tiff",
        "image/bmp",
        "image/webp",
        "application/octet-stream",
    ] = Field(..., description="文件 MIME 类型")
    detect_language: bool = Field(default=True, description="是否自动检测语言")
    contract_version: int = Field(default=1, description="契约版本号，用于追踪 schema 变更")


class ExtractionResult(BaseModel):
    """文本提取环节输出结果.

    包含原始文本及元数据，供后续环节②结构分析使用。
    """

    raw_text: str = Field(..., min_length=1, description="提取的原始文本内容")
    language: str = Field(..., description="ISO 639-1 语言代码")
    page_count: int = Field(..., ge=0, description="总页数")
    has_ocr: bool = Field(default=False, description="是否使用了 OCR")
    ocr_page_ratio: float = Field(default=0.0, ge=0.0, le=1.0, description="OCR 处理页占比")
    warnings: list[str] = Field(default_factory=list, description="提取过程中的警告信息")
    # Task 4 多模态视觉理解产物。图内容已合并进 raw_text；此字段保留结构化描述供下游/API 使用。
    visual_descriptions: list[VisualElement] = Field(
        default_factory=list, description="图文混排中视觉元素的多模态理解结果"
    )
    multimodal_used: bool = Field(default=False, description="本次提取是否实际调用了多模态视觉理解")
    contract_version: int = Field(default=2, description="契约版本号，用于追踪 schema 变更")

    model_config = {"from_attributes": True, "extra": "forbid"}
