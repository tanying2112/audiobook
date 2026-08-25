"""Pipeline Stage 5: Synthesize - Audio synthesis orchestration via RemoteTTSPort.

This pipeline routes TTS synthesis requests through the RemoteTTSPort contract,
which isolates the internal orchestration layer from the external Hermes
scheduling layer (Redis state machine + R2 object storage).

All synthesis engines (Kokoro, Edge, Azure, GCP, VoxCPM2, etc.) are accessed
via the Port abstraction. The pipeline never makes direct HTTP calls or
manages engine clients directly.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Coroutine, Dict, List, Literal, Optional, Tuple, TypeVar, cast

from ..audio_quality import QualityReport, SegmentQualityResult, check_all_segments, save_quality_report
from ..config.acoustic_mapping import get_emotion_map
from ..config.hardware_profile import HardwareProfile, get_hardware_profile
from ..di import get_app_container
from ..export.pool import get_ffmpeg_semaphore, run_ffmpeg
from ..llm import LLMRouter, create_router
from ..monitoring.langfuse_client import is_enabled, observe_quality_check, observe_tts_synthesis, trace_function
from ..monitoring.telemetry import record_tts_fallback, record_tts_quality_check, record_tts_retry, record_tts_segment
from ..pipeline.progress_emitter import emit_stage_enter, emit_stage_exit, emit_stage_progress, emit_paragraph_complete
from ..api.websocket import emit_pipeline_event
from ..schemas import AudioPostProcessParams, ParagraphAnnotation, TtsRoutingDecision, TtsRoutingInput
from ..tts.audio_semantic_cache import AudioSemanticCache, get_audio_semantic_cache
from ..security import safe_subprocess_args
from ..tts import (
    EngineRegistry,
    RemoteTTSPort,
    SynthesisResult,
    TTSEngine,
    TTSProsody,
    TTSStatus,
    TTSTaskPayload,
    TTSTaskResult,
    TTSTaskStatus,
    TTSVoiceAnchor,
    VoiceInfo,
)
from ..di import get_app_container
from ..tts.streaming import (
    StreamingTTSConfig,
    StreamingTTSResult,
    StreamingTTSEngine,
    create_streaming_tts_engine,
)
from ..tts.fake_port import FakeRemoteTTSPort
from ..tts.clone import CloningConfig, VoiceCloningManager
from ..utils.ffmpeg_probe import get_duration_sync

logger = logging.getLogger(__name__)


# Edge-TTS voice ID -> Kokoro voice ID mapping
_EDGE_TO_KOKORO: Dict[str, str] = {
    "zh-CN-XiaoxiaoNeural": "zf_xiaoxiao",
    "zh-CN-YunxiNeural": "zm_yunxi",
    "zh-CN-YunjianNeural": "zm_yunjian",
    "zh-CN-XiaoyiNeural": "zf_xiaoni",
    "zh-CN-XiaochenNeural": "zf_xiaoxuan",
    "zh-CN-XiaohanNeural": "zf_xiaobei",
    "zh-CN-XiaomengNeural": "zf_xiaoxuan",
    "zh-CN-XiaomoNeural": "zf_xiaoxiao",
    "zh-CN-XiaoqiuNeural": "zf_xiaoxiao",
    "zh-CN-XiaoruiNeural": "zf_xiaoxiao",
    "zh-CN-XiaoshuangNeural": "zf_xiaoxiao",
    "zh-CN-XiaoxuanNeural": "zf_xiaoxuan",
    "zh-CN-YangxiNeural": "zm_yunyang",
    "zh-CN-YangyangNeural": "zm_yunyang",
    "zh-CN-YunhaoNeural": "zm_yunjian",
    "zh-CN-YunzeNeural": "zm_yunjian",
    "en-US-AriaNeural": "zf_xiaoxiao",
    "en-US-JennyNeural": "zf_xiaoxiao",
    "en-US-GuyNeural": "zm_yunjian",
    "en-US-ChristopherNeural": "zm_yunjian",
    "en-US-EricNeural": "zm_yunjian",
    "en-US-RogerNeural": "zm_yunjian",
    "en-US-SteffanNeural": "zm_yunjian",
    "ja-JP-NanamiNeural": "zf_xiaoxiao",
    "ja-JP-KeitaNeural": "zm_yunjian",
    "ko-KR-SunHiNeural": "zf_xiaoxiao",
    "ko-KR-InJoonNeural": "zm_yunjian",
}


def _normalize_voice_id(voice_id: str, engine_choice: str, *, strict: bool = False) -> str:
    """Pick a voice_id understood by the chosen TTS engine.

    Edge-TTS voice IDs (e.g. ``zh-CN-XiaoxiaoNeural``) are the default stored in
    the book analyse stage. Kokoro uses a different naming scheme (e.g.
    ``zf_xiaoxiao``). If a non-native voice_id is passed to Kokoro it rejects
    the voice and silently fails synthesis. This helper cross-maps when
    possible and otherwise falls back to a safe default for the engine.

    P1.9 red-line #1 (主路径真实性): introducing ``strict`` decouples the two
    legitimate intents that previously collided in a single silent-fallback:

    * ``strict=False`` (default) — production-safe: an unknown voice_id (not in
      either naming scheme) is replaced with the engine's canonical narrator
      voice (Kokoro ``zf_xiaoxiao`` / Edge ``zh-CN-XiaoxiaoNeural``) and
      ``"default"`` resolves to the same. This matches the old behaviour and
      keeps a misconfigured book from silently failing synthesis. Use it for
      the engine-facing call (``_synthesize_via_port``) where the routing layer
      has *already* decided what to trust.

    * ``strict=True`` — pass-through: an unknown voice_id (e.g. a caller-supplied
      ``suggested_voice_id`` for a custom/clone voice, or a test fixture ID) is
      returned **as-is**, NOT swallowed into the narrator default. Edge↔Kokoro
      cross-mapping still applies when an ID is recognised and needs translating
      to the chosen engine's scheme; ``strict`` only governs what happens to IDs
      the engine does not know. The routing decision uses this when an explicit
      ``character_voice_map`` binding was matched — the user explicitly named a
      voice, so we honour it instead of overriding it. Unknown → engine still
      owns the final accept/reject (it may raise honestly at synthesis time,
      which is preferable to silently swapping voices).
    """
    if voice_id == "default":
        return "zf_xiaoxiao" if engine_choice == "kokoro" else "zh-CN-XiaoxiaoNeural"
    if engine_choice == "kokoro":
        # Map Edge voice_id to Kokoro equivalent; pass through if it's already a
        # Kokoro ID, else default to ``zf_xiaoxiao``.
        if voice_id in _EDGE_TO_KOKORO:
            return _EDGE_TO_KOKORO[voice_id]
        # Already a Kokoro ID? accept as-is.
        if voice_id in (
            "zf_xiaobei",
            "zf_xiaoni",
            "zf_xiaoxuan",
            "zf_xiaoxiao",
            "zm_yunjian",
            "zm_yunxi",
            "zm_yunxia",
            "zm_yunyang",
        ):
            return voice_id
        # Unknown — in strict mode honour it (caller explicitly named a voice,
        # e.g. a custom voice ID); the engine owns the honest accept/reject.
        # Otherwise fall back to the canonical narrator voice (production-safe).
        if strict:
            return voice_id
        return "zf_xiaoxiao"
    # engine_choice == "edge": Edge accepts its own IDs and ignores Kokoro IDs;
    # map Kokoro IDs back to Edge if we get one (edge case).
    if not voice_id.startswith("zh-"):
        # Unknown / Kokoro-style ID on edge engine. Strict mode honours it
        # (edge may reject honestly); non-strict falls back to the Edge default.
        return voice_id if strict else "zh-CN-XiaoxiaoNeural"
    return voice_id


def _port_engine_name(port: RemoteTTSPort) -> str:
    """Return the active engine name (kokoro/edge/voxcpm2/...) for a port.

    ``port_factory.get_port()`` returns an ``EnginePortAdapter`` wrapping the
    default ``TTSEngine``; we infer the engine kind from the wrapped object's
    class name because the routing ``engine_choice`` field is only advisory
    and may disagree with the production port in degraded local-only setups.
    """
    inner = getattr(port, "engine", None)
    if inner is None:
        return "kokoro"  # safe default; matches the production Kokoro link
    cls = inner.__class__.__name__.lower()
    for tag in ("kokoro", "edge", "voxcpm2"):
        if tag in cls:
            return tag
    # Unknown engine class — default to kokoro normalization.
    return "kokoro"


@dataclass
class AudioSegment:
    """Represents a synthesized audio segment."""

    segment_id: str
    file_path: str
    duration_ms: int
    engine: str
    voice_id: str
    text_hash: str  # For incremental regeneration detection

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "segment_id": self.segment_id,
            "file_path": self.file_path,
            "duration_ms": self.duration_ms,
            "engine": self.engine,
            "voice_id": self.voice_id,
            "text_hash": self.text_hash,
        }


class SynthesizePipeline:
    """Pipeline for audio synthesis with incremental regeneration via RemoteTTSPort.

    This pipeline submits synthesis tasks to the Hermes scheduling layer via
    the RemoteTTSPort abstraction and polls for completion. It does NOT contain
    any engine-specific logic - all engines are hidden behind the Port.
    """

    # Default crossfade duration in milliseconds between segments
    DEFAULT_CROSSFADE_MS = 50

    # Configurable crossfade duration (can be overridden via CROSSFADE_MS env var)
    @classmethod
    def get_crossfade_ms(cls) -> int:
        """Get crossfade duration from environment or default."""
        import os

        try:
            return int(os.environ.get("CROSSFADE_MS", cls.DEFAULT_CROSSFADE_MS))
        except ValueError:
            return cls.DEFAULT_CROSSFADE_MS

    def __init__(
        self,
        router: Optional[LLMRouter] = None,
        output_dir: str = "./output",
        mock_mode: Optional[bool] = None,
        hardware_profile: Optional[HardwareProfile] = None,
        port: Optional[RemoteTTSPort] = None,
        crossfade_ms: Optional[int] = None,
    ):
        """Initialize the synthesis pipeline.

        Args:
            router: Optional LLM router for routing decisions (not yet used for TTS).
            output_dir: Directory for output audio files and metadata.
            mock_mode: If True, uses mock synthesis. Defaults to MOCK_LLM env var.
            hardware_profile: Hardware profile for engine selection.
            port: RemoteTTSPort instance. If None, uses global default via get_port().
            crossfade_ms: Crossfade duration in ms for segment stitching.
                          Defaults to CROSSFADE_MS env var or DEFAULT_CROSSFADE_MS.
        """
        if mock_mode is not None:
            self.mock_mode = mock_mode
        else:
            self.mock_mode = os.environ.get("MOCK_LLM", "false").lower() == "true"

        # Create router
        if router is None:
            self.router = create_router()
        else:
            self.router = router

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Hardware profile for TTS engine selection (used by Hermes for routing)
        self.hardware_profile = hardware_profile or get_hardware_profile()

        # Voice cloning manager (for local voice cloning if needed)
        self.voice_cloning_manager = VoiceCloningManager(
            CloningConfig(
                model_path="./models/kokoro-onnx",
                output_dir=str(self.output_dir / "cloned"),
            )
        )

        # Remote TTS Port - the single abstraction for all synthesis
        # Use mock port for mock_mode, lazy initialization for real port
        self._port: Optional[RemoteTTSPort]
        self._pending_port: Optional["Coroutine[Any, Any, RemoteTTSPort]"]
        if port is not None:
            self._port = port
        elif self.mock_mode:
            # Use FakeRemoteTTSPort for testing - synchronous, no async init needed
            self._port = FakeRemoteTTSPort()
        else:
            # Lazy initialization: port will be created on first use
            self._port = None
            self._pending_port = self._create_port()

        # Crossfade duration for segment stitching
        if crossfade_ms is not None:
            self.crossfade_ms = crossfade_ms
        else:
            self.crossfade_ms = self.get_crossfade_ms()


        # Audio semantic cache for TTS segment caching
        self._audio_cache: Optional[AudioSemanticCache] = None
        self._cache_enabled = os.environ.get("AUDIO_SEMANTIC_CACHE_ENABLED", "false").lower() == "true"
        if self._cache_enabled:
            self._audio_cache = get_audio_semantic_cache()
        # Track existing segments for incremental synthesis
        self.existing_segments: dict[str, AudioSegment] = {}
        self._mock_segment_counter = 0

        logger.info(f"SynthesizePipeline initialized with mock_mode={self.mock_mode}, crossfade_ms={self.crossfade_ms}")

    async def _create_port(self) -> RemoteTTSPort:
        """Create a new port instance via DI container."""
        from ..tts.port_factory import get_port
        return await get_port()

    async def _get_port(self) -> RemoteTTSPort:
        """Lazily initialize and return the RemoteTTSPort."""
        if self._port is None:
            # Lazy initialization for real port
            if hasattr(self, "_pending_port") and self._pending_port is not None:
                self._port = await self._pending_port
                self._pending_port = None
            else:
                # Create new port via DI
                self._port = await self._create_port()
        return self._port

    def _text_hash(self, text: str) -> str:
        # Use SHA256 with usedforsecurity=False for cache key generation (non-cryptographic)
        return hashlib.sha256(text.encode(), usedforsecurity=False).hexdigest()[:12]

    def _metadata_path(self, segment_id: str) -> Path:
        """Return the sidecar metadata path for a synthesized segment."""
        return self.output_dir / f"{segment_id}.json"

    def _load_existing_segment_from_disk(self, segment_id: str, text_hash: str) -> Optional[AudioSegment]:
        """Load an existing segment from disk if its text hash matches."""
        metadata_path = self._metadata_path(segment_id)
        if not metadata_path.exists():
            return None

        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Unable to read segment metadata %s: %s", metadata_path, exc)
            return None

        if metadata.get("text_hash") != text_hash:
            return None

        file_path = metadata.get("file_path")
        if not file_path or not Path(file_path).exists():
            logger.warning("Existing segment file missing for %s, ignoring metadata", segment_id)
            return None

        return AudioSegment(
            segment_id=metadata.get("segment_id", segment_id),
            file_path=file_path,
            duration_ms=int(metadata.get("duration_ms", 0)),
            engine=metadata.get("engine", ""),
            voice_id=metadata.get("voice_id", ""),
            text_hash=metadata.get("text_hash", text_hash),
        )

    def _persist_segment_metadata(self, segment: AudioSegment) -> None:
        """Persist segment metadata so future pipeline instances can skip regeneration."""
        metadata_path = self._metadata_path(segment.segment_id)
        try:
            metadata_path.write_text(
                json.dumps(
                    {
                        "segment_id": segment.segment_id,
                        "file_path": segment.file_path,
                        "duration_ms": segment.duration_ms,
                        "engine": segment.engine,
                        "voice_id": segment.voice_id,
                        "text_hash": segment.text_hash,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Unable to persist segment metadata %s: %s", metadata_path, exc)

    def _build_payload(self, text: str, voice_id: str, prosody: dict[str, Any]) -> TTSTaskPayload:
        """Build a TTSTaskPayload from synthesis parameters."""
        # Convert prosody dict to TTSProsody
        # P2.15: 透传 seed (若 prosody_overrides 带 seed 则注入 TTSProsody.seed → backend → generate)。
        _raw_seed = prosody.get("seed")
        # 容错: 非整数 → 透传 None (避免非 int 进 generate 链路, 诚实降级)。
        seed_val = int(_raw_seed) if isinstance(_raw_seed, (int, float)) else None
        tts_prosody = TTSProsody(
            rate=float(prosody.get("rate", 1.0)),
            pitch=float(prosody.get("pitch", 0.0)),
            volume=float(prosody.get("volume", 0.0)),
            emotion=prosody.get("emotion"),
            seed=seed_val,
        )

        # Create voice anchor - the Hermes layer will resolve voice_id to actual profile
        voice_anchor = TTSVoiceAnchor(
            voice_id=voice_id,
            speaker_name=None,
            language="zh-CN",  # TODO: infer from text or prosody
        )

        return TTSTaskPayload(
            text=text,
            voice_anchor=voice_anchor,
            prosody=tts_prosody,
            metadata={
                "source": "synthesize_pipeline",
                "prosody_raw": prosody,
            },
        )

    async def _synthesize_via_port(
        self,
        text: str,
        voice_id: str,
        prosody: dict[str, Any],
        output_path: Path,
        segment_id: str,
    ) -> tuple[int, str]:
        """Synthesize text to audio via RemoteTTSPort.

        Submits task to Hermes layer, polls for completion, downloads result.

        Args:
            text: Text to synthesize.
            voice_id: Voice identifier.
            prosody: Prosody parameters.
            output_path: Local path to save audio.
            segment_id: Unique segment identifier for task tracking.

        Returns:
            Tuple of (duration_ms, engine_name).

        Raises:
            RuntimeError: If synthesis fails or times out.
        """
        # Build payload
        port = await self._get_port()
        # The routing decision may have tagged ``engine_choice`` based on cost
        # preferences, but the production port is whichever engine the
        # registry defaults to (Kokoro today). Re-normalize voice_id against
        # the port's real engine so we never feed an Edge voice_id to
        # Kokoro (or vice versa). See ADR-005 / fallback-chain.
        actual_engine = _port_engine_name(port)
        voice_id = _normalize_voice_id(voice_id, actual_engine)
        payload = self._build_payload(text, voice_id, prosody)

        # Check audio semantic cache first (Tier 1: exact, Tier 2: semantic)
        if self._cache_enabled and self._audio_cache:
            cached = self._audio_cache.get(text, voice_id, prosody)
            if cached:
                cached_audio_path, cached_duration_ms, cache_meta = cached
                logger.info(
                    f"Audio cache hit for segment {segment_id}: type={cache_meta.get('cache_type')}, "
                    f"similarity={cache_meta.get('similarity', 1.0):.3f}, duration={cached_duration_ms}ms"
                )
                # Copy cached audio to output path
                import shutil
                shutil.copy2(cached_audio_path, output_path)
                engine = cache_meta.get("engine", "cache")
                return cached_duration_ms, engine

        # Submit to Hermes layer
        task_id = f"{segment_id}-{int(time.time() * 1000)}"
        logger.info(
            "Submitting synthesis task %s for segment %s (engine=%s, voice=%s)",
            task_id,
            segment_id,
            actual_engine,
            voice_id,
        )
        accepted = await port.submit(task_id, payload)
        if not accepted:
            raise RuntimeError(f"Task {task_id} rejected by scheduling layer (duplicate or unavailable)")

        # Poll for completion
        poll_interval = 0.5  # seconds
        max_wait = 300  # 5 minutes max
        waited = 0.0
        result: Optional[TTSTaskResult] = None

        while waited < max_wait:
            status = await port.get_status(task_id)
            logger.debug(f"Task {task_id} status: {status.status.value}, progress: {status.progress}")

            if status.status == TTSStatus.DONE:
                # Get full result
                result = await port.get_result(task_id)
                break
            elif status.status == TTSStatus.FAILED:
                error_msg = status.error_message or "Unknown error"
                raise RuntimeError(f"Synthesis failed: {error_msg}")
            elif status.status in (TTSStatus.PENDING, TTSStatus.RUNNING):
                await asyncio.sleep(poll_interval)
                waited += poll_interval
                continue
            else:
                raise RuntimeError(f"Unknown task status: {status.status}")

        # If the poll loop exited without a DONE break (timeout), result is
        # still None — there is no synthesis to download.
        if result is None:
            raise RuntimeError(f"Synthesis task {task_id} timed out after {max_wait}s")

        # Download audio from R2/path to local output_path
        if result.audio_path:
            # If audio_path is an R2 key, we need to download it
            # For now, assume it's a local path or we have a download helper
            await self._download_audio(result.audio_path, output_path)
        else:
            raise RuntimeError("Synthesis completed but no audio path returned")

        # Get duration
        duration_ms = result.duration_ms or get_duration_sync(output_path)

        # Store in audio semantic cache for future reuse
        if self._cache_enabled and self._audio_cache:
            try:
                self._audio_cache.put(
                    text=text,
                    voice_id=voice_id,
                    prosody=prosody,
                    audio_path=str(output_path),
                    duration_ms=duration_ms,
                    metadata={"engine": engine, "segment_id": segment_id},
                )
            except Exception as e:
                logger.warning(f"Failed to store audio in semantic cache: {e}")

        # Engine name from metadata or default. ``TTSTaskResult`` itself does
        # not carry metadata, but some port implementations (e.g. the Edge
        # port) attach an extra ``metadata`` dict to the returned result; fall
        # back to "hermes" when it is absent or None.
        result_meta: Optional[dict[str, Any]] = getattr(result, "metadata", None)
        engine = result_meta.get("engine", "hermes") if result_meta else "hermes"

        logger.info(f"Segment {segment_id} synthesized via {engine}: {duration_ms}ms")
        return duration_ms, engine

    async def _download_audio(self, source_path: str, dest_path: Path) -> None:
        """Download audio from source (R2/local) to destination.

        For the fake port, source_path might be a local path.
        For the real Hermes port, it would be an R2 object key.
        """
        source = Path(source_path)
        if source.exists():
            # Local file - copy
            import shutil

            shutil.copy2(source, dest_path)
        else:
            # Remote path (R2 key) - would need R2 client
            # For fake port, it generates local files
            # TODO: Implement R2 download for production Hermes port
            logger.warning(f"Remote audio path not implemented: {source_path}")
            # In testing with fake port, the fake port creates local files
            # This is a placeholder for real implementation
            raise NotImplementedError(f"Remote audio download from {source_path} not implemented")

    async def _synthesize_streaming(
        self,
        text: str,
        voice_id: str,
        prosody: dict[str, Any],
        output_path: Path,
        segment_id: str,
        project_id: int,
        chapter_index: int,
        paragraph_index: int,
        progress_callback: callable = None,
    ) -> tuple[int, str]:
        """Synthesize text to audio via Streaming TTS engine with WebSocket progress.

        This method provides first-byte latency < 500ms by streaming audio chunks
        in real-time via WebSocket to the frontend.

        Args:
            text: Text to synthesize.
            voice_id: Voice identifier.
            prosody: Prosody parameters.
            output_path: Local path to save complete audio.
            segment_id: Unique segment identifier for task tracking.
            project_id: Project ID for WebSocket events.
            chapter_index: Chapter index for progress.
            paragraph_index: Paragraph index for progress.
            progress_callback: Optional callback for chunk-level progress.

        Returns:
            Tuple of (duration_ms, engine_name).

        Raises:
            RuntimeError: If synthesis fails or times out.
        """
        # Determine streaming engine from environment or config
        streaming_engine = os.getenv("STREAMING_TTS_ENGINE", "cosyvoice_stream")
        streaming_host = os.getenv("STREAMING_TTS_HOST", "localhost")
        streaming_port = int(os.getenv("STREAMING_TTS_PORT", "5000"))

        # Check if streaming is enabled
        if os.getenv("ENABLE_STREAMING_TTS", "false").lower() != "true":
            logger.info("Streaming TTS not enabled, falling back to port synthesis")
            return await self._synthesize_via_port(text, voice_id, prosody, output_path, segment_id)

        # Build streaming config
        config = StreamingTTSConfig(
            engine=streaming_engine,
            host=streaming_host,
            port=streaming_port,
            sample_rate=24000,
            chunk_size_ms=100,
            voice_id=voice_id,
            speed=prosody.get("rate", 1.0),
        )

        # Create streaming engine
        try:
            streaming_engine_instance = create_streaming_tts_engine(config)
        except Exception as e:
            logger.warning(f"Failed to create streaming engine: {e}, falling back to port")
            return await self._synthesize_via_port(text, voice_id, prosody, output_path, segment_id)

        # Stream synthesis with WebSocket progress
        import io
        audio_buffer = io.BytesIO()
        total_duration_ms = 0
        first_chunk = True
        first_byte_latency_ms = 0
        start_time = time.time()

        try:
            # Use async streaming for real-time WebSocket updates
            chunk_index = 0
            async for chunk in streaming_engine_instance.synthesize_stream_async(
                text, voice_id=voice_id, **prosody
            ):
                # Write chunk to buffer
                audio_buffer.write(chunk.audio_data)

                # Calculate latency for first chunk
                if first_chunk:
                    first_byte_latency_ms = int((time.time() - start_time) * 1000)
                    first_chunk = False
                    logger.info(f"Streaming TTS first-byte latency: {first_byte_latency_ms}ms for {segment_id}")

                    # Emit first-byte event
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(emit_pipeline_event(
                            project_id=project_id,
                            event_type="first_byte",
                            chapter_id=chapter_index,
                            paragraph_index=paragraph_index,
                            data={
                                "segment_id": segment_id,
                                "latency_ms": first_byte_latency_ms,
                                "engine": streaming_engine,
                            },
                        ))
                    except RuntimeError:
                        pass

                # Emit chunk progress via WebSocket
                if progress_callback:
                    try:
                        progress_callback(chunk_index, chunk.is_final, chunk.latency_ms)
                    except Exception as e:
                        logger.debug(f"Progress callback error: {e}")

                # Emit WebSocket event for real-time progress
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(emit_pipeline_event(
                        project_id=project_id,
                        event_type="stream_chunk",
                        chapter_id=chapter_index,
                        paragraph_index=paragraph_index,
                        progress=0.5 if not chunk.is_final else 1.0,
                        data={
                            "segment_id": segment_id,
                            "chunk_index": chunk_index,
                            "is_final": chunk.is_final,
                            "latency_ms": chunk.latency_ms,
                        },
                    ))
                except RuntimeError:
                    pass

                chunk_index += 1

                if chunk.is_final:
                    break

            # Save complete audio to file
            audio_data = audio_buffer.getvalue()
            output_path.write_bytes(audio_data)

            # Get duration
            duration_ms = get_duration_sync(output_path)

            logger.info(
                f"Streaming synthesis complete: {segment_id} via {streaming_engine}, "
                f"{duration_ms}ms, first-byte={first_byte_latency_ms}ms, chunks={chunk_index}"
            )

            return duration_ms, streaming_engine

        except Exception as e:
            logger.error(f"Streaming synthesis failed for {segment_id}: {e}")
            # Fallback to port synthesis
            logger.info("Falling back to port synthesis")
            return await self._synthesize_via_port(text, voice_id, prosody, output_path, segment_id)

    @trace_function(name="pipeline.synthesize.run", stage="synthesize")  # type: ignore[untyped-decorator]  # trace_function (monitoring/) returns Callable[...,Any] w/o preserving the wrapped signature; fix lives outside this file's scope.
    async def run(self, inputs: List[TtsRoutingInput]) -> List[AudioSegment]:
        """Synthesize multiple paragraphs incrementally with quality gate.

        For each input, checks if regeneration is needed (text changed),
        submits synthesis via Port, runs quality checks with auto-retry (max 2),
        and returns audio segments. Produces quality_report.json.

        Args:
            inputs: List of TtsRoutingInput with text, voice, and prosody.

        Returns:
            List of AudioSegment with file paths and metadata.
        """
        from ..monitoring import record_stage_performance

        # P2.12: 发音字典一次性加载 (项目级覆盖全局); 注音替换无条目时原样透传 (向后兼容)。
        # 字典加载失败 → 降级 warn 且 registry 为空 → apply 等价原样透传, 主路径不崩。
        from ..tts.pronunciation_dict import apply_pronunciation_dict, load_pronunciation_dict

        pronunciation_registry = load_pronunciation_dict()

        logger.info(f"Synthesizing {len(inputs)} paragraphs via Port")

        segments: list[AudioSegment] = []
        segment_files: list[Path] = []
        segment_ids: list[str] = []

        for i, inp in enumerate(inputs):
            decision = self._make_routing_decision(inp)

            # P2.12: 合成前按字典对 inp.text 做注音替换 (在 hash 前, 保证 cache 键与
            # 实际合成文本幂等一致; 无条目原样透传, 不破主路径)。就地改 inp.text 局部副本安全。
            inp.text = apply_pronunciation_dict(inp.text, pronunciation_registry)

            # Check if regeneration needed (text changed)
            text_hash = self._text_hash(inp.text)
            segment_id = decision.segment_id

            # Emit stage progress for each paragraph
            if inputs:
                project_id = inputs[0].book_id
                chapter_index = inputs[0].chapter_index
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(emit_stage_progress(
                        stage="synthesize",
                        project_id=project_id,
                        chapter_index=chapter_index,
                        current=i + 1,
                        total=len(inputs),
                        message=f"Synthesizing paragraph {i + 1}/{len(inputs)}",
                    ))
                except RuntimeError:
                    pass  # Silently skip if no event loop

            if segment_id in self.existing_segments:
                existing = self.existing_segments[segment_id]
                if existing.text_hash == text_hash:
                    logger.info(f"Segment {segment_id} unchanged, skipping")
                    segments.append(existing)

                    # Emit paragraph complete for cached segment
                    if inputs:
                        project_id = inputs[0].book_id
                        chapter_index = inputs[0].chapter_index
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(emit_paragraph_complete(
                                project_id=project_id,
                                chapter_index=chapter_index,
                                paragraph_index=inp.paragraph_index,
                                total_paragraphs=len(inputs),
                            ))
                        except RuntimeError:
                            pass
                    continue

            disk_existing = self._load_existing_segment_from_disk(segment_id, text_hash)
            if disk_existing is not None:
                self.existing_segments[segment_id] = disk_existing
                logger.info(f"Segment {segment_id} loaded from disk, skipping")
                segments.append(disk_existing)

                # Emit paragraph complete for disk-cached segment
                if inputs:
                    project_id = inputs[0].book_id
                    chapter_index = inputs[0].chapter_index
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(emit_paragraph_complete(
                            project_id=project_id,
                            chapter_index=chapter_index,
                            paragraph_index=inp.paragraph_index,
                            total_paragraphs=len(inputs),
                        ))
                    except RuntimeError:
                        pass
                continue

            # Synthesize via Port
            output_path = self.output_dir / f"{segment_id}.wav"

            success = False
            duration = 0
            # ``engine`` starts as the routing-decision Literal but is later
            # overwritten with the real engine name (a plain ``str`` from
            # ``_synthesize_via_port``, which may even report "hermes"), so
            # type it as ``str`` rather than the narrow Literal.
            engine: str = decision.engine_choice
            synthesis_latency_ms: float = 0.0
            cost_usd = 0.0
            tokens_in = max(1, len(inp.text) // 4)
            tokens_out = 0

            try:
                start_time = time.time()

                # Check if streaming TTS is enabled for first-byte latency optimization
                enable_streaming = os.getenv("ENABLE_STREAMING_TTS", "false").lower() == "true"
                
                if enable_streaming:
                    # Run streaming synthesis with WebSocket progress
                    duration, engine = await self._synthesize_streaming(
                        inp.text,
                        decision.voice_id,
                        decision.prosody_overrides or {},
                        output_path,
                        segment_id,
                        project_id=inputs[0].book_id if inputs else 0,
                        chapter_index=inputs[0].chapter_index if inputs else 0,
                        paragraph_index=inp.paragraph_index,
                    )
                else:
                    # Run async synthesis via port (legacy path)
                    duration, engine = await self._synthesize_via_port(
                        inp.text,
                        decision.voice_id,
                        decision.prosody_overrides or {},
                        output_path,
                        segment_id,
                    )

                synthesis_latency_ms = (time.time() - start_time) * 1000
                success = True

                # P2.13: 首段注册锚 — 角色在本章首次成功合成, 用本段真实音频作该章
                # 参考音频 (VoiceAnchor.register_character 拷贝到 anchor 目录持久化)。
                # §35 profile-lock 依赖此锚: 同章后续段锁 voice_id; §34 漂移门用它做基准
                # vs 生成音频比对. 键 = chapter_index 顺序号 (与 quality_check 同源, 非
                # DB chapter_id). 首段即锚保证每章起点一致, 跨段漂移有基准.
                if success:
                    try:
                        from .voice_anchor import get_voice_anchor_manager

                        va = get_voice_anchor_manager()
                        char_name = inp.paragraph_annotation.speaker_canonical_name
                        if (
                            va.config.enabled
                            and char_name
                            and not va.has_anchor(char_name, chapter_index=inp.chapter_index)
                        ):
                            output_path_obj = Path(output_path)
                            if output_path_obj.exists():
                                va.register_character(
                                    character_name=char_name,
                                    voice_id=decision.voice_id,
                                    reference_audio_path=str(output_path_obj),
                                    chapter_index=inp.chapter_index,
                                    paragraph_index=inp.paragraph_index,
                                )
                    except Exception as e:
                        logger.debug(f"P2.13 voice anchor register failed for {segment_id}: {e}")

                # Observe TTS synthesis for Langfuse tracing
                if is_enabled():
                    observe_tts_synthesis(
                        voice_id=decision.voice_id,
                        text_length=len(inp.text),
                        audio_duration_ms=duration,
                        latency_ms=synthesis_latency_ms,
                        backend=engine,
                    )

                # Estimate token usage and cost
                tokens_in = max(1, len(inp.text) // 4)
                tokens_out = max(1, duration // 100)  # Rough approximation

                # Cost estimation
                if engine in ("kokoro", "hermes"):
                    cost_usd = 0.0  # Local/free
                elif engine == "edge":
                    cost_usd = (len(inp.text) / 1_000_000) * 4.0
                elif engine == "azure":
                    cost_usd = 0.0  # Free tier
                elif engine == "gcp":
                    cost_usd = 0.0  # Free tier
                else:
                    cost_usd = 0.01  # Placeholder

            except Exception as e:
                logger.error(f"Synthesis failed for segment {segment_id}: {e}")
                synthesis_latency_ms = (time.time() - start_time) * 1000 if "start_time" in locals() else 0
                success = False
                if engine == "kokoro":
                    cost_usd = 0.0
                elif engine == "edge":
                    cost_usd = (len(inp.text) / 1_000_000) * 4.0
                else:
                    cost_usd = 0.01
                raise  # Re-raise to maintain existing error handling
            finally:
                # Record performance metric (both success and failure)
                record_stage_performance(
                    stage=f"synthesize_{engine}",
                    latency_ms=synthesis_latency_ms,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    success=success,
                    quality_score=None,  # Will be filled by quality_check stage
                    provider=engine,
                    model=decision.voice_id,
                    schema_compliance=None,
                )

                # Record TTS telemetry
                record_tts_segment(
                    duration_ms=duration if success else 0,
                    latency_ms=synthesis_latency_ms,
                    provider=engine,
                    cost_usd=cost_usd,
                    success=success,
                )

            segment = AudioSegment(
                segment_id=segment_id,
                file_path=str(output_path),
                duration_ms=duration,
                engine=engine,
                voice_id=decision.voice_id,
                text_hash=text_hash,
            )

            self.existing_segments[segment_id] = segment
            self._persist_segment_metadata(segment)
            segments.append(segment)
            segment_files.append(output_path)
            segment_ids.append(segment_id)

            # Emit paragraph complete for synthesized segment
            if inputs:
                project_id = inputs[0].book_id
                chapter_index = inputs[0].chapter_index
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(emit_paragraph_complete(
                        project_id=project_id,
                        chapter_index=chapter_index,
                        paragraph_index=inp.paragraph_index,
                        total_paragraphs=len(inputs),
                    ))
                except RuntimeError:
                    pass

        # Quality Gate: Check all segments with auto-retry (max 2 retries)
        if segment_files:
            logger.info(f"Running quality checks on {len(segment_files)} segments...")

            # Get project info for report
            project_id = inputs[0].book_id if inputs else "unknown"
            chapter_index = inputs[0].chapter_index if inputs else 0

            # Define retry callback for quality failures
            async def retry_callback(seg_id: str, attempt: int) -> Optional[Path]:
                """Re-synthesize a failed segment."""
                # Find the original input for this segment
                seg_input = next((inp for inp in inputs if f"_p{inp.paragraph_index}" in seg_id), None)
                if seg_input is None:
                    logger.warning(f"No input found for segment {seg_id}")
                    return None

                decision = self._make_routing_decision(seg_input)
                retry_output = self.output_dir / f"{seg_id}_retry{attempt}.wav"

                try:
                    logger.info(f"Retrying synthesis for {seg_id} (attempt {attempt})")
                    retry_duration, retry_engine = await self._synthesize_via_port(
                            seg_input.text,
                            decision.voice_id,
                            decision.prosody_overrides or {},
                            retry_output,
                            f"{seg_id}_retry{attempt}",
                        )
                    # Record retry telemetry
                    record_tts_retry(fallback_from=decision.engine_choice)

                    # Update segment with new file
                    for seg in segments:
                        if seg.segment_id == seg_id:
                            seg.file_path = str(retry_output)
                            seg.duration_ms = retry_duration
                            seg.engine = retry_engine
                            self._persist_segment_metadata(seg)
                            break
                    return retry_output
                except Exception as e:
                    logger.error(f"Retry synthesis failed for {seg_id}: {e}")
                    return None

            # P2.13: 透传 segment_id -> speaker_canonical_name 给质量层, 驱动
            # VoiceAnchor 参考音频注入 + §36 嵌入缓存 + 漂移门 (单层映射, 与
            # check_all_segments 的 speaker_map 同源, 键用 inp 决定的 segment_id 公式)。
            speaker_map = {
                f"{inp.book_id}_ch{inp.chapter_index}_p{inp.paragraph_index}": inp.paragraph_annotation.speaker_canonical_name
                for inp in inputs
            }

            # Run quality checks with auto-retry
            quality_report: QualityReport = await check_all_segments(
                segment_files=segment_files,
                segment_ids=segment_ids,
                project_id=project_id,
                chapter_index=chapter_index,
                max_retries=2,
                retry_callback=retry_callback,
                speaker_map=speaker_map,
            )

            # Save quality report
            report_path = self.output_dir / "quality_report.json"
            save_quality_report(quality_report, report_path)

            # Record quality check telemetry
            for result in quality_report.segment_results:
                record_tts_quality_check(result.passed)

            # Log quality results
            logger.info(
                f"Quality check complete: {quality_report.passed_segments}/{quality_report.total_segments} passed, "
                f"overall={'PASSED' if quality_report.overall_passed else 'FAILED'}"
            )
            for result in quality_report.segment_results:
                if getattr(result, "needs_manual_review", False):
                    # 三振出局：已重合 max_retries 次仍不过 → 人工复核，不再无限重试（P0.2）
                    logger.warning(
                        f"  Segment {result.segment_id} needs MANUAL REVIEW "
                        f"(3-strike exhausted, issues: {', '.join(result.issues)})"
                    )
                elif not result.passed:
                    logger.warning(f"  Segment {result.segment_id} FAILED: {', '.join(result.issues)}")
                else:
                    logger.debug(f"  Segment {result.segment_id} passed")

        # Stitch chapter-level audio (optional)
        if len(segments) > 1:
            chapter_output = self.output_dir / f"{inputs[0].book_id}_ch{inputs[0].chapter_index}.mp3"
            await self._crossfade_stitch(segments, chapter_output)

        # Emit stage exit for synthesize
        if inputs:
            project_id = inputs[0].book_id
            chapter_index = inputs[0].chapter_index
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(emit_stage_exit(
                    stage="synthesize",
                    project_id=project_id,
                    chapter_index=chapter_index,
                    success=True,
                ))
            except RuntimeError:
                pass

        return segments

    async def _crossfade_stitch(self, segments: List[AudioSegment], output_path: Path) -> int:
        """Stitch segments with crossfade using ffmpeg filter_complex. Returns total duration_ms."""

        if not segments:
            logger.warning("No segments to stitch")
            return 0

        # Filter valid segment files
        valid_segments = [s for s in segments if Path(s.file_path).exists()]
        if not valid_segments:
            logger.warning("No valid segment files found")
            return 0

        if len(valid_segments) == 1:
            # Single segment, just copy
            import shutil

            shutil.copy2(valid_segments[0].file_path, output_path)
            return valid_segments[0].duration_ms

        try:
            # Build ffmpeg filter_complex for crossfade stitching
            crossfade_ms = self.crossfade_ms

            # Build input arguments
            input_args = []
            for seg in valid_segments:
                input_args.extend(["-i", str(seg.file_path)])

            # Build filter complex: chain acrossfade filters
            filter_parts = []
            crossfade_sec = crossfade_ms / 1000.0

            for i in range(len(valid_segments) - 1):
                if i == 0:
                    filter_parts.append(f"[0:a][1:a]acrossfade=d={crossfade_sec}:c1=tri:c2=tri[a01]")
                else:
                    filter_parts.append(f"[a{0}{i}][{i+1}:a]acrossfade=d={crossfade_sec}:c1=tri:c2=tri[a{0}{i+1}]")

            filter_complex = ";".join(filter_parts)
            output_label = f"[a{0}{len(valid_segments)-1}]"

            # Build ffmpeg command
            cmd = (
                [
                    "ffmpeg",
                    "-y",
                ]
                + input_args
                + [
                    "-filter_complex",
                    filter_complex,
                    "-map",
                    output_label,
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    "128k",
                    str(output_path),
                ]
            )

            # Validate command args for security
            cmd = safe_subprocess_args(cmd)

            logger.info(f"Crossfade stitching {len(valid_segments)} segments with {crossfade_ms}ms crossfade")
            # Run under global semaphore with timeout
            result = await run_ffmpeg(cmd, timeout=120)

            if result.returncode != 0:
                stderr_text = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
                logger.error(f"ffmpeg crossfade failed: {stderr_text}")
                # Fallback: simple concat without crossfade
                return await self._simple_concat(valid_segments, output_path)

            # Get duration of output using ffprobe
            duration = get_duration_sync(output_path)
            logger.info(
                f"Stitched {len(valid_segments)} segments into {output_path.name}, "
                f"total {duration}ms, crossfade={crossfade_ms}ms"
            )

            # Record stitching performance
            if is_enabled():
                from ..monitoring.langfuse_client import trace

                with trace(
                    "pipeline.synthesize.crossfade_stitch",
                    metadata={
                        "stage": "synthesize_stitch",
                        "segment_count": len(valid_segments),
                        "crossfade_ms": crossfade_ms,
                        "output_duration_ms": duration,
                    },
                ):
                    pass  # Context manager handles the trace

            return duration

        except FileNotFoundError:
            logger.error("ffmpeg not found for crossfade stitching")
            return await self._simple_concat(valid_segments, output_path)
        except Exception as e:
            logger.error(f"Crossfade stitching failed: {e}")
            return await self._simple_concat(valid_segments, output_path)

    async def _simple_concat(self, segments: List[AudioSegment], output_path: Path) -> int:
        """Simple concatenation without crossfade as fallback."""
        try:
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                concat_list = Path(tmpdir) / "concat.txt"
                with open(concat_list, "w") as f:
                    for seg in segments:
                        f.write(f"file '{Path(seg.file_path).absolute()}'\n")

                cmd = [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_list),
                    "-c",
                    "copy",
                    str(output_path),
                ]

                # Validate command args for security
                cmd = safe_subprocess_args(cmd)

                # Run under global semaphore with timeout
                result = await run_ffmpeg(cmd, timeout=60)
                result.check_returncode()

            duration = get_duration_sync(output_path)
            logger.info(f"Simple concat {len(segments)} segments into {output_path.name}, total {duration}ms")
            return duration
        except Exception as e:
            logger.error(f"Simple concat failed: {e}")
            return sum(s.duration_ms for s in segments)

    async def crossfade_replace_segment(
        self,
        chapter_audio_path: Path,
        segment_index: int,
        new_segment_path: Path,
        output_path: Path,
        segment_boundaries_ms: List[tuple[int, int]],
    ) -> int:
        """
        Replace a single segment in chapter audio with crossfade at boundaries.

        Args:
            chapter_audio_path: Path to full chapter audio file
            segment_index: Index of segment to replace (0-based)
            new_segment_path: Path to new segment audio
            output_path: Output path for modified chapter audio
            segment_boundaries_ms: List of (start_ms, end_ms) for each segment in chapter

        Returns:
            Total duration of output in ms
        """

        crossfade_ms = self.crossfade_ms

        if not chapter_audio_path.exists():
            logger.warning(f"Chapter audio not found: {chapter_audio_path}")
            # Just copy new segment
            import shutil

            shutil.copy2(new_segment_path, output_path)
            return get_duration_sync(new_segment_path)

        if segment_index >= len(segment_boundaries_ms):
            logger.warning(f"Segment index {segment_index} out of bounds")
            import shutil

            shutil.copy2(chapter_audio_path, output_path)
            return get_duration_sync(chapter_audio_path)

        start_ms, end_ms = segment_boundaries_ms[segment_index]

        # Build ffmpeg filter complex for replacement with crossfade
        # We need to:
        # 1. Extract pre-replacement part (0 to start_ms - crossfade_ms/2)
        # 2. Crossfade with new segment
        # 3. Extract post-replacement part (end_ms + crossfade_ms/2 to end)

        half_crossfade = crossfade_ms // 2
        pre_end = max(0, start_ms - half_crossfade)
        post_start = end_ms + half_crossfade

        # Get total duration
        total_duration = get_duration_sync(chapter_audio_path)
        if total_duration <= post_start:
            post_start = total_duration

        try:
            input_args = [
                "-i",
                str(chapter_audio_path),
                "-i",
                str(new_segment_path),
            ]

            filter_parts = []

            # Extract pre part
            if pre_end > 0:
                filter_parts.append(f"[0:a]atrim=0:{pre_end/1000.0},asetpts=PTS-STARTPTS[pre]")
            else:
                filter_parts.append("[0:a]atrim=0:0,asetpts=PTS-STARTPTS[pre]")

            # Extract post part
            if post_start < total_duration:
                filter_parts.append(
                    f"[0:a]atrim={post_start/1000.0}:{total_duration/1000.0},asetpts=PTS-STARTPTS[post]"
                )
            else:
                filter_parts.append("[0:a]atrim=0:0,asetpts=PTS-STARTPTS[post]")

            # Crossfade pre with new segment
            crossfade_sec = half_crossfade / 1000.0
            filter_parts.append(f"[pre][1:a]acrossfade=d={crossfade_sec}:c1=tri:c2=tri[pre_new]")

            # Crossfade new segment with post
            if post_start < total_duration:
                filter_parts.append(f"[1:a][post]acrossfade=d={crossfade_sec}:c1=tri:c2=tri[new_post]")
                filter_parts.append("[pre_new][new_post]concat=n=2:v=0:a=1[out]")
            else:
                filter_parts.append("[pre_new]anull[out]")

            filter_complex = ";".join(filter_parts)

            cmd = (
                [
                    "ffmpeg",
                    "-y",
                ]
                + input_args
                + [
                    "-filter_complex",
                    filter_complex,
                    "-map",
                    "[out]",
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    "128k",
                    str(output_path),
                ]
            )

            # Validate command args for security
            cmd = safe_subprocess_args(cmd)

            logger.info(
                f"Crossfade replacing segment {segment_index} in {chapter_audio_path.name} with {crossfade_ms}ms crossfade"
            )
            result = await run_ffmpeg(cmd, timeout=120)
            result.check_returncode()

            duration = get_duration_sync(output_path)
            logger.info(f"Crossfade replace complete: {output_path.name}, total {duration}ms")
            return duration

        except Exception as e:
            logger.error(f"Crossfade replace failed: {e}")
            return await self._simple_replace_segment(
                chapter_audio_path, segment_index, new_segment_path, output_path, segment_boundaries_ms
            )

    async def _simple_replace_segment(
        self,
        chapter_audio_path: Path,
        segment_index: int,
        new_segment_path: Path,
        output_path: Path,
        segment_boundaries_ms: List[tuple[int, int]],
    ) -> int:
        """Simple segment replacement without crossfade as fallback."""
        try:
            start_ms, end_ms = segment_boundaries_ms[segment_index]
            total_duration = get_duration_sync(chapter_audio_path)

            # Build filter: pre + new + post
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                pre_path: Optional[Path] = Path(tmpdir) / "pre.mp3"
                post_path: Optional[Path] = Path(tmpdir) / "post.mp3"

                # Extract pre
                if start_ms > 0:
                    cmd_pre = [
                        "ffmpeg",
                        "-y",
                        "-i",
                        str(chapter_audio_path),
                        "-ss",
                        "0",
                        "-to",
                        f"{start_ms/1000.0}",
                        "-c",
                        "copy",
                        str(pre_path),
                    ]
                    cmd_pre = safe_subprocess_args(cmd_pre)
                    result = await run_ffmpeg(cmd_pre, timeout=60)
                    result.check_returncode()
                else:
                    pre_path = None

                # Extract post
                if end_ms < total_duration:
                    cmd_post = [
                        "ffmpeg",
                        "-y",
                        "-i",
                        str(chapter_audio_path),
                        "-ss",
                        f"{end_ms/1000.0}",
                        "-c",
                        "copy",
                        str(post_path),
                    ]
                    cmd_post = safe_subprocess_args(cmd_post)
                    result = await run_ffmpeg(cmd_post, timeout=60)
                    result.check_returncode()
                else:
                    post_path = None

                # Concat
                concat_list = Path(tmpdir) / "concat.txt"
                with open(concat_list, "w") as f:
                    if pre_path and pre_path.exists():
                        f.write(f"file '{pre_path.absolute()}'\n")
                    f.write(f"file '{new_segment_path.absolute()}'\n")
                    if post_path and post_path.exists():
                        f.write(f"file '{post_path.absolute()}'\n")

                cmd_concat = [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_list),
                    "-c",
                    "copy",
                    str(output_path),
                ]
                cmd_concat = safe_subprocess_args(cmd_concat)
                result = await run_ffmpeg(cmd_concat, timeout=60)
                result.check_returncode()

            duration = get_duration_sync(output_path)
            return duration
        except Exception as e:
            logger.error(f"Simple replace failed: {e}")
            import shutil

            shutil.copy2(chapter_audio_path, output_path)
            return get_duration_sync(chapter_audio_path)

    def _make_routing_decision(self, inp: TtsRoutingInput) -> TtsRoutingDecision:
        """Make TTS routing decision (simplified for now).

        In the future, this would use the LLM router for intelligent routing.
        """
        import os

        from ..schemas import TtsRoutingDecision

        char = next(
            (c for c in inp.character_voice_map if c.canonical_name == inp.paragraph_annotation.speaker_canonical_name),
            None,
        )
        suggested = char.suggested_voice_id if char else None
        voice_id: str = suggested or "default"

        # Respect ENABLE_LOCAL_TTS environment variable for engine selection
        enable_local_tts = os.environ.get("ENABLE_LOCAL_TTS", "true").lower() == "true"

        engine_choice: EngineChoice
        fallback_engine: EngineChoice
        if enable_local_tts:
            # Prefer local engine (Kokoro) when enabled
            engine_choice = "kokoro"
            fallback_engine = "edge"
            mock_info = "Local TTS enabled"
        else:
            # Prefer cloud engine (Edge-TTS) when local disabled
            engine_choice = "edge"
            fallback_engine = "kokoro"
            mock_info = "Local TTS disabled - using cloud"

        # Override with prefer_local if explicitly set
        if inp.prefer_local is not None:
            if inp.prefer_local:
                engine_choice = "kokoro"
                fallback_engine = "edge"
            else:
                engine_choice = "edge"
                fallback_engine = "kokoro"
            mock_info += f" (prefer_local={inp.prefer_local})"

        reasoning = f"Auto routing: {engine_choice} preferred, {fallback_engine} fallback ({mock_info})"
        # Voice IDs are engine-specific. The book analyse stage writes
        # Edge-TTS voice IDs (``zh-CN-XiaoxiaoNeural`` etc.) since that is the
        # default suggested_voice_id in CharacterVoiceBinding. Kokoro voices a
        # disjoint set (``zf_xiaoxiao``/``zm_yunjian`` etc.). Without mapping,
        # Kokoro rejects the Edge voice ID and synthesize fails silently.
        # Map Edge voice IDs to Kokoro equivalents when engine_choice is
        # kokoro; pass through Edge IDs (and Kokoro IDs) to their native engine.
        #
        # P1.9 strict pass-through (red-line #1): when an explicit
        # ``character_voice_map`` binding was matched (``char is not None``) the
        # user *named* a voice, so honour an unknown ID as-is instead of
        # silently swapping it for the narrator default — the engine then owns
        # the honest accept/reject at synthesis time. When no binding matched
        # (``char is None``, voice_id == "default") keep the production-safe
        # fallback. See ``_normalize_voice_id`` docstring for the contract.
        voice_id = _normalize_voice_id(voice_id, engine_choice, strict=(char is not None))
        # P1.9 red-line #1: ``prosody_overrides`` MUST carry the emotion-derived
        # ``volume`` and the emotion tag itself, not just rate/pitch. The acoustic
        # emotion map (``config.acoustic_mapping.get_emotion_map``) already maps
        # each emotion -> (speed, volume_db, pitch_hz); the routing decision
        # pre-existed for ``rate`` (speed) and ``pitch`` (semitones, already the
        # right unit — do NOT use ``pitch_hz`` here, different unit). We add
        # ``volume`` (the emotion's ``volume_db`` as a numeric dB float, matching
        # ``TTSProsody.volume``) and ``emotion`` (the annotation's emotion tag,
        # passed through so downstream engines that support emotion can use it and
        # those that don't can ignore it).
        annotation = inp.paragraph_annotation
        emotion_tag = annotation.emotion
        emotion_acoustic = get_emotion_map().get(emotion_tag)
        volume_db = float(emotion_acoustic.volume_db) if emotion_acoustic is not None else 0.0

        # P2.13: profile-lock — 角色在本章已注册声纹锚 (首段成功合成后) 时, 锁定
        # voice_id 为首段锚的 voice_id, 防同章跨段声纹漂移. 锁是首段决定 (已过
        # _normalize_voice_id 的 strict pass-through) 的固化, 不改变 P1.9 语义——
        # 仍是 honour 该角色绑定最早选用, 而非旁路换 ID. 无锚 (首段或 VA 禁用) 时
        # 保持上面 normalize 后的 voice_id. 同时把参考音频注入 prosody (§34 漂移门
        # 用 quality_check 真主路径核对生成 vs 锚).
        ref_audio_for_prosody: Optional[str] = None
        char_name = annotation.speaker_canonical_name
        try:
            from .voice_anchor import get_voice_anchor_manager

            va = get_voice_anchor_manager()
            if va.config.enabled and char_name and va.has_anchor(char_name, chapter_index=inp.chapter_index):
                anchor = va.get_anchor(char_name, chapter_index=inp.chapter_index)
                if anchor:
                    voice_id = anchor.voice_id
                    ref_audio_for_prosody = va.get_reference_audio(char_name, chapter_index=inp.chapter_index)
        except Exception as e:
            logger.debug(f"P2.13 profile-lock resolve failed for {char_name}: {e}")

        prosody_overrides = {
            "rate": float(annotation.speech_rate) if annotation.speech_rate else 1.0,
            "pitch": (float(annotation.pitch_shift_semitones) if annotation.pitch_shift_semitones is not None else 0.0),
            # emotion-derived volume (dB); angry>0, whisper<0, neutral=0.
            "volume": volume_db,
            # pass the emotion tag through for engines that support emotion
            "emotion": emotion_tag,
        }
        # P2.13: 注入参考音频到 prosody (引擎若支持 reference_audio 则用于声纹对齐).
        if ref_audio_for_prosody:
            prosody_overrides["reference_audio"] = ref_audio_for_prosody

        return TtsRoutingDecision(
            segment_id=f"{inp.book_id}_ch{inp.chapter_index}_p{inp.paragraph_index}",
            engine_choice=engine_choice,
            voice_id=voice_id,
            prosody_overrides=prosody_overrides,
            fallback_engine=fallback_engine,
            reasoning=reasoning,
            estimated_cost_usd=0.0 if engine_choice == "kokoro" else 0.001,
            estimated_duration_ms=3000,
        )

    async def close(self) -> None:
        """Close the port and release resources."""
        if self._port:
            try:
                await self._port.close()
            except RuntimeError:
                # Event loop may be closed
                pass
            self._port = None


def synthesize_paragraphs(
    inputs: List[TtsRoutingInput],
    output_dir: str = "./output",
    mock_mode: bool = False,
    port: Optional[RemoteTTSPort] = None,
) -> List[AudioSegment]:
    """Convenience function to synthesize paragraphs."""
    pipeline = SynthesizePipeline(output_dir=output_dir, mock_mode=mock_mode, port=port)
    try:
        return cast(List[AudioSegment], pipeline.run(inputs))
    finally:
        pipeline.close()


if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(level=logging.INFO)
    logger.info("SynthesizePipeline ready")

