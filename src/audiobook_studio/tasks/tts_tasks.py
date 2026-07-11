"""
Celery tasks for TTS chapter synthesis with remote VoxCPM2.

Provides async chapter-level TTS synthesis with:
- Redis idempotency keys (text|voice_id|prosody hash)
- Redis semaphore for remote concurrency control (max 4)
- Progress reporting via Celery states
- Chapter-level crossfade stitching
- Failed paragraph tracking for resume
- RemoteVoxCPM2Client lifecycle management
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from celery import Celery
from celery.states import SUCCESS, FAILURE, RETRY, STARTED

from ..celery_app import celery_app
from ..database import SessionLocal
from ..models import AudioSegment, Chapter, Paragraph, Project
from ..pipeline.synthesize import SynthesizePipeline, AudioSegment as PipelineAudioSegment
from ..tts import RemoteVoxCPM2Client, RemoteVoxCPM2Config, create_remote_voxcpm2_client

logger = logging.getLogger(__name__)

# Redis connection for idempotency/semaphore/failed tracking
_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
try:
    import redis
    _redis_client = redis.from_url(_REDIS_URL, decode_responses=True)
except Exception as e:
    logger.warning(f"Redis client init failed, idempotency/semaphore disabled: {e}")
    _redis_client = None

# Lua script for atomic semaphore acquire
_ACQUIRE_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local current = redis.call('GET', key)
if current == false then
    redis.call('SET', key, 1, 'EX', ttl)
    return 1
end
if tonumber(current) < limit then
    redis.call('INCR', key)
    return 1
end
return 0
"""

# Lua script for atomic semaphore release
_RELEASE_LUA = """
local key = KEYS[1]
local current = redis.call('GET', key)
if current and tonumber(current) > 0 then
    redis.call('DECR', key)
    return 1
end
return 0
"""

_acquire_sha = None
_release_sha = None


def _get_redis() -> Optional["redis.Redis"]:
    """Get Redis client, initializing if needed."""
    global _redis_client, _acquire_sha, _release_sha
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.from_url(_REDIS_URL, decode_responses=True)
            _acquire_sha = _redis_client.script_load(_ACQUIRE_LUA)
            _release_sha = _redis_client.script_load(_RELEASE_LUA)
        except Exception as e:
            logger.warning(f"Redis client init failed: {e}")
            _redis_client = None
    return _redis_client


class TTSChapterTask(celery_app.Task):
    """Base task class for TTS chapter synthesis with retry/acks_late semantics."""

    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 300
    retry_jitter = True
    max_retries = 3
    acks_late = True
    reject_on_worker_lost = True

    def __init__(self):
        super().__init__()
        self._voxcpm2_client: Optional[RemoteVoxCPM2Client] = None
        self._semaphore_acquired = False

    def _get_voxcpm2_client(self) -> RemoteVoxCPM2Client:
        """Get or create RemoteVoxCPM2Client (lazy init)."""
        if self._voxcpm2_client is None:
            config = RemoteVoxCPM2Config.from_env()
            self._voxcpm2_client = create_remote_voxcpm2_client(config)
        return self._voxcpm2_client

    def _cleanup_voxcpm2_client(self) -> None:
        """Properly close RemoteVoxCPM2Client."""
        if self._voxcpm2_client is not None:
            try:
                import asyncio
                asyncio.run(self._voxcpm2_client.close())
            except Exception as e:
                logger.warning(f"Error closing RemoteVoxCPM2Client: {e}")
            finally:
                self._voxcpm2_client = None

    def _acquire_semaphore(self) -> bool:
        """Acquire semaphore slot for remote TTS concurrency control (max 4)."""
        global _acquire_sha
        client = _get_redis()
        if client is None:
            logger.warning("Redis unavailable, skipping semaphore acquire")
            return True

        try:
            result = client.evalsha(_acquire_sha, 1, "tts:remote:sem", 4, 3600)
            if result == 1:
                self._semaphore_acquired = True
                logger.debug("Acquired tts:remote:sem semaphore")
                return True
            logger.warning("Failed to acquire tts:remote:sem semaphore (limit reached)")
            return False
        except Exception as e:
            logger.warning(f"Semaphore acquire failed: {e}, proceeding without limit")
            return True

    def _release_semaphore(self) -> None:
        """Release semaphore slot."""
        global _release_sha
        if not self._semaphore_acquired:
            return
        client = _get_redis()
        if client is None:
            return
        try:
            client.evalsha(_release_sha, 1, "tts:remote:sem")
            self._semaphore_acquired = False
            logger.debug("Released tts:remote:sem semaphore")
        except Exception as e:
            logger.warning(f"Semaphore release failed: {e}")

    def _idem_key(self, text: str, voice_id: str, prosody: dict) -> str:
        """Generate idempotency key from text|voice_id|prosody."""
        payload = f"{text}|{voice_id}|{json.dumps(prosody, sort_keys=True, ensure_ascii=False)}"
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return f"tts:idem:{digest}"

    def _check_and_set_idempotency(self, idem_key: str) -> bool:
        """Check idempotency key with SETNX + 1h TTL. Returns True if acquired (first time)."""
        client = _get_redis()
        if client is None:
            return True
        try:
            # SETNX with 1 hour TTL
            acquired = client.set(idem_key, "1", nx=True, ex=3600)
            return bool(acquired)
        except Exception as e:
            logger.warning(f"Idempotency check failed: {e}, proceeding")
            return True

    def _record_failed_paragraph(self, project_id: int, chapter_id: int, paragraph_index: int) -> None:
        """Record failed paragraph index in Redis for resume capability."""
        client = _get_redis()
        if client is None:
            return
        key = f"tts:failed:{project_id}:{chapter_id}"
        try:
            client.sadd(key, str(paragraph_index))
            client.expire(key, 86400)  # 24h TTL
            logger.warning(f"Recorded failed paragraph {paragraph_index} for project {project_id} chapter {chapter_id}")
        except Exception as e:
            logger.warning(f"Failed to record failed paragraph: {e}")

    def _get_failed_paragraphs(self, project_id: int, chapter_id: int) -> set:
        """Get set of failed paragraph indices for resume."""
        client = _get_redis()
        if client is None:
            return set()
        key = f"tts:failed:{project_id}:{chapter_id}"
        try:
            members = client.smembers(key)
            return {int(m) for m in members}
        except Exception:
            return set()

    def _clear_failed_paragraphs(self, project_id: int, chapter_id: int) -> None:
        """Clear failed paragraph tracking on success."""
        client = _get_redis()
        if client is None:
            return
        key = f"tts:failed:{project_id}:{chapter_id}"
        try:
            client.delete(key)
        except Exception:
            pass

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Cleanup on task failure."""
        self._release_semaphore()
        self._cleanup_voxcpm2_client()
        super().on_failure(exc, task_id, args, kwargs, einfo)

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Cleanup on retry."""
        self._release_semaphore()
        self._cleanup_voxcpm2_client()
        super().on_retry(exc, task_id, args, kwargs, einfo)

    def on_success(self, retval, task_id, args, kwargs):
        """Cleanup on success."""
        self._release_semaphore()
        self._cleanup_voxcpm2_client()
        super().on_success(retval, task_id, args, kwargs)


@celery_app.task(
    bind=True,
    base=TTSChapterTask,
    name="src.audiobook_studio.tasks.tts_tasks.synthesize_chapter_task",
    max_retries=3,
    default_retry_delay=60,
)
def synthesize_chapter_task(
    self,
    project_id: int,
    chapter_id: int,
    chapter_index: int,
    paragraphs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Synthesize a full chapter TTS using remote VoxCPM2 with crossfade stitching.

    Args:
        project_id: Project ID
        chapter_id: Chapter ID
        chapter_index: Chapter index (1-based)
        paragraphs: List of paragraph dicts with keys:
            - paragraph_id: int
            - paragraph_index: int
            - text: str
            - voice_id: str
            - prosody: dict (rate, pitch, volume, etc.)

    Returns:
        Dict with task_id, status, chapter_audio_path, segments, failed_indices, error
    """
    task_id = self.request.id
    logger.info(f"[{task_id}] Starting TTS chapter synthesis: project={project_id}, chapter={chapter_id}, index={chapter_index}")

    # Acquire semaphore for remote concurrency control
    if not self._acquire_semaphore():
        return {
            "task_id": task_id,
            "status": "failed",
            "error": "Remote TTS concurrency limit reached (max 4)",
            "chapter_audio_path": None,
            "segments": [],
            "failed_indices": [],
        }

    db = SessionLocal()
    try:
        # Verify project and chapter exist
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return {"task_id": task_id, "status": "failed", "error": f"Project {project_id} not found"}

        chapter = db.query(Chapter).filter(Chapter.id == chapter_id, Chapter.project_id == project_id).first()
        if not chapter:
            return {"task_id": task_id, "status": "failed", "error": f"Chapter {chapter_id} not found in project {project_id}"}

        # Get output directory from project or default
        output_dir = Path(f"./output/project_{project_id}/chapter_{chapter_index}")
        output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize pipeline for crossfade stitching
        pipeline = SynthesizePipeline(output_dir=str(output_dir), mock_mode=False)

        # Get failed paragraph indices for resume
        failed_indices = self._get_failed_paragraphs(project_id, chapter_id)
        if failed_indices:
            logger.info(f"[{task_id}] Resuming from failed paragraphs: {sorted(failed_indices)}")

        client = self._get_voxcpm2_client()
        segments: List[PipelineAudioSegment] = []
        total = len(paragraphs)
        failed_this_run = []

        for i, para in enumerate(paragraphs):
            para_id = para["paragraph_id"]
            para_index = para["paragraph_index"]
            text = para["text"]
            voice_id = para["voice_id"]
            prosody = para.get("prosody", {})

            # Progress reporting
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": i + 1,
                    "total": total,
                    "paragraph_id": para_id,
                    "paragraph_index": para_index,
                },
            )

            # Skip if already succeeded (not in failed set)
            if para_index not in failed_indices:
                # Check idempotency key
                idem_key = self._idem_key(text, voice_id, prosody)
                if not self._check_and_set_idempotency(idem_key):
                    logger.info(f"[{task_id}] Paragraph {para_index} already synthesized (idempotent), skipping")
                    # Try to load existing segment from DB
                    existing = db.query(AudioSegment).filter(
                        AudioSegment.project_id == project_id,
                        AudioSegment.chapter_id == chapter_id,
                        AudioSegment.paragraph_id == para_id,
                        AudioSegment.is_current == True,
                    ).first()
                    if existing and Path(existing.file_path).exists():
                        segments.append(PipelineAudioSegment(
                            segment_id=f"{project_id}_ch{chapter_index}_p{para_index}",
                            file_path=existing.file_path,
                            duration_ms=existing.duration_ms or 0,
                            engine=existing.engine or "voxcpm2_remote",
                            voice_id=existing.voice_id or voice_id,
                            text_hash=hashlib.md5(text.encode()).hexdigest()[:12],
                        ))
                        continue

            # Synthesize paragraph
            segment_id = f"{project_id}_ch{chapter_index}_p{para_index}"
            output_path = output_dir / f"{segment_id}.wav"

            try:
                logger.info(f"[{task_id}] Synthesizing paragraph {para_index}/{total}: {segment_id}")
                import asyncio
                audio_data = asyncio.run(client.synthesize(text, voice_id, prosody))

                # Save audio file
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(audio_data)

                # Get duration using ffprobe
                duration_ms = _get_audio_duration(output_path)

                # Create AudioSegment DB record
                audio_segment = AudioSegment(
                    project_id=project_id,
                    chapter_id=chapter_id,
                    paragraph_id=para_id,
                    file_path=str(output_path),
                    format="wav",
                    duration_ms=duration_ms,
                    file_size_bytes=output_path.stat().st_size,
                    sample_rate=24000,
                    channels=1,
                    engine="voxcpm2_remote",
                    voice_id=voice_id,
                    prosody_overrides=prosody if prosody else None,
                    version=1,
                    is_current=True,
                    status="completed",
                )
                db.add(audio_segment)
                db.commit()

                # Add to segments for stitching
                segments.append(PipelineAudioSegment(
                    segment_id=segment_id,
                    file_path=str(output_path),
                    duration_ms=duration_ms,
                    engine="voxcpm2_remote",
                    voice_id=voice_id,
                    text_hash=hashlib.md5(text.encode()).hexdigest()[:12],
                ))

                logger.info(f"[{task_id}] Paragraph {para_index} synthesized: {duration_ms}ms")

            except Exception as e:
                logger.error(f"[{task_id}] Paragraph {para_index} synthesis failed: {e}")
                failed_this_run.append(para_index)
                self._record_failed_paragraph(project_id, chapter_id, para_index)
                # Continue with other paragraphs

        # Chapter-level crossfade stitching
        chapter_audio_path = None
        if segments:
            chapter_output = output_dir / f"chapter_{chapter_index}.mp3"
            try:
                total_duration = pipeline._crossfade_stitch(segments, chapter_output)
                chapter_audio_path = str(chapter_output)
                logger.info(f"[{task_id}] Chapter stitched: {chapter_output} ({total_duration}ms)")
            except Exception as e:
                logger.error(f"[{task_id}] Chapter stitching failed: {e}")
                chapter_audio_path = None
        else:
            logger.warning(f"[{task_id}] No segments synthesized for chapter {chapter_index}")

        # Clear failed tracking if all succeeded
        if not failed_this_run:
            self._clear_failed_paragraphs(project_id, chapter_id)

        # Build response
        response = {
            "task_id": task_id,
            "status": "completed" if not failed_this_run else "partial",
            "chapter_audio_path": chapter_audio_path,
            "segments": [s.to_dict() for s in segments],
            "failed_indices": failed_this_run,
            "total_paragraphs": total,
            "succeeded": total - len(failed_this_run),
            "failed": len(failed_this_run),
        }

        if failed_this_run:
            response["error"] = f"{len(failed_this_run)} paragraphs failed: {failed_this_run}"
            logger.warning(f"[{task_id}] Chapter synthesis partial: {len(failed_this_run)}/{total} failed")

        logger.info(f"[{task_id}] Chapter synthesis completed: {response['status']}")
        return response

    except Exception as e:
        logger.exception(f"[{task_id}] Chapter synthesis failed: {e}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        return {
            "task_id": task_id,
            "status": "failed",
            "error": str(e),
            "chapter_audio_path": None,
            "segments": [],
            "failed_indices": list(range(len(paragraphs))),
        }
    finally:
        db.close()


@celery_app.task(
    bind=True,
    base=TTSChapterTask,
    name="src.audiobook_studio.tasks.tts_tasks.resume_chapter_task",
    max_retries=3,
    default_retry_delay=60,
)
def resume_chapter_task(
    self,
    project_id: int,
    chapter_id: int,
    chapter_index: int,
) -> Dict[str, Any]:
    """
    Resume a chapter synthesis from failed paragraphs.

    Fetches chapter paragraphs from DB and re-runs synthesis for failed indices only.
    """
    task_id = self.request.id
    logger.info(f"[{task_id}] Resuming chapter synthesis: project={project_id}, chapter={chapter_id}")

    db = SessionLocal()
    try:
        # Get chapter and paragraphs
        chapter = db.query(Chapter).filter(Chapter.id == chapter_id, Chapter.project_id == project_id).first()
        if not chapter:
            return {"task_id": task_id, "status": "failed", "error": f"Chapter {chapter_id} not found"}

        paragraphs = (
            db.query(Paragraph)
            .filter(Paragraph.project_id == project_id, Paragraph.chapter_id == chapter_id)
            .order_by(Paragraph.index)
            .all()
        )

        if not paragraphs:
            return {"task_id": task_id, "status": "failed", "error": "No paragraphs found for chapter"}

        # Build paragraph dicts
        para_dicts = [
            {
                "paragraph_id": p.id,
                "paragraph_index": p.index,
                "text": p.text,
                "voice_id": p.suggested_voice_id or "zh_female_1",
                "prosody": p.prosody_overrides or {},
            }
            for p in paragraphs
        ]

        # Delegate to main synthesis task (will use failed indices from Redis)
        return synthesize_chapter_task(project_id, chapter_id, chapter_index, para_dicts)

    finally:
        db.close()


@celery_app.task(
    name="src.audiobook_studio.tasks.tts_tasks.get_tts_status"
)
def get_tts_status(task_id: str) -> Dict[str, Any]:
    """
    Get the status of a TTS task by Celery task ID.

    Returns:
        Dict with task_id, state, progress info, and error if any.
    """
    result = celery_app.AsyncResult(task_id)

    response = {
        "task_id": task_id,
        "state": result.state,
        "info": result.info or {},
    }

    state_map = {
        "PENDING": "pending",
        "STARTED": "processing",
        "PROGRESS": "processing",
        "SUCCESS": "completed",
        "FAILURE": "failed",
        "RETRY": "retrying",
    }
    response["progress"] = state_map.get(result.state, result.state.lower())

    if isinstance(result.info, dict):
        response["current"] = result.info.get("current", 0)
        response["total"] = result.info.get("total", 0)
        response["paragraph_id"] = result.info.get("paragraph_id")
        response["paragraph_index"] = result.info.get("paragraph_index")

    if result.state == "FAILURE":
        response["error"] = str(result.info) if not isinstance(result.info, dict) else result.info.get("error", "Unknown error")

    return response


def _get_audio_duration(file_path: Path) -> int:
    """Get audio duration in milliseconds using ffprobe."""
    try:
        import subprocess
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            duration_sec = float(result.stdout.strip())
            return int(duration_sec * 1000)
    except Exception as e:
        logger.warning(f"ffprobe failed for {file_path}: {e}")

    # Fallback: estimate from file size (rough approximation for 24kHz mono WAV)
    try:
        size = file_path.stat().st_size
        # 24000 samples/sec * 2 bytes/sample = 48000 bytes/sec
        estimated_sec = size / 48000
        return int(estimated_sec * 1000)
    except Exception:
        return 0


# Ensure task is registered with celery_app
__all__ = [
    "TTSChapterTask",
    "synthesize_chapter_task",
    "resume_chapter_task",
    "get_tts_status",
]