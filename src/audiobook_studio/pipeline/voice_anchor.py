"""Voice Anchor Module — 跨章节声纹锚定机制 (Issue 1.3).

解决跨章节声纹漂移问题：
- 角色首次出现时注册声纹参考音频
- 后续章节合成时通过 reference_audio 注入参考音频
- 结合 SpeakerSimilarityMetric 监控声纹一致性
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config.hardware_profile import get_hardware_profile
from ..quality.metrics import SpeakerSimilarityMetric, SpeakerSimilarityResult
from ..schemas.book import CharacterVoiceBinding
from ..schemas.tts_routing import TtsRoutingInput

logger = logging.getLogger(__name__)


@dataclass
class VoiceAnchorRecord:
    """声纹锚定记录 - 存储角色的参考音频信息."""

    character_name: str
    voice_id: str
    reference_audio_path: str
    chapter_index: int
    paragraph_index: int
    similarity_threshold: float = 0.85  # 声音相似度阈值 (cosine similarity, range 0-1)
    embedding_model: str = "ecapa_tdnn"  # P2.13: 统一走 ECAPA (speechbrain/spkrec-ecapa-voxceleb)
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "character_name": self.character_name,
            "voice_id": self.voice_id,
            "reference_audio_path": self.reference_audio_path,
            "chapter_index": self.chapter_index,
            "paragraph_index": self.paragraph_index,
            "similarity_threshold": self.similarity_threshold,
            "embedding_model": self.embedding_model,
            "created_at": self.created_at,
        }


@dataclass
class VoiceAnchorConfig:
    """Voice Anchor 配置."""

    enabled: bool = True
    embedding_model: str = "ecapa_tdnn"  # P2.13: 统一走 ECAPA (唯一 speaker embedding 体系)
    similarity_threshold: float = 0.85  # 声音相似度阈值 (cosine similarity, range 0-1)
    max_drift_alerts_per_chapter: int = 3
    reference_audio_dir: str = "storage/voice_anchors"
    mock_mode: bool = False  # 测试模式，不加载真实模型
    device: str = "cpu"  # 计算设备 (cpu | cuda)
    cache_dir: Optional[str] = None  # 模型缓存目录


class VoiceAnchorManager:
    """Voice Anchor 管理器 - 跨章节声纹一致性保障.

    核心功能：
    1. 首次角色出现时自动注册参考音频
    2. 后续章节合成时自动注入参考音频
    3. 声纹漂移检测与告警
    4. 支持多角色并行管理
    """

    def __init__(self, config: Optional[VoiceAnchorConfig] = None):
        self.config = config or VoiceAnchorConfig()
        # P2.13: per-chapter 双层 dict — character_name -> {chapter_index -> anchor}.
        # 同一角色在每章独立布锚 (首段生成时注册), 后续章节命中本章节锚即可,
        # 跨章节独立监控漂移. 单层 (character -> anchor) 时跨章会互相覆盖.
        self._anchors: Dict[str, Dict[int, VoiceAnchorRecord]] = {}
        self._drift_alerts: Dict[int, List[Dict[str, Any]]] = {}  # chapter_index -> alerts
        self._reference_audio_dir = Path(self.config.reference_audio_dir)
        self._reference_audio_dir.mkdir(parents=True, exist_ok=True)

        # Speaker similarity metric for drift detection
        # Map embedding_model to backend
        backend = "wavlm_large" if self.config.embedding_model == "wavlm_large" else "ecapa_tdnn"
        self._similarity_metric = SpeakerSimilarityMetric(
            backend=backend,
            threshold=self.config.similarity_threshold,
            mock_mode=self.config.mock_mode,
            device=self.config.device,
            cache_dir=Path(self.config.cache_dir) if self.config.cache_dir else None,
        )

        logger.info(
            "VoiceAnchorManager initialized: enabled=%s, threshold=%.2f",
            self.config.enabled,
            self.config.similarity_threshold,
        )

    def register_character(
        self,
        character_name: str,
        voice_id: str,
        reference_audio_path: str,
        chapter_index: int,
        paragraph_index: int,
    ) -> Optional[VoiceAnchorRecord]:
        """注册角色的首次声纹参考音频.

        Args:
            character_name: 角色规范名称
            voice_id: 声音ID
            reference_audio_path: 参考音频文件路径
            chapter_index: 首次出现的章节索引
            paragraph_index: 首次出现的段落索引

        Returns:
            VoiceAnchorRecord: 创建的锚定记录
        """
        if not self.config.enabled:
            logger.debug("Voice Anchor disabled, skipping registration")
            return None

        from datetime import datetime

        anchor = VoiceAnchorRecord(
            character_name=character_name,
            voice_id=voice_id,
            reference_audio_path=reference_audio_path,
            chapter_index=chapter_index,
            paragraph_index=paragraph_index,
            similarity_threshold=self.config.similarity_threshold,
            embedding_model=self.config.embedding_model,
            created_at=datetime.now().isoformat(),
        )

        # P2.13: per-chapter 双层 dict — 同角色每章独立布锚, 不互相覆盖.
        self._anchors.setdefault(character_name, {})[chapter_index] = anchor

        # Copy reference audio to anchor directory for persistence
        # P2.13: 文件名按章节区分, 避免跨章节参考音频互相覆盖.
        import shutil

        safe_char = character_name.replace("/", "_")
        dest_path = self._reference_audio_dir / f"{safe_char}_ch{chapter_index}_ref.mp3"
        try:
            shutil.copy2(reference_audio_path, dest_path)
            anchor.reference_audio_path = str(dest_path)
            logger.info(
                "Registered voice anchor for '%s' (ch%d): voice=%s, ref=%s",
                character_name,
                chapter_index,
                voice_id,
                dest_path,
            )
        except Exception as e:
            logger.warning("Failed to copy reference audio: %s", e)

        return anchor

    def _resolve_anchor(
        self,
        character_name: str,
        chapter_index: Optional[int],
    ) -> Optional[VoiceAnchorRecord]:
        """按章节解析声纹锚定 (双层 dict 内部辅助).

        chapter_index=None -> 任一章节命中均可 (兼容旧接口/全章统一锁); 否则精确匹配本章节锚,
        未命中则回退到该角色的任一锚 (跨章容错, 用最早锚作基准监控漂移).
        """
        char_anchors = self._anchors.get(character_name)
        if not char_anchors:
            return None
        if chapter_index is None:
            # 任一章节命中: 优先与传入 chapter_index 最近者. 单测/旧调用无章号时取首个.
            return next(iter(char_anchors.values()))
        exact = char_anchors.get(chapter_index)
        if exact is not None:
            return exact
        # 回退: 跨章容错, 取该角色任一已登记的锚作漂移基准.
        return next(iter(char_anchors.values()))

    def get_anchor(self, character_name: str, chapter_index: Optional[int] = None) -> Optional[VoiceAnchorRecord]:
        """获取角色的声纹锚定记录.

        chapter_index: 指定章节锚; None (默认) -> 任一章节命中 (向后兼容旧调用).
        """
        return self._resolve_anchor(character_name, chapter_index)

    def has_anchor(self, character_name: str, chapter_index: Optional[int] = None) -> bool:
        """检查角色是否已注册声纹锚定.

        chapter_index=None -> 该角色在任一章节有锚即 True (向后兼容旧调用).
        """
        char_anchors = self._anchors.get(character_name)
        if not char_anchors:
            return False
        if chapter_index is None:
            return bool(char_anchors)
        return chapter_index in char_anchors

    def get_reference_audio(self, character_name: str, chapter_index: Optional[int] = None) -> Optional[str]:
        """获取角色的参考音频路径 (用于后续合成注入).

        chapter_index: 指定章节锚; None (默认) -> 任一章节命中.
        """
        anchor = self._resolve_anchor(character_name, chapter_index)
        if anchor and Path(anchor.reference_audio_path).exists():
            return anchor.reference_audio_path
        return None

    def check_drift(
        self,
        character_name: str,
        generated_audio_path: str,
        chapter_index: int,
    ) -> Optional[SpeakerSimilarityResult]:
        """检查生成音频是否发生声纹漂移.

        Args:
            character_name: 角色名称
            generated_audio_path: 新生成的音频文件路径
            chapter_index: 当前章节索引

        Returns:
            SpeakerSimilarityResult: 相似度检测结果，None 表示未启用或无锚定
        """
        if not self.config.enabled:
            return None

        # P2.13: 双层 dict 下按章节解析锚 (本章节优先, 跨章容错回退).
        anchor = self._resolve_anchor(character_name, chapter_index)
        if not anchor:
            logger.debug("No anchor for '%s' (ch%d), skipping drift check", character_name, chapter_index)
            return None

        if not Path(anchor.reference_audio_path).exists():
            logger.warning(
                "Reference audio missing for '%s': %s",
                character_name,
                anchor.reference_audio_path,
            )
            return None

        if not Path(generated_audio_path).exists():
            logger.warning("Generated audio not found: %s", generated_audio_path)
            return None

        try:
            # Compare generated audio with reference
            result = self._similarity_metric.compute(
                target_audio=Path(generated_audio_path),
                reference_audio=Path(anchor.reference_audio_path),
            )

            # Record drift alert if similarity below threshold
            if not result.is_same_speaker:
                self._record_drift_alert(
                    character_name=character_name,
                    chapter_index=chapter_index,
                    similarity=result.similarity,
                    threshold=result.threshold,
                    generated_audio=generated_audio_path,
                )
                logger.warning(
                    "Voice drift detected for '%s' in chapter %d: similarity=%.3f < threshold=%.3f",
                    character_name,
                    chapter_index,
                    result.similarity,
                    result.threshold,
                )
            else:
                logger.debug(
                    "Voice anchor OK for '%s' in chapter %d: similarity=%.3f",
                    character_name,
                    chapter_index,
                    result.similarity,
                )

            return result

        except Exception as e:
            logger.error("Drift check failed for '%s': %s", character_name, e)
            return None

    def _record_drift_alert(
        self,
        character_name: str,
        chapter_index: int,
        similarity: float,
        threshold: float,
        generated_audio: str,
    ) -> None:
        """记录声纹漂移告警."""
        if chapter_index not in self._drift_alerts:
            self._drift_alerts[chapter_index] = []

        alert = {
            "character_name": character_name,
            "chapter_index": chapter_index,
            "similarity": similarity,
            "threshold": threshold,
            "generated_audio": generated_audio,
        }

        self._drift_alerts[chapter_index].append(alert)

        # Check alert count limit
        if len(self._drift_alerts[chapter_index]) > self.config.max_drift_alerts_per_chapter:
            logger.error(
                "Max drift alerts (%d) exceeded for chapter %d",
                self.config.max_drift_alerts_per_chapter,
                chapter_index,
            )

    def get_drift_alerts(self, chapter_index: int) -> List[Dict[str, Any]]:
        """获取章节的声纹漂移告警."""
        return self._drift_alerts.get(chapter_index, [])

    def get_all_anchors(self) -> Dict[str, VoiceAnchorRecord]:
        """获取所有已注册的声纹锚定.

        P2.13: 双层 dict 下返回 character_name -> 任一章节锚 (最新注册者),
        保留单层扁平视图供向后兼容读取 (老接口契约).
        """
        flat: Dict[str, VoiceAnchorRecord] = {}
        for name, chap_anchors in self._anchors.items():
            if chap_anchors:
                flat[name] = next(reversed(chap_anchors.values()))
        return flat

    def inject_reference_audio(
        self,
        character_name: str,
        prosody_overrides: Dict[str, Any],
        chapter_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        """将参考音频注入韵律覆盖参数 (供 TTS 引擎使用).

        Args:
            character_name: 角色名称
            prosody_overrides: 现有的韵律覆盖参数
            chapter_index: 指定章节锚 (P2.13); None (默认) -> 任一章节命中 (向后兼容)

        Returns:
            更新后的韵律覆盖参数 (包含 reference_audio)
        """
        if not self.config.enabled:
            return prosody_overrides

        ref_audio = self.get_reference_audio(character_name, chapter_index=chapter_index)
        if ref_audio:
            prosody_overrides = prosody_overrides or {}
            prosody_overrides["reference_audio"] = ref_audio
            logger.debug("Injected reference audio for '%s': %s", character_name, ref_audio)

        return prosody_overrides

    def get_summary(self) -> Dict[str, Any]:
        """获取 Voice Anchor 状态摘要 (P2.13: 双层 dict 扁平化展示)."""
        total = sum(len(chap_anchors) for chap_anchors in self._anchors.values())
        anchors_flat: Dict[str, Any] = {}
        for name, chap_anchors in self._anchors.items():
            for ch_idx, anchor in chap_anchors.items():
                anchors_flat[f"{name}#ch{ch_idx}"] = anchor.to_dict()
        return {
            "enabled": self.config.enabled,
            "total_anchors": total,
            "anchors": anchors_flat,
            "drift_alerts": {ch: alerts for ch, alerts in self._drift_alerts.items()},
            "config": {
                "embedding_model": self.config.embedding_model,
                "similarity_threshold": self.config.similarity_threshold,
                "max_drift_alerts_per_chapter": self.config.max_drift_alerts_per_chapter,
            },
        }


# Global singleton instance (for backward compatibility)
_voice_anchor_manager: Optional[VoiceAnchorManager] = None


def get_voice_anchor_manager() -> VoiceAnchorManager:
    """获取全局 Voice Anchor 管理器实例."""
    global _voice_anchor_manager
    if _voice_anchor_manager is None:
        # Load config from hardware profile
        hw_profile = get_hardware_profile()
        va_config = hw_profile.voice_anchor

        config = VoiceAnchorConfig(
            enabled=va_config.enabled,
            embedding_model=va_config.embedding_model,
            similarity_threshold=va_config.similarity_threshold,
            max_drift_alerts_per_chapter=va_config.max_drift_alerts_per_chapter,
            mock_mode=getattr(va_config, "mock_mode", False),
            device=getattr(va_config, "device", "cpu"),
            cache_dir=getattr(va_config, "cache_dir", None),
        )
        _voice_anchor_manager = VoiceAnchorManager(config)

    return _voice_anchor_manager


def reset_voice_anchor_manager() -> None:
    """重置全局 Voice Anchor 管理器 (用于测试)."""
    global _voice_anchor_manager
    _voice_anchor_manager = None


# Integration helper for SynthesizePipeline
async def apply_voice_anchor(
    manager: VoiceAnchorManager,
    inputs: List[TtsRoutingInput],  # List[TtsRoutingInput]
    voice_map: List[CharacterVoiceBinding],  # List[CharacterVoiceBinding]
) -> List[TtsRoutingInput]:
    """为输入段落应用 Voice Anchor (自动注入 reference_audio).

    此函数在 SynthesizePipeline.run() 内部调用，
    为每个段落的 routing decision 注入 reference_audio。

    Args:
        manager: VoiceAnchorManager 实例
        inputs: TtsRoutingInput 列表
        voice_map: CharacterVoiceBinding 列表

    Returns:
        更新后的 inputs (prosody_overrides 已注入 reference_audio)
    """
    if not manager.config.enabled:
        return inputs

    for inp in inputs:
        char_name = inp.paragraph_annotation.speaker_canonical_name

        # Check if this is the first appearance (register anchor)
        if not manager.has_anchor(char_name):
            # Find voice_id from voice_map
            char_binding = next(
                (c for c in inp.character_voice_map if c.canonical_name == char_name),
                None,
            )
            if char_binding:
                # Will be registered after first synthesis
                # (need actual audio file path)
                pass
        else:
            # Inject reference audio for subsequent appearances
            ref_audio = manager.get_reference_audio(char_name)
            if ref_audio:
                # This will be picked up by _make_routing_decision or run().
                # Stashed dynamically: ParagraphAnnotation (extra="forbid") has
                # no declared voice_anchor_ref field, so use setattr to express
                # the runtime stash without overshooting the schema contract.
                inp.paragraph_annotation.voice_anchor_ref = ref_audio

    return inputs


if __name__ == "__main__":
    # Demo
    logging.basicConfig(level=logging.INFO)

    config = VoiceAnchorConfig(
        enabled=True,
        similarity_threshold=0.85,
        reference_audio_dir="./test_voice_anchors",
    )

    manager = VoiceAnchorManager(config)

    # Simulate registering a character
    anchor = manager.register_character(
        character_name="narrator",
        voice_id="zf_xiaoxiao",
        reference_audio_path="/fake/narrator_ref.mp3",
        chapter_index=1,
        paragraph_index=0,
    )
    logger.info(f"Registered anchor: {anchor}")

    # Check if anchor exists
    logger.info(f"Has anchor for narrator: {manager.has_anchor('narrator')}")
    logger.info(f"Reference audio: {manager.get_reference_audio('narrator')}")

    # Get summary
    logger.info(f"Summary: {manager.get_summary()}")
