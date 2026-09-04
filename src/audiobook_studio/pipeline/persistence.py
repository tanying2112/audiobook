"""Database persistence layer for pipeline stages.

This module contains all database write operations for pipeline stages,
extracted from orchestrator.py to break the circular dependency with stage_registry.py.

All functions support both sync (Session) and async (AsyncSession) callers.
"""

import json
import logging
from typing import Any, Dict, Optional, Union, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
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
)
from .segment import SegmentationResult

logger = logging.getLogger(__name__)


# Sync/Async helpers
def _is_async(db: Union[Session, AsyncSession]) -> bool:
    """Check if db is an AsyncSession."""
    return isinstance(db, AsyncSession)


def _commit(db: Union[Session, AsyncSession]) -> None:
    """Commit transaction (sync)."""
    if _is_async(db):
        raise RuntimeError("_commit called on AsyncSession from sync context; use await _acommit")
    else:
        db.commit()


def _refresh(db: Union[Session, AsyncSession], obj: Any) -> None:
    """Refresh object (sync)."""
    if _is_async(db):
        raise RuntimeError("_refresh called on AsyncSession from sync context; use await _arefresh")
    else:
        db.refresh(obj)


def _flush(db: Union[Session, AsyncSession]) -> None:
    """Flush session (sync)."""
    if _is_async(db):
        raise RuntimeError("_flush called on AsyncSession from sync context; use await _aflush")
    else:
        db.flush()


def _execute(db: Union[Session, AsyncSession], stmt: Any) -> Any:
    """Execute statement (sync)."""
    if _is_async(db):
        raise RuntimeError("_execute called on AsyncSession from sync context; use await _aexecute")
    else:
        return db.execute(stmt)


# Async variants
async def _acommit(db: Union[Session, AsyncSession]) -> None:
    """Commit transaction (async). Works with both AsyncSession and Session."""
    if _is_async(db):
        await db.commit()
    else:
        db.commit()


async def _arefresh(db: Union[Session, AsyncSession], obj: Any) -> None:
    """Refresh object (async). Works with both AsyncSession and Session."""
    if _is_async(db):
        await db.refresh(obj)
    else:
        db.refresh(obj)


async def _aflush(db: Union[Session, AsyncSession]) -> None:
    """Flush session (async). Works with both AsyncSession and Session."""
    if _is_async(db):
        await db.flush()
    else:
        db.flush()


async def _aexecute(db: Union[Session, AsyncSession], stmt: Any) -> Any:
    """Execute statement. Returns Result for both session types.

    Call with await in async context - works for both sync and async sessions.
    """
    if _is_async(db):
        # For AsyncSession, db.execute returns a coroutine that must be awaited
        return await db.execute(stmt)
    else:
        # For sync Session, execute returns Result directly.
        # Wrap in a coroutine so caller can await it uniformly.
        async def _sync_execute():
            return db.execute(stmt)

        return await _sync_execute()


# ── Sync write functions (for sync Session callers) ─────────────────────────────


def write_extract_sync(
    db: Session,
    project_id: int,
    chapter_index: int,
    result: ExtractionResult,
    *,
    chapter_id: Optional[int] = None,
) -> Chapter:
    """Create or update a Chapter record with extraction output (sync version)."""
    chapter: Optional[Chapter] = None
    if chapter_id:
        result_q = _execute(db, select(Chapter).filter(Chapter.id == chapter_id))
        chapter = result_q.scalar_one_or_none()
    if not chapter:
        result_q = _execute(
            db,
            select(Chapter).filter(
                Chapter.project_id == project_id,
                Chapter.index == chapter_index,
            ),
        )
        chapter = result_q.scalar_one_or_none()
    if not chapter:
        chapter = Chapter(project_id=project_id, index=chapter_index)
        db.add(chapter)

    chapter.raw_text = result.raw_text
    chapter.extracted_text = result.raw_text
    chapter.extract_status = "completed"
    _commit(db)
    _refresh(db, chapter)
    logger.info("DB write [extract]: Chapter %d (id=%s)", chapter_index, chapter.id)
    return chapter


def write_segment_sync(
    db: Session,
    project_id: int,
    chapter: Chapter,
    result: SegmentationResult,
) -> None:
    """Update Chapter with segmentation results (sync version)."""
    segments_data = []
    for seg in result.segments:
        segments_data.append(
            {
                "index": seg.index,
                "text": seg.text,
                "start_char": seg.start_char,
                "end_char": seg.end_char,
                "metadata": seg.metadata,
            }
        )

    chapter.segment_data = segments_data
    chapter.segment_strategy = result.strategy_used.value
    chapter.segment_stats = result.stats
    chapter.segment_status = "completed"
    _commit(db)
    logger.info("DB write [segment]: Chapter %d, %d segments", chapter.index, len(result.segments))


def write_analyze_sync(
    db: Session,
    chapter: Chapter,
    result: BookAnalysisOutput,
) -> None:
    """Update Chapter with structure analysis output (sync version)."""
    chapter.analyzed_json = json.loads(result.model_dump_json())
    chapter.analyze_status = "completed"
    _commit(db)
    logger.info("DB write [analyze]: Chapter %d", chapter.index)


def write_annotate_sync(
    db: Session,
    project_id: int,
    chapter: Chapter,
    paragraph_index: int,
    result: ParagraphAnnotation,
) -> Paragraph:
    """Create or update a Paragraph record with annotation output (sync version)."""
    result_q = _execute(
        db,
        select(Paragraph).filter(
            Paragraph.project_id == project_id,
            Paragraph.chapter_id == chapter.id,
            Paragraph.index == paragraph_index,
        ),
    )
    para: Optional[Paragraph] = result_q.scalar_one_or_none()
    if not para:
        para = Paragraph(
            project_id=project_id,
            chapter_id=chapter.id,
            chapter_index=chapter.index,
            index=paragraph_index,
            text=result.text or "",
        )
        db.add(para)

    para.speaker_canonical_name = result.speaker_canonical_name
    para.is_dialogue = result.is_dialogue
    para.emotion = result.emotion
    para.emotion_intensity = result.emotion_intensity
    para.pause_before_ms = result.pause_before_ms or 0
    para.pause_after_ms = result.pause_after_ms or 0
    para.confidence = result.confidence
    para.notes = result.notes
    para.status = "annotated"
    _commit(db)
    _refresh(db, para)
    logger.info("DB write [annotate]: Paragraph %d (id=%s)", paragraph_index, para.id)
    return para


def write_edit_sync(
    db: Session,
    para: Paragraph,
    result: TtsEditOutput,
) -> TTSEdit:
    """Create a TTSEdit record and update the Paragraph with edit output (sync version)."""
    para.edited_text = result.edited_text
    para.edit_changes_made = result.changes_made if result.changes_made else None
    para.edit_forbidden_removed = result.forbidden_content_removed
    para.edit_confidence = result.confidence
    para.edit_rationale = result.rationale
    para.edit_difficulty = result.difficulty
    para.edit_forbid_edit = result.forbid_edit
    para.status = "edited"
    _commit(db)

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
    _commit(db)
    logger.info("DB write [edit]: Paragraph %d, TTSEdit id=%s", para.index, tts_edit.id)
    return tts_edit


def write_synthesize_sync(
    db: Session,
    project_id: int,
    chapter: Chapter,
    para: Paragraph,
    segment_info: Dict[str, Any],
) -> AudioSegmentModel:
    """Create or update an AudioSegment record from synthesis output (sync version)."""
    result_q = _execute(
        db,
        select(AudioSegmentModel)
        .filter(AudioSegmentModel.paragraph_id == para.id)
        .order_by(AudioSegmentModel.version.desc())
        .limit(1),
    )
    existing: Optional[AudioSegmentModel] = result_q.scalar_one_or_none()

    if existing:
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

    _commit(db)
    _refresh(db, audio)

    para.audio_segment_id = audio.id
    para.status = "synthesized"
    _commit(db)

    logger.info(
        "DB write [synthesize]: AudioSegment id=%s for Paragraph %d",
        audio.id,
        para.index,
    )
    return audio


def write_quality_sync(
    db: Session,
    project_id: int,
    chapter: Chapter,
    para: Paragraph,
    result: QualityJudgment,
) -> Quality:
    """Create a Quality record and update Paragraph with quality scores (sync version)."""
    result_q = _execute(
        db, select(TTSEdit).filter(TTSEdit.paragraph_id == para.id).order_by(TTSEdit.version.desc()).limit(1)
    )
    tts_edit: Optional[TTSEdit] = result_q.scalar_one_or_none()

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
        _flush(db)
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
    _commit(db)
    _refresh(db, quality)

    para.quality_speaker_clarity = result.speaker_clarity
    para.quality_emotion_match = result.emotion_match
    para.quality_prosody_naturalness = result.prosody_naturalness
    para.quality_text_audio_alignment = result.text_audio_alignment
    para.quality_overall_score = result.overall_score
    para.quality_issues = cast(list[str], result.issues)
    para.quality_fix_suggestions = [s.model_dump() for s in result.fix_suggestions] if result.fix_suggestions else None
    para.quality_needs_regeneration = result.needs_regeneration
    para.status = "quality_checked"
    _commit(db)
    logger.info(
        "DB write [quality]: Quality id=%s overall=%.2f for Paragraph %d",
        quality.id,
        result.overall_score,
        para.index,
    )
    return quality


def write_audio_postprocess_sync(
    db: Session,
    para: Paragraph,
    params: Union[AudioPostProcessParams, Dict[str, Any]],
) -> None:
    """Update Paragraph DB record with audio post-process params (sync version)."""
    if isinstance(params, AudioPostProcessParams):
        speech_rate = params.speech_rate
        pitch_shift_semitones = params.pitch_shift_semitones
        needs_sfx = params.needs_sfx
        sfx_tags = params.sfx_tags
        pause_after_ms = getattr(params, "pause_after_ms", 0)
        volume_db = getattr(params, "volume_db", 0.0)
    else:
        speech_rate = params.get("speed", 1.0)
        pitch_hz = params.get("pitch_hz", 0.0)
        pitch_shift_semitones = round(pitch_hz / 6.0)
        needs_sfx = params.get("needs_sfx", False)
        sfx_tags = params.get("sfx_tags", [])
        pause_after_ms = params.get("pause_after_ms", 300)
        volume_db = params.get("volume_db", 0.0)

    para.speech_rate = speech_rate
    para.pitch_shift_semitones = pitch_shift_semitones
    para.needs_sfx = needs_sfx
    para.sfx_tags = sfx_tags
    para.pause_after_ms = pause_after_ms
    para.status = "audio_processed"

    para.routing_prosody_overrides = {
        "rate": speech_rate,
        "pitch": float(pitch_shift_semitones),
        "volume": float(volume_db),
        "pause_after_ms": pause_after_ms,
        "_source": "audio_postprocess",
    }

    _commit(db)
    logger.info(
        "DB write [audio_postprocess]: Paragraph %d speed=%.1f pitch_semitones=%d volume=%.1fdB pause_ms=%d",
        para.index,
        speech_rate,
        pitch_shift_semitones,
        volume_db,
        pause_after_ms,
    )


# ── Async write functions (for AsyncSession callers, always await) ──────────────


async def write_extract(
    db: Union[Session, AsyncSession],
    project_id: int,
    chapter_index: int,
    result: ExtractionResult,
    *,
    chapter_id: Optional[int] = None,
) -> Chapter:
    """Create or update a Chapter record with extraction output (async version).

    Works with both sync (Session) and async (AsyncSession) sessions.
    Always call with await from async context.
    """
    chapter: Optional[Chapter] = None
    if chapter_id:
        result_q = await _aexecute(db, select(Chapter).filter(Chapter.id == chapter_id))
        chapter = result_q.scalar_one_or_none()
    if not chapter:
        result_q = await _aexecute(
            db,
            select(Chapter).filter(
                Chapter.project_id == project_id,
                Chapter.index == chapter_index,
            ),
        )
        chapter = result_q.scalar_one_or_none()
    if not chapter:
        chapter = Chapter(project_id=project_id, index=chapter_index)
        db.add(chapter)

    chapter.raw_text = result.raw_text
    chapter.extracted_text = result.raw_text
    chapter.extract_status = "completed"
    await _acommit(db)
    await _arefresh(db, chapter)
    logger.info("DB write [extract]: Chapter %d (id=%s)", chapter_index, chapter.id)
    return chapter


async def write_segment(
    db: Union[Session, AsyncSession],
    project_id: int,
    chapter: Chapter,
    result: SegmentationResult,
) -> None:
    """Update Chapter with segmentation results (async version)."""
    segments_data = []
    for seg in result.segments:
        segments_data.append(
            {
                "index": seg.index,
                "text": seg.text,
                "start_char": seg.start_char,
                "end_char": seg.end_char,
                "metadata": seg.metadata,
            }
        )

    chapter.segment_data = segments_data
    chapter.segment_strategy = result.strategy_used.value
    chapter.segment_stats = result.stats
    chapter.segment_status = "completed"
    await _acommit(db)
    logger.info("DB write [segment]: Chapter %d, %d segments", chapter.index, len(result.segments))


async def write_analyze(
    db: Union[Session, AsyncSession],
    chapter: Chapter,
    result: BookAnalysisOutput,
) -> None:
    """Update Chapter with structure analysis output (async version)."""
    chapter.analyzed_json = json.loads(result.model_dump_json())
    chapter.analyze_status = "completed"
    await _acommit(db)
    logger.info("DB write [analyze]: Chapter %d", chapter.index)


async def write_annotate(
    db: Union[Session, AsyncSession],
    project_id: int,
    chapter: Chapter,
    paragraph_index: int,
    result: ParagraphAnnotation,
) -> Paragraph:
    """Create or update a Paragraph record with annotation output (async version)."""
    result_q = await _aexecute(
        db,
        select(Paragraph).filter(
            Paragraph.project_id == project_id,
            Paragraph.chapter_id == chapter.id,
            Paragraph.index == paragraph_index,
        ),
    )
    para: Optional[Paragraph] = result_q.scalar_one_or_none()
    if not para:
        para = Paragraph(
            project_id=project_id,
            chapter_id=chapter.id,
            chapter_index=chapter.index,
            index=paragraph_index,
            text=result.text or "",
        )
        db.add(para)

    para.speaker_canonical_name = result.speaker_canonical_name
    para.is_dialogue = result.is_dialogue
    para.emotion = result.emotion
    para.emotion_intensity = result.emotion_intensity
    para.pause_before_ms = result.pause_before_ms or 0
    para.pause_after_ms = result.pause_after_ms or 0
    para.confidence = result.confidence
    para.notes = result.notes
    para.status = "annotated"
    await _acommit(db)
    await _arefresh(db, para)
    logger.info("DB write [annotate]: Paragraph %d (id=%s)", paragraph_index, para.id)
    return para


async def write_edit(
    db: Union[Session, AsyncSession],
    para: Paragraph,
    result: TtsEditOutput,
) -> TTSEdit:
    """Create a TTSEdit record and update the Paragraph with edit output (async version)."""
    para.edited_text = result.edited_text
    para.edit_changes_made = result.changes_made if result.changes_made else None
    para.edit_forbidden_removed = result.forbidden_content_removed
    para.edit_confidence = result.confidence
    para.edit_rationale = result.rationale
    para.edit_difficulty = result.difficulty
    para.edit_forbid_edit = result.forbid_edit
    para.status = "edited"
    await _acommit(db)

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
    await _acommit(db)
    logger.info("DB write [edit]: Paragraph %d, TTSEdit id=%s", para.index, tts_edit.id)
    return tts_edit


async def write_synthesize(
    db: Union[Session, AsyncSession],
    project_id: int,
    chapter: Chapter,
    para: Paragraph,
    segment_info: Dict[str, Any],
) -> AudioSegmentModel:
    """Create or update an AudioSegment record from synthesis output (async version)."""
    result_q = await _aexecute(
        db,
        select(AudioSegmentModel)
        .filter(AudioSegmentModel.paragraph_id == para.id)
        .order_by(AudioSegmentModel.version.desc())
        .limit(1),
    )
    existing: Optional[AudioSegmentModel] = result_q.scalar_one_or_none()

    if existing:
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

    await _acommit(db)
    await _arefresh(db, audio)

    para.audio_segment_id = audio.id
    para.status = "synthesized"
    await _acommit(db)

    logger.info(
        "DB write [synthesize]: AudioSegment id=%s for Paragraph %d",
        audio.id,
        para.index,
    )
    return audio


async def write_quality(
    db: Union[Session, AsyncSession],
    project_id: int,
    chapter: Chapter,
    para: Paragraph,
    result: QualityJudgment,
) -> Quality:
    """Create a Quality record and update Paragraph with quality scores (async version)."""
    result_q = await _aexecute(
        db, select(TTSEdit).filter(TTSEdit.paragraph_id == para.id).order_by(TTSEdit.version.desc()).limit(1)
    )
    tts_edit: Optional[TTSEdit] = result_q.scalar_one_or_none()

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
        await _aflush(db)
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
    await _acommit(db)
    await _arefresh(db, quality)

    para.quality_speaker_clarity = result.speaker_clarity
    para.quality_emotion_match = result.emotion_match
    para.quality_prosody_naturalness = result.prosody_naturalness
    para.quality_text_audio_alignment = result.text_audio_alignment
    para.quality_overall_score = result.overall_score
    para.quality_issues = cast(list[str], result.issues)
    para.quality_fix_suggestions = [s.model_dump() for s in result.fix_suggestions] if result.fix_suggestions else None
    para.quality_needs_regeneration = result.needs_regeneration
    para.status = "quality_checked"
    await _acommit(db)
    logger.info(
        "DB write [quality]: Quality id=%s overall=%.2f for Paragraph %d",
        quality.id,
        result.overall_score,
        para.index,
    )
    return quality


async def write_audio_postprocess(
    db: Union[Session, AsyncSession],
    para: Paragraph,
    params: Union[AudioPostProcessParams, Dict[str, Any]],
) -> None:
    """Update Paragraph DB record with audio post-process params (async version)."""
    if isinstance(params, AudioPostProcessParams):
        speech_rate = params.speech_rate
        pitch_shift_semitones = params.pitch_shift_semitones
        needs_sfx = params.needs_sfx
        sfx_tags = params.sfx_tags
        pause_after_ms = getattr(params, "pause_after_ms", 0)
        volume_db = getattr(params, "volume_db", 0.0)
    else:
        speech_rate = params.get("speed", 1.0)
        pitch_hz = params.get("pitch_hz", 0.0)
        pitch_shift_semitones = round(pitch_hz / 6.0)
        needs_sfx = params.get("needs_sfx", False)
        sfx_tags = params.get("sfx_tags", [])
        pause_after_ms = params.get("pause_after_ms", 300)
        volume_db = params.get("volume_db", 0.0)

    para.speech_rate = speech_rate
    para.pitch_shift_semitones = pitch_shift_semitones
    para.needs_sfx = needs_sfx
    para.sfx_tags = sfx_tags
    para.pause_after_ms = pause_after_ms
    para.status = "audio_processed"

    para.routing_prosody_overrides = {
        "rate": speech_rate,
        "pitch": float(pitch_shift_semitones),
        "volume": float(volume_db),
        "pause_after_ms": pause_after_ms,
        "_source": "audio_postprocess",
    }

    await _acommit(db)
    logger.info(
        "DB write [audio_postprocess]: Paragraph %d speed=%.1f pitch_semitones=%d volume=%.1fdB pause_ms=%d",
        para.index,
        speech_rate,
        pitch_shift_semitones,
        volume_db,
        pause_after_ms,
    )
