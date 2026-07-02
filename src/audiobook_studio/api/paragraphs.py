"""FastAPI router for ``Paragraph`` CRUD operations (legacy API)."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..models.audio_segment import AudioSegment
from ..models.paragraph import Paragraph
from ..models.quality import Quality
from ..models.routing import Routing
from ..models.tts_edit import TTSEdit
from ..schemas.legacy import Paragraph as ParagraphSchema
from ..storage import audio_dir
from .dependencies import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/paragraphs", tags=["paragraphs"])


@router.post("/", response_model=ParagraphSchema, status_code=status.HTTP_201_CREATED)
def create_paragraph(paragraph: ParagraphSchema, db: Session = Depends(get_db)):
    db_par = Paragraph(**paragraph.model_dump())
    db.add(db_par)
    db.commit()
    db.refresh(db_par)
    return db_par.to_schema()


@router.get("/", response_model=List[ParagraphSchema])
def list_paragraphs(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    items = db.query(Paragraph).offset(skip).limit(limit).all()
    return [p.to_schema() for p in items]


@router.get("/{paragraph_id}", response_model=ParagraphSchema)
def get_paragraph(paragraph_id: int, db: Session = Depends(get_db)):
    p = db.query(Paragraph).filter(Paragraph.id == paragraph_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Paragraph not found")
    return p.to_schema()


@router.put("/{paragraph_id}", response_model=ParagraphSchema)
def update_paragraph(paragraph_id: int, payload: ParagraphSchema, db: Session = Depends(get_db)):
    p = db.query(Paragraph).filter(Paragraph.id == paragraph_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Paragraph not found")
    # Exclude id and other read-only fields from update
    update_data = {k: v for k, v in payload.model_dump().items() if k not in ("id",) and v is not None}
    for field, value in update_data.items():
        setattr(p, field, value)
    db.commit()
    db.refresh(p)
    return p.to_schema()


@router.delete("/{paragraph_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_paragraph(paragraph_id: int, db: Session = Depends(get_db)):
    p = db.query(Paragraph).filter(Paragraph.id == paragraph_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Paragraph not found")
    db.delete(p)
    db.commit()
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Paragraph Detail Endpoint (P0-5: Aggregated endpoint with _embedded data)
# ─────────────────────────────────────────────────────────────────────────────


class ParagraphAnnotationDetail(BaseModel):
    """Paragraph annotation details."""

    speaker_canonical_name: Optional[str] = None
    is_dialogue: bool = False
    emotion: Optional[str] = None
    emotion_intensity: float = 0.5
    speech_rate: float = 1.0
    pitch_shift_semitones: int = 0
    pause_before_ms: int = 300
    pause_after_ms: int = 500
    confidence: float = 0.9
    difficulty: str = "B"
    forbid_edit: bool = False


class ParagraphTTSEditDetail(BaseModel):
    """Paragraph TTS edit details."""

    changes_made: List[str] = Field(default_factory=list)
    edited_text: Optional[str] = None
    edit_reason: Optional[str] = None


class ParagraphRoutingDetail(BaseModel):
    """Paragraph TTS routing details."""

    engine_choice: str = "kokoro"
    voice_id: str = "kokoro_narrator"
    fallback_engine: str = "edge"
    estimated_cost_usd: float = 0.0
    estimated_duration_ms: int = 5000
    reasoning: Optional[str] = None


class ParagraphQualityDetail(BaseModel):
    """Paragraph quality check details."""

    overall_score: float = 0.5
    speaker_clarity: float = 0.5
    emotion_match: float = 0.5
    prosody_naturalness: float = 0.5
    text_audio_alignment: float = 0.5
    needs_regeneration: bool = False
    issues: List[str] = Field(default_factory=list)
    fix_suggestions: List[str] = Field(default_factory=list)


class ParagraphDetailOut(BaseModel):
    """
    Aggregated paragraph detail response with embedded data.

    This endpoint joins:
    - Paragraph base data
    - Annotation (speaker/emotion/etc.)
    - TTS Edit decisions
    - Routing decisions
    - Quality scores
    """

    id: int
    chapter_id: int
    paragraph_index: int
    original_text: str
    edited_text: Optional[str] = None
    status: str = "pending"

    # Embedded full data (using alias for frontend compatibility)
    embedded_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Aggregated data from all related tables",
        alias="_embedded",
    )

    # Convenience fields (flattened from embedded)
    annotation: Optional[ParagraphAnnotationDetail] = None
    tts_edit: Optional[ParagraphTTSEditDetail] = None
    routing: Optional[ParagraphRoutingDetail] = None
    quality: Optional[ParagraphQualityDetail] = None

    # Metadata
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@router.get("/{paragraph_id}/detail", response_model=ParagraphDetailOut)
def get_paragraph_detail(
    paragraph_id: int,
    db: Session = Depends(get_db),
):
    """
    Get paragraph with full embedded data.

    Returns aggregated data from:
    - Paragraph base table
    - ParagraphAnnotation (speaker, emotion, difficulty, etc.)
    - TTSEdit (edit decisions)
    - Routing (TTS engine/voice selection)
    - Quality (scores, issues, suggestions)

    This is the recommended endpoint for frontend detail views.
    For list views, use GET /paragraphs/ (limited fields).
    """
    # Get base paragraph
    p = db.query(Paragraph).filter(Paragraph.id == paragraph_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Paragraph not found")

    # Get latest TTS edit
    tts_edit_record = db.query(TTSEdit).filter(TTSEdit.paragraph_id == paragraph_id).order_by(TTSEdit.id.desc()).first()
    # Get latest Routing
    routing_record = db.query(Routing).filter(Routing.paragraph_id == paragraph_id).order_by(Routing.id.desc()).first()
    # Get latest Quality
    quality_record = db.query(Quality).filter(Quality.paragraph_id == paragraph_id).order_by(Quality.id.desc()).first()

    # Build annotation data from paragraph attributes (with fallback to placeholder defaults)
    annotation_data = {
        "speaker_canonical_name": getattr(p, "speaker_canonical_name", getattr(p, "speaker", None)),
        "is_dialogue": getattr(p, "is_dialogue", False),
        "emotion": getattr(p, "emotion", "neutral"),
        "emotion_intensity": getattr(p, "emotion_intensity", 0.5),
        "speech_rate": getattr(p, "speech_rate", 1.0),
        "pitch_shift_semitones": getattr(p, "pitch_shift_semitones", 0),
        "pause_before_ms": getattr(p, "pause_before_ms", 300),
        "pause_after_ms": getattr(p, "pause_after_ms", 500),
        "confidence": getattr(p, "confidence", 0.9),
        "difficulty": getattr(p, "edit_difficulty", getattr(p, "difficulty", "B")),
        "forbid_edit": getattr(p, "edit_forbid_edit", getattr(p, "difficulty", "B") == "A"),
    }

    # Build tts_edit data
    if tts_edit_record:
        tts_edit_data = {
            "changes_made": (tts_edit_record.changes_made if hasattr(tts_edit_record, "changes_made") else []),
            "edited_text": getattr(tts_edit_record, "edited_text", None),
            "edit_reason": getattr(tts_edit_record, "rationale", None),
        }
    else:
        # Fallback to paragraph's edited_text or text, and empty changes_made, no edit_reason
        tts_edit_data = {
            "changes_made": [],
            "edited_text": getattr(p, "edited_text", p.text if hasattr(p, "text") else None),
            "edit_reason": None,
        }

    # Build routing data
    if routing_record:
        routing_data = {
            "engine_choice": getattr(routing_record, "engine_choice", "kokoro"),
            "voice_id": getattr(routing_record, "voice_id", "kokoro_narrator"),
            "fallback_engine": getattr(routing_record, "fallback_engine", "edge"),
            "estimated_cost_usd": getattr(routing_record, "estimated_cost_usd", 0.001),
            "estimated_duration_ms": getattr(routing_record, "estimated_duration_ms", 5000),
            "reasoning": getattr(routing_record, "reasoning", None),
        }
    else:
        routing_data = {
            "engine_choice": "kokoro",
            "voice_id": "kokoro_narrator",
            "fallback_engine": "edge",
            "estimated_cost_usd": 0.001,
            "estimated_duration_ms": 5000,
            "reasoning": "Default routing for narration",
        }

    # Build quality data
    if quality_record:
        quality_data = {
            "overall_score": getattr(quality_record, "overall_score", 0.5),
            "speaker_clarity": getattr(quality_record, "speaker_clarity", 0.5),
            "emotion_match": getattr(quality_record, "emotion_match", 0.5),
            "prosody_naturalness": getattr(quality_record, "prosody_naturalness", 0.5),
            "text_audio_alignment": getattr(quality_record, "text_audio_alignment", 0.5),
            "needs_regeneration": getattr(quality_record, "needs_regeneration", False),
            "issues": getattr(quality_record, "issues", []),
            "fix_suggestions": getattr(quality_record, "fix_suggestions", []),
        }
    else:
        quality_data = {
            "overall_score": 0.5,
            "speaker_clarity": 0.5,
            "emotion_match": 0.5,
            "prosody_naturalness": 0.5,
            "text_audio_alignment": 0.5,
            "needs_regeneration": False,
            "issues": [],
            "fix_suggestions": [],
        }

    # Build _embedded data structure
    embedded = {
        "annotation": annotation_data,
        "tts_edit": tts_edit_data,
        "routing": routing_data,
        "quality": quality_data,
    }

    # Determine status from embedded data
    status = "pending"
    if embedded["annotation"]:
        status = "annotated"
    if embedded["tts_edit"]["edited_text"]:
        status = "edited"
    if embedded["routing"]:
        status = "routed"
    if embedded["quality"]["overall_score"] > 0:
        status = "quality_checked"

    # Prepare the response
    return ParagraphDetailOut(
        id=p.id,
        chapter_id=getattr(p, "chapter_id", 0),
        paragraph_index=getattr(p, "index", 0),
        original_text=getattr(p, "text", getattr(p, "original_text", "")),
        edited_text=embedded["tts_edit"]["edited_text"],
        status=status,
        embedded_data=embedded,
        annotation=ParagraphAnnotationDetail(**annotation_data),
        tts_edit=ParagraphTTSEditDetail(**tts_edit_data),
        routing=ParagraphRoutingDetail(**routing_data),
        quality=ParagraphQualityDetail(**quality_data),
        created_at=(getattr(p, "created_at", datetime.now()).isoformat() if hasattr(p, "created_at") else None),
        updated_at=(getattr(p, "updated_at", datetime.now()).isoformat() if hasattr(p, "updated_at") else None),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Audio serving endpoint (P0-3)
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{paragraph_id}/audio")
def serve_paragraph_audio(paragraph_id: int, db: Session = Depends(get_db)):
    """Serve the audio file for a paragraph.

    Looks up the AudioSegment record, then serves the file from storage.
    Returns 404 if no audio has been generated for this paragraph.
    """
    segment = (
        db.query(AudioSegment)
        .filter(
            AudioSegment.paragraph_id == paragraph_id,
            AudioSegment.is_current.is_(True),
        )
        .first()
    )
    if not segment:
        raise HTTPException(status_code=404, detail="No audio found for this paragraph")

    file_path = Path(segment.file_path)
    if not file_path.is_absolute():
        # Resolve relative paths against storage root
        file_path = audio_dir(segment.project_id) / file_path.name

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk")

    media_type = "audio/mpeg" if segment.format == "mp3" else "audio/wav"
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=f"paragraph_{paragraph_id}.{segment.format}",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Audio segments list endpoint (P0-3)
# ─────────────────────────────────────────────────────────────────────────────


class AudioSegmentOut(BaseModel):
    id: int
    file_path: str
    format: str = "mp3"
    duration_ms: Optional[int] = None
    engine: Optional[str] = None
    voice_id: Optional[str] = None
    status: str = "pending"
    version: int = 1
    is_current: bool = True

    model_config = ConfigDict(from_attributes=True)


@router.get("/{paragraph_id}/audio-segments", response_model=List[AudioSegmentOut])
def list_paragraph_audio_segments(paragraph_id: int, db: Session = Depends(get_db)):
    """List all audio segments for a paragraph (including old versions)."""
    segments = (
        db.query(AudioSegment)
        .filter(AudioSegment.paragraph_id == paragraph_id)
        .order_by(AudioSegment.version.desc())
        .all()
    )
    return segments


# ─────────────────────────────────────────────────────────────────────────────
# Quality results endpoint (P0-4)
# ─────────────────────────────────────────────────────────────────────────────


class QualityResultOut(BaseModel):
    id: int
    paragraph_id: Optional[int] = None
    tts_edit_id: Optional[int] = None
    overall_score: Optional[float] = None
    speaker_clarity: Optional[float] = None
    emotion_match: Optional[float] = None
    prosody_naturalness: Optional[float] = None
    text_audio_alignment: Optional[float] = None
    needs_regeneration: bool = False
    issues: Optional[list] = None
    fix_suggestions: Optional[list] = None
    judge_model: Optional[str] = None
    judge_prompt_version: Optional[str] = None
    audio_file_path: Optional[str] = None
    audio_duration_ms: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


@router.get("/{paragraph_id}/quality", response_model=List[QualityResultOut])
def get_paragraph_quality(paragraph_id: int, db: Session = Depends(get_db)):
    """Get quality check results for a paragraph."""
    qualities = db.query(Quality).filter(Quality.paragraph_id == paragraph_id).order_by(Quality.id.desc()).all()
    return qualities


# ─────────────────────────────────────────────────────────────────────────────
# Regeneration endpoint (P0-5)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/{paragraph_id}/regenerate")
def trigger_paragraph_regeneration(paragraph_id: int, db: Session = Depends(get_db)):
    """Trigger audio regeneration for a single paragraph.

    Marks the paragraph's audio for re-synthesis.
    The actual synthesis will be picked up by the next pipeline run.
    """
    p = db.query(Paragraph).filter(Paragraph.id == paragraph_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Paragraph not found")

    # Mark current audio segment as not current
    current_segment = (
        db.query(AudioSegment)
        .filter(
            AudioSegment.paragraph_id == paragraph_id,
            AudioSegment.is_current.is_(True),
        )
        .first()
    )
    if current_segment:
        current_segment.is_current = False
        db.commit()

    # Reset paragraph status to trigger re-synthesis
    p.status = "edited"
    db.commit()

    return {
        "status": "queued",
        "paragraph_id": paragraph_id,
        "message": "Paragraph marked for regeneration",
    }
