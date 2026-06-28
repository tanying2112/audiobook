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
            return result  # type: ignore
        else:
            return {"result": str(result)}


class StageRegistry:
    """Registry for stage handlers with lazy initialization."""

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
        """Get a stage handler instance."""
        if name not in cls._handlers:
            raise ValueError(
                f"Unknown pipeline stage: {name}. "
                f"Registered stages: {list(cls._handlers.keys())}"
            )
        return cls._handlers[name]()

    @classmethod
    def has(cls, name: str) -> bool:
        """Check if stage is registered."""
        return name in cls._handlers

    @classmethod
    def list_stages(cls) -> List[str]:
        """Get list of registered stage names."""
        return list(cls._handlers.keys())


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
        # For extract stage, chapter may not exist yet - _write_extract creates it
        from .orchestrator import _write_extract

        chapter_result = _write_extract(db, project_id, chapter_index or 1, result)
        result._chapter_id = chapter_result.id


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
            from .orchestrator import _write_analyze

            _write_analyze(db, chapter, result)


from .annotate_paragraph import AnnotateParagraphPipeline


class AnnotateStage(StageHandler):
    """Annotate stage: annotate paragraph with prosody metadata."""

    def run(self, **kwargs) -> Any:
        # Filter out orchestrator-internal params only
        exclude_keys = {"chapter", "paragraph", "db"}
        filtered = {k: v for k, v in kwargs.items() if k not in exclude_keys}
        # Build ParagraphAnnotationInput from kwargs
        input_data = ParagraphAnnotationInput(
            paragraph_text=filtered.get("paragraph_text", ""),
            paragraph_index=filtered.get("paragraph_index", 0),
            chapter_index=filtered.get("chapter_index", 1),
            book_meta=filtered.get("book_meta"),
            character_voice_map=filtered.get("character_voice_map", []),
            emotion_snapshot=filtered.get("emotion_snapshot"),
            story_line_summary=filtered.get("story_line_summary", ""),
            global_style_notes=filtered.get("global_style_notes", ""),
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
            from .orchestrator import _write_annotate

            para_index = getattr(result, "paragraph_index", paragraph_index or 0)
            para = _write_annotate(
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
        # Filter out orchestrator-internal params only
        exclude_keys = {"chapter", "paragraph", "db"}
        filtered = {k: v for k, v in kwargs.items() if k not in exclude_keys}
        # Build TtsEditInput from kwargs
        paragraph_annotation = filtered.get("paragraph_annotation")
        input_data = TtsEditInput(
            paragraph_text=filtered.get("paragraph_text", ""),
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
            from .orchestrator import _write_edit

            _write_edit(db, paragraph, result)


import json

from ..schemas import ParagraphAnnotation
from ..schemas.book import CharacterVoiceBinding
from .audio_postprocess import AudioPostProcessor


class AudioPostprocessStage(StageHandler):
    """Audio postprocess stage: apply audio processing params."""

    def run(self, **kwargs) -> Any:
        # paragraph and chapter are passed from orchestrator context
        para = kwargs.get("paragraph")
        chapter = kwargs.get("chapter")

        if para is None:
            raise ValueError(
                "audio_postprocess requires paragraph_id or paragraph_index"
            )

        # Build annotation from para
        annotation = ParagraphAnnotation(
            paragraph_index=para.index,
            speaker_canonical_name=para.speaker_canonical_name or "_narrator_",
            is_dialogue=para.is_dialogue,
            emotion=para.emotion or "neutral",
            emotion_intensity=para.emotion_intensity or 0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            pause_before_ms=para.pause_before_ms or 0,
            pause_after_ms=para.pause_after_ms or 0,
            confidence=para.confidence or 1.0,
            needs_sfx=False,
            sfx_tags=[],
        )

        # Build voice_map from chapter's analyzed_json
        voice_map: list[CharacterVoiceBinding] = []
        if chapter and chapter.analyzed_json:
            raw = chapter.analyzed_json
            if isinstance(raw, str):
                raw = json.loads(raw)
            vms = raw.get("character_voice_map", [])
            for vm in vms:
                voice_map.append(CharacterVoiceBinding(**vm))

        processor = AudioPostProcessor()
        params = processor.process(
            annotation=annotation,
            voice_map=voice_map if voice_map else None,
        )
        return params

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
            from .orchestrator import _write_audio_postprocess

            _write_audio_postprocess(db, paragraph, result)


from unittest.mock import MagicMock

from ..schemas.book import CharacterVoiceBinding
from ..schemas.paragraph import ParagraphAnnotation
from ..schemas.tts_routing import TtsRoutingInput
from .synthesize import SynthesizePipeline


class SynthesizeStage(StageHandler):
    """Synthesize stage: convert text to audio."""

    def run(self, **kwargs) -> Any:
        # Filter out orchestrator-internal params only
        exclude_keys = {"chapter", "paragraph", "db"}
        filtered = {k: v for k, v in kwargs.items() if k not in exclude_keys}
        # Build TtsRoutingInput list from kwargs (single item for single paragraph synthesis)
        voice_map = filtered.get("character_voice_map", [])
        if not voice_map and filtered.get("voice_id"):
            # Create minimal voice map from voice_id
            voice_map = [
                CharacterVoiceBinding(
                    canonical_name="旁白",
                    aliases=[],
                    gender="neutral",
                    age_range="adult",
                    suggested_voice_id=filtered.get("voice_id"),
                    sample_quote="",
                )
            ]
        paragraph_annotation = filtered.get("paragraph_annotation")
        input_data = TtsRoutingInput(
            paragraph_annotation=paragraph_annotation,
            text=filtered.get("text", ""),
            character_voice_map=voice_map,
            book_id=str(filtered.get("project_id", "")),
            chapter_index=filtered.get("chapter_index", 1),
            paragraph_index=filtered.get("paragraph_index", 0),
            cumulative_cost_usd=filtered.get("cumulative_cost_usd", 0.0),
            cost_limit_per_book=filtered.get("cost_limit_per_book", 20.0),
            cost_limit_per_chapter=filtered.get("cost_limit_per_chapter", 5.0),
            prefer_local=filtered.get("prefer_local", True),
            contract_version=filtered.get("contract_version", 1),
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
            from .orchestrator import _write_synthesize

            for seg in result:
                seg_dict = {
                    "file_path": seg.file_path,
                    "duration_ms": seg.duration_ms,
                    "engine": seg.engine,
                    "voice_id": seg.voice_id,
                    "format": (
                        seg.file_path.split(".")[-1] if "." in seg.file_path else "mp3"
                    ),
                }
                _write_synthesize(db, project_id, chapter, paragraph, seg_dict)

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
        # Filter out orchestrator-internal params only
        exclude_keys = {"chapter", "paragraph", "db"}
        filtered = {k: v for k, v in kwargs.items() if k not in exclude_keys}
        # Build input tuple list for quality check pipeline
        # Input format: List[(audio_path, paragraph_annotation, routing_decision, reference_text)]
        inputs = [
            (
                filtered.get("audio_path", ""),
                filtered.get("annotation"),
                filtered.get("routing_decision"),
                filtered.get("text", ""),
            )
        ]
        pipeline = QualityCheckPipeline()
        return pipeline.run(inputs)

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
            from .orchestrator import _write_quality

            _write_quality(db, project_id, chapter, paragraph, result)


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
StageRegistry.register("synthesize", SynthesizeStage)
StageRegistry.register("quality", QualityStage)
from ..schemas.paragraph import ParagraphAnnotationInput
