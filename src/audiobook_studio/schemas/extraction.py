"""Extraction schemas — 文本提取环节契约 (HARNESS §2.1.7).

对应环节①：多模态 LLM 流式提取 + 结构语义工程清洗。
输入：ExtractionInput (文件路径、MIME 类型、语言检测开关)
输出：ExtractionResult (原始文本、语言、页数、OCR 统计、警告)
"""

from typing import Literal

from pydantic import BaseModel, Field


class ExtractionInput(BaseModel):
    """文本提取环节输入参数."""

    file_path: str = Field(..., description="源文件路径")
    mime_type: Literal[
        "application/pdf",
        "application/epub+zip",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "image/*",
    ] = Field(..., description="文件 MIME 类型")
    detect_language: bool = Field(default=True, description="是否自动检测语言")
    contract_version: int = Field(
        default=1, description="契约版本号，用于追踪 schema 变更"
    )


class ExtractionResult(BaseModel):
    """文本提取环节输出结果.

    包含原始文本及元数据，供后续环节②结构分析使用。
    """

    raw_text: str = Field(..., min_length=1, description="提取的原始文本内容")
    language: str = Field(..., description="ISO 639-1 语言代码")
    page_count: int = Field(..., ge=0, description="总页数")
    has_ocr: bool = Field(default=False, description="是否使用了 OCR")
    ocr_page_ratio: float = Field(
        default=0.0, ge=0.0, le=1.0, description="OCR 处理页占比"
    )
    warnings: list[str] = Field(
        default_factory=list, description="提取过程中的警告信息"
    )
    contract_version: int = Field(
        default=1, description="契约版本号，用于追踪 schema 变更"
    )

    model_config = {"from_attributes": True, "extra": "forbid"}
