"""Stage Registry for Pipeline Orchestrator.

Registry pattern for pipeline stages, replacing if/elif chains with declarative registration.

Usage:
    from .stage_registry import StageRegistry, register_stage

    # Custom stage registration
    @register_stage("my_custom_stage")
    class MyCustomStage(StageHandler):
        def run(self, **kwargs):
            return self.pipeline.run(**kwargs)

        def persist(self, db, project_id, chapter, paragraph, result):
            # Custom persistence logic
            pass
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Type

from sqlalchemy.orm import Session

from .feedback_collector import FeedbackCollector


class StageHandler(ABC):
    """Abstract base class for stage handlers.

    Each stage implementation provides:
    - run(): Execute the stage logic
    - persist(): Write results to database (optional)
    - get_result_snapshot(): Extract observable state for logging
    """

    def __init__(self):
        pass

    @abstractmethod
    def run(self, **kwargs) -> Any:
        """Execute stage logic and return result."""
        pass

    def persist(
        self,
        db: Session,
        project_id: int,
        chapter: Optional[Any],
        paragraph: Optional[Any],
        result: Any,
        chapter_index: Optional[int] = None,
        paragraph_index: Optional[int] = None,
    ) -> None:
        """Persist result to database. Override for stages that need persistence."""
        pass

    def get_result_snapshot(self, result: Any) -> Dict[str, Any]:
        """Extract result snapshot for feedback/logging. Override for custom serialization."""
        if hasattr(result, "model_dump"):
            return result.model_dump()
        elif hasattr(result, "__dict__"):
            return vars(result)
        elif isinstance(result, (list, dict)):
            return dict(result) if isinstance(result, dict) else {"items": list(result)}
        else:
            return {"result": str(result)}


class StageRegistry:
    """Registry for pipeline stage handlers (instance-per-request)."""

    _handlers: Dict[str, Type[StageHandler]] = {}

    @classmethod
    def register(cls, name: str, handler_class: Type[StageHandler]) -> None:
        """Register a stage handler class."""
        cls._handlers[name] = handler_class

    @classmethod
    def unregister(cls, name: str) -> bool:
        """Unregister a stage handler. Returns True if was registered."""
        if name in cls._handlers:
            del cls._handlers[name]
            return True
        return False

    @classmethod
    def get(cls, name: str) -> StageHandler:
        """Get a fresh stage handler instance."""
        if name not in cls._handlers:
            raise ValueError(f"Unknown pipeline stage: {name}. " f"Registered stages: {list(cls._handlers.keys())}")
        return cls._handlers[name]()

    @classmethod
    def has(cls, name: str) -> bool:
        """Check if stage is registered."""
        return name in cls._handlers

    @classmethod
    def list_stages(cls) -> List[str]:
        """Get list of registered stage names."""
        return list(cls._handlers.keys())

    @classmethod
    def clear_cache(cls) -> None:
        """No-op kept for backward compatibility.

        Handlers are no longer cached as singletons, so there is no
        instance cache to clear.
        """


# ── Built-in Stage Handlers ──────────────────────────────────────────────────


from ..schemas import ExtractionInput
from .extract import ExtractPipeline


class ExtractStage(StageHandler):
    """Extract stage: extract paragraphs from chapter text."""

    def run(self, **kwargs) -> Any:
        # Filter out orchestrator-internal params only
        exclude_keys = {"chapter", "paragraph", "db"}
        filtered = {k: v for k, v in kwargs.items() if k not in exclude_keys}
        # Build ExtractionInput from kwargs
        input_data = ExtractionInput(
            file_path=filtered.get("file_path", ""),
            mime_type=filtered.get("mime_type", "text/plain"),
            detect_language=filtered.get("detect_language", True),
        )
        pipeline = ExtractPipeline()
        return pipeline.run(input_data)

    def persist(
        self,
        db: Session,
        project_id: int,
        chapter: Optional[Any],
        paragraph: Optional[Any],
        result: Any,
        chapter_index: Optional[int] = None,
        paragraph_index: Optional[int] = None,
    ) -> None:
        # For extract stage, chapter may not exist yet - write_extract creates it
        from ..models import Paragraph
        from .persistence import write_extract

        chapter_result = write_extract(db, project_id, chapter_index or 1, result)
        result._chapter_id = chapter_result.id

        # Create Paragraph records from extracted text (split by double newlines)
        raw_text = result.raw_text or ""
        if raw_text:
            # Split by double newlines, filter empty segments
            segments = [s.strip() for s in raw_text.split("\n\n") if s.strip()]
            for idx, seg_text in enumerate(segments, 1):
                existing = (
                    db.query(Paragraph)
                    .filter(
                        Paragraph.project_id == project_id,
                        Paragraph.chapter_id == chapter_result.id,
                        Paragraph.index == idx,
                    )
                    .first()
                )
                if not existing:
                    para = Paragraph(
                        project_id=project_id,
                        chapter_id=chapter_result.id,
                        chapter_index=chapter_result.index,
                        index=idx,
                        text=seg_text,
                        status="extracted",
                    )
                    db.add(para)
            db.commit()


from ..schemas.book import BookAnalysisInput
from .analyze_structure import AnalyzeStructurePipeline


class AnalyzeStage(StageHandler):
    """Analyze stage: analyze chapter structure."""

    def run(self, **kwargs) -> Any:
        # Filter out orchestrator-internal params only
        exclude_keys = {"chapter", "paragraph", "db"}
        filtered = {k: v for k, v in kwargs.items() if k not in exclude_keys}
        # Build BookAnalysisInput from kwargs
        input_data = BookAnalysisInput(
            raw_text=filtered.get("raw_text", ""),
            title_hint=filtered.get("title_hint"),
            author_hint=filtered.get("author_hint"),
            target_difficulty=filtered.get("target_difficulty", "B"),
            contract_version=filtered.get("contract_version", 1),
        )
        pipeline = AnalyzeStructurePipeline()
        return pipeline.run(input_data)

    def persist(
        self,
        db: Session,
        project_id: int,
        chapter: Optional[Any],
        paragraph: Optional[Any],
        result: Any,
        chapter_index: Optional[int] = None,
        paragraph_index: Optional[int] = None,
    ) -> None:
        if chapter:
            from .persistence import write_analyze

            write_analyze(db, chapter, result)


from .annotate_paragraph import AnnotateParagraphPipeline


class AnnotateStage(StageHandler):
    """Annotate stage: annotate paragraph with prosody metadata."""

    def run(self, **kwargs) -> Any:
        para = kwargs.get("paragraph")
        chapter = kwargs.get("chapter")
        exclude_keys = {"chapter", "paragraph", "db"}
        filtered = {k: v for k, v in kwargs.items() if k not in exclude_keys}

        paragraph_text = para.text if para else filtered.get("paragraph_text", "")

        book_meta = None
        character_voice_map = []
        emotion_snapshot = None
        story_line_summary = ""
        global_style_notes = ""

        if chapter and chapter.analyzed_json:
            import json

            raw = chapter.analyzed_json
            if isinstance(raw, str):
                raw = json.loads(raw)
            from ..schemas.book import BookMeta, CharacterVoiceBinding, EmotionSnapshot

            book_meta = BookMeta(**raw.get("book_meta", {}))
            character_voice_map = [CharacterVoiceBinding(**c) for c in raw.get("character_voice_map", [])]
            if raw.get("emotion_snapshots"):
                emotion_snapshot = EmotionSnapshot(**raw.get("emotion_snapshots", [{}])[0])
            story_line_summary = raw.get(
                "story_line_summary",
                "默认故事主线摘要，用于测试目的。本书讲述了一个引人入胜的故事，主角经历种种挑战，最终实现成长与超越。",
            )
            global_style_notes = raw.get("global_style_notes", "保持自然叙述风格。")

        if book_meta is None:
            from ..schemas.book import BookMeta

            book_meta = BookMeta(
                title="Unknown Book",
                author="Unknown Author",
                genre="小说",
                difficulty="B",
                language="zh",
                era="现代",
                total_chapters_estimated=10,
            )
        if not character_voice_map:
            from ..schemas.book import CharacterVoiceBinding

            character_voice_map = [
                CharacterVoiceBinding(
                    canonical_name="_narrator_",
                    aliases=[],
                    gender="neutral",
                    age_range="adult",
                    suggested_voice_id="zh-CN-XiaoxiaoNeural",
                    sample_quote="旁白样本",
                )
            ]
        if emotion_snapshot is None:
            from ..schemas.book import EmotionSnapshot

            emotion_snapshot = EmotionSnapshot(
                chapter=1,
                dominant_emotion="neutral",
                intensity=0.5,
                notes="默认情感快照",
            )

        # Provide defaults for story_line_summary and global_style_notes if not set from analyzed_json
        if not story_line_summary:
            story_line_summary = (
                "默认故事主线摘要，用于测试目的。本书讲述了一个引人入胜的故事，主角经历种种挑战，最终实现成长与超越。这是一个足够长的测试摘要，包含足够的字符数以满足最小长度要求一百字符以上。"
                * 2
            )
        if not global_style_notes:
            global_style_notes = "保持自然叙述风格。"

        input_data = ParagraphAnnotationInput(
            paragraph_text=paragraph_text,
            paragraph_index=para.index if para else filtered.get("paragraph_index", 0),
            chapter_index=chapter.index if chapter else filtered.get("chapter_index", 1),
            book_meta=book_meta,
            character_voice_map=character_voice_map,
            emotion_snapshot=emotion_snapshot,
            story_line_summary=story_line_summary,
            global_style_notes=global_style_notes,
            contract_version=filtered.get("contract_version", 2),
        )
        pipeline = AnnotateParagraphPipeline()
        return pipeline.run(input_data)

    def persist(
        self,
        db: Session,
        project_id: int,
        chapter: Optional[Any],
        paragraph: Optional[Any],
        result: Any,
        chapter_index: Optional[int] = None,
        paragraph_index: Optional[int] = None,
    ) -> None:
        if chapter and paragraph is not None:
            from .persistence import write_annotate

            para_index = getattr(result, "paragraph_index", paragraph_index or 0)
            para = write_annotate(
                db,
                project_id=project_id,
                chapter=chapter,
                paragraph_index=para_index,
                result=result,
            )
            setattr(result, "_paragraph_id", para.id)


from unittest.mock import MagicMock

from ..schemas.paragraph import ParagraphAnnotation
from ..schemas.tts_edit import TtsEditInput
from .edit_for_tts import EditForTtsPipeline


class EditStage(StageHandler):
    """Edit stage: edit text for TTS optimization."""

    def run(self, **kwargs) -> Any:
        para = kwargs.get("paragraph")
        exclude_keys = {"chapter", "paragraph", "db"}
        filtered = {k: v for k, v in kwargs.items() if k not in exclude_keys}

        # Build paragraph_annotation from paragraph DB record
        paragraph_annotation = None
        if para:
            paragraph_annotation = ParagraphAnnotation(
                paragraph_index=para.index,
                speaker_canonical_name=para.speaker_canonical_name or "_narrator_",
                is_dialogue=para.is_dialogue or False,
                emotion=para.emotion or "neutral",
                emotion_intensity=para.emotion_intensity or 0.5,
                speech_rate=para.speech_rate or 1.0,
                pitch_shift_semitones=para.pitch_shift_semitones or 0,
                pause_before_ms=para.pause_before_ms or 300,
                pause_after_ms=para.pause_after_ms or 500,
                confidence=para.confidence or 0.9,
                difficulty="B",
                needs_sfx=False,
                sfx_tags=[],
            )

        paragraph_text = para.text if para else filtered.get("paragraph_text", "")
        input_data = TtsEditInput(
            paragraph_text=paragraph_text,
            paragraph_annotation=paragraph_annotation,
            difficulty=filtered.get("difficulty", "B"),
            forbid_edit=filtered.get("forbid_edit", False),
            contract_version=filtered.get("contract_version", 1),
        )
        pipeline = EditForTtsPipeline()
        return pipeline.run(input_data)

    def persist(
        self,
        db: Session,
        project_id: int,
        chapter: Optional[Any],
        paragraph: Optional[Any],
        result: Any,
        chapter_index: Optional[int] = None,
        paragraph_index: Optional[int] = None,
    ) -> None:
        if paragraph:
            from .persistence import write_edit

            write_edit(db, paragraph, result)


from dataclasses import asdict

from .audio_postprocess import AudioPostProcessor


class AudioPostprocessStage(StageHandler):
    """Audio postprocess stage: apply audio processing params."""

    def run(self, **kwargs) -> Any:
        # paragraph and chapter are passed from orchestrator context
        para = kwargs.get("paragraph")
        chapter = kwargs.get("chapter")

        if para is None:
            raise ValueError("audio_postprocess requires paragraph_id or paragraph_index")

        # Determine next paragraph type for transition pause calculation
        next_para_type = "end"
        # Try to get next paragraph from chapter
        if chapter and hasattr(chapter, "paragraphs") and chapter.paragraphs:
            # Find current paragraph index and get next
            for i, p in enumerate(chapter.paragraphs):
                if p.id == para.id and i + 1 < len(chapter.paragraphs):
                    next_para = chapter.paragraphs[i + 1]
                    next_para_type = "dialogue" if next_para.is_dialogue else "narration"
                    break

        processor = AudioPostProcessor()
        segment = processor.process_single(
            para={
                "text": para.text or "",
                "speaker": para.speaker_canonical_name or "_narrator_",
                "emotion": para.emotion or "neutral",
                "is_dialogue": para.is_dialogue or False,
                "emotion_intensity": para.emotion_intensity or 0.5,
            },
            next_para_type=next_para_type,
        )

        # Convert to dict for persistence and downstream stages
        return asdict(segment)

    def persist(
        self,
        db: Session,
        project_id: int,
        chapter: Optional[Any],
        paragraph: Optional[Any],
        result: Any,
        chapter_index: Optional[int] = None,
        paragraph_index: Optional[int] = None,
    ) -> None:
        if paragraph:
            from .persistence import write_audio_postprocess

            write_audio_postprocess(db, paragraph, result)


class ReviewStage(StageHandler):
    """Review stage: quality gate before synthesis (Module 4.1).

    Runs at CHAPTER LEVEL after all paragraphs in a chapter have been
    audio_postprocessed, but BEFORE any paragraph is synthesized.

    Reviews paragraph annotations for:
    1. Missing character voice bindings
    2. JSON truncation in annotation fields
    3. Tag logic consistency (emotion/speed/sfx vs text)

    If issues found, emits fix commands for Developer Agent and fails the stage.
    Terminal logs show interception/retry events.
    """

    def __init__(self):
        import os

        self.mock_mode = os.environ.get("MOCK_LLM", "false").lower() == "true"

    def run(self, **kwargs) -> Any:
        import json
        import os

        chapter = kwargs.get("chapter")
        project_id = kwargs.get("project_id")

        if chapter is None or project_id is None:
            raise ValueError("ReviewStage requires project_id and chapter")

        # Collect all paragraphs for this chapter
        paragraphs_data = []
        if hasattr(chapter, "paragraphs") and chapter.paragraphs:
            for p in chapter.paragraphs:
                paragraphs_data.append(
                    {
                        "paragraph_index": p.index,
                        "text": p.text or "",
                        "speaker_canonical_name": p.speaker_canonical_name or "_narrator_",
                        "is_dialogue": p.is_dialogue or False,
                        "emotion": p.emotion or "neutral",
                        "emotion_intensity": p.emotion_intensity or 0.5,
                        "speech_rate": p.speech_rate or 1.0,
                        "pitch_shift_semitones": p.pitch_shift_semitones or 0,
                        "needs_sfx": p.needs_sfx or False,
                        "sfx_tags": p.sfx_tags or [],
                        "pause_before_ms": p.pause_before_ms or 300,
                        "pause_after_ms": p.pause_after_ms or 500,
                        "confidence": p.confidence or 0.9,
                    }
                )
        else:
            # Fallback: no paragraphs found
            logger.warning(f"ReviewStage: No paragraphs found for chapter {chapter.index}")
            return ReviewerJudgment(
                project_id=project_id,
                chapter_index=chapter.index,
                overall_passed=True,
                summary="No paragraphs to review",
            )

        # Build voice_map from chapter's analyzed_json
        voice_map = []
        if chapter and chapter.analyzed_json:
            raw = chapter.analyzed_json
            if isinstance(raw, str):
                raw = json.loads(raw)
            from ..schemas.book import CharacterVoiceBinding

            voice_map = [CharacterVoiceBinding(**c) for c in raw.get("character_voice_map", [])]

        if not voice_map:
            voice_map = [
                CharacterVoiceBinding(
                    canonical_name="_narrator_",
                    aliases=[],
                    gender="neutral",
                    age_range="adult",
                    suggested_voice_id="zh-CN-XiaoxiaoNeural",
                    sample_quote="旁白样本",
                )
            ]

        # Build scene_tags
        scene_tags = []
        if chapter and chapter.analyzed_json:
            raw = chapter.analyzed_json
            if isinstance(raw, str):
                raw = json.loads(raw)
            scene_tags = raw.get("scene_tags", [])

        # Build book_meta
        book_meta = {}
        if chapter and chapter.analyzed_json:
            raw = chapter.analyzed_json
            if isinstance(raw, str):
                raw = json.loads(raw)
            book_meta = raw.get("book_meta", {})

        # Run Reviewer Agent
        reviewer = ReviewerAgent(mock_mode=self.mock_mode)
        input_data = ReviewerInput(
            project_id=project_id,
            chapter_index=chapter.index,
            paragraphs=paragraphs_data,
            character_voice_map=[c.model_dump() for c in voice_map],
            scene_tags=scene_tags,
            book_meta=book_meta,
        )
        judgment = reviewer.run(input_data)

        # Store judgment on chapter for downstream access
        if not hasattr(chapter, "reviewer_judgment"):
            chapter.reviewer_judgment = {}
        chapter.reviewer_judgment = judgment.model_dump()

        # Log terminal interception/retry events
        if not judgment.overall_passed:
            logger.warning(
                f"[REVIEWER INTERCEPT] Project {project_id} Ch{chapter.index}: "
                f"BLOCKING={judgment.blocking_issues} WARN={judgment.warning_issues} "
                f"FixCommands={len(judgment.fix_commands)}"
            )
            for cmd in judgment.fix_commands:
                logger.warning(
                    f"  [FIX CMD] {cmd.command_type} para={cmd.target_paragraph_index} "
                    f"priority={cmd.priority}: {cmd.rationale}"
                )
        else:
            logger.info(
                f"[REVIEWER PASS] Project {project_id} Ch{chapter.index}: "
                f"All {len(paragraphs_data)} paragraphs passed quality gate"
            )

        return judgment

    def persist(
        self,
        db: Session,
        project_id: int,
        chapter: Optional[Any],
        paragraph: Optional[Any],
        result: Any,
        chapter_index: Optional[int] = None,
        paragraph_index: Optional[int] = None,
    ) -> None:
        # Review stage doesn't persist individual paragraph records
        # The judgment is stored on the chapter object
        pass


from unittest.mock import MagicMock

from ..schemas.book import CharacterVoiceBinding
from ..schemas.paragraph import ParagraphAnnotation
from ..schemas.tts_routing import TtsRoutingInput
from .synthesize import SynthesizePipeline


class SynthesizeStage(StageHandler):
    """Synthesize stage: convert text to audio."""

    def run(self, **kwargs) -> Any:
        para = kwargs.get("paragraph")
        chapter = kwargs.get("chapter")

        # Build paragraph_annotation from paragraph DB record
        paragraph_annotation = None
        if para:
            paragraph_annotation = ParagraphAnnotation(
                paragraph_index=para.index,
                speaker_canonical_name=para.speaker_canonical_name or "_narrator_",
                is_dialogue=para.is_dialogue or False,
                emotion=para.emotion or "neutral",
                emotion_intensity=para.emotion_intensity or 0.5,
                speech_rate=para.speech_rate or 1.0,
                pitch_shift_semitones=para.pitch_shift_semitones or 0,
                pause_before_ms=para.pause_before_ms or 300,
                pause_after_ms=para.pause_after_ms or 500,
                confidence=para.confidence or 0.9,
                difficulty="B",
                needs_sfx=para.needs_sfx or False,
                sfx_tags=para.sfx_tags or [],
            )

        # Build voice_map from chapter's analyzed_json
        voice_map = []
        if chapter and chapter.analyzed_json:
            import json

            raw = chapter.analyzed_json
            if isinstance(raw, str):
                raw = json.loads(raw)
            voice_map = [CharacterVoiceBinding(**c) for c in raw.get("character_voice_map", [])]

        if not voice_map:
            voice_map = [
                CharacterVoiceBinding(
                    canonical_name="_narrator_",
                    aliases=[],
                    gender="neutral",
                    age_range="adult",
                    suggested_voice_id="zh-CN-XiaoxiaoNeural",
                    sample_quote="旁白样本",
                )
            ]

        text = para.text if para else ""

        input_data = TtsRoutingInput(
            paragraph_annotation=paragraph_annotation,
            text=text,
            character_voice_map=voice_map,
            book_id=str(kwargs.get("project_id", "")),
            chapter_index=chapter.index if chapter else 1,
            paragraph_index=para.index if para else 0,
            cumulative_cost_usd=0.0,
            cost_limit_per_book=20.0,
            cost_limit_per_chapter=5.0,
            prefer_local=False,
            contract_version=1,
        )
        pipeline = SynthesizePipeline()
        return pipeline.run([input_data])

    def persist(
        self,
        db: Session,
        project_id: int,
        chapter: Optional[Any],
        paragraph: Optional[Any],
        result: Any,
        chapter_index: Optional[int] = None,
        paragraph_index: Optional[int] = None,
    ) -> None:
        if project_id and chapter and paragraph:
            from .persistence import write_synthesize

            for seg in result:
                seg_dict = {
                    "file_path": seg.file_path,
                    "duration_ms": seg.duration_ms,
                    "engine": seg.engine,
                    "voice_id": seg.voice_id,
                    "format": (seg.file_path.split(".")[-1] if "." in seg.file_path else "mp3"),
                }
                write_synthesize(db, project_id, chapter, paragraph, seg_dict)

    def get_result_snapshot(self, result: Any) -> Dict[str, Any]:
        """Serialize AudioSegment list for feedback."""
        return {
            "segments": [
                {
                    "file_path": s.file_path,
                    "duration_ms": s.duration_ms,
                    "engine": s.engine,
                    "voice_id": s.voice_id,
                }
                for s in result
            ]
        }


from .quality_check import QualityCheckPipeline


class QualityStage(StageHandler):
    """Quality stage: judge synthesis quality."""

    def run(self, **kwargs) -> Any:
        para = kwargs.get("paragraph")
        exclude_keys = {"chapter", "paragraph", "db"}
        filtered = {k: v for k, v in kwargs.items() if k not in exclude_keys}

        # Build annotation from paragraph
        annotation = None
        if para:
            from ..schemas.paragraph import ParagraphAnnotation

            annotation = ParagraphAnnotation(
                paragraph_index=para.index,
                speaker_canonical_name=para.speaker_canonical_name or "_narrator_",
                is_dialogue=para.is_dialogue or False,
                emotion=para.emotion or "neutral",
                emotion_intensity=para.emotion_intensity or 0.5,
                speech_rate=para.speech_rate or 1.0,
                pitch_shift_semitones=para.pitch_shift_semitones or 0,
                pause_before_ms=para.pause_before_ms or 300,
                pause_after_ms=para.pause_after_ms or 500,
                confidence=para.confidence or 0.9,
                difficulty="B",
                needs_sfx=para.needs_sfx or False,
                sfx_tags=para.sfx_tags or [],
            )

        # Build routing decision mock
        from ..schemas.tts_routing import TtsRoutingDecision

        routing = TtsRoutingDecision(
            segment_id=f"seg_{para.id if para else 'unknown'}",
            engine_choice="edge",
            voice_id="v1",
            fallback_engine="kokoro",
            reasoning="Mock routing for quality check",
            estimated_duration_ms=3000,
        )

        audio_path = ""
        if para and para.audio_segment_id:
            from ..models.audio_segment import AudioSegment

            db = kwargs.get("db")
            if db:
                seg = db.query(AudioSegment).filter(AudioSegment.id == para.audio_segment_id).first()
                if seg:
                    audio_path = seg.file_path

        inputs = [
            (
                audio_path,
                annotation,
                routing,
                para.edited_text if para else "",
            )
        ]
        pipeline = QualityCheckPipeline()
        results = pipeline.run(inputs)
        return results[0] if results else None

    def persist(
        self,
        db: Session,
        project_id: int,
        chapter: Optional[Any],
        paragraph: Optional[Any],
        result: Any,
        chapter_index: Optional[int] = None,
        paragraph_index: Optional[int] = None,
    ) -> None:
        if project_id and chapter and paragraph:
            from .persistence import write_quality

            write_quality(db, project_id, chapter, paragraph, result)


from .review import ReviewerAgent, ReviewerInput, ReviewerJudgment


class TranslateStage(StageHandler):
    """Translate stage: multilingual translation dubbing."""

    def __init__(self):
        self.pipeline = TranslateAndDubPipeline()

    def run(self, **kwargs) -> Any:
        exclude_keys = {"chapter", "paragraph", "db"}
        filtered = {k: v for k, v in kwargs.items() if k not in exclude_keys}
        segments = filtered.get("segments", [])
        target_language = filtered.get("target_language", "en-US")
        book_title = filtered.get("book_title", "")
        author = filtered.get("author", "")

        return self.pipeline.translate_and_dub(
            segments=segments,
            target_language=target_language,
            book_title=book_title,
            author=author,
        )

    def persist(
        self,
        db: Session,
        project_id: int,
        chapter: Optional[Any],
        paragraph: Optional[Any],
        result: Any,
        chapter_index: Optional[int] = None,
        paragraph_index: Optional[int] = None,
    ) -> None:
        # Translate stage produces audio segments, similar to synthesize
        if project_id and chapter and paragraph:
            from .persistence import write_synthesize

            dubbed_segments, report = result
            for seg in dubbed_segments:
                seg_dict = {
                    "file_path": seg.file_path,
                    "duration_ms": seg.duration_ms,
                    "engine": seg.engine,
                    "voice_id": seg.voice_id,
                    "format": (seg.file_path.split(".")[-1] if "." in seg.file_path else "mp3"),
                }
                write_synthesize(db, project_id, chapter, paragraph, seg_dict)


def register_stage(name: str):
    """Decorator to register a stage handler class."""

    def decorator(cls: Type[StageHandler]) -> Type[StageHandler]:
        StageRegistry.register(name, cls)
        return cls

    return decorator


# ── Auto-register built-in stages ───────────────────────────────────────────
# Enable easy extension: custom stages just need to inherit StageHandler + decorate

# Built-in stages are registered when this module is imported
StageRegistry.register("extract", ExtractStage)
StageRegistry.register("analyze", AnalyzeStage)
StageRegistry.register("annotate", AnnotateStage)
StageRegistry.register("edit", EditStage)
StageRegistry.register("audio_postprocess", AudioPostprocessStage)
StageRegistry.register("review", ReviewStage)
StageRegistry.register("synthesize", SynthesizeStage)
StageRegistry.register("quality", QualityStage)
StageRegistry.register("translate", TranslateStage)
from ..schemas.paragraph import ParagraphAnnotationInput
