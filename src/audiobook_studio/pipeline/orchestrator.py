"""Pipeline orchestrator — wraps each stage with DB persistence and feedback collection.

Keeps pipeline stages pure (no DB awareness) by providing a coordinator
that calls the stage, writes results to the database, and returns the result.

Usage::

    from src.audiobook_studio.pipeline.orchestrator import run_stage

    result = run_stage("extract", session, project_id=1, input=...)
    result = run_stage("annotate", session, project_id=1, chapter_id=1, input=...)
"""

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from ..models import AudioSegment as AudioSegmentModel
from ..models import Chapter, Paragraph, Quality, TTSEdit
from ..schemas import (
    AudioPostProcessParams,
    BookAnalysisOutput,
    ExtractionResult,
    ParagraphAnnotation,
    QualityJudgment,
    TtsEditOutput,
    TtsRoutingDecision,
)
from .analyze_structure import AnalyzeStructurePipeline
from .annotate_paragraph import AnnotateParagraphPipeline
from .audio_postprocess import AudioPostProcessor
from .edit_for_tts import EditForTtsPipeline
from .extract import ExtractPipeline
from .feedback_collector import FeedbackCollector, StageCapture
from .quality_check import QualityCheckPipeline
from .synthesize import SynthesizePipeline

logger = logging.getLogger(__name__)


# ── Stage → DB mapping ────────────────────────────────────────────────────────


def _write_extract(
    db: Session,
    project_id: int,
    chapter_index: int,
    result: ExtractionResult,
    *,
    chapter_id: Optional[int] = None,
) -> Chapter:
    """Create or update a Chapter record with extraction output."""
    chapter = None
    if chapter_id:
        chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        chapter = (
            db.query(Chapter)
            .filter(
                Chapter.project_id == project_id,
                Chapter.index == chapter_index,
            )
            .first()
        )
    if not chapter:
        chapter = Chapter(project_id=project_id, index=chapter_index)
        db.add(chapter)

    chapter.raw_text = result.raw_text
    chapter.extracted_text = result.raw_text  # same for now
    chapter.extract_status = "completed"
    db.commit()
    db.refresh(chapter)
    logger.info("DB write [extract]: Chapter %d (id=%s)", chapter_index, chapter.id)
    return chapter


def _write_analyze(
    db: Session,
    chapter: Chapter,
    result: BookAnalysisOutput,
) -> None:
    """Update Chapter with structure analysis output."""
    chapter.analyzed_json = json.loads(result.model_dump_json())
    chapter.analyze_status = "completed"
    db.commit()
    logger.info("DB write [analyze]: Chapter %d", chapter.index)


def _write_annotate(
    db: Session,
    project_id: int,
    chapter: Chapter,
    paragraph_index: int,
    result: ParagraphAnnotation,
) -> Paragraph:
    """Create or update a Paragraph record with annotation output."""
    para = (
        db.query(Paragraph)
        .filter(
            Paragraph.project_id == project_id,
            Paragraph.chapter_id == chapter.id,
            Paragraph.index == paragraph_index,
        )
        .first()
    )
    if not para:
        para = Paragraph(
            project_id=project_id,
            chapter_id=chapter.id,
            index=paragraph_index,
            chapter_index=chapter.index,
        )
        db.add(para)

    para.speaker_canonical_name = result.speaker_canonical_name
    para.is_dialogue = result.is_dialogue
    para.emotion = result.emotion
    para.emotion_intensity = result.emotion_intensity
    # 声学字段 (speech_rate/pitch/sfx) 由 audio_postprocess 阶段写入
    para.pause_before_ms = result.pause_before_ms
    para.pause_after_ms = result.pause_after_ms
    para.confidence = result.confidence
    para.notes = result.notes
    para.status = "annotated"
    db.commit()
    db.refresh(para)
    logger.info("DB write [annotate]: Paragraph %d (id=%s)", paragraph_index, para.id)
    return para


def _write_edit(
    db: Session,
    para: Paragraph,
    result: TtsEditOutput,
) -> TTSEdit:
    """Create a TTSEdit record and update the Paragraph with edit output."""
    para.edited_text = result.edited_text
    para.edit_changes_made = (
        [c.model_dump() for c in result.changes_made] if result.changes_made else None
    )
    para.edit_forbidden_removed = result.forbidden_content_removed
    para.edit_confidence = result.confidence
    para.edit_rationale = result.rationale
    para.edit_difficulty = result.difficulty
    para.edit_forbid_edit = result.forbid_edit
    para.status = "edited"
    db.commit()

    # Also persist a TtsEdit record for version tracking
    tts_edit = TTSEdit(
        project_id=para.project_id,
        chapter_id=para.chapter_id,
        paragraph_id=para.id,
        edited_text=result.edited_text,
        changes_made=(
            [c.model_dump() for c in result.changes_made]
            if result.changes_made
            else None
        ),
        forbidden_content_removed=result.forbidden_content_removed,
        confidence=result.confidence,
        rationale=result.rationale,
        difficulty=result.difficulty,
        forbid_edit=result.forbid_edit,
    )
    db.add(tts_edit)
    db.commit()
    logger.info("DB write [edit]: Paragraph %d, TTSEdit id=%s", para.index, tts_edit.id)
    return tts_edit


def _write_synthesize(
    db: Session,
    project_id: int,
    chapter: Chapter,
    para: Paragraph,
    segment_info: Dict[str, Any],
) -> AudioSegmentModel:
    """Create an AudioSegment record from synthesis output."""
    audio = AudioSegmentModel(
        project_id=project_id,
        chapter_id=chapter.id,
        paragraph_id=para.id,
        file_path=segment_info.get("file_path", ""),
        format=segment_info.get("format", "mp3"),
        duration_ms=segment_info.get("duration_ms", 0),
        file_size_bytes=segment_info.get("file_size_bytes", 0),
        engine=segment_info.get("engine", ""),
        voice_id=segment_info.get("voice_id", ""),
        prosody_overrides=segment_info.get("prosody_overrides"),
        status="completed",
    )
    db.add(audio)
    db.commit()
    db.refresh(audio)

    # Link back to Paragraph
    para.audio_segment_id = audio.id
    para.status = "synthesized"
    db.commit()
    logger.info(
        "DB write [synthesize]: AudioSegment id=%s for Paragraph %d",
        audio.id,
        para.index,
    )
    return audio


def _write_quality(
    db: Session,
    project_id: int,
    chapter: Chapter,
    para: Paragraph,
    result: QualityJudgment,
) -> Quality:
    """Create a Quality record and update Paragraph with quality scores."""
    # Find the latest TTSEdit for this paragraph
    from ..models import TTSEdit

    tts_edit = (
        db.query(TTSEdit)
        .filter(TTSEdit.paragraph_id == para.id)
        .order_by(TTSEdit.version.desc())
        .first()
    )
    tts_edit_id = tts_edit.id if tts_edit else None

    quality = Quality(
        project_id=project_id,
        chapter_id=chapter.id,
        paragraph_id=para.id,
        tts_edit_id=tts_edit_id,
        speaker_clarity=result.speaker_clarity,
        emotion_match=result.emotion_match,
        prosody_naturalness=result.prosody_naturalness,
        text_audio_alignment=result.text_audio_alignment,
        overall_score=result.overall_score,
        issues=result.issues,
        fix_suggestions=(
            [s.model_dump() for s in result.fix_suggestions]
            if result.fix_suggestions
            else None
        ),
        needs_regeneration=result.needs_regeneration,
        judge_model=result.judge_model,
    )
    db.add(quality)
    db.commit()
    db.refresh(quality)

    # Update Paragraph quality fields
    para.quality_speaker_clarity = result.speaker_clarity
    para.quality_emotion_match = result.emotion_match
    para.quality_prosody_naturalness = result.prosody_naturalness
    para.quality_text_audio_alignment = result.text_audio_alignment
    para.quality_overall_score = result.overall_score
    para.quality_issues = result.issues
    para.quality_fix_suggestions = (
        [s.model_dump() for s in result.fix_suggestions]
        if result.fix_suggestions
        else None
    )
    para.quality_needs_regeneration = result.needs_regeneration
    para.status = "quality_checked"
    db.commit()
    logger.info(
        "DB write [quality]: Quality id=%s overall=%.2f for Paragraph %d",
        quality.id,
        result.overall_score,
        para.index,
    )
    return quality


def _write_audio_postprocess(
    db: Session,
    para: Paragraph,
    params: AudioPostProcessParams,
) -> None:
    """Update Paragraph DB record with audio post-process params."""
    para.speech_rate = params.speech_rate
    para.pitch_shift_semitones = params.pitch_shift_semitones
    para.needs_sfx = params.needs_sfx
    para.sfx_tags = params.sfx_tags
    para.status = "audio_processed"
    db.commit()
    logger.info(
        "DB write [audio_postprocess]: Paragraph %d speech_rate=%.1f pitch=%d",
        para.index,
        params.speech_rate,
        params.pitch_shift_semitones,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def run_stage(
    stage: str,
    db: Session,
    *,
    project_id: Optional[int] = None,
    chapter_index: Optional[int] = None,
    chapter_id: Optional[int] = None,
    paragraph_index: Optional[int] = None,
    paragraph_id: Optional[int] = None,
    mock_mode: bool = False,
    feedback_collector: Optional[FeedbackCollector] = None,
    **kwargs,
) -> Any:
    """Run a pipeline stage and persist its output to the database.

    Parameters
    ----------
    stage:
        One of ``"extract"``, ``"analyze"``, ``"annotate"``, ``"edit"``,
        ``"audio_postprocess"``, ``"synthesize"``, ``"quality"``.
    db:
        SQLAlchemy session for persistence.
    project_id:
        Required for stages that create/update Project-level records.
    chapter_index:
        1-based chapter number (required for extract, analyze).
    chapter_id:
        DB primary key of the Chapter (required for annotate/edit/synthesize/quality
        if chapter resolution is needed).
    paragraph_index:
        1-based paragraph index (required for annotate/edit/synthesize/quality).
    paragraph_id:
        DB primary key of the Paragraph (alternative to paragraph_index).
    mock_mode:
        Passed through to the pipeline stage.
    feedback_collector:
        Optional FeedbackCollector for capturing LLM inputs/outputs for self-iteration.
    **kwargs:
        Forwarded to the pipeline stage's ``run()`` method.

    Returns
    -------
    The pipeline stage result (Pydantic model) and writes side effects to DB.
    """
    # Resolve chapter
    chapter = None
    if chapter_id:
        chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    elif chapter_index is not None and project_id is not None:
        chapter = (
            db.query(Chapter)
            .filter(
                Chapter.project_id == project_id,
                Chapter.index == chapter_index,
            )
            .first()
        )

    # Resolve paragraph
    para = None
    if paragraph_id:
        para = db.query(Paragraph).filter(Paragraph.id == paragraph_id).first()
    elif paragraph_index is not None and chapter is not None:
        para = (
            db.query(Paragraph)
            .filter(
                Paragraph.project_id == project_id,
                Paragraph.chapter_id == chapter.id,
                Paragraph.index == paragraph_index,
            )
            .first()
        )

    # Build input snapshot for feedback collection
    input_snapshot = {
        "stage": stage,
        "project_id": project_id,
        "chapter_index": chapter_index,
        "chapter_id": chapter.id if chapter else chapter_id,
        "paragraph_index": paragraph_index,
        "paragraph_id": para.id if para else paragraph_id,
        "kwargs": _sanitize_kwargs(kwargs),
    }

    # Create feedback capture context if collector provided
    feedback_capture: Optional[StageCapture] = None
    if feedback_collector and project_id:
        feedback_capture = feedback_collector.capture_stage(
            stage=stage,
            chapter_index=chapter_index,
            paragraph_index=paragraph_index,
            chapter_id=chapter.id if chapter else chapter_id,
            paragraph_id=para.id if para else paragraph_id,
            input_snapshot=input_snapshot,
        )

    # ── Stage dispatch ────────────────────────────────────────────────────
    try:
        if stage == "extract":
            pipeline = ExtractPipeline(mock_mode=mock_mode)
            result: ExtractionResult = pipeline.run(**kwargs)
            chapter = _write_extract(
                db,
                project_id=project_id,
                chapter_index=chapter_index or 1,
                result=result,
                chapter_id=chapter_id,
            )
            # Attach the chapter for convenience
            result._chapter_id = chapter.id  # type: ignore[attr-defined]

            # Capture feedback
            if feedback_capture:
                feedback_capture.set_llm_output(result.model_dump())
                # Note: corrected_output and rationale would be set externally when human provides feedback

            return result

        elif stage == "analyze":
            pipeline = AnalyzeStructurePipeline(mock_mode=mock_mode)
            result: BookAnalysisOutput = pipeline.run(**kwargs)
            if chapter:
                _write_analyze(db, chapter, result)

            if feedback_capture:
                feedback_capture.set_llm_output(result.model_dump())

            return result

        elif stage == "annotate":
            pipeline = AnnotateParagraphPipeline(mock_mode=mock_mode)
            result: ParagraphAnnotation = pipeline.run(**kwargs)
            if chapter and paragraph_index is not None:
                para = _write_annotate(
                    db,
                    project_id=project_id,
                    chapter=chapter,
                    paragraph_index=paragraph_index,
                    result=result,
                )
                result._paragraph_id = para.id  # type: ignore[attr-defined]

            if feedback_capture:
                feedback_capture.set_llm_output(result.model_dump())

            return result

        elif stage == "edit":
            pipeline = EditForTtsPipeline(mock_mode=mock_mode)
            result: TtsEditOutput = pipeline.run(**kwargs)
            if para:
                _write_edit(db, para, result)

            if feedback_capture:
                feedback_capture.set_llm_output(result.model_dump())

            return result

        elif stage == "audio_postprocess":
            if para is None:
                raise ValueError(
                    "audio_postprocess requires paragraph_id or paragraph_index + chapter"
                )
            from ..schemas.book import CharacterVoiceBinding

            # Build annotation from para
            annotation = ParagraphAnnotation(
                paragraph_index=para.index,
                speaker_canonical_name=para.speaker_canonical_name or "_narrator_",
                is_dialogue=para.is_dialogue,
                emotion=para.emotion or "neutral",
                emotion_intensity=para.emotion_intensity or 0.5,
                speech_rate=1.0,  # Default value
                pitch_shift_semitones=0,  # Default value
                pause_before_ms=para.pause_before_ms or 0,
                pause_after_ms=para.pause_after_ms or 0,
                confidence=para.confidence or 1.0,
                needs_sfx=False,  # Default value
                sfx_tags=[],  # Default value
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
            _write_audio_postprocess(db, para, params)

            if feedback_capture:
                feedback_capture.set_llm_output(params.model_dump())

            return params

        elif stage == "synthesize":
            pipeline = SynthesizePipeline(mock_mode=mock_mode)
            # synthesize returns a list of AudioSegment dataclasses
            segments = pipeline.run(**kwargs)
            for seg in segments:
                seg_dict = {
                    "file_path": seg.file_path,
                    "duration_ms": seg.duration_ms,
                    "engine": seg.engine,
                    "voice_id": seg.voice_id,
                    "format": (
                        seg.file_path.split(".")[-1] if "." in seg.file_path else "mp3"
                    ),
                }
                if project_id and chapter and para:
                    _write_synthesize(db, project_id, chapter, para, seg_dict)

            if feedback_capture:
                # Capture synthesis output as list
                feedback_capture.set_llm_output(
                    {
                        "segments": [
                            {
                                "file_path": s.file_path,
                                "duration_ms": s.duration_ms,
                                "engine": s.engine,
                                "voice_id": s.voice_id,
                            }
                            for s in segments
                        ]
                    }
                )

            return segments

        elif stage == "quality":
            pipeline = QualityCheckPipeline(mock_mode=mock_mode)
            result: QualityJudgment = pipeline.run(**kwargs)
            if project_id and chapter and para:
                _write_quality(db, project_id, chapter, para, result)

            if feedback_capture:
                feedback_capture.set_llm_output(result.model_dump())
                # For quality stage, source is typically "quality_judge"
                feedback_capture.set_source("quality_judge")

            return result

        else:
            raise ValueError(f"Unknown pipeline stage: {stage}")

    except Exception as e:
        # Log error but don't break pipeline
        logger.error("Stage %s failed: %s", stage, e)
        if feedback_capture:
            feedback_capture.set_llm_output({"error": str(e)})
        raise


def _sanitize_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize kwargs for feedback snapshot (remove non-serializable objects)."""
    sanitized = {}
    for k, v in kwargs.items():
        if hasattr(v, "model_dump"):  # Pydantic model
            sanitized[k] = v.model_dump()
        elif hasattr(v, "__dict__"):  # Generic object
            sanitized[k] = str(v)
        else:
            sanitized[k] = v
    return sanitized
