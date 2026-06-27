"""LLM 语义分析 schema — 反馈语义分析契约.

LLMFeedbackAnalyzer 的输出模型，替代 processor.py 中的关键词匹配。
通过 LLM 理解修改意图，提取语义级模式，不再限于预定义 tag 字典。
"""

from typing import Literal

from pydantic import BaseModel, Field

# 严重程度
Severity = Literal["high", "medium", "low"]


class FeedbackAnalysis(BaseModel):
    """LLM 语义分析单条反馈的结果.

    替代 processor.py 的 _infer_pattern_tags() 关键词匹配。
    LLM 理解修改的深层原因，提取可复用的改进模式。
    """

    pattern_tags: list[str] = Field(
        default_factory=list,
        description=(
            "模式标签列表。可以是 PATTERN_TAXONOMY 中的已知标签，"
            "也可以是 LLM 新发现的标签（如 'narrator_pacing_inconsistent'）。"
            "不再限于 16 个预定义 tag。"
        ),
    )

    semantic_summary: str = Field(
        default="",
        description="修改原因的语义级摘要（1-2 句话），解释为什么需要修改。",
    )

    severity: Severity = Field(
        default="medium",
        description="严重程度：high=致命错误(角色混淆/截断), medium=明显问题, low=微调",
    )

    actionable_instruction: str = Field(
        default="",
        description=(
            "可直接写入 prompt 的改进指令。"
            "例如：'在标注对话段落时，必须检查引号归属，"
            "若引号内无明确主语，需从上下文推断说话人。'"
        ),
    )

    root_cause: str = Field(
        default="",
        description="根因分析：LLM 输出错误的根本原因（如 prompt 缺少示例/规则模糊/上下文不足）。",
    )

    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="分析置信度 0-1。低于 0.5 时建议人工复核。",
    )

    model_config = {"extra": "forbid"}
