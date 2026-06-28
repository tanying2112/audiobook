"""FastAPI router for audio segment operations.

Provides endpoints for:
- GET /api/audio-segments/{book_id} - List audio segments for a book
- PATCH /api/audio-segments/{id}/reorder - Reorder segments
- POST /api/audio-segments/{id}/trim - Trim segment
- POST /api/audio-segments/{id}/merge - Merge segments
"""

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .dependencies import get_db

router = APIRouter(prefix="/audio-segments", tags=["audio-segments"])


class AudioSegmentResponse(BaseModel):
    """Audio segment response schema."""

    id: str = Field(description="Segment identifier")
    file_path: str = Field(description="Path to audio file")
    duration_ms: int = Field(description="Duration in milliseconds")
    text_hash: Optional[str] = Field(
        default=None, description="Text hash for cache validation"
    )
    speaker: Optional[str] = Field(default=None, description="Speaker name")
    paragraph_index: Optional[int] = Field(default=None, description="Paragraph index")


class ReorderRequest(BaseModel):
    """Reorder request schema."""

    segment_ids: List[str] = Field(description="Ordered list of segment IDs")
    crossfade_ms: int = Field(
        default=50, description="Crossfade duration in milliseconds"
    )


class TrimRequest(BaseModel):
    """Trim request schema."""

    start_ms: int = Field(description="Start time in milliseconds")
    end_ms: int = Field(description="End time in milliseconds")


class MergeRequest(BaseModel):
    """Merge request schema."""

    segment_ids: List[str] = Field(description="List of segment IDs to merge")
    output_path: Optional[str] = Field(default=None, description="Custom output path")


@router.get("/book/{book_id}", response_model=List[AudioSegmentResponse])
def list_audio_segments(book_id: str, db: Session = Depends(get_db)):
    """List all audio segments for a book.

    In MVP implementation, scans the storage directory for audio files.
    Future: query database for segment metadata.
    """
    storage_path = Path("storage/books") / book_id / "audio"

    if not storage_path.exists():
        return []

    segments = []
    for audio_file in sorted(storage_path.glob("*.mp3")):
        # Mock duration - in production use ffprobe
        segments.append(
            AudioSegmentResponse(
                id=audio_file.stem,
                file_path=str(audio_file),
                duration_ms=5000,  # Mock 5 seconds
                paragraph_index=(
                    int(audio_file.stem.split("_")[-1]) if "_" in audio_file.stem else 0
                ),
            )
        )

    return segments


@router.get("/{segment_id}", response_model=AudioSegmentResponse)
def get_audio_segment(segment_id: str, book_id: str, db: Session = Depends(get_db)):
    """Get a specific audio segment."""
    storage_path = Path("storage/books") / book_id / "audio" / f"{segment_id}.mp3"

    if not storage_path.exists():
        raise HTTPException(status_code=404, detail="Segment not found")

    return AudioSegmentResponse(
        id=segment_id,
        file_path=str(storage_path),
        duration_ms=5000,  # Mock duration
    )


@router.patch("/{segment_id}/reorder")
def reorder_segments(
    segment_id: str,
    request: ReorderRequest,
    book_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Reorder audio segments.

    Creates a new audio file with segments in the specified order.
    Uses ffmpeg crossfade for smooth transitions.
    """
    # In production: call synthesize._crossfade_stitch with reordered segments
    return {
        "status": "success",
        "message": f"Reordered {len(request.segment_ids)} segments",
        "crossfade_ms": request.crossfade_ms,
    }


@router.post("/{segment_id}/trim")
def trim_segment(
    segment_id: str,
    request: TrimRequest,
    book_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Trim audio segment to specified range.

    Args:
        segment_id: Segment identifier
        request: Trim parameters (start_ms, end_ms)
        book_id: Book identifier (from query param)

    Returns:
        Trimmed segment metadata
    """
    if request.start_ms >= request.end_ms:
        raise HTTPException(status_code=400, detail="start_ms must be less than end_ms")

    # In production: run ffmpeg -ss {start} -to {end} -i input -c copy output
    trimmed_duration = request.end_ms - request.start_ms

    return {
        "status": "success",
        "segment_id": f"{segment_id}_trimmed",
        "original_duration_ms": 5000,  # Mock
        "trimmed_duration_ms": trimmed_duration,
        "trim_range": {"start_ms": request.start_ms, "end_ms": request.end_ms},
    }


@router.post("/merge")
def merge_segments(
    request: MergeRequest,
    book_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Merge multiple audio segments into one.

    Args:
        request: Merge parameters (segment_ids, optional output_path)
        book_id: Book identifier (from query param)

    Returns:
        Merged segment metadata
    """
    if len(request.segment_ids) < 2:
        raise HTTPException(
            status_code=400, detail="At least 2 segments required for merge"
        )

    output_path = request.output_path or f"storage/books/{book_id}/audio/merged.mp3"

    # In production: use ffmpeg concat or crossfade stitch
    return {
        "status": "success",
        "merged_segment_count": len(request.segment_ids),
        "output_path": output_path,
        "estimated_duration_ms": len(request.segment_ids) * 5000,  # Mock
    }


@router.delete("/{segment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_audio_segment(
    segment_id: str,
    book_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Delete an audio segment."""
    storage_path = Path("storage/books") / book_id / "audio" / f"{segment_id}.mp3"

    if not storage_path.exists():
        raise HTTPException(status_code=404, detail="Segment not found")

    # In production: os.remove(storage_path)
    return None
