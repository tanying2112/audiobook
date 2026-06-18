"""TTS Routing schemas — 环节⑤ 音频合成编排契约 (HARNESS §2.4.3).

包含：
- TtsRoutingInput: 环节⑤输入 (段落标注 + 角色声音表 + 系统状态)
- TtsRoutingDecision: 环节⑤输出 (引擎选择、声音、韵律覆盖、降级路径、理由)

马具规则:
1. Kokoro 优先: 本地免费优先；超长或情感过强时降级到 Edge
2. 声音克隆: 仅当 character_voice_map.sample_quote 非空时启用
3. 成本监控: 单本书 TTS 成本 > 阈值时暂停并告警
4. 同一 LLM 可服务多环节: 路由配置由客户可调整
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, confloat
from typing_extensions import Annotated as AnnotatedExt

from .book import CharacterVoiceBinding
from .paragraph import ParagraphAnnotation

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
CostUsd = Annotated[float, Field(ge=0.0)]


class TtsRoutingInput(BaseModel):
    """环节⑤输入：段落标注 + 角色声音表 + 系统状态."""

    paragraph_annotation: ParagraphAnnotation = Field(..., description="段落标注")
    # 待合成文本 (来自 TtsEditOutput.edited_text 或原始段落文本)
    text: str = Field(..., min_length=1, description="待合成文本")
    character_voice_map: list[CharacterVoiceBinding] = Field(
        ..., min_length=1, description="角色声音绑定表"
    )
    book_id: str = Field(..., description="书籍 ID")
    chapter_index: int = Field(..., ge=1, description="章节索引")
    paragraph_index: int = Field(..., ge=0, description="段落索引")
    # 运行时状态
    cumulative_cost_usd: CostUsd = Field(default=0.0, description="已累计 TTS 成本")
    cost_limit_per_book: CostUsd = Field(default=20.0, description="单本成本上限")
    cost_limit_per_chapter: CostUsd = Field(default=5.0, description="单章成本上限")
    prefer_local: bool = Field(default=True, description="优先使用本地引擎")
    contract_version: int = Field(
        default=1, description="契约版本号，用于追踪 schema 变更"
    )


class TtsRoutingDecision(BaseModel):
    """环节⑤输出：TTS 路由决策."""

    segment_id: str = Field(
        ..., description="音频片段唯一 ID (格式: {book_id}_ch{chapter}_p{paragraph})"
    )
    engine_choice: Literal["kokoro", "edge", "azure", "gcp", "human_clone"] = Field(
        ..., description="选择的 TTS 引擎"
    )
    voice_id: str = Field(
        ..., description="声音 ID (必须从 character_voice_map.suggested_voice_id 中选)"
    )
    prosody_overrides: dict | None = Field(
        default=None, description="韵律覆盖参数 (如: {'rate': '1.2', 'pitch': '+2st'})"
    )
    fallback_engine: Literal["kokoro", "edge", "azure", "gcp", "human_clone"] = Field(
        ..., description="降级引擎"
    )
    reasoning: str = Field(..., description="路由决策理由 (用于审计与学习)")
    estimated_cost_usd: CostUsd = Field(default=0.0, description="预估成本")
    estimated_duration_ms: int = Field(default=0, ge=0, description="预估时长毫秒")
    contract_version: int = Field(
        default=1, description="契约版本号，用于追踪 schema 变更"
    )

    model_config = {"from_attributes": True, "extra": "forbid"}
