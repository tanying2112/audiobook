"""Audio finalize schemas — TTS 合成后音频后处理契约.

包含：
- AudioFinalizeParams: 后处理参数配置
- AudioFinalizeResult: 后处理结果

设计意图:
TTS 合成完成后，对音频进行标准化后处理：
1. loudnorm - EBU R128 响度标准化
2. afade - 淡入淡出
3. SFX 叠加 - 场景音效混音
4. 元数据嵌入 - 章节标记、Cover Art 等
"""

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field

LoudnormTargetI = Annotated[float, Field(ge=-30, le=-10)]
LoudnormTargetLRA = Annotated[float, Field(ge=0, le=20)]
LoudnormTargetTP = Annotated[float, Field(le=-1)]
FadeDuration = Annotated[int, Field(ge=0, le=5000)]


class AudioFinalizeParams(BaseModel):
    """音频后处理参数.

    用于配置 TTS 合成后的标准化处理流程。
    """

    # Loudnorm (EBU R128)
    apply_loudnorm: bool = Field(default=True, description="是否应用 EBU R128 响度标准化")
    loudnorm_target_i: LoudnormTargetI = Field(default=-20.0, description="目标综合响度 (LUFS)，EBU R128 建议 -23，有声书常用 -20")
    loudnorm_target_lra: LoudnormTargetLRA = Field(default=7.0, description="目标响度范围 (LU)")
    loudnorm_target_tp: LoudnormTargetTP = Field(default=-2.0, description="目标真峰值")

    # Fade in/out
    apply_fade: bool = Field(default=True, description="是否应用淡入淡出")
    fade_in_ms: FadeDuration = Field(default=500, description="淡入时长 (毫秒)")
    fade_out_ms: FadeDuration = Field(default=500, description="淡出时长 (毫秒)")
    fade_shape: Literal["tri", "exp", "log", "sin"] = Field(default="tri", description="淡入淡出曲线形状")

    # SFX Overlay
    apply_sfx: bool = Field(default=True, description="是否叠加场景音效")
    sfx_gain_db: float = Field(default=-20.0, description="SFX 增益 (dB)，负值表示比主轨低")

    # Metadata
    embed_metadata: bool = Field(default=True, description="是否嵌入元数据")
    metadata_title: Optional[str] = Field(default=None, description="标题")
    metadata_artist: Optional[str] = Field(default=None, description="作者/朗读者")
    metadata_album: Optional[str] = Field(default=None, description="书名")
    metadata_track: Optional[int] = Field(default=None, description="章节号")
    metadata_year: Optional[int] = Field(default=None, description="年份")
    metadata_genre: str = Field(default="Audiobook", description="流派")
    metadata_cover_path: Optional[str] = Field(default=None, description="封面图片路径")

    # Output format
    output_format: Literal["mp3", "m4b", "wav"] = Field(default="mp3", description="输出格式")
    output_bitrate: str = Field(default="128k", description="输出比特率")

    model_config = {"from_attributes": True, "extra": "forbid"}


class AudioFinalizeResult(BaseModel):
    """音频后处理结果."""

    input_path: str = Field(description="输入音频文件路径")
    output_path: str = Field(description="输出音频文件路径")
    duration_ms: int = Field(description="输出音频时长 (毫秒)")

    # Measured loudness (after loudnorm)
    measured_i: float = Field(description="测量综合响度 (LUFS)")
    measured_lra: float = Field(description="测量响度范围 (LU)")
    measured_tp: float = Field(description="测量真峰值")
    measured_thresh: float = Field(description="测量阈值")

    # Processing info
    loudnorm_applied: bool = Field(default=False)
    fade_applied: bool = Field(default=False)
    sfx_applied: bool = Field(default=False)
    metadata_embedded: bool = Field(default=False)

    # Errors/warnings
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True, "extra": "forbid"}