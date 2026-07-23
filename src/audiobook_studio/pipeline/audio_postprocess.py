"""Audio Post-Processor — 语义标注到物理声学参数的动态映射引擎.

核心职责：
1. 接收 Schema v2 的纯语义段落标注列表
2. 根据情感、段落类型、标点符号、文本长度动态计算声学参数
3. 输出供 TTS 引擎消费的 PhysicalAudioSegment 控制对象

设计原则：
- 确定性：相同输入必产生相同输出，无随机性
- 配置驱动：所有映射规则外置在 acoustic_mapping.py，可热重载
- 可测试：纯函数风格，便于单元测试验证每个映射规则
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from ..config.acoustic_mapping import (
    DIALOGUE_SPEED_BOOST,
    LENGTH_BUFFER_MAX_MS,
    LENGTH_BUFFER_MS_PER_CHAR,
    PITCH_HZ_MAX,
    PITCH_HZ_MIN,
    SPEED_MAX,
    SPEED_MIN,
    VOLUME_DB_MAX,
    VOLUME_DB_MIN,
    EmotionAcousticProfile,
    get_emotion_map,
    get_punctuation_map,
    get_transition_map,
)

if TYPE_CHECKING:
    from ..schemas.paragraph import ParagraphAnnotation


@dataclass(frozen=True)
class PhysicalAudioSegment:
    """TTS 合成所需的物理声学控制块.

    此对象直接传递给 TTS 引擎 (Edge-TTS / VoxCPM2 / Kokoro 等)
    """

    text: str  # 待合成文本
    speaker: str  # 说话人标识
    speed: float  # 语速倍率 (0.7-1.3)
    volume_db: float  # 音量增益 dB (-6 到 +6)
    pitch_hz: float  # 音高偏移 Hz (-50 到 +50)
    pause_after_ms: int  # 句后停顿毫秒数
    emotion: str  # 情感标签 (用于引擎内部风格选择)
    paragraph_type: str  # "narration" | "dialogue"
    audio_format: str = "wav"  # 输出格式

    def to_tts_prosody(self) -> Dict[str, Any]:
        """转换为通用 TTS prosody 参数字典."""
        return {
            "rate": f"{self.speed:.2f}",
            "volume": f"{self.volume_db:+.1f}dB",
            "pitch": f"{self.pitch_hz:+.0f}Hz",
        }

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典 (用于日志/存储)."""
        return {
            "text": self.text,
            "speaker": self.speaker,
            "speed": self.speed,
            "volume_db": self.volume_db,
            "pitch_hz": self.pitch_hz,
            "pause_after_ms": self.pause_after_ms,
            "emotion": self.emotion,
            "paragraph_type": self.paragraph_type,
            "audio_format": self.audio_format,
        }


class AudioPostProcessor:
    """声学后处理器 — 语义标注列表 → 物理声学控制流.

    用法示例：
        processor = AudioPostProcessor()
        schedule = processor.generate_acoustic_schedule(paragraphs)
        for segment in schedule:
            tts.synthesize(segment.text, segment.to_tts_prosody())
    """

    def __init__(
        self,
        emotion_map: Optional[Dict[str, EmotionAcousticProfile]] = None,
        transition_map: Optional[Dict[Tuple[str, str], int]] = None,
        punctuation_map: Optional[Dict[str, int]] = None,
    ):
        """初始化处理器.

        Args:
            emotion_map: 情感→声学参数映射表，默认使用配置模块
            transition_map: 段落过渡→基础停顿映射表
            punctuation_map: 标点符号→微停顿增量映射表
        """
        self.emotion_map = emotion_map or get_emotion_map()
        self.transition_map = transition_map or get_transition_map()
        self.punctuation_map = punctuation_map or get_punctuation_map()

    def _determine_paragraph_type(self, para: Dict[str, Any]) -> str:
        """根据标注判断段落类型: narration 或 dialogue."""
        # 优先使用显式字段
        if "paragraph_type" in para:
            pt = para["paragraph_type"]
            if pt in ("narration", "dialogue"):
                return str(pt)

        # 回退：根据 is_dialogue 推断
        if para.get("is_dialogue", False):
            return "dialogue"
        return "narration"

    def _calculate_punctuation_delay(self, text: str) -> int:
        """根据文本末尾标点符号计算动态微停顿增量."""
        if not text:
            return 0
        stripped = text.strip()
        if not stripped:
            return 0
        last_char = stripped[-1]
        return self.punctuation_map.get(last_char, 0)

    def _calculate_length_buffer(self, text: str) -> int:
        """计算文本长度缓冲停顿 (每字符 1.5ms，上限 200ms)."""
        if not text:
            return 0
        # 统计有效字符数（去除空白）
        char_count = len(text.strip())
        buffer_ms = int(char_count * LENGTH_BUFFER_MS_PER_CHAR)
        return min(buffer_ms, LENGTH_BUFFER_MAX_MS)

    def _clamp_speed(self, speed: float) -> float:
        """将语速钳制到允许范围 [0.7, 1.3] 并四舍五入到 0.1 (标准四舍五入)."""
        clamped = max(SPEED_MIN, min(SPEED_MAX, speed))
        # 使用标准四舍五入 (round half up) 而非 banker's rounding
        return round(clamped * 10 + 1e-10) / 10

    def _clamp_volume(self, volume_db: float) -> float:
        """将音量钳制到允许范围 [-6, +6]."""
        return max(VOLUME_DB_MIN, min(VOLUME_DB_MAX, volume_db))

    def _clamp_pitch(self, pitch_hz: float) -> float:
        """将音高钳制到允许范围 [-50, +50]."""
        return max(PITCH_HZ_MIN, min(PITCH_HZ_MAX, pitch_hz))

    def generate_acoustic_schedule(
        self,
        paragraphs: List[Dict[str, Any]],
    ) -> List[PhysicalAudioSegment]:
        """
        生成声学调度表.

        Args:
            paragraphs: Schema v2 语义标注段落列表，每项包含：
                - text: 段落文本
                - speaker: 说话人规范名
                - emotion: 情感标签 (14 枚举之一)
                - is_dialogue: 是否对话
                - paragraph_type: 可选，显式指定 "narration" | "dialogue"
                - emotion_intensity: 可选，情感强度 0-1 (用于微调)

        Returns:
            PhysicalAudioSegment 列表，包含完整的 TTS 物理控制参数
        """
        if not paragraphs:
            return []

        schedule = []
        total = len(paragraphs)

        for i, para in enumerate(paragraphs):
            next_para_type = "end"
            if i < total - 1:
                next_para_type = self._determine_paragraph_type(paragraphs[i + 1])
            segment = self._process_single_paragraph(para, next_para_type)
            schedule.append(segment)

        return schedule

    def process_single(
        self,
        para: Dict[str, Any],
        next_para_type: str = "end",
    ) -> PhysicalAudioSegment:
        """处理单个段落，用于流水线逐段处理模式.

        Args:
            para: 段落字典，包含 text, speaker, emotion, is_dialogue 等
            next_para_type: 下一段落类型 ("narration" | "dialogue" | "end")，用于计算过渡停顿

        Returns:
            PhysicalAudioSegment 物理声学控制块
        """
        return self._process_single_paragraph(para, next_para_type)

    # ── Backward Compatibility ─────────────────────────────────────────────
    def process(
        self,
        annotation: "ParagraphAnnotation",
        voice_map: Optional[list[str]] = None,
        next_para_type: str = "end",
    ) -> PhysicalAudioSegment:
        """向后兼容的旧 API: 将 ParagraphAnnotation 转换为新格式并处理.

        Args:
            annotation: ParagraphAnnotation 对象
            voice_map: 角色声音映射列表 (已弃用，保留兼容性)
            next_para_type: 下一段落类型

        Returns:
            PhysicalAudioSegment 物理声学控制块
        """
        # Convert ParagraphAnnotation to dict format
        para_dict = {
            "text": annotation.text or "",
            "speaker": annotation.speaker_canonical_name or "_narrator_",
            "emotion": annotation.emotion or "neutral",
            "is_dialogue": annotation.is_dialogue or False,
            "emotion_intensity": annotation.emotion_intensity or 0.5,
        }
        return self.process_single(para_dict, next_para_type)

    def _process_single_paragraph(
        self,
        para: Dict[str, Any],
        next_para_type: str,
    ) -> PhysicalAudioSegment:
        """内部单段处理逻辑."""
        text = para.get("text", "")
        speaker = para.get("speaker", "Narrator")
        emotion = para.get("emotion", "neutral")
        intensity = para.get("emotion_intensity", 0.5)
        para_type = self._determine_paragraph_type(para)

        # 1. 基础情绪声学概貌
        from ..config.acoustic_mapping import EmotionAcousticProfile

        default_neutral = EmotionAcousticProfile(speed=1.0, volume_db=0.0, pitch_hz=0.0)
        profile = self.emotion_map.get(emotion, self.emotion_map.get("neutral", default_neutral))
        speed = profile.speed
        volume_db = profile.volume_db
        pitch_hz = profile.pitch_hz

        # 2. 情感强度微调：高强度 → 略微加速/增大偏移
        if intensity > 0.8:
            speed += 0.05
            pitch_hz += 5.0 if pitch_hz >= 0 else -5.0
            volume_db += 0.5
        elif intensity < 0.3:
            speed -= 0.05
            pitch_hz -= 5.0 if pitch_hz >= 0 else -5.0
            volume_db -= 0.5

        # 3. 对话特殊处理：默认略微加速
        if para_type == "dialogue":
            speed += DIALOGUE_SPEED_BOOST

        # 4. 钳制到允许范围
        speed = self._clamp_speed(speed)
        volume_db = self._clamp_volume(volume_db)
        pitch_hz = self._clamp_pitch(pitch_hz)

        # 5. 动态停顿计算
        # 5.1 基础过渡停顿
        base_pause = self.transition_map.get((para_type, next_para_type), 300)

        # 5.2 标点微停顿
        punct_pause = self._calculate_punctuation_delay(text)

        # 5.3 文本长度缓冲
        length_buffer = self._calculate_length_buffer(text)

        total_pause_after = base_pause + punct_pause + length_buffer

        # 6. 组装物理控制块
        segment = PhysicalAudioSegment(
            text=text,
            speaker=speaker,
            speed=speed,
            volume_db=volume_db,
            pitch_hz=pitch_hz,
            pause_after_ms=total_pause_after,
            emotion=emotion,
            paragraph_type=para_type,
        )
        return segment


# ── 便捷函数 ─────────────────────────────────────────────────────────────


def generate_acoustic_schedule(
    paragraphs: List[Dict[str, Any]],
    emotion_map: Optional[Dict[str, EmotionAcousticProfile]] = None,
    transition_map: Optional[Dict[Tuple[str, str], int]] = None,
    punctuation_map: Optional[Dict[str, int]] = None,
) -> List[PhysicalAudioSegment]:
    """模块级便捷函数：生成声学调度表."""
    processor = AudioPostProcessor(
        emotion_map=emotion_map,
        transition_map=transition_map,
        punctuation_map=punctuation_map,
    )
    return processor.generate_acoustic_schedule(paragraphs)
