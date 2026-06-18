"""Pipeline Stage 5: Synthesize - Audio synthesis orchestration.

Routes to TTS engines (Kokoro/Edge/Human Clone), performs incremental synthesis
with crossfade stitching, outputs audio segments with metadata.
"""

import hashlib
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from ..llm import LLMRouter, create_router
from ..monitoring import record_stage_performance
from ..monitoring.langfuse_client import (
    is_enabled,
    observe_quality_check,
    observe_tts_synthesis,
    trace_function,
)
from ..schemas import (
    AudioPostProcessParams,
    ParagraphAnnotation,
    TtsRoutingDecision,
    TtsRoutingInput,
)
from ..utils.ffmpeg_probe import get_duration_sync

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


class SynthesizePipeline:
    """Pipeline for audio synthesis with incremental regeneration."""

    # Default crossfade duration in milliseconds between segments
    DEFAULT_CROSSFADE_MS = 50

    def __init__(
        self,
        router=None,
        output_dir="./output",
        mock_mode=False,
    ):
        self.router = router or create_router(mock_mode=mock_mode)
        self.mock_mode = mock_mode
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Track existing segments for incremental synthesis
        self.existing_segments = {}

    # Common Edge-TTS voice mapping (short → full SSML format)
    EDGE_VOICE_MAP = {
        "zh-CN-XiaoxiaoNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)",
        "zh-CN-YunxiNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, YunxiNeural)",
        "zh-CN-YunjianNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, YunjianNeural)",
        "zh-CN-XiaoyiNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoyiNeural)",
        "zh-CN-YunyangNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, YunyangNeural)",
        "zh-CN-XiaochenNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaochenNeural)",
        "zh-CN-XiaohanNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaohanNeural)",
        "zh-CN-XiaomengNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaomengNeural)",
        "zh-CN-XiaomoNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaomoNeural)",
        "zh-CN-XiaoqiuNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoqiuNeural)",
        "zh-CN-XiaoruiNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoruiNeural)",
        "zh-CN-XiaoshuangNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoshuangNeural)",
        "en-US-AriaNeural": "Microsoft Server Speech Text to Speech Voice (en-US, AriaNeural)",
        "en-US-GuyNeural": "Microsoft Server Speech Text to Speech Voice (en-US, GuyNeural)",
        "en-US-JennyNeural": "Microsoft Server Speech Text to Speech Voice (en-US, JennyNeural)",
    }

    # Azure TTS voice mapping (neural voices)
    AZURE_VOICE_MAP = {
        "zh-CN-XiaoxiaoNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)",
        "zh-CN-YunxiNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, YunxiNeural)",
        "zh-CN-YunjianNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, YunjianNeural)",
        "zh-CN-XiaoyiNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoyiNeural)",
        "zh-CN-YunyangNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, YunyangNeural)",
        "zh-CN-XiaochenNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaochenNeural)",
        "zh-CN-XiaohanNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaohanNeural)",
        "zh-CN-XiaomengNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaomengNeural)",
        "zh-CN-XiaomoNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaomoNeural)",
        "zh-CN-XiaoqiuNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoqiuNeural)",
        "zh-CN-XiaoruiNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoruiNeural)",
        "zh-CN-XiaoshuangNeural": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoshuangNeural)",
        "en-US-AriaNeural": "Microsoft Server Speech Text to Speech Voice (en-US, AriaNeural)",
        "en-US-GuyNeural": "Microsoft Server Speech Text to Speech Voice (en-US, GuyNeural)",
        "en-US-JennyNeural": "Microsoft Server Speech Text to Speech Voice (en-US, JennyNeural)",
    }

    # GCP TTS voice mapping
    GCP_VOICE_MAP = {
        "zh-CN-Standard-A": "cmn-CN-Standard-A",
        "zh-CN-Standard-B": "cmn-CN-Standard-B",
        "zh-CN-Standard-C": "cmn-CN-Standard-C",
        "zh-CN-Standard-D": "cmn-CN-Standard-D",
        "zh-CN-Wavenet-A": "cmn-CN-Wavenet-A",
        "zh-CN-Wavenet-B": "cmn-CN-Wavenet-B",
        "zh-CN-Wavenet-C": "cmn-CN-Wavenet-C",
        "zh-CN-Wavenet-D": "cmn-CN-Wavenet-D",
        "zh-CN-Neural2-A": "cmn-CN-Neural2-A",
        "zh-CN-Neural2-B": "cmn-CN-Neural2-B",
        "zh-CN-Neural2-C": "cmn-CN-Neural2-C",
        "zh-CN-Neural2-D": "cmn-CN-Neural2-D",
        "en-US-Standard-A": "en-US-Standard-A",
        "en-US-Standard-B": "en-US-Standard-B",
        "en-US-Standard-C": "en-US-Standard-C",
        "en-US-Standard-D": "en-US-Standard-D",
        "en-US-Wavenet-A": "en-US-Wavenet-A",
        "en-US-Wavenet-B": "en-US-Wavenet-B",
        "en-US-Wavenet-C": "en-US-Wavenet-C",
        "en-US-Wavenet-D": "en-US-Wavenet-D",
        "en-US-Neural2-A": "en-US-Neural2-A",
        "en-US-Neural2-B": "en-US-Neural2-B",
        "en-US-Neural2-C": "en-US-Neural2-C",
        "en-US-Neural2-D": "en-US-Neural2-D",
    }

    def _resolve_edge_voice(self, voice_id: str) -> str:
        """Resolve a short voice ID to Edge-TTS full SSML format."""
        # Already in full format
        if voice_id.startswith("Microsoft Server Speech Text to Speech Voice"):
            return voice_id
        # Check mapping
        if voice_id in self.EDGE_VOICE_MAP:
            return self.EDGE_VOICE_MAP[voice_id]
        # Try to build dynamically: normalize short name to proper casing
        # Common pattern: zh-CN-Name → Microsoft Server Speech Text to Speech Voice (zh-CN, Name)
        if voice_id.count("-") >= 2:
            parts = voice_id.rsplit("-", 1)
            region = parts[0]
            name = parts[1].capitalize()
            mapped = f"Microsoft Server Speech Text to Speech Voice ({region}, {name})"
            logger.info(f"Resolved voice '{voice_id}' → '{mapped}'")
            return mapped
        # Last resort: return as-is and let edge-tts handle it
        logger.warning(f"Unable to resolve voice '{voice_id}', using raw value")
        return voice_id

    def _text_hash(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()[:12]

    def _metadata_path(self, segment_id: str) -> Path:
        """Return the sidecar metadata path for a synthesized segment."""
        return self.output_dir / f"{segment_id}.json"

    def _load_existing_segment_from_disk(
        self, segment_id: str, text_hash: str
    ) -> Optional[AudioSegment]:
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
            logger.warning(
                "Existing segment file missing for %s, ignoring metadata", segment_id
            )
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
            logger.warning(
                "Unable to persist segment metadata %s: %s", metadata_path, exc
            )

    def _synthesize_kokoro(
        self, text: str, voice_id: str, prosody: dict, output_path: Path
    ) -> int:
        """Synthesize using Kokoro-ONNX (local). Falls back to Edge-TTS if unavailable."""
        if self.mock_mode:
            output_path.write_bytes(b"RIFF" + b"\x00" * 1000)
            return 3000

        # kokoro-onnx is optional; fall back to edge-tts if not installed
        try:
            import kokoro  # noqa: F811

            # TODO: implement real kokoro-onnx synthesis
            logger.warning(
                "Kokoro-ONNX not fully integrated yet, falling back to Edge-TTS"
            )
            return self._synthesize_edge(text, voice_id, prosody, output_path)
        except ImportError:
            logger.info("kokoro-onnx not installed, falling back to Edge-TTS")
            return self._synthesize_edge(text, voice_id, prosody, output_path)
        except Exception as e:
            logger.error(f"Kokoro synthesis failed: {e}")
            return self._synthesize_edge(text, voice_id, prosody, output_path)

    def _synthesize_edge(
        self, text: str, voice_id: str, prosody: dict, output_path: Path
    ) -> int:
        """Synthesize using Edge-TTS (cloud). Returns duration_ms."""
        if self.mock_mode:
            output_path.write_bytes(b"RIFF" + b"\x00" * 1500)
            return 2800

        try:
            import asyncio

            import edge_tts

            async def _synthesize():
                resolved_voice = self._resolve_edge_voice(voice_id)
                communicate = edge_tts.Communicate(text, resolved_voice)
                await communicate.save(str(output_path))

            asyncio.run(_synthesize())

            # Get duration using utility
            try:
                return get_duration_sync(output_path)
            except (FileNotFoundError, ValueError) as e:
                logger.warning(
                    f"ffprobe unavailable or failed ({e}), estimating duration from text"
                )

            # Fallback: estimate duration from text length
            # Chinese: ~3 chars/sec at normal speed, English: ~10 chars/sec
            chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
            english_chars = len(text) - chinese_chars
            estimated_sec = (chinese_chars / 3.5) + (english_chars / 10)
            estimated_ms = max(500, int(estimated_sec * 1000))
            logger.info(
                f"Estimated duration from text: {estimated_ms}ms ({len(text)} chars)"
            )
            return estimated_ms
            return estimated_ms

        except ImportError:
            logger.error("edge-tts not installed. Run: pip install edge-tts")
            raise
        except Exception as e:
            logger.error(f"Edge-TTS synthesis failed: {e}")
            raise

    def _synthesize_azure(
        self, text: str, voice_id: str, prosody: dict, output_path: Path
    ) -> int:
        """Synthesize using Azure Cognitive Services TTS. Returns duration_ms."""
        if self.mock_mode:
            output_path.write_bytes(b"RIFF" + b"" * 1500)
            return 2800

        # Check for Azure credentials
        azure_key = os.getenv("AZURE_TTS_KEY") or os.getenv("AZURE_SPEECH_KEY")
        azure_region = os.getenv("AZURE_TTS_REGION") or os.getenv("AZURE_SPEECH_REGION")
        
        if not azure_key or not azure_region:
            logger.warning("Azure TTS credentials not configured (AZURE_TTS_KEY, AZURE_TTS_REGION)")
            raise RuntimeError("Azure TTS not configured")

        try:
            import azure.cognitiveservices.speech as speechsdk

            speech_config = speechsdk.SpeechConfig(subscription=azure_key, region=azure_region)
            speech_config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
            )
            
            # Resolve voice name - use the short form for Azure
            azure_voice = voice_id
            if voice_id in self.AZURE_VOICE_MAP:
                azure_voice = self.AZURE_VOICE_MAP[voice_id]
            elif voice_id.startswith("Microsoft Server Speech Text to Speech Voice"):
                # Already in full format
                pass
            else:
                # Try to convert to Azure format
                if voice_id.count("-") >= 2:
                    parts = voice_id.rsplit("-", 1)
                    region = parts[0]
                    name = parts[1].capitalize()
                    azure_voice = f"Microsoft Server Speech Text to Speech Voice ({region}, {name})"
            
            speech_config.speech_synthesis_voice_name = azure_voice

            # Apply prosody via SSML if provided
            if prosody:
                # Build SSML with prosody
                rate = prosody.get("rate", "1.0")
                pitch = prosody.get("pitch", "+0st")
                volume = prosody.get("volume", "+0%")
                ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">
                    <voice name="{azure_voice}">
                        <prosody rate="{rate}" pitch="{pitch}" volume="{volume}">{text}</prosody>
                    </voice>
                </speak>"""
            else:
                ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">
                    <voice name="{azure_voice}">{text}</voice>
                </speak>"""

            audio_config = speechsdk.audio.AudioOutputConfig(filename=str(output_path))
            synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
            
            result = synthesizer.speak_ssml_async(ssml).get()
            
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                logger.info(f"Azure TTS synthesis completed: {output_path}")
                duration = get_duration_sync(output_path)
                return duration
            elif result.reason == speechsdk.ResultReason.Canceled:
                cancellation = result.cancellation_details
                logger.error(f"Azure TTS canceled: {cancellation.reason} - {cancellation.error_details}")
                raise RuntimeError(f"Azure TTS canceled: {cancellation.error_details}")
            else:
                logger.error(f"Azure TTS failed: {result.reason}")
                raise RuntimeError(f"Azure TTS failed: {result.reason}")

        except ImportError:
            logger.error("azure-cognitiveservices-speech not installed. Run: pip install azure-cognitiveservices-speech")
            raise
        except Exception as e:
            logger.error(f"Azure TTS synthesis failed: {e}")
            raise

    def _synthesize_gcp(
        self, text: str, voice_id: str, prosody: dict, output_path: Path
    ) -> int:
        """Synthesize using Google Cloud TTS. Returns duration_ms."""
        if self.mock_mode:
            output_path.write_bytes(b"RIFF" + b"" * 1500)
            return 2800

        # Check for GCP credentials
        gcp_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if not gcp_creds or not Path(gcp_creds).exists():
            logger.warning("GCP credentials not configured (GOOGLE_APPLICATION_CREDENTIALS)")
            raise RuntimeError("GCP TTS not configured")

        try:
            from google.cloud import texttospeech

            client = texttospeech.TextToSpeechClient()

            # Resolve voice name for GCP
            gcp_voice = voice_id
            if voice_id in self.GCP_VOICE_MAP:
                gcp_voice = self.GCP_VOICE_MAP[voice_id]
            
            # Parse language code and voice name
            # Format: "cmn-CN-Neural2-A" -> language_code="cmn-CN", name="cmn-CN-Neural2-A"
            if "-" in gcp_voice and gcp_voice.startswith(("cmn-", "en-")):
                parts = gcp_voice.split("-")
                if len(parts) >= 3:
                    language_code = "-".join(parts[:2])  # e.g., "cmn-CN"
                else:
                    language_code = "cmn-CN"
            else:
                language_code = "cmn-CN"

            synthesis_input = texttospeech.SynthesisInput(text=text)

            voice = texttospeech.VoiceSelectionParams(
                language_code=language_code,
                name=gcp_voice,
            )

            # Build audio config with prosody
            audio_config_kwargs = {
                "audio_encoding": texttospeech.AudioEncoding.MP3,
                "speaking_rate": prosody.get("rate", 1.0),
                "pitch": prosody.get("pitch", 0.0),  # semitones for GCP
                "volume_gain_db": prosody.get("volume", 0.0),
            }
            audio_config = texttospeech.AudioConfig(**audio_config_kwargs)

            response = client.synthesize_speech(
                input=synthesis_input, voice=voice, audio_config=audio_config
            )

            if response.audio_content:
                output_path.write_bytes(response.audio_content)
                logger.info(f"GCP TTS synthesis completed: {output_path}")
                duration = get_duration_sync(output_path)
                return duration
            else:
                logger.error("GCP TTS returned empty audio content")
                raise RuntimeError("GCP TTS returned empty audio content")

        except ImportError:
            logger.error("google-cloud-texttospeech not installed. Run: pip install google-cloud-texttospeech")
            raise
        except Exception as e:
            logger.error(f"GCP TTS synthesis failed: {e}")
            raise

    def _crossfade_stitch(self, segments: List[AudioSegment], output_path: Path) -> int:
        """Stitch segments with crossfade using ffmpeg filter_complex. Returns total duration_ms."""
        if self.mock_mode:
            return sum(s.duration_ms for s in segments)

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

        # Trace the crossfade stitching operation
        try:
            # Build ffmpeg filter_complex for crossfade stitching
            # Use acrossfade filter for smooth crossfades between segments
            crossfade_ms = self.DEFAULT_CROSSFADE_MS

            # Build input arguments
            input_args = []
            for seg in valid_segments:
                input_args.extend(["-i", str(seg.file_path)])

            # Build filter complex: chain acrossfade filters
            # [0:a][1:a]acrossfade=d=0.05:c1=tri:c2=tri[a01];
            # [a01][2:a]acrossfade=d=0.05:c1=tri:c2=tri[a012]; ...
            filter_parts = []
            crossfade_sec = crossfade_ms / 1000.0

            for i in range(len(valid_segments) - 1):
                if i == 0:
                    filter_parts.append(
                        f"[0:a][1:a]acrossfade=d={crossfade_sec}:c1=tri:c2=tri[a{i}{i+1}]"
                    )
                else:
                    filter_parts.append(
                        f"[a{0}{i}][{i+1}:a]acrossfade=d={crossfade_sec}:c1=tri:c2=tri[a{0}{i+1}]"
                    )

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

            logger.info(
                f"Crossfade stitching {len(valid_segments)} segments with {crossfade_ms}ms crossfade"
            )
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

                with trace("pipeline.synthesize.crossfade_stitch", metadata={
                    "stage": "synthesize_stitch",
                    "segment_count": len(valid_segments),
                    "crossfade_ms": crossfade_ms,
                    "output_duration_ms": duration,
                }):
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
                subprocess.run(
                    cmd, check=True, capture_output=True, text=True, timeout=60
                )

            duration = get_duration_sync(output_path)
            logger.info(
                f"Simple concat {len(segments)} segments into {output_path.name}, total {duration}ms"
            )
            return duration
        except Exception as e:
            logger.error(f"Simple concat failed: {e}")
            return sum(s.duration_ms for s in segments)

    @trace_function(name="pipeline.synthesize.run", stage="synthesize")
    def run(self, inputs: List[TtsRoutingInput]) -> List[AudioSegment]:
        """Synthesize multiple paragraphs incrementally."""
        logger.info(f"Synthesizing {len(inputs)} paragraphs")

        segments = []

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

            # Synthesize
            output_path = self.output_dir / f"{segment_id}.mp3"

            success = False
            duration = 0
            engine = decision.engine_choice
            synthesis_latency_ms = 0
            cost_usd = 0.0
            tokens_in = max(1, len(inp.text) // 4)
            tokens_out = 0

            try:
                start_time = time.time()
                if decision.engine_choice == "kokoro":
                    duration = self._synthesize_kokoro(
                        inp.text,
                        decision.voice_id,
                        decision.prosody_overrides or {},
                        output_path,
                    )
                    engine = "kokoro"
                elif decision.engine_choice == "edge":
                    duration = self._synthesize_edge(
                        inp.text,
                        decision.voice_id,
                        decision.prosody_overrides or {},
                        output_path,
                    )
                    engine = "edge"
                elif decision.engine_choice == "azure":
                    duration = self._synthesize_azure(
                        inp.text,
                        decision.voice_id,
                        decision.prosody_overrides or {},
                        output_path,
                    )
                    engine = "azure"
                elif decision.engine_choice == "gcp":
                    duration = self._synthesize_gcp(
                        inp.text,
                        decision.voice_id,
                        decision.prosody_overrides or {},
                        output_path,
                    )
                    engine = "gcp"
                else:  # human_clone
                    # Would use voice cloning model
                    duration = self._synthesize_edge(  # fallback
                        inp.text,
                        decision.voice_id,
                        decision.prosody_overrides or {},
                        output_path,
                    )
                    engine = "human_clone"
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
                # For TTS, approximate: 1 token ≈ 4 characters
                tokens_in = max(1, len(inp.text) // 4)
                # Output tokens not really applicable for TTS, use duration as proxy
                tokens_out = max(1, duration // 100)  # Rough approximation

                # Calculate cost based on engine
                if engine == "kokoro":
                    cost_usd = 0.0  # Local, no cost
                elif engine == "edge":
                    # Azure Edge TTS pricing: ~$4 per 1 million characters
                    # Approximate cost based on input text length
                    cost_usd = (len(inp.text) / 1_000_000) * 4.0
                elif engine == "azure":
                    # Azure TTS free tier: 5M characters/month, then ~$4/M chars
                    cost_usd = 0.0  # Free tier
                elif engine == "gcp":
                    # GCP TTS free tier: 1M characters/month, then ~$4/M chars
                    cost_usd = 0.0  # Free tier
                else:  # human_clone
                    cost_usd = 0.01  # Placeholder for voice cloning

            except Exception as e:
                logger.error(f"Synthesis failed for segment {segment_id}: {e}")
                synthesis_latency_ms = (
                    (time.time() - start_time) * 1000 if "start_time" in locals() else 0
                )
                success = False
                # Still record the failed attempt
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

            segment = AudioSegment(
                segment_id=segment_id,
                file_path=str(output_path),
                duration_ms=duration,
                engine=decision.engine_choice,
                voice_id=decision.voice_id,
                text_hash=text_hash,
            )

            self.existing_segments[segment_id] = segment
            self._persist_segment_metadata(segment)
            segments.append(segment)

        # Stitch chapter-level audio (optional)
        if len(segments) > 1:
            chapter_output = (
                self.output_dir / f"{inputs[0].book_id}_ch{inputs[0].chapter_index}.mp3"
            )
            self._crossfade_stitch(segments, chapter_output)

        return segments

    def _make_routing_decision(self, inp: TtsRoutingInput) -> TtsRoutingDecision:
        if self.mock_mode:
            from ..schemas import CharacterVoiceBinding, TtsRoutingDecision

            char = next(
                (
                    c
                    for c in inp.character_voice_map
                    if c.canonical_name
                    == inp.paragraph_annotation.speaker_canonical_name
                ),
                None,
            )
            voice_id = char.suggested_voice_id if char else "default"
            return TtsRoutingDecision(
                segment_id=f"{inp.book_id}_ch{inp.chapter_index}_p{inp.paragraph_index}",
                engine_choice="kokoro",
                voice_id=voice_id,
                prosody_overrides={
                    "rate": str(inp.paragraph_annotation.speech_rate),
                    "pitch": f"{inp.paragraph_annotation.pitch_shift_semitones}st",
                },
                fallback_engine="edge",
                reasoning="Mock mode: using Kokoro local engine",
                estimated_cost_usd=0.0,
                estimated_duration_ms=3000,
            )

        # Real routing via LLM
        # Build prompt for routing decision
        # ... (would use router.call with stage="route")

        # Fallback simple logic
        from ..schemas import TtsRoutingDecision

        char = next(
            (
                c
                for c in inp.character_voice_map
                if c.canonical_name == inp.paragraph_annotation.speaker_canonical_name
            ),
            None,
        )
        voice_id = char.suggested_voice_id if char else "default"

        return TtsRoutingDecision(
            segment_id=f"{inp.book_id}_ch{inp.chapter_index}_p{inp.paragraph_index}",
            engine_choice="kokoro" if inp.prefer_local else "edge",
            voice_id=voice_id,
            prosody_overrides={
                "rate": str(inp.paragraph_annotation.speech_rate),
                "pitch": f"{inp.paragraph_annotation.pitch_shift_semitones}st",
            },
            fallback_engine="edge",
            reasoning="Auto routing: local preferred for Chinese, Edge for English",
            estimated_cost_usd=0.0 if inp.prefer_local else 0.001,
            estimated_duration_ms=3000,
        )


def synthesize_paragraphs(
    inputs: List[TtsRoutingInput],
    output_dir: str = "./output",
    mock_mode: bool = False,
) -> List:
    pipeline = SynthesizePipeline(output_dir=output_dir, mock_mode=mock_mode)
    return pipeline.run(inputs)


if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(level=logging.INFO)
    print("SynthesizePipeline ready")
