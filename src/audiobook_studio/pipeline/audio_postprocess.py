"""Audio post-process pipeline module — 语义→声学参数映射.

在 TTS 合成前将 ParagraphAnnotation (纯语义) + CharacterVoiceBinding
+ EmotionSnapshot 映射为 AudioPostProcessParams (含语速/音高/音效)。

设计原则:
- ParagraphAnnotation 只保留语义信息 (谁在说、什么情绪、说什么)
- 声学参数 (怎么读、什么效果) 由本模块根据预设 + 规则动态生成
- 解耦后可独立优化声学参数策略而不影响 LLM 标注环节

声学默认预设 (EMOTION_PRESETS):
  每个情感标签映射到 {speech_rate, pitch_shift, sfx_tags} 的默认值。
  角色级别的覆盖通过 CharacterVoiceBinding 的 voice_preset 字段实现。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from ..schemas.audio_postprocess import AudioPostProcessParams
from ..schemas.book import CharacterVoiceBinding, EmotionSnapshot
from ..schemas.paragraph import ParagraphAnnotation

logger = logging.getLogger(__name__)

# ── 情感→声学预设映射 ─────────────────────────────────────────────────────────
# key: emotion label → {speech_rate, pitch_shift_semitones, sfx_tags}
# 这些是通用默认值，可通过 voice_preset 在角色级别覆盖。
EMOTION_PRESETS: Dict[str, Dict] = {
    "neutral": {
        "speech_rate": 1.0,
        "pitch_shift_semitones": 0,
        "sfx_tags": [],
    },
    "happy": {
        "speech_rate": 1.1,
        "pitch_shift_semitones": 1,
        "sfx_tags": ["ambient_cheerful"],
    },
    "sad": {
        "speech_rate": 0.8,
        "pitch_shift_semitones": -1,
        "sfx_tags": ["ambient_melancholic"],
    },
    "angry": {
        "speech_rate": 1.2,
        "pitch_shift_semitones": 2,
        "sfx_tags": ["ambient_tense"],
    },
    "fearful": {
        "speech_rate": 1.2,
        "pitch_shift_semitones": 3,
        "sfx_tags": ["ambient_suspense"],
    },
    "surprised": {
        "speech_rate": 1.2,
        "pitch_shift_semitones": 2,
        "sfx_tags": ["ambient_surprise"],
    },
    "disgusted": {
        "speech_rate": 0.9,
        "pitch_shift_semitones": -2,
        "sfx_tags": [],
    },
    "tense": {
        "speech_rate": 1.1,
        "pitch_shift_semitones": 1,
        "sfx_tags": ["ambient_suspense"],
    },
    "tender": {
        "speech_rate": 0.8,
        "pitch_shift_semitones": -1,
        "sfx_tags": ["ambient_soft"],
    },
    "contemplative": {
        "speech_rate": 0.8,
        "pitch_shift_semitones": -1,
        "sfx_tags": [],
    },
    "whisper": {
        "speech_rate": 0.7,
        "pitch_shift_semitones": -2,
        "sfx_tags": [],
    },
    "cold_laugh": {
        "speech_rate": 0.9,
        "pitch_shift_semitones": 0,
        "sfx_tags": [],
    },
    "sigh": {
        "speech_rate": 0.7,
        "pitch_shift_semitones": -1,
        "sfx_tags": ["ambient_sigh"],
    },
    "sarcastic": {
        "speech_rate": 0.9,
        "pitch_shift_semitones": 1,
        "sfx_tags": [],
    },
}


class AudioPostProcessor:
    """声学后处理器 — 语义标注 → TTS 声学参数.

    用法::

        processor = AudioPostProcessor()
        params = processor.process(
            annotation=paragraph_annotation,
            voice_map=character_voice_map,
            emotion_snapshot=emotion_snapshot,
        )
        # params.speech_rate, params.pitch_shift_semitones, ...
    """

    def __init__(self, emotion_presets: Optional[Dict[str, Dict]] = None):
        self.emotion_presets = emotion_presets or EMOTION_PRESETS

    def process(
        self,
        annotation: ParagraphAnnotation,
        voice_map: Optional[List[CharacterVoiceBinding]] = None,
        emotion_snapshot: Optional[EmotionSnapshot] = None,
    ) -> AudioPostProcessParams:
        """计算段落的声学参数.

        Args:
            annotation: 段落语义标注 (环节③输出)
            voice_map: 角色声音绑定表 (用于角色级预设覆盖)
            emotion_snapshot: 章节情感快照 (用于环境基调参考)

        Returns:
            AudioPostProcessParams: 声学参数 (语速/音高/音效)
        """
        emotion = annotation.emotion
        intensity = annotation.emotion_intensity

        # 1. 从情感预设获取基线
        preset = self.emotion_presets.get(emotion, self.emotion_presets["neutral"])
        speech_rate = preset["speech_rate"]
        pitch_shift = preset["pitch_shift_semitones"]
        sfx_tags = list(preset["sfx_tags"])

        # 2. 角色级覆盖 (通过 voice_map 查找角色特定声学配置)
        if voice_map and annotation.speaker_canonical_name:
            matched = [
                v
                for v in voice_map
                if v.canonical_name == annotation.speaker_canonical_name
            ]
            if matched and hasattr(matched[0], "voice_preset"):
                vp = matched[0].voice_preset
                if vp:
                    speech_rate = vp.get("speech_rate", speech_rate)
                    pitch_shift = vp.get("pitch_shift_semitones", pitch_shift)
                    extra_sfx = vp.get("sfx_tags", [])
                    if extra_sfx:
                        sfx_tags.extend(extra_sfx)

        # 3. 情感强度微调: 高强度 → 略微加速/加大偏移
        if intensity is not None:
            if intensity > 0.8:
                speech_rate = min(1.3, speech_rate + 0.05)
                pitch_shift = max(-5, min(5, pitch_shift + (1 if pitch_shift >= 0 else -1)))
            elif intensity < 0.3:
                speech_rate = max(0.7, speech_rate - 0.05)

        # 4. 对话特殊处理: 对话默认略微加速
        if annotation.is_dialogue:
            speech_rate = min(1.3, speech_rate + 0.05)

        # 四舍五入到最接近的 0.1 步长
        speech_rate = round(speech_rate * 10) / 10
        speech_rate = max(0.7, min(1.3, speech_rate))

        return AudioPostProcessParams(
            speech_rate=speech_rate,
            pitch_shift_semitones=max(-5, min(5, pitch_shift)),
            needs_sfx=len(sfx_tags) > 0,
            sfx_tags=sfx_tags,
            pause_before_ms=annotation.pause_before_ms or 0,
            pause_after_ms=annotation.pause_after_ms or 0,
        )
