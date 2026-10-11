"""Schema for Text Clean stage — SRT/字幕文本清洗为可读版本."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TextCleanInput(BaseModel):
    """文本清洗输入参数."""

    srt_path: str = Field(..., description="输入 SRT 文件路径")
    use_llm: bool = Field(default=False, description="是否使用 LLM 润色")
    llm_prompt: Optional[str] = Field(default=None, description="自定义 LLM 提示词")
    project_id: int = Field(default=0, description="项目 ID（用于日志/追踪）")
    chapter_index: int = Field(default=1, description="章节索引")


class TextCleanResult(BaseModel):
    """文本清洗输出结果."""

    cleaned_text: str = Field(..., description="清洗后的完整文本")
    paragraphs: List[str] = Field(default_factory=list, description="分段后的段落列表")
    stats: Dict[str, Any] = Field(default_factory=dict, description="清洗统计信息")
    warnings: List[str] = Field(default_factory=list, description="警告信息")

    # 元信息
    source_srt: str = Field(default="", description="源 SRT 文件路径")
    llm_used: bool = Field(default=False, description="是否使用了 LLM")


class TextCleanConfig(BaseModel):
    """文本清洗配置."""

    use_llm: bool = Field(default=False, description="全局启用 LLM 润色")
    llm_prompt_template: Optional[str] = Field(default=None, description="LLM 提示词模板")
    name_normalization: Dict[str, str] = Field(default_factory=dict, description="人名规范化映射")
    protected_patterns: List[str] = Field(default_factory=list, description="受保护的正则模式（避免过度合并）")
