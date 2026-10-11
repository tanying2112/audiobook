"""Batch 3.1 — audio_director stage 输入/输出契约.

LLM 音频导演: 对已编辑 (edit_for_tts 后) 的段落文本生成逐句演绎建议
(sentence_overrides), 落入 Paragraph.sentence_overrides 供
SynthesizePipeline._synthesize_paragraph_with_overrides 消费。

字段语义与 pipeline/synthesize.py 的合并逻辑一一对应:
  - speed      → override["speed"]       (替换 rate)
  - pitch_st   → override["pitch_st"]    (替换 pitch, ffmpeg 带式 ±6st)
  - gain_db    → override["gain_db"]      (叠加到 volume)
  - voice_id   → override["voice_id"]    (替换句子音色, 支持 blend 语法)
  - pause_after_ms / pause_category → 句后停顿 (显式值 > 类别默认 > 标点分级)

人工优先: 本 stage 只在 Paragraph.sentence_overrides 为空时落库;
一旦人工在 ReviewEditPanel 编辑过 (字段非空), 导演不覆盖人工结果。
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# Batch 3.2: 停顿类别 (LLM 抽象语义 → 合成侧映射默认毫秒)
# clause=从句边界 / comma=逗号级微顿 / dramatic=戏剧性长停 / paragraph=段落收束
PauseCategory = Literal["clause", "comma", "dramatic", "paragraph"]


class SentenceOverrideSuggestion(BaseModel):
    """单句演绎建议 (字段全部可选 — 缺省即「该轴不干预」)."""

    idx: int = Field(..., ge=0, description="句子序号 (0-based, 对应切句结果)")
    voice_id: Optional[str] = Field(
        None, description="句子音色 (支持 blend 语法 'am_onyx*0.6+am_fenrir*0.4')"
    )
    speed: Optional[float] = Field(
        None, ge=0.5, le=2.0, description="语速倍率 (替换段落级 rate)"
    )
    pitch_st: Optional[float] = Field(
        None, ge=-6.0, le=6.0, description="音高移位半音 (替换段落级 pitch)"
    )
    gain_db: Optional[float] = Field(
        None, ge=-6.0, le=6.0, description="响度增量 dB (叠加到段落 volume)"
    )
    pause_after_ms: Optional[int] = Field(
        None, ge=0, le=5000, description="句后停顿毫秒 (显式值, 优先于类别)"
    )
    pause_category: Optional[PauseCategory] = Field(
        None, description="停顿类别 (clause/comma/dramatic/paragraph → 默认毫秒)"
    )


class AudioDirectorInput(BaseModel):
    """audio_director 输入: 编辑后文本 + 预切句 + 段落演绎上下文."""

    paragraph_text: str = Field(..., description="编辑后段落文本 (edit_for_tts 产物)")
    sentences: List[str] = Field(
        default_factory=list,
        description="预切句结果 (与合成侧 _split_sentences 同源, idx 与此对齐)",
    )
    speaker_name: str = Field(default="_narrator_", description="说话人 (角色名或 _narrator_)")
    emotion: str = Field(default="neutral", description="段落情感标注")
    emotion_intensity: float = Field(default=0.5, ge=0.0, le=1.0, description="情感强度 0-1")
    is_dialogue: bool = Field(default=False, description="是否对白")
    language: str = Field(default="zh", description="目标语言 (zh/en)")
    voice_id: Optional[str] = Field(None, description="段落当前音色 (供导演参考, 不强制沿用)")


class AudioDirectorOutput(BaseModel):
    """audio_director 输出: 逐句演绎建议 + 导演理由."""

    sentence_overrides: List[SentenceOverrideSuggestion] = Field(
        default_factory=list, description="逐句建议 (可为空 = 本段无需干预)"
    )
    rationale: str = Field(..., description="导演决策理由 (用于反馈学习)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="导演置信度 0-1")
