"""Database persistence layer for pipeline stages.

This module contains all database write operations for pipeline stages,
extracted from orchestrator.py to break the circular dependency with stage_registry.py.
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

logger = logging.getLogger(__name__)


def write_extract(
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


def write_analyze(
    db: Session,
    chapter: Chapter,
    result: BookAnalysisOutput,
) -> None:
    """Update Chapter with structure analysis output."""
    chapter.analyzed_json = json.loads(result.model_dump_json())
    chapter.analyze_status = "completed"
    db.commit()
    logger.info("DB write [analyze]: Chapter %d", chapter.index)


def write_annotate(
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
            text=result.text or "",
        )
        db.add(para)

    para.speaker_canonical_name = result.speaker_canonical_name
    para.is_dialogue = result.is_dialogue
    para.emotion = result.emotion
    para.emotion_intensity = result.emotion_intensity
    # Acoustic fields (speech_rate/pitch/sfx) written by audio_postprocess stage
    para.pause_before_ms = result.pause_before_ms
    para.pause_after_ms = result.pause_after_ms
    para.confidence = result.confidence
    para.notes = result.notes
    para.status = "annotated"
    db.commit()
    db.refresh(para)
    logger.info("DB write [annotate]: Paragraph %d (id=%s)", paragraph_index, para.id)
    return para


def write_edit(
    db: Session,
    para: Paragraph,
    result: TtsEditOutput,
) -> TTSEdit:
    """Create a TTSEdit record and update the Paragraph with edit output."""
    para.edited_text = result.edited_text
    para.edit_changes_made = result.changes_made if result.changes_made else None
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
        changes_made=result.changes_made if result.changes_made else None,
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


def write_synthesize(
    db: Session,
    project_id: int,
    chapter: Chapter,
    para: Paragraph,
    segment_info: Dict[str, Any],
) -> AudioSegmentModel:
    """Create or update an AudioSegment record from synthesis output."""
    # Check if audio segment already exists for this paragraph
    existing = db.query(AudioSegmentModel).filter(AudioSegmentModel.paragraph_id == para.id).first()

    if existing:
        # Update existing record
        for attr in [
            "file_path",
            "format",
            "duration_ms",
            "file_size_bytes",
            "engine",
            "voice_id",
            "prosody_overrides",
        ]:
            if attr in segment_info:
                setattr(existing, attr, segment_info[attr])
        existing.status = "completed"
        audio = existing
    else:
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


def write_quality(
    db: Session,
    project_id: int,
    chapter: Chapter,
    para: Paragraph,
    result: QualityJudgment,
) -> Quality:
    """Create a Quality record and update Paragraph with quality scores.

    Ensures tts_edit_id is never NULL by:
    1. Finding the latest TTSEdit for this paragraph
    2. If none exists, creating a dummy TTSEdit with edited_text=""
    """
    # Find the latest TTSEdit for this paragraph
    tts_edit = db.query(TTSEdit).filter(TTSEdit.paragraph_id == para.id).order_by(TTSEdit.version.desc()).first()

    # If no TTSEdit exists, create a dummy one to satisfy NOT NULL constraint
    if tts_edit is None:
        tts_edit = TTSEdit(
            project_id=project_id,
            chapter_id=chapter.id,
            paragraph_id=para.id,
            edited_text=para.edited_text or "",
            changes_made=None,
            forbidden_content_removed=None,
            confidence=para.edit_confidence or 1.0,
            rationale="Auto-created for quality check (no prior edit)",
            difficulty=para.edit_difficulty or "B",
            forbid_edit=para.edit_forbid_edit or False,
        )
        db.add(tts_edit)
        db.flush()  # Get the ID without committing
        logger.info(
            "Created dummy TTSEdit id=%s for quality check on Paragraph %d",
            tts_edit.id,
            para.index,
        )

    tts_edit_id = tts_edit.id

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
        fix_suggestions=([s.model_dump() for s in result.fix_suggestions] if result.fix_suggestions else None),
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
    para.quality_fix_suggestions = [s.model_dump() for s in result.fix_suggestions] if result.fix_suggestions else None
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


def write_audio_postprocess(
    db: Session,
    para: Paragraph,
    params: Dict[str, Any],
) -> None:
    """Update Paragraph DB record with audio post-process params.

    Accepts both legacy AudioPostProcessParams and new PhysicalAudioSegment dict format.
    """
    # Handle both dict and object with attributes
    if hasattr(params, "speech_rate"):
        # Legacy AudioPostProcessParams object
        speech_rate = params.speech_rate
        pitch_shift_semitones = params.pitch_shift_semitones
        needs_sfx = params.needs_sfx
        sfx_tags = params.sfx_tags
        pause_after_ms = getattr(params, "pause_after_ms", 0)
    else:
        # New PhysicalAudioSegment dict
        speech_rate = params.get("speed", 1.0)
        # Convert pitch_hz to semitones (approximate: 1 semitone ≈ 5.95% frequency change)
        pitch_hz = params.get("pitch_hz", 0.0)
        pitch_shift_semitones = round(pitch_hz / 6.0)  # rough conversion
        needs_sfx = params.get("needs_sfx", False)
        sfx_tags = params.get("sfx_tags", [])
        pause_after_ms = params.get("pause_after_ms", 300)

    para.speech_rate = speech_rate
    para.pitch_shift_semitones = pitch_shift_semitones
    para.needs_sfx = needs_sfx
    para.sfx_tags = sfx_tags
    para.pause_after_ms = pause_after_ms
    para.status = "audio_processed"
    db.commit()
    logger.info(
        "DB write [audio_postprocess]: Paragraph %d speed=%.1f pitch_semitones=%d pause_ms=%d",
        para.index,
        speech_rate,
        pitch_shift_semitones,
        pause_after_ms,
    )
