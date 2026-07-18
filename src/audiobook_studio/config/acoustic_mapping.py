"""Acoustic Mapping Configuration — 语义到物理声学参数的动态映射规范.

此模块定义了 AudioPostProcessor 使用的所有映射表：
- EMOTION_ACOUSTIC_MAP: 情感 → 物理声学参数 (语速/音量/音高)
- TRANSITION_PAUSE_MAP: 段落过渡类型 → 基础停顿毫秒数
- PUNCTUATION_PAUSE_MAP: 标点符号 → 微停顿增量毫秒数

设计原则：
- 纯配置驱动，无硬编码魔法数字
- 支持通过环境变量或配置文件热重载
- 所有参数含义明确，便于音频工程师调优
"""

from typing import Dict, Tuple, Optional
from dataclasses import dataclass, field
import os


@dataclass(frozen=True)
class EmotionAcousticProfile:
    """单一情感的声学概貌."""
    speed: float = 1.0          # 语速倍率 (0.7-1.3)
    volume_db: float = 0.0      # 音量增益 dB (-6 到 +6)
    pitch_hz: float = 0.0       # 音高偏移 Hz (-50 到 +50)


# 情感 → 声学参数映射表 (核心配置)
# 可通过 ACOUSTIC_EMOTION_MAP_JSON 环境变量覆盖 (JSON 格式)
EMOTION_ACOUSTIC_MAP: Dict[str, EmotionAcousticProfile] = {
    "angry":      EmotionAcousticProfile(speed=1.15, volume_db=1.5,  pitch_hz=20.0),
    "sad":        EmotionAcousticProfile(speed=0.85, volume_db=-2.0, pitch_hz=-10.0),
    "fearful":    EmotionAcousticProfile(speed=1.20, volume_db=-1.0, pitch_hz=40.0),
    "tense":      EmotionAcousticProfile(speed=1.08, volume_db=0.0,  pitch_hz=10.0),
    "happy":      EmotionAcousticProfile(speed=1.10, volume_db=1.0,  pitch_hz=15.0),
    "surprised":  EmotionAcousticProfile(speed=1.15, volume_db=1.0,  pitch_hz=25.0),
    "disgusted":  EmotionAcousticProfile(speed=0.90, volume_db=-2.0, pitch_hz=-20.0),
    "tender":     EmotionAcousticProfile(speed=0.80, volume_db=-1.0, pitch_hz=-10.0),
    "contemplative": EmotionAcousticProfile(speed=0.80, volume_db=-1.0, pitch_hz=-10.0),
    "whisper":    EmotionAcousticProfile(speed=0.70, volume_db=-6.0, pitch_hz=-20.0),
    "cold_laugh": EmotionAcousticProfile(speed=0.90, volume_db=0.0,  pitch_hz=0.0),
    "sigh":       EmotionAcousticProfile(speed=0.70, volume_db=-3.0, pitch_hz=-10.0),
    "sarcastic":  EmotionAcousticProfile(speed=0.90, volume_db=0.0,  pitch_hz=10.0),
    "neutral":    EmotionAcousticProfile(speed=1.00, volume_db=0.0,  pitch_hz=0.0),
}

# 段落过渡类型 → 基础停顿映射
# key: (当前段落类型, 下一段落类型) -> 毫秒数
# 类型: "narration" (旁白) 或 "dialogue" (对话)
TRANSITION_PAUSE_MAP: Dict[Tuple[str, str], int] = {
    ("narration", "narration"): 300,
    ("narration", "dialogue"):  550,
    ("dialogue", "dialogue"):   400,
    ("dialogue", "narration"):  600,
}

# 标点符号 → 微停顿增量 (ms)
# 用于根据句末标点动态增加 pause_after_ms
PUNCTUATION_PAUSE_MAP: Dict[str, int] = {
    "。": 250,
    "！": 350,
    "？": 300,
    "；": 150,
    "，": 100,
    ".": 250,
    "!": 350,
    "?": 300,
    ";": 150,
    ",": 100,
}

# 文本长度缓冲参数
# 每字符增加的停顿时间 (ms)，用于给听众留出消化长句的时间
LENGTH_BUFFER_MS_PER_CHAR: float = 1.5
LENGTH_BUFFER_MAX_MS: int = 200

# 语速/音量/音高的允许范围 (用于 clamp)
SPEED_MIN: float = 0.7
SPEED_MAX: float = 1.3
VOLUME_DB_MIN: float = -6.0
VOLUME_DB_MAX: float = 6.0
PITCH_HZ_MIN: float = -50.0
PITCH_HZ_MAX: float = 50.0

# 对话加速补偿 (对话默认略微加速以增加自然感)
DIALOGUE_SPEED_BOOST: float = 0.05


def load_emotion_map_from_env() -> Dict[str, EmotionAcousticProfile]:
    """从环境变量加载情感映射覆盖 (JSON 格式).

    环境变量格式示例:
    ACOUSTIC_EMOTION_MAP_JSON='{"angry": {"speed": 1.2, "volume_db": 2.0, "pitch_hz": 30}}'
    """
    import json
    env_json = os.environ.get("ACOUSTIC_EMOTION_MAP_JSON")
    if not env_json:
        return {}
    try:
        data = json.loads(env_json)
        result = {}
        for emotion, params in data.items():
            result[emotion] = EmotionAcousticProfile(
                speed=params.get("speed", 1.0),
                volume_db=params.get("volume_db", 0.0),
                pitch_hz=params.get("pitch_hz", 0.0),
            )
        return result
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        # 静默失败，使用默认配置
        return {}


def load_transition_map_from_env() -> Dict[Tuple[str, str], int]:
    """从环境变量加载过渡停顿映射覆盖."""
    import json
    env_json = os.environ.get("ACOUSTIC_TRANSITION_MAP_JSON")
    if not env_json:
        return {}
    try:
        data = json.loads(env_json)
        result = {}
        for key, value in data.items():
            # key 格式: "narration|dialogue"
            parts = key.split("|")
            if len(parts) == 2:
                result[(parts[0], parts[1])] = int(value)
        return result
    except (json.JSONDecodeError, ValueError):
        return {}


def get_emotion_map() -> Dict[str, EmotionAcousticProfile]:
    """获取合并了环境变量覆盖的情感映射."""
    base = dict(EMOTION_ACOUSTIC_MAP)
    overrides = load_emotion_map_from_env()
    base.update(overrides)
    return base


def get_transition_map() -> Dict[Tuple[str, str], int]:
    """获取合并了环境变量覆盖的过渡映射."""
    base = dict(TRANSITION_PAUSE_MAP)
    overrides = load_transition_map_from_env()
    base.update(overrides)
    return base


def get_punctuation_map() -> Dict[str, int]:
    """获取标点停顿映射 (可扩展支持环境变量)."""
    return dict(PUNCTUATION_PAUSE_MAP)