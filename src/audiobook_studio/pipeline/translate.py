"""Pipeline Stage 7: Multilingual Translation Dubbing - 朗译配音系统.

实现多语言翻译配音，保持角色/情绪映射并进行情感连贯性检查。
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..llm import create_router
from ..models.audio_segment import AudioSegment
from ..schemas import CharacterVoiceBinding, ParagraphAnnotation, TtsRoutingInput
from ..tts.clone import VoiceCloningManager
from .annotate_paragraph import AnnotateParagraphPipeline
from .synthesize import SynthesizePipeline

logger = logging.getLogger(__name__)


class TranslateAndDubPipeline:
    """Pipeline for multilingual translation dubbing (Stage 7)."""

    def __init__(
        self,
        voice_cloning_manager: Optional[VoiceCloningManager] = None,
        annotate_pipeline: Optional[AnnotateParagraphPipeline] = None,
    ):
        self.voice_cloning_manager = voice_cloning_manager
        self.annotate_pipeline = annotate_pipeline

        # Initialize managers if not provided
        if self.voice_cloning_manager is None:
            self.voice_cloning_manager = VoiceCloningManager()
        if self.annotate_pipeline is None:
            self.annotate_pipeline = AnnotateParagraphPipeline()

        # LLM router for translation (uses environment MOCK_LLM etc.)
        self.router = create_router()
        # Synthesizer for TTS (uses environment MOCK_LLM to decide real/mock)
        self.synthesizer = SynthesizePipeline(output_dir="/tmp/tts_output")

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
            from src.audiobook_studio.quality.semantic_coherence import (
                SemanticCoherenceChecker,
            )

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
                source_text = getattr(segment, "text", f"[段落 {segment.id}]")

                # 2. 如果我们有标注信息，使用它来保持角色和情感一致性
                # 否则，创建一个基本的标注
                annotation = getattr(segment, "annotation", None)
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
                    annotation.emotion,
                )

                # 4. 翻译文本（这里我们调用语音克隆管理器的翻译功能）
                # 在实际实现中，这可能涉及调用翻译API
                translated_text = self._translate_text(
                    source_text,
                    "zh-CN",  # 假设源语言是中文
                    target_language,
                    annotation.speaker_canonical_name,
                    annotation.emotion,
                )

                # 5. 应用角色和情感到声音参数
                voice_params = self._apply_voice_characteristics(
                    annotation, target_voice
                )

                # 6. 合成目标语言的音频
                # 在实际实现中，这里会调用TTS引擎
                dubbed_segment = self._synthesize_dubbed_segment(
                    segment, translated_text, target_language, voice_params
                )

                dubbed_segments.append(dubbed_segment)
                report["successful_translations"] += 1

            except Exception as e:
                seg_id = getattr(segment, "id", "unknown")
                logger.error(f"❌ 片段 {seg_id} 翻译失败: {str(e)}")
                report["failed_translations"] += 1
                report["warnings"].append(f"片段 {seg_id} 翻译失败: {str(e)}")

                # 创建失败的段落以保持流程继续
                failed_segment = AudioSegment(
                    project_id=getattr(segment, "project_id", 1),
                    chapter_id=getattr(segment, "chapter_id", 1),
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
                source_texts = [
                    getattr(s, "text", "") for s in segments if hasattr(s, "text")
                ]
                dubbed_texts = [
                    getattr(s, "text", "")
                    for s in dubbed_segments
                    if hasattr(s, "text")
                    and not (hasattr(s, "segment_id") and "_FAILED" in s.segment_id)
                ]

                if source_texts and dubbed_texts:
                    # 调用语义连贯性检查器
                    coherence_result = semantic_checker.check_coherence(
                        source_texts, dubbed_texts, check_emotional_curve=True
                    )

                    report["semantic_coherence_score"] = coherence_result.get("score")
                    report["emotional_continuity_passed"] = coherence_result.get(
                        "passed", False
                    )
                    report["continuity_issues"] = coherence_result.get("issues", [])

                    if report["emotional_continuity_passed"]:
                        logger.info("✅ 情感连贯性检查通过")
                    else:
                        logger.warning(
                            f"⚠️ 情感连贯性检查失败: {len(report['continuity_issues'])} 个问题"
                        )

            except Exception as e:
                logger.error(f"❌ 情感连贯性检查过程中出错: {str(e)}")
                report["warnings"].append(f"情感连贯性检查失败: {str(e)}")

        logger.info(
            f"📊 翻译完成: {report['successful_translations']} 成功, "
            f"{report['failed_translations']} 失败"
        )

        return dubbed_segments, report

    def _get_target_voice(
        self, character_name: str, target_language: str, emotion: str
    ) -> dict:
        """Return a voice configuration for the given target language by querying
        the character voice binding database. Falls back to default if not found.
        """
        from ..database import SessionLocal
        from ..models import Character

        db = SessionLocal()
        try:
            # 查找角色的声音绑定
            character = db.query(Character).filter(
                Character.canonical_name == character_name
            ).first()
            
            if character and character.voice_mapping:
                # 尝试获取目标语言的 voice_id
                voice_mapping = character.voice_mapping
                if isinstance(voice_mapping, dict):
                    voice_id = voice_mapping.get(target_language)
                    if voice_id:
                        return {
                            "voice_id": voice_id,
                            "language": target_language,
                            "base_pitch_shift": 0.0,
                            "base_speed_rate": 1.0,
                            "base_volume": 1.0,
                        }
            
            # 如果没有找到特定语言的声音，使用默认映射
            default_voices = {
                "en-US": "en-US-JennyNeural",
                "es-ES": "es-ES-ElviraNeural",
                "ja-JP": "ja-JP-NanamiNeural",
                "fr-FR": "fr-FR-DeniseNeural",
                "de-DE": "de-DE-KatjaNeural",
                "zh-CN": "zh-CN-XiaoyiNeural",
            }
            voice_id = default_voices.get(target_language, "en-US-JennyNeural")
            
            return {
                "voice_id": voice_id,
                "language": target_language,
                "base_pitch_shift": 0.0,
                "base_speed_rate": 1.0,
                "base_volume": 1.0,
            }
        finally:
            db.close()

    def _translate_text(
        self,
        text: str,
        source_language: str,
        target_language: str,
        character_name: str,
        emotion: str,
    ) -> str:
        """Translate text using LLM while preserving character name and emotion markers."""
        # We'll ask the LLM to translate the text, keeping any special markers like [CharacterName] etc.
        # For simplicity, we just translate the raw text; the caller should ensure that
        # character name and emotion are not part of the text to translate.
        # Build prompt
        prompt = f"""Translate the following text from {source_language} to {target_language}.
        Preserve any special formatting or tags, but translate the natural language parts.
        Text: {text}"""
        # Define a simple Pydantic model for the response
        from pydantic import BaseModel

        class TranslationResult(BaseModel):
            translated_text: str

        try:
            result = self.router.call(
                stage="translate",
                response_model=TranslationResult,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert translator. Translate accurately and naturally.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            return result.output.translated_text.strip()
        except Exception as e:
            logger.error(f"LLM translation failed: {e}")
            # Fallback to a simple placeholder if translation fails
            return f"[{target_language}] {text}"

    def _apply_voice_characteristics(
        self, annotation: ParagraphAnnotation, voice_config: dict
    ) -> dict:
        """Convert emotion to speech_rate and pitch_shift_semitones adjustments."""
        emotion_adjustments = {
            "neutral": (1.0, 0.0),
            "happy": (1.1, 2.0),
            "sad": (0.9, -3.0),
            "angry": (1.2, 1.0),
            "fearful": (1.1, -1.0),
            "surprised": (1.15, 3.0),
            "disgusted": (0.95, -2.0),
        }
        rate, pitch = emotion_adjustments.get(annotation.emotion, (1.0, 0.0))
        base_rate = voice_config.get("base_speed_rate", 1.0)
        base_pitch = voice_config.get("base_pitch_shift", 0.0)
        return {
            "speech_rate": base_rate * rate,
            "pitch_shift_semitones": base_pitch + pitch,
        }

    def _synthesize_dubbed_segment(
        self,
        original_segment: AudioSegment,
        translated_text: str,
        target_language: str,
        voice_config: dict,
    ) -> AudioSegment:
        """Synthesize dubbed audio using the TTS pipeline."""
        # Obtain annotation (make a mutable copy if needed)
        annotation = getattr(original_segment, "annotation", None)
        if annotation is None:
            annotation = ParagraphAnnotation(
                paragraph_index=0,
                speaker_canonical_name="旁白",
                is_dialogue=False,
                emotion="neutral",
                emotion_intensity=0.5,
                speech_rate=1.0,
                pitch_shift_semitones=0.0,
                pause_before_ms=300,
                pause_after_ms=500,
                confidence=0.9,
                needs_sfx=False,
                sfx_tags=[],
            )
        # Apply voice adjustments to annotation
        adj = self._apply_voice_characteristics(annotation, voice_config)
        annotation.speech_rate = adj["speech_rate"]
        annotation.pitch_shift_semitones = adj["pitch_shift_semitones"]
        # Note: we do not modify other annotation fields.

        # Prepare CharacterVoiceBinding for TtsRoutingInput
        sample_quote = translated_text[:20] if translated_text else "样本"
        binding = CharacterVoiceBinding(
            canonical_name=annotation.speaker_canonical_name,
            aliases=[],
            gender="unknown",
            age_range="unknown",
            suggested_voice_id="kokoro_narrator",
            sample_quote=sample_quote,
            cost_limit_per_book=20.0,
            cost_limit_per_chapter=5.0,
            prefer_local=True,
            contract_version=1,
        )

        # Build TtsRoutingInput
        routing_input = TtsRoutingInput(
            paragraph_annotation=annotation,
            text=translated_text,
            character_voice_map=[binding],
            book_id=str(getattr(original_segment, "project_id", "1")),
            chapter_index=int(getattr(original_segment, "chapter_id", 1)),
            paragraph_index=int(getattr(original_segment, "paragraph_id", 0)),
            prefer_local=True,
        )

        # Synthesize audio
        synth_outputs = self.synthesizer.synthesize_paragraphs([routing_input])
        if not synth_outputs:
            raise RuntimeError("Synthesis succeeded but returned no output")
        synth = synth_outputs[0]  # Internal AudioSegment dataclass from synthesize.py

        # Map to ORM AudioSegment
        new_segment = AudioSegment(
            project_id=int(getattr(original_segment, "project_id", 1)),
            chapter_id=int(getattr(original_segment, "chapter_id", 1)),
            paragraph_id=int(getattr(original_segment, "paragraph_id", 0)) + 10000,
            file_path=str(synth.file_path),
            format="mp3",
            duration_ms=int(synth.duration_ms),
            file_size_bytes=None,  # unknown
            sample_rate=24000,  # default; could be derived from synth if available
            channels=1,
            engine=str(synth.engine),
            voice_id=str(synth.voice_id),
            prosody_overrides=None,
        )
        return new_segment
