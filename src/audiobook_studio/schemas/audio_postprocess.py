"""Audio post-process schemas — TTS 前声学参数契约.

包含：
- AudioPostProcessParams: 声学后处理器输出 (语速/音高/音效)

设计意图:
从 ParagraphAnnotation 中剥离的声学特征在此由 AudioPostProcessor
基于 VOICE_MAP/EMOTION_PRESETS 动态生成，实现语义与声学解耦。
"""

from typing import Annotated

from pydantic import BaseModel, Field

SpeechRate = Annotated[float, Field(ge=0.7, le=1.3)]
PitchShift = Annotated[int, Field(ge=-5, le=5)]
PauseMs = Annotated[int, Field(ge=0, le=2000)]


class AudioPostProcessParams(BaseModel):
    """声学后处理器输出参数.

    由 AudioPostProcessor 根据段落标注 + 角色声音绑定 + 情感预设
    动态计算生成，在 TTS 合成前注入路由决策。
    """

    speech_rate: SpeechRate = Field(
        default=1.0, description="语速 (7 档离散值: 0.7-1.3)"
    )
    pitch_shift_semitones: PitchShift = Field(
        default=0, description="音高偏移 半音 -5 到 +5"
    )
    needs_sfx: bool = Field(default=False, description="是否需要场景音效")
    sfx_tags: list[str] = Field(default_factory=list, description="音效标签列表")
    pause_before_ms: PauseMs = Field(default=0, description="前停顿毫秒")
    pause_after_ms: PauseMs = Field(default=0, description="后停顿毫秒")

    model_config = {"from_attributes": True, "extra": "forbid"}
