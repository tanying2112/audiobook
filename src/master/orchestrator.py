"""
Audiobook Orchestrator — Semantic Chunking + Async Pipeline + Result Reassembly.

Responsibilities:
1. Semantic chunking: Split text at clause boundaries (。！？\\n) into ≤200 char chunks
2. Async pipeline: Submit chunks to tts:tasks queue with idempotency keys
3. Result listener: Redis pub/sub listener for tts:results channel
4. Reassembly: Stitch chunk audio URLs in order, upload final audiobook to R2
5. Progress tracking: Real-time progress via Redis pub/sub
"""

import json
import os
import re

# Import state store components
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import boto3
import redis
from botocore.config import Config

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from state_store import IDEMPOTENCY_TTL, HermesStateStore, TaskState, TTSTask


class ChunkStrategy(str, Enum):
    """Text chunking strategy."""

    SEMANTIC = "semantic"  # Split at 。！？\n, max 200 chars
    FIXED = "fixed"  # Fixed character chunks
    SENTENCE = "sentence"  # Split at sentence boundaries only


@dataclass
class AudiobookTask:
    """Audiobook generation task submitted by user."""

    book_id: str
    title: str
    author: str
    chapters: List[Dict[str, Any]]  # [{"title": "Ch1", "text": "..."}, ...]
    voice_id: str
    prosody: Dict[str, Any]
    reference_audio: Optional[str] = None
    chunk_strategy: ChunkStrategy = ChunkStrategy.SEMANTIC
    max_chunk_chars: int = 200
    idempotency_key: Optional[str] = None
    callback_url: Optional[str] = None


@dataclass
class ChunkTask:
    """Individual TTS chunk task."""

    chunk_id: str
    book_id: str
    chapter_index: int
    chunk_index: int
    text: str
    voice_id: str
    prosody: Dict[str, Any]
    reference_audio: Optional[str]
    idempotency_key: str


@dataclass
class AudiobookProgress:
    """Real-time progress tracker."""

    book_id: str
    total_chunks: int
    completed_chunks: int = 0
    failed_chunks: int = 0
    chunk_urls: Dict[int, str] = field(default_factory=dict)  # chunk_index -> url
    status: str = "PENDING"  # PENDING, PROCESSING, COMPLETED, FAILED
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class SemanticChunker:
    """
    Semantic text chunking at clause boundaries.

    Strategy:
    1. Split at Chinese punctuation: 。！？ and newlines
    2. Merge small fragments to approach max_chunk_chars
    3. Never split mid-sentence; hard cap at max_chunk_chars
    """

    # Clause-ending punctuation (Chinese + common Western)
    CLAUSE_ENDINGS = re.compile(r"([。！？\n]|[.!?]\s+)")

    def __init__(self, max_chars: int = 200, min_chars: int = 50):
        self.max_chars = max_chars
        self.min_chars = min_chars

    def chunk(self, text: str) -> List[str]:
        """Split text into semantic chunks."""
        if not text or not text.strip():
            return []

        # Split at clause boundaries
        parts = self.CLAUSE_ENDINGS.split(text)

        # Reconstruct with punctuation
        chunks = []
        current = ""

        for i, part in enumerate(parts):
            if i % 2 == 0:
                # Text segment
                current += part
            else:
                # Punctuation - end of clause
                current += part

                # Check if we should flush
                if len(current) >= self.min_chars and len(current) <= self.max_chars:
                    chunks.append(current.strip())
                    current = ""
                elif len(current) > self.max_chars:
                    # Hard split - find last punctuation within limit
                    flush = current[: self.max_chars]
                    last_punct = max(flush.rfind("。"), flush.rfind("！"), flush.rfind("？"), flush.rfind("\n"))
                    if last_punct > 0:
                        chunks.append(flush[: last_punct + 1].strip())
                        current = flush[last_punct + 1 :] + current[self.max_chars :]
                    else:
                        # No punctuation - hard split
                        chunks.append(flush.strip())
                        current = current[self.max_chars :]

        # Flush remainder
        if current.strip():
            chunks.append(current.strip())

        # Merge tiny trailing chunks
        merged = []
        for chunk in chunks:
            if merged and len(merged[-1]) + len(chunk) <= self.max_chars:
                merged[-1] += " " + chunk
            else:
                merged.append(chunk)

        return [c for c in merged if c.strip()]


class R2Uploader:
    """Cloudflare R2 uploader with multipart support for large files."""

    def __init__(
        self,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        public_url_base: Optional[str] = None,
        verify_ssl: bool = False,
    ):
        import ssl

        self.bucket = bucket
        self.public_url_base = public_url_base or f"https://{bucket}.r2.cloudflarestorage.com"

        # Create a permissive SSL context for custom R2 domains with handshake issues
        if verify_ssl is False:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            # Allow older TLS versions and more ciphers for compatibility
            ssl_context.set_ciphers("DEFAULT:@SECLEVEL=1")
            ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
            ssl_context.maximum_version = ssl.TLSVersion.TLSv1_3
            verify = ssl_context
        else:
            verify = verify_ssl

        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
            config=Config(max_pool_connections=10),
            verify=verify,  # R2 custom domains may have SSL verification issues
        )

    def upload_bytes(self, data: bytes, key: str, content_type: str = "audio/wav") -> str:
        """Upload bytes directly (for small files < 100MB)."""
        self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return f"{self.public_url_base}/{key}"

    def upload_file(self, file_path: str, key: str, content_type: str = "audio/wav") -> str:
        """Upload file with automatic multipart for large files."""
        self.s3.upload_file(
            file_path,
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        return f"{self.public_url_base}/{key}"

    def download_bytes(self, key: str) -> bytes:
        """Download object as bytes."""
        response = self.s3.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()


class AudiobookOrchestrator:
    """
    Orchestrates full audiobook generation pipeline:

    1. Semantic chunking of chapters
    2. Submit chunk tasks to Redis queue with idempotency keys
    3. Listen for results on Redis pub/sub (tts:results)
    4. Track progress in real-time
    5. Download chunk audio, concatenate, upload final audiobook
    6. Callback on completion (if webhook provided)
    """

    def __init__(
        self,
        redis_host: str,
        redis_port: int,
        redis_auth: str,
        r2_endpoint: str,
        r2_access_key: str,
        r2_secret_key: str,
        r2_bucket: str,
        r2_public_url: Optional[str] = None,
        worker_id: Optional[str] = None,
    ):
        self.worker_id = worker_id or f"orchestrator-{uuid.uuid4().hex[:8]}"

        # State store for task management
        self.state_store = HermesStateStore(redis_host, redis_port, redis_auth)

        # Direct Redis for pub/sub
        self.redis = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_auth,
            decode_responses=True,
            ssl=True,  # Upstash requires TLS
        )

        # R2 for final audiobook upload
        self.r2 = R2Uploader(r2_endpoint, r2_access_key, r2_secret_key, r2_bucket, r2_public_url, verify_ssl=False)

        # Progress tracking
        self._progress: Dict[str, AudiobookProgress] = {}
        self._progress_lock = threading.Lock()

        # Result listener
        self._listener_thread: Optional[threading.Thread] = None
        self._listener_stop = threading.Event()
        self._result_callbacks: List[Callable[[str, Dict], None]] = []

        # Chunker
        self.chunker = SemanticChunker()

    # --- Chunking ---

    def chunk_chapter(self, text: str, max_chars: int = 200) -> List[str]:
        """Split chapter text into semantic chunks."""
        self.chunker.max_chars = max_chars
        return self.chunker.chunk(text)

    # --- Task Submission ---

    def submit_audiobook(
        self,
        book_id: str,
        title: str,
        author: str,
        chapters: List[Dict[str, Any]],
        voice_id: str,
        prosody: Dict[str, Any],
        reference_audio: Optional[str] = None,
        chunk_strategy: ChunkStrategy = ChunkStrategy.SEMANTIC,
        max_chunk_chars: int = 200,
        idempotency_key: Optional[str] = None,
        callback_url: Optional[str] = None,
    ) -> AudiobookTask:
        """
        Submit full audiobook for generation.

        Returns AudiobookTask with chunking plan.
        """
        task = AudiobookTask(
            book_id=book_id,
            title=title,
            author=author,
            chapters=chapters,
            voice_id=voice_id,
            prosody=prosody,
            reference_audio=reference_audio,
            chunk_strategy=chunk_strategy,
            max_chunk_chars=max_chunk_chars,
            idempotency_key=idempotency_key,
            callback_url=callback_url,
        )

        # Chunk all chapters
        all_chunks = []
        for ch_idx, chapter in enumerate(chapters):
            chapter_text = chapter.get("text", "")
            if not chapter_text.strip():
                continue

            if chunk_strategy == ChunkStrategy.SEMANTIC:
                chunks = self.chunk_chapter(chapter_text, max_chunk_chars)
            else:
                # Fallback: fixed-size chunks
                chunks = [chapter_text[i : i + max_chunk_chars] for i in range(0, len(chapter_text), max_chunk_chars)]

            for chunk_idx, chunk_text in enumerate(chunks):
                chunk_id = f"{book_id}-ch{ch_idx}-ck{chunk_idx}"
                idempotency_key = (
                    f"tts:{chunk_id}" if not task.idempotency_key else f"{task.idempotency_key}:{chunk_id}"
                )

                all_chunks.append(
                    ChunkTask(
                        chunk_id=chunk_id,
                        book_id=book_id,
                        chapter_index=ch_idx,
                        chunk_index=chunk_idx,
                        text=chunk_text,
                        voice_id=voice_id,
                        prosody=prosody,
                        reference_audio=reference_audio,
                        idempotency_key=idempotency_key,
                    )
                )

        # Initialize progress
        with self._progress_lock:
            self._progress[book_id] = AudiobookProgress(
                book_id=book_id,
                total_chunks=len(all_chunks),
                status="PROCESSING",
            )

        # Submit chunk tasks
        submitted = 0
        for chunk in all_chunks:
            try:
                tts_task = self.state_store.create_task(
                    text=chunk.text,
                    voice_id=chunk.voice_id,
                    prosody=chunk.prosody,
                    reference_audio=chunk.reference_audio,
                    idempotency_key=chunk.idempotency_key,
                )
                submitted += 1
            except Exception as e:
                print(f"❌ [{self.worker_id}] Failed to submit chunk {chunk.chunk_id}: {e}", file=sys.stderr)

        print(f"✅ [{self.worker_id}] Submitted {submitted}/{len(all_chunks)} chunks for book {book_id}")
        return task

    # --- Progress Tracking ---

    def get_progress(self, book_id: str) -> Optional[AudiobookProgress]:
        """Get current progress for a book."""
        with self._progress_lock:
            return self._progress.get(book_id)

    def _update_progress(self, book_id: str, **updates):
        """Thread-safe progress update."""
        with self._progress_lock:
            if book_id in self._progress:
                prog = self._progress[book_id]
                for k, v in updates.items():
                    setattr(prog, k, v)
                prog.updated_at = time.time()

                # Publish progress event
                self.redis.publish(
                    f"audiobook:progress:{book_id}",
                    json.dumps(
                        {
                            "book_id": book_id,
                            "total_chunks": prog.total_chunks,
                            "completed_chunks": prog.completed_chunks,
                            "failed_chunks": prog.failed_chunks,
                            "status": prog.status,
                            "percent": (
                                round(prog.completed_chunks / prog.total_chunks * 100, 1) if prog.total_chunks else 0
                            ),
                        }
                    ),
                )

    # --- Result Listener ---

    def start_result_listener(self):
        """Start background thread listening for TTS results."""
        if self._listener_thread and self._listener_thread.is_alive():
            return

        self._listener_stop.clear()
        self._listener_thread = threading.Thread(target=self._listen_results, daemon=True)
        self._listener_thread.start()
        print(f"🎧 [{self.worker_id}] Result listener started")

    def stop_result_listener(self):
        """Stop result listener thread."""
        self._listener_stop.set()
        if self._listener_thread:
            self._listener_thread.join(timeout=5)
        print(f"🛑 [{self.worker_id}] Result listener stopped")

    def _listen_results(self):
        """Background listener for tts:results pub/sub."""
        pubsub = self.redis.pubsub()
        pubsub.subscribe("tts:results")

        for message in pubsub.listen():
            if self._listener_stop.is_set():
                break

            if message["type"] != "message":
                continue

            try:
                result = json.loads(message["data"])
                self._handle_chunk_result(result)
            except Exception as e:
                print(f"❌ [{self.worker_id}] Error processing result: {e}", file=sys.stderr)

    def _handle_chunk_result(self, result: Dict):
        """
        Handle completed chunk result.

        Expected result format:
        {
            "task_id": "tts-abc123",
            "status": "completed" | "failed",
            "chunk_id": "book1-ch0-ck0",
            "book_id": "book1",
            "chunk_index": 0,
            "audio_url": "https://.../chunk.wav",
            "error": "error message if failed"
        }
        """
        task_id = result.get("task_id")
        chunk_id = result.get("chunk_id")
        book_id = result.get("book_id")
        chunk_index = result.get("chunk_index")
        status = result.get("status")

        if not all([task_id, chunk_id, book_id, chunk_index is not None]):
            return

        if status == "completed":
            audio_url = result.get("audio_url")
            if audio_url:
                self._update_progress(book_id, completed_chunks=1)
                self._update_progress(book_id, chunk_urls={chunk_index: audio_url})
                print(f"✅ [{self.worker_id}] Chunk {chunk_id} completed → {audio_url}")

                # Check if book is complete
                prog = self.get_progress(book_id)
                if prog and prog.completed_chunks + prog.failed_chunks >= prog.total_chunks:
                    self._finalize_audiobook(book_id)

        elif status == "failed":
            error = result.get("error", "Unknown error")
            self._update_progress(book_id, failed_chunks=1, error=error)
            print(f"❌ [{self.worker_id}] Chunk {chunk_id} failed: {error}")

    def _finalize_audiobook(self, book_id: str):
        """Download all chunks, concatenate, upload final audiobook."""
        prog = self.get_progress(book_id)
        if not prog or prog.status in ("COMPLETED", "FAILED"):
            return

        print(f"🔗 [{self.worker_id}] Finalizing audiobook {book_id} ({prog.completed_chunks} chunks)")

        # Sort chunks by index
        sorted_chunks = sorted(prog.chunk_urls.items())

        if not sorted_chunks:
            self._update_progress(book_id, status="FAILED", error="No completed chunks")
            return

        try:
            # Download and concatenate
            import io

            import numpy as np
            import soundfile as sf

            combined_audio = []
            sample_rate = None

            for idx, url in sorted_chunks:
                # Download chunk from R2
                # Extract key from URL
                key = url.replace(self.r2.public_url_base + "/", "")
                chunk_bytes = self.r2.download_bytes(key)

                # Read audio
                data, sr = sf.read(io.BytesIO(chunk_bytes))
                if sample_rate is None:
                    sample_rate = sr
                elif sr != sample_rate:
                    # Resample if needed
                    import librosa

                    data = librosa.resample(data, orig_sr=sr, target_sr=sample_rate)

                combined_audio.append(data)

            # Concatenate
            final_audio = np.concatenate(combined_audio)

            # Upload final audiobook
            final_key = f"audiobooks/{book_id}/final.wav"
            import io

            buffer = io.BytesIO()
            sf.write(buffer, final_audio, sample_rate, format="WAV")
            buffer.seek(0)

            final_url = self.r2.upload_bytes(buffer.read(), final_key, "audio/wav")

            self._update_progress(book_id, status="COMPLETED", final_url=final_url)
            print(f"🎉 [{self.worker_id}] Audiobook {book_id} complete: {final_url}")

            # Trigger callback if provided
            # TODO: Implement webhook callback

        except Exception as e:
            self._update_progress(book_id, status="FAILED", error=str(e))
            print(f"💥 [{self.worker_id}] Finalization failed: {e}", file=sys.stderr)

    # --- Orchestration ---

    def run(self):
        """Run orchestrator main loop."""
        print(f"🚀 [{self.worker_id}] Audiobook Orchestrator starting...")
        self.start_result_listener()

        try:
            while True:
                time.sleep(60)  # Heartbeat
                # Cleanup old progress entries
                self._cleanup_progress()
        except KeyboardInterrupt:
            print(f"\n🛑 [{self.worker_id}] Shutdown signal received")
        finally:
            self.stop_result_listener()

    def _cleanup_progress(self, max_age: int = 86400):
        """Remove completed/failed progress entries older than max_age."""
        now = time.time()
        with self._progress_lock:
            to_remove = [
                bid
                for bid, prog in self._progress.items()
                if prog.status in ("COMPLETED", "FAILED") and (now - prog.updated_at) > max_age
            ]
            for bid in to_remove:
                del self._progress[bid]


def main():
    """Standalone orchestrator entry point."""
    redis_host = os.getenv("REDIS_HOST")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    redis_auth = os.getenv("REDIS_AUTH")
    r2_endpoint = os.getenv("R2_ENDPOINT")
    r2_access_key = os.getenv("R2_ACCESS_KEY_ID")
    r2_secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
    r2_bucket = os.getenv("R2_BUCKET")
    r2_public_url = os.getenv("R2_PUBLIC_URL")

    required = {
        "REDIS_HOST": redis_host,
        "REDIS_AUTH": redis_auth,
        "R2_ENDPOINT": r2_endpoint,
        "R2_ACCESS_KEY_ID": r2_access_key,
        "R2_SECRET_ACCESS_KEY": r2_secret_key,
        "R2_BUCKET": r2_bucket,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"ERROR: Missing env vars: {missing}", file=sys.stderr)
        sys.exit(1)

    orchestrator = AudiobookOrchestrator(
        redis_host=redis_host,
        redis_port=redis_port,
        redis_auth=redis_auth,
        r2_endpoint=r2_endpoint,
        r2_access_key=r2_access_key,
        r2_secret_key=r2_secret_key,
        r2_bucket=r2_bucket,
        r2_public_url=r2_public_url,
    )

    orchestrator.run()


if __name__ == "__main__":
    main()
