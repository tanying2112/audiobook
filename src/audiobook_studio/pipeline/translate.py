"""Pipeline Stage 7: Multilingual Translation Dubbing - 朗译配音系统.

实现多语言翻译配音，保持角色/情绪映射并进行情感连贯性检查。
"""

import logging
from typing import List, Tuple, Dict, Any, Optional

from ..models.audio_segment import AudioSegment
from ..schemas import ParagraphAnnotation
from ..tts.clone import VoiceCloningManager
from .annotate_paragraph import AnnotateParagraphPipeline

logger = logging.getLogger(__name__)


class TranslateAndDubPipeline:
    """Pipeline for multilingual translation dubbing (Stage 7)."""

    def __init__(
        self,
        voice_cloning_manager: Optional[VoiceCloningManager] = None,
        annotate_pipeline: Optional[AnnotateParagraphPipeline] = None,        mock_mode: bool = False,
    ):
        self.voice_cloning_manager = voice_cloning_manager
        self.annotate_pipeline = annotate_pipeline
        self.mock_mode = mock_mode

        # Initialize managers if not provided
        if self.voice_cloning_manager is None:
            self.voice_cloning_manager = VoiceCloningManager()

        if self.annotate_pipeline is None:
            self.annotate_pipeline = AnnotateParagraphPipeline(mock_mode=mock_mode)
    def translate_and_dub(
        self,
        segments: List[AudioSegment],
        target_language: str,
        book_title: str = "",
        author: str = "",
    ) -> Tuple[List[AudioSegment], Dict[str, Any]]:
        """
        执行多语言翻译配音流程.

        Args:
            segments: 源语言音频片段列表
            target_language: 目标语言代码 (如 "en-US", "es-ES")
            book_title: 书籍标题 (用于上下文)
            author: 作者 (用于上下文)

        Returns:
            (翻译后的音频片段列表, 处理报告)
        """
        logger.info(f"🌍 开始多语言翻译配音: {len(segments)} 片段 → {target_language}")

        # 导入语义连贯性检查器
        try:
            from scripts.semantic_coherence import SemanticCoherenceChecker
            semantic_checker = SemanticCoherenceChecker()
        except ImportError:
            logger.warning("⚠️ 语义连贯性检查器未找到，将跳过 emotional continuity 检查")
            semantic_checker = None

        dubbed_segments = []
        report = {
            "source_segments": len(segments),
            "target_language": target_language,
            "book_title": book_title,
            "author": author,
            "successful_translations": 0,
            "failed_translations": 0,
            "warnings": [],
            "emotional_continuity_passed": False,
            "continuity_issues": [],
            "semantic_coherence_score": None,
        }

        # 为每个片段执行翻译和配音
        for segment in segments:
            try:
                # 1. 提取片段文本和元数据
                # 注意：这里我们假设AudioSegment有一个text属性或可以从其他地方获取文本
                # 在实际实现中，可能需要从数据库或其他源获取原始文本
                source_text = getattr(segment, 'text', f"[段落 {segment.id}]")

                # 2. 如果我们有标注信息，使用它来保持角色和情感一致性
                # 否则，创建一个基本的标注
                annotation = getattr(segment, 'annotation', None)
                if annotation is None:
                    # 创建默认标注（在实际系统中，这应该来自管线的前面步骤）
                    annotation = ParagraphAnnotation(
                        paragraph_index=0,  # 这应该从segment中获取
                        speaker_canonical_name="旁白",
                        is_dialogue=False,
                        emotion="neutral",
                        emotion_intensity=0.5,
                        speech_rate=1.0,
                        pitch_shift_semitones=0,
                        pause_before_ms=300,
                        pause_after_ms=500,
                        confidence=0.9,
                        needs_sfx=False,
                        sfx_tags=[],
                    )

                # 3. 获取目标语言的角色声音
                target_voice = self._get_target_voice(
                    annotation.speaker_canonical_name,
                    target_language,
                    annotation.emotion
                )

                # 4. 翻译文本（这里我们调用语音克隆管理器的翻译功能）
                # 在实际实现中，这可能涉及调用翻译API
                translated_text = self._translate_text(
                    source_text,
                    "zh-CN",  # 假设源语言是中文
                    target_language,
                    annotation.speaker_canonical_name,
                    annotation.emotion
                )

                # 5. 应用角色和情感到声音参数
                voice_params = self._apply_voice_characteristics(
                    annotation,
                    target_voice
                )

                # 6. 合成目标语言的音频
                # 在实际实现中，这里会调用TTS引擎
                dubbed_segment = self._synthesize_dubbed_segment(
                    segment,
                    translated_text,
                    target_language,
                    voice_params
                )

                dubbed_segments.append(dubbed_segment)
                report["successful_translations"] += 1

            except Exception as e:
                seg_id = getattr(segment, 'id', 'unknown')
                logger.error(f"❌ 片段 {seg_id} 翻译失败: {str(e)}")
                report["failed_translations"] += 1
                report["warnings"].append(f"片段 {seg_id} 翻译失败: {str(e)}")

                # 创建失败的段落以保持流程继续
                failed_segment = AudioSegment(
                    project_id=getattr(segment, 'project_id', 1),
                    chapter_id=getattr(segment, 'chapter_id', 1),
                    paragraph_id=-1,  # Mark as failed
                    file_path="",
                    duration_ms=0,
                    engine="failed",
                    voice_id="",
                )
                dubbed_segments.append(failed_segment)

        # 7. 检查情感连贯性（如果有语义连贯性检查器）
        if semantic_checker and len(segments) > 1 and len(dubbed_segments) > 1:
            try:
                # 这里我们需要提取文本进行语义连贯性检查
                # 在实际实现中，这会更复杂
                source_texts = [getattr(s, 'text', '') for s in segments if hasattr(s, 'text')]
                dubbed_texts = [getattr(s, 'text', '') for s in dubbed_segments if hasattr(s, 'text') and not (hasattr(s, 'segment_id') and '_FAILED' in s.segment_id)]

                if source_texts and dubbed_texts:
                    # 调用语义连贯性检查器
                    coherence_result = semantic_checker.check_coherence(
                        source_texts,
                        dubbed_texts,
                        check_emotional_curve=True
                    )

                    report["semantic_coherence_score"] = coherence_result.get("score")
                    report["emotional_continuity_passed"] = coherence_result.get("passed", False)
                    report["continuity_issues"] = coherence_result.get("issues", [])

                    if report["emotional_continuity_passed"]:
                        logger.info("✅ 情感连贯性检查通过")
                    else:
                        logger.warning(f"⚠️ 情感连贯性检查失败: {len(report['continuity_issues'])} 个问题")

            except Exception as e:
                logger.error(f"❌ 情感连贯性检查过程中出错: {str(e)}")
                report["warnings"].append(f"情感连贯性检查失败: {str(e)}")

        logger.info(
            f"📊 翻译完成: {report['successful_translations']} 成功, "
            f"{report['failed_translations']} 失败"
        )

        return dubbed_segments, report

    def _get_target_voice(
        self,
        character_name: str,
        target_language: str,
        emotion: str
    ) -> Dict[str, Any]:
        """获取目标语言的角色声音配置."""
        # 在实际实现中，这会从声音库或数据库获取
        # 这里我们返回一个模拟的声音配置
        return {
            "voice_id": f"{character_name}_{target_language}_{emotion}",
            "language": target_language,
            "base_pitch_shift": 0.0,
            "base_speed_rate": 1.0,
            "base_volume": 1.0
        }

    def _translate_text(
        self,
        text: str,
        source_language: str,
        target_language: str,
        character_name: str,
        emotion: str
    ) -> str:
        """翻译文本同时保持角色和情感标记."""
        # 在实际实现中，这里会调用翻译API（如Google Translate, DeepL等）
        # 并且会保护角色和情感标记不被翻译

        # 简化实现：添加翻译前缀
        if source_language != target_language:
            lang_names = {
                "zh-CN": "中文",
                "en-US": "English",
                "es-ES": "Español",
                "ja-JP": "日本語"
            }
            source_name = lang_names.get(source_language, source_language)
            target_name = lang_names.get(target_language, target_language)
            return f"[{target_name} translation of: {text}]"
        else:
            return text

    def _apply_voice_characteristics(
        self,
        annotation: ParagraphAnnotation,
        voice_config: Dict[str, Any]
    ) -> Dict[str, float]:
        """应用角色和情感特征到声音参数."""
        # 获取情感映射（在实际系统中，这可能来自配置）
        emotion_adjustments = {
            "neutral": {"pitch_shift": 0.0, "speed_rate": 1.0, "volume": 1.0},
            "happy": {"pitch_shift": 2.0, "speed_rate": 1.1, "volume": 1.05},
            "sad": {"pitch_shift": -3.0, "speed_rate": 0.9, "volume": 0.9},
            "angry": {"pitch_shift": 1.0, "speed_rate": 1.2, "volume": 1.3},
            "fearful": {"pitch_shift": -1.0, "speed_rate": 1.1, "volume": 0.8},
            "surprised": {"pitch_shift": 3.0, "speed_rate": 1.15, "volume": 1.1},
            "disgusted": {"pitch_shift": -2.0, "speed_rate": 0.95, "volume": 0.9},
        }

        adjustment = emotion_adjustments.get(annotation.emotion, emotion_adjustments["neutral"])

        return {
            "pitch_shift": voice_config["base_pitch_shift"] + adjustment["pitch_shift"],
            "speed_rate": voice_config["base_speed_rate"] * adjustment["speed_rate"],
            "volume": voice_config["base_volume"] * adjustment["volume"],
        }

    def _synthesize_dubbed_segment(
        self,
        original_segment: AudioSegment,
        translated_text: str,
        target_language: str,
        voice_params: Dict[str, float]
    ) -> AudioSegment:
        """合成目标语言的配音片段."""
        # 在实际实现中，这里会调用TTS引擎（如Kokoro-ONNX或Edge-TTS）
        # 这里我们创建一个模拟的音频片段

        # 估算持续时间（基于文本长度和语速）
        base_duration_per_char = 100  # 毫秒/字符（估算）
        estimated_duration = max(
            1000,  # 最小1秒
            len(translated_text) * base_duration_per_char / voice_params["speed_rate"]
        )

        segment = AudioSegment(
            # Use original segment's id to create new paragraph_id
            project_id=original_segment.project_id,
            chapter_id=original_segment.chapter_id,
            paragraph_id=original_segment.paragraph_id + 10000,  # Offset to avoid collision
            file_path=f"/tmp/dubbed_{original_segment.id}_{target_language}.wav",
            duration_ms=int(estimated_duration),
            engine="kokoro",
            voice_id=voice_params.get("voice_id", "default"),
        )
        # Store translated text for semantic coherence checks
        segment.text = translated_text
        return segment