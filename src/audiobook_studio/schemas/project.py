"""Project schema — ORM 模型 Project 的 Pydantic 对应.

用于 API 序列化和数据验证。
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, confloat

ProgressType = Annotated[float, Field(ge=0.0, le=1.0)]
CostType = Annotated[float, Field(ge=0.0)]


class Project(BaseModel):
    """书籍项目 Schema (对应 ORM Project 模型)."""

    id: int = Field(..., description="Database primary key")
    title: str = Field(..., description="书名")
    author: str | None = Field(default=None, description="作者")
    genre: str | None = Field(default=None, description="体裁")
    difficulty: Literal["A", "B", "C", "D"] | None = Field(
        default=None, description="难度等级"
    )
    language: str = Field(default="zh", description="ISO 639-1 语言代码")
    era: str | None = Field(default=None, description="时代背景")
    total_chapters_estimated: int | None = Field(
        default=None, ge=1, description="预估总章节数"
    )

    # 全局文风备注
    global_style_notes: str | None = Field(default=None, description="全局文风备注")
    story_line_summary: str | None = Field(default=None, description="故事主线摘要")

    # 状态追踪
    status: str = Field(default="draft", description="项目状态")
    current_stage: str | None = Field(default=None, description="当前处理阶段")
    progress: ProgressType = Field(default=0.0, description="项目进度 0-1")

    # 成本追踪
    total_cost_usd: CostType = Field(default=0.0, description="已花费成本 (USD)")
    cost_limit_per_book: CostType = Field(
        default=20.0, description="每本书成本上限 (USD)"
    )
    cost_limit_per_chapter: CostType = Field(
        default=5.0, description="每章成本上限 (USD)"
    )

    # 时间戳
    created_at: str | None = Field(default=None, description="创建时间")
    updated_at: str | None = Field(default=None, description="更新时间")
    completed_at: str | None = Field(default=None, description="完成时间")

    model_config = {"from_attributes": True, "extra": "ignore"}
