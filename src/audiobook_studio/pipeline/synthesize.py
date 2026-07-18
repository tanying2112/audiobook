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
from typing import List, Optional

from ..config.hardware_profile import HardwareProfile, get_hardware_profile
from ..di import get_app_container
from ..llm import LLMRouter, create_router
from ..monitoring.telemetry import record_tts_segment, record_tts_retry, record_tts_fallback, record_tts_quality_check
from ..monitoring.langfuse_client import is_enabled, observe_quality_check, observe_tts_synthesis, trace_function
from ..schemas import AudioPostProcessParams, ParagraphAnnotation, TtsRoutingDecision, TtsRoutingInput
from ..audio_quality import QualityReport, SegmentQualityResult, check_all_segments, save_quality_report
from ..tts import (
    EngineRegistry,
    SynthesisResult,
    TTSEngine,
    VoiceInfo,
    RemoteTTSPort,
    TTSTaskPayload,
    TTSTaskResult,
    TTSTaskStatus,
    TTSStatus,
    TTSVoiceAnchor,
    TTSProsody,
    get_port,
)
from ..tts.clone import CloningConfig, VoiceCloningManager
from ..utils.ffmpeg_probe import get_duration_sync
from ..audio_quality import (
    check_all_segments,
    QualityReport,
    SegmentQualityResult,
    save_quality_report,
)

logger = logging.getLogger(__name__)


@dataclass
class AudioSegment:
    """Represents a synthesized audio segment."""

    segment_id: str
    file_path: str
    duration_ms: int
    engine: str
    voice_id: str
    text_hash: str  # For incremental regeneration detection

    def to_dict(self) -> dict:
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

    def __init__(
        self,
        router: Optional[LLMRouter] = None,
        output_dir: str = "./output",
        mock_mode: Optional[bool] = None,
        hardware_profile: Optional[HardwareProfile] = None,
        port: Optional[RemoteTTSPort] = None,
    ):
        """Initialize the synthesis pipeline.

        Args:
            router: Optional LLM router for routing decisions (not yet used for TTS).
            output_dir: Directory for output audio files and metadata.
            mock_mode: If True, uses mock synthesis. Defaults to MOCK_LLM env var.
            hardware_profile: Hardware profile for engine selection.
            port: RemoteTTSPort instance. If None, uses global default via get_port().
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
        self._port = port or get_port()

        # Track existing segments for incremental synthesis
        self.existing_segments = {}
        self._mock_segment_counter = 0

        logger.info(f"SynthesizePipeline initialized with port: {type(self._port).__name__}")

    def _text_hash(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()[:12]

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

    def _build_payload(self, text: str, voice_id: str, prosody: dict) -> TTSTaskPayload:
        """Build a TTSTaskPayload from synthesis parameters."""
        # Convert prosody dict to TTSProsody
        tts_prosody = TTSProsody(
            rate=float(prosody.get("rate", 1.0)),
            pitch=float(prosody.get("pitch", 0.0)),
            volume=float(prosody.get("volume", 0.0)),
            emotion=prosody.get("emotion"),
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
        prosody: dict,
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
        payload = self._build_payload(text, voice_id, prosody)

        # Submit to Hermes layer
        task_id = f"{segment_id}-{int(time.time() * 1000)}"
        logger.info(f"Submitting synthesis task {task_id} for segment {segment_id}")

        accepted = await self._port.submit(task_id, payload)
        if not accepted:
            raise RuntimeError(f"Task {task_id} rejected by scheduling layer (duplicate or unavailable)")

        # Poll for completion
        poll_interval = 0.5  # seconds
        max_wait = 300  # 5 minutes max
        waited = 0.0

        while waited < max_wait:
            status = await self._port.get_status(task_id)
            logger.debug(f"Task {task_id} status: {status.status.value}, progress: {status.progress}")

            if status.status == TTSStatus.DONE:
                # Get full result
                result = await self._port.get_result(task_id)
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

        # Download audio from R2/path to local output_path
        if result.audio_path:
            # If audio_path is an R2 key, we need to download it
            # For now, assume it's a local path or we have a download helper
            await self._download_audio(result.audio_path, output_path)
        else:
            raise RuntimeError("Synthesis completed but no audio path returned")

        # Get duration
        duration_ms = result.duration_ms or get_duration_sync(output_path)

        # Engine name from metadata or default
        engine = result.metadata.get("engine", "hermes") if hasattr(result, "metadata") else "hermes"

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

    @trace_function(name="pipeline.synthesize.run", stage="synthesize")
    def run(self, inputs: List[TtsRoutingInput]) -> List[AudioSegment]:
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
        logger.info(f"Synthesizing {len(inputs)} paragraphs via Port")

        segments = []
        segment_files = []
        segment_ids = []

        for inp in inputs:
            decision = self._make_routing_decision(inp)

            # Check if regeneration needed (text changed)
            text_hash = self._text_hash(inp.text)
            segment_id = decision.segment_id

            if segment_id in self.existing_segments:
                existing = self.existing_segments[segment_id]
                if existing.text_hash == text_hash:
                    logger.info(f"Segment {segment_id} unchanged, skipping")
                    segments.append(existing)
                    continue

            existing = self._load_existing_segment_from_disk(segment_id, text_hash)
            if existing is not None:
                self.existing_segments[segment_id] = existing
                logger.info(f"Segment {segment_id} loaded from disk, skipping")
                segments.append(existing)
                continue

            # Synthesize via Port
            output_path = self.output_dir / f"{segment_id}.wav"

            success = False
            duration = 0
            engine = decision.engine_choice
            synthesis_latency_ms = 0
            cost_usd = 0.0
            tokens_in = max(1, len(inp.text) // 4)
            tokens_out = 0

            try:
                start_time = time.time()

                # Run async synthesis via port
                duration, engine = asyncio.run(
                    self._synthesize_via_port(
                        inp.text,
                        decision.voice_id,
                        decision.prosody_overrides or {},
                        output_path,
                        segment_id,
                    )
                )

                synthesis_latency_ms = (time.time() - start_time) * 1000
                success = True

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

        # Quality Gate: Check all segments with auto-retry (max 2 retries)
        if segment_files:
            logger.info(f"Running quality checks on {len(segment_files)} segments...")

            # Get project info for report
            project_id = inputs[0].book_id if inputs else "unknown"
            chapter_index = inputs[0].chapter_index if inputs else 0

            # Define retry callback for quality failures
            def retry_callback(seg_id: str, attempt: int) -> Optional[Path]:
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
                    retry_duration, retry_engine = asyncio.run(
                        self._synthesize_via_port(
                            seg_input.text,
                            decision.voice_id,
                            decision.prosody_overrides or {},
                            retry_output,
                            f"{seg_id}_retry{attempt}",
                        )
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

            # Run quality checks with auto-retry
            quality_report: QualityReport = check_all_segments(
                segment_files=segment_files,
                segment_ids=segment_ids,
                project_id=project_id,
                chapter_index=chapter_index,
                max_retries=2,
                retry_callback=retry_callback,
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
                if not result.passed:
                    logger.warning(f"  Segment {result.segment_id} FAILED: {', '.join(result.issues)}")
                else:
                    logger.debug(f"  Segment {result.segment_id} passed")

        # Stitch chapter-level audio (optional)
        if len(segments) > 1:
            chapter_output = self.output_dir / f"{inputs[0].book_id}_ch{inputs[0].chapter_index}.mp3"
            self._crossfade_stitch(segments, chapter_output)

        return segments

    def _crossfade_stitch(self, segments: List[AudioSegment], output_path: Path) -> int:
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
            crossfade_ms = self.DEFAULT_CROSSFADE_MS

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

            logger.info(f"Crossfade stitching {len(valid_segments)} segments with {crossfade_ms}ms crossfade")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode != 0:
                logger.error(f"ffmpeg crossfade failed: {result.stderr}")
                # Fallback: simple concat without crossfade
                return self._simple_concat(valid_segments, output_path)

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
            return self._simple_concat(valid_segments, output_path)
        except Exception as e:
            logger.error(f"Crossfade stitching failed: {e}")
            return self._simple_concat(valid_segments, output_path)

    def _simple_concat(self, segments: List[AudioSegment], output_path: Path) -> int:
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
                subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)

            duration = get_duration_sync(output_path)
            logger.info(f"Simple concat {len(segments)} segments into {output_path.name}, total {duration}ms")
            return duration
        except Exception as e:
            logger.error(f"Simple concat failed: {e}")
            return sum(s.duration_ms for s in segments)

    def _make_routing_decision(self, inp: TtsRoutingInput) -> TtsRoutingDecision:
        """Make TTS routing decision (simplified for now).

        In the future, this would use the LLM router for intelligent routing.
        """
        from ..schemas import TtsRoutingDecision
        import os

        char = next(
            (c for c in inp.character_voice_map if c.canonical_name == inp.paragraph_annotation.speaker_canonical_name),
            None,
        )
        voice_id = char.suggested_voice_id if char else "default"

        # Respect ENABLE_LOCAL_TTS environment variable for engine selection
        enable_local_tts = os.environ.get("ENABLE_LOCAL_TTS", "true").lower() == "true"

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
        return TtsRoutingDecision(
            segment_id=f"{inp.book_id}_ch{inp.chapter_index}_p{inp.paragraph_index}",
            engine_choice=engine_choice,
            voice_id=voice_id,
            prosody_overrides={
                "rate": float(inp.paragraph_annotation.speech_rate) if inp.paragraph_annotation.speech_rate else 1.0,
                "pitch": float(inp.paragraph_annotation.pitch_shift_semitones) if inp.paragraph_annotation.pitch_shift_semitones is not None else 0.0,
            },
            fallback_engine=fallback_engine,
            reasoning=reasoning,
            estimated_cost_usd=0.0 if engine_choice == "kokoro" else 0.001,
            estimated_duration_ms=3000,
        )

    def close(self) -> None:
        """Close the port and release resources."""
        if self._port:
            try:
                asyncio.run(self._port.close())
            except RuntimeError:
                # Event loop may be closed
                pass
            self._port = None


def synthesize_paragraphs(
    inputs: List[TtsRoutingInput],
    output_dir: str = "./output",
    mock_mode: bool = False,
    port: Optional[RemoteTTSPort] = None,
) -> List:
    """Convenience function to synthesize paragraphs."""
    pipeline = SynthesizePipeline(output_dir=output_dir, mock_mode=mock_mode, port=port)
    try:
        return pipeline.run(inputs)
    finally:
        pipeline.close()


if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(level=logging.INFO)
    logger.info("SynthesizePipeline ready")