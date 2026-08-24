"""TTS Routing schemas — 环节⑤ 音频合成编排契约 (HARNESS §2.4.3).

包含：
- TtsRoutingInput: 环节⑤输入 (段落标注 + 角色声音表 + 系统状态)
- TtsRoutingDecision: 环节⑤输出 (引擎选择、声音、韵律覆盖、降级路径、理由)

马具规则:
1. 本地免费优先 (Kokoro/Edge)；超长/高情感/需克隆时升级到云端
2. 流式优先: 实时预览场景优先选择流式引擎
3. 声音克隆: 仅当 character_voice_map.sample_quote 非空时启用零样本克隆
4. 成本监控: 单本书 TTS 成本 > 阈值时暂停并告警
5. 同一 LLM 可服务多环节: 路由配置由客户可调整

v0.4 新增引擎:
- Streaming: cosyvoice_stream, seed_tts_stream, melotts_stream
- Zero-shot Clone: xtts_v2, openvoice_v2, cosyvoice_clone
- VoxCPM2: voxcpm2 (远程 GPU 推理)
"""

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field
from typing_extensions import Annotated as AnnotatedExt

from .book import CharacterVoiceBinding
from .paragraph import ParagraphAnnotation

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
CostUsd = Annotated[float, Field(ge=0.0)]

# v0.4 引擎选择枚举
EngineChoice = Literal[
    # 本地/免费引擎
    "kokoro",
    "edge",
    # 云端/付费引擎
    "azure",
    "gcp",
    # v0.3: 人工克隆
    "human_clone",
    # v0.4: 流式合成
    "cosyvoice_stream",
    "seed_tts_stream",
    "melotts_stream",
    # v0.4: 零样本克隆
    "xtts_v2",
    "openvoice_v2",
    "cosyvoice_clone",
    # v0.4: 远程 GPU 推理
    "voxcpm2",
]

# 本地引擎集合 (免费)
LOCAL_ENGINES = {"kokoro", "edge"}

# 流式引擎集合
STREAMING_ENGINES = {"cosyvoice_stream", "seed_tts_stream", "melotts_stream"}

# 零样本克隆引擎集合
CLONE_ENGINES = {"xtts_v2", "openvoice_v2", "cosyvoice_clone"}

# 远程 GPU 引擎
REMOTE_GPU_ENGINES = {"voxcpm2"}


class TtsRoutingInput(BaseModel):
    """环节⑤输入：段落标注 + 角色声音表 + 系统状态."""

    paragraph_annotation: ParagraphAnnotation = Field(..., description="段落标注")
    # 待合成文本 (来自 TtsEditOutput.edited_text 或原始段落文本)
    text: str = Field(..., min_length=1, description="待合成文本")
    character_voice_map: list[CharacterVoiceBinding] = Field(..., min_length=1, description="角色声音绑定表")
    book_id: str = Field(..., description="书籍 ID")
    chapter_index: int = Field(..., ge=1, description="章节索引")
    paragraph_index: int = Field(..., ge=0, description="段落索引")
    # 运行时状态
    cumulative_cost_usd: CostUsd = Field(default=0.0, description="已累计 TTS 成本")
    cost_limit_per_book: CostUsd = Field(default=20.0, description="单本成本上限")
    cost_limit_per_chapter: CostUsd = Field(default=5.0, description="单章成本上限")
    prefer_local: bool = Field(default=True, description="优先使用本地引擎")
    # v0.4 新增
    enable_streaming: bool = Field(default=False, description="启用流式合成 (实时预览)")
    enable_cloning: bool = Field(default=False, description="启用零样本克隆 (需 sample_quote)")
    contract_version: int = Field(default=1, description="契约版本号，用于追踪 schema 变更")


class TtsRoutingDecision(BaseModel):
    """环节⑤输出：TTS 路由决策."""

    segment_id: str = Field(..., description="音频片段唯一 ID (格式: {book_id}_ch{chapter}_p{paragraph})")
    engine_choice: EngineChoice = Field(..., description="选择的 TTS 引擎")
    voice_id: str = Field(..., description="声音 ID (必须从 character_voice_map.suggested_voice_id 中选)")
    prosody_overrides: dict | None = Field(
        default=None, description="韵律覆盖参数 (如: {'rate': '1.2', 'pitch': '+2st'})"
    )
    fallback_engine: EngineChoice = Field(..., description="降级引擎")
    reasoning: str = Field(..., description="路由决策理由 (用于审计与学习)")
    estimated_cost_usd: CostUsd = Field(default=0.0, description="预估成本")
    estimated_duration_ms: int = Field(default=0, ge=0, description="预估时长毫秒")
    # v0.4 新增
    use_streaming: bool = Field(default=False, description="是否使用流式模式")
    use_cloning: bool = Field(default=False, description="是否使用零样本克隆")
    reference_audio_path: Optional[str] = Field(default=None, description="克隆参考音频路径")
    contract_version: int = Field(default=1, description="契约版本号，用于追踪 schema 变更")

    model_config = {"from_attributes": True, "extra": "forbid"}


# 导出引擎分类常量供其他模块使用
__all__ = [
    "TtsRoutingInput",
    "TtsRoutingDecision",
    "EngineChoice",
    "LOCAL_ENGINES",
    "STREAMING_ENGINES",
    "CLONE_ENGINES",
    "REMOTE_GPU_ENGINES",
]
