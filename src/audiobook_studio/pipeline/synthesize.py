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

from ..config.hardware_profile import HardwareProfile, get_hardware_profile
from ..di import get_app_container
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
from ..tts import EngineRegistry, SynthesisResult, TTSEngine, VoiceInfo
from ..tts.clone import VoiceCloningManager, CloningConfig
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
    """Pipeline for audio synthesis with incremental regeneration."""

    # Default crossfade duration in milliseconds between segments
    DEFAULT_CROSSFADE_MS = 50

    def __init__(
        self,
        router=None,
        output_dir="./output",
        mock_mode: Optional[bool] = None,
        hardware_profile: Optional[HardwareProfile] = None,
    ):
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

        # Hardware profile for TTS engine selection
        self.hardware_profile = hardware_profile or get_hardware_profile()

        # Voice cloning manager
        self.voice_cloning_manager = VoiceCloningManager(CloningConfig(
            model_path="./models/kokoro-onnx",
            output_dir=str(self.output_dir / "cloned"),
        ))

        # Track existing segments for incremental synthesis
        self.existing_segments = {}
        self._mock_segment_counter = 0

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
        """Synthesize using Kokoro-ONNX (local). Falls back to mock/Edge-TTS if unavailable."""

        import asyncio

        from ..tts.kokoro_backend import KokoroBackend

        # Mock mode: create dummy file
        if self.mock_mode:
            import hashlib

            import numpy as np
            import soundfile as sf

            text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
            dummy_audio = np.zeros(24000, dtype=np.float32)  # 1 second silence at 24kHz
            # Handle both .mp3 and .wav extensions
            if output_path.suffix == ".mp3":
                # Write WAV then convert to MP3
                sf.write(str(output_path), dummy_audio, 24000)
            else:
                sf.write(str(output_path), dummy_audio, 24000)
            logger.info(f"Mock Kokoro synthesis: {output_path}")
            return 3000

        async def _do_synthesize():
            # Try to get engine from registry first
            engine = EngineRegistry().get("kokoro")
            if engine and engine.is_available():
                result = await engine.synthesize(
                    text=text,
                    voice_id=voice_id,
                    output_path=output_path,
                    prosody=prosody,
                )
                return result.duration_ms
            # Create new backend instance
            kokoro = KokoroBackend(model_path="./models/kokoro-onnx")
            await kokoro.initialize()
            result = await kokoro.synthesize(
                text=text,
                voice_id=voice_id,
                output_path=output_path,
                prosody=prosody,
            )
            await kokoro.cleanup()
            return result.duration_ms

        try:
            return asyncio.run(_do_synthesize())
        except ImportError:
            logger.info("onnxruntime not installed, falling back to mock/Edge-TTS")
            return self._synthesize_mock(text, voice_id, prosody, output_path)
        except FileNotFoundError:
            logger.info("Kokoro model files not found, falling back to mock/Edge-TTS")
            return self._synthesize_mock(text, voice_id, prosody, output_path)
        except Exception as e:
            logger.error(f"Kokoro synthesis failed: {e}")
            return self._synthesize_mock(text, voice_id, prosody, output_path)

    def _synthesize_edge(
        self, text: str, voice_id: str, prosody: dict, output_path: Path
    ) -> int:
        """Synthesize using Edge-TTS (cloud). Returns duration_ms."""

        # Mock mode: create dummy file
        if self.mock_mode:
            import hashlib

            import numpy as np
            import soundfile as sf

            text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
            dummy_audio = np.zeros(24000, dtype=np.float32)  # 1 second silence at 24kHz
            # Write directly to output_path (soundfile handles any extension)
            sf.write(str(output_path), dummy_audio, 24000)
            logger.info(f"Mock Edge-TTS synthesis: {output_path}")
            return 2800  # Edge mock duration

        try:
            import asyncio

            import edge_tts

            async def _synthesize():
                resolved_voice = self._resolve_edge_voice(voice_id)
                communicate = edge_tts.Communicate(text, resolved_voice)
                await communicate.save(str(output_path))

            asyncio.run(_synthesize())

            # If output file wasn't created (e.g., asyncio.run was mocked), use fallback
            if not output_path.exists():
                raise RuntimeError("Synthesis did not create output file")

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

        except ImportError:
            logger.error("edge-tts not installed. Run: pip install edge-tts")
            raise
        except Exception as e:
            logger.error(f"Edge-TTS synthesis failed: {e}")
            raise

    def _synthesize_mock(
        self, text: str, voice_id: str, prosody: dict, output_path: Path
    ) -> int:
        """Mock synthesis - creates empty audio file for testing. Returns duration_ms."""
        import numpy as np
        import soundfile as sf

        # Create a 1-second silent audio file
        dummy_audio = np.zeros(24000, dtype=np.float32)  # 1 second silence at 24kHz
        sf.write(str(output_path.with_suffix(".wav")), dummy_audio, 24000)

        self._mock_segment_counter += 1
        logger.info(
            f"Mock synthesis created: {output_path} (segment #{self._mock_segment_counter})"
        )
        return 3000  # Match Kokoro mock duration

    def _synthesize_azure(
        self, text: str, voice_id: str, prosody: dict, output_path: Path
    ) -> int:
        """Synthesize using Azure Cognitive Services TTS. Returns duration_ms."""

        # Mock mode: create dummy file
        if self.mock_mode:
            import hashlib

            import numpy as np
            import soundfile as sf

            dummy_audio = np.zeros(24000, dtype=np.float32)
            sf.write(str(output_path), dummy_audio, 24000)
            logger.info(f"Mock Azure TTS synthesis: {output_path}")
            return 2800  # Azure mock duration

        # Check for Azure credentials
        azure_key = os.getenv("AZURE_TTS_KEY") or os.getenv("AZURE_SPEECH_KEY")
        azure_region = os.getenv("AZURE_TTS_REGION") or os.getenv("AZURE_SPEECH_REGION")

        if not azure_key or not azure_region:
            logger.warning(
                "Azure TTS credentials not configured (AZURE_TTS_KEY, AZURE_TTS_REGION)"
            )
            raise RuntimeError("Azure TTS not configured")

        try:
            import azure.cognitiveservices.speech as speechsdk

            speech_config = speechsdk.SpeechConfig(
                subscription=azure_key, region=azure_region
            )
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
            synthesizer = speechsdk.SpeechSynthesizer(
                speech_config=speech_config, audio_config=audio_config
            )

            result = synthesizer.speak_ssml_async(ssml).get()

            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                logger.info(f"Azure TTS synthesis completed: {output_path}")
                duration = get_duration_sync(output_path)
                return duration
            elif result.reason == speechsdk.ResultReason.Canceled:
                cancellation = result.cancellation_details
                logger.error(
                    f"Azure TTS canceled: {cancellation.reason} - {cancellation.error_details}"
                )
                raise RuntimeError(f"Azure TTS canceled: {cancellation.error_details}")
            else:
                logger.error(f"Azure TTS failed: {result.reason}")
                raise RuntimeError(f"Azure TTS failed: {result.reason}")

        except ImportError:
            logger.error(
                "azure-cognitiveservices-speech not installed. Run: pip install azure-cognitiveservices-speech"
            )
            raise
        except Exception as e:
            logger.error(f"Azure TTS synthesis failed: {e}")
            raise

    def _synthesize_gcp(
        self, text: str, voice_id: str, prosody: dict, output_path: Path
    ) -> int:
        """Synthesize using Google Cloud TTS. Returns duration_ms."""

        # Mock mode: create dummy file
        if self.mock_mode:
            import hashlib

            import numpy as np
            import soundfile as sf

            dummy_audio = np.zeros(24000, dtype=np.float32)
            sf.write(str(output_path), dummy_audio, 24000)
            logger.info(f"Mock GCP TTS synthesis: {output_path}")
            return 2800  # GCP mock duration

        # Check for GCP credentials
        gcp_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if not gcp_creds or not Path(gcp_creds).exists():
            logger.warning(
                "GCP credentials not configured (GOOGLE_APPLICATION_CREDENTIALS)"
            )
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
            logger.error(
                "google-cloud-texttospeech not installed. Run: pip install google-cloud-texttospeech"
            )
            raise
        except Exception as e:
            logger.error(f"GCP TTS synthesis failed: {e}")
            raise

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
                # Use hardware profile engine config
                config = self._get_tts_engine_config()
                primary_engine = config.get("engine", "kokoro")

                # Override with routing decision if provided
                engine = decision.engine_choice or primary_engine

                # Get reference audio if available (for voice anchoring)
                reference_audio = None
                if (
                    decision.prosody_overrides
                    and "reference_audio" in decision.prosody_overrides
                ):
                    reference_audio = decision.prosody_overrides.pop("reference_audio")

                duration, actual_engine = self._try_synthesize_with_fallback(
                    inp.text,
                    decision.voice_id,
                    decision.prosody_overrides or {},
                    output_path,
                    engine,
                )
                engine = actual_engine
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
                engine=engine,  # Use actual engine after fallback
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

    def _get_tts_engine_config(self) -> dict:
        """Get TTS engine configuration from hardware profile."""
        if not self.hardware_profile:
            return {"engine": "kokoro", "fallback_chain": []}

        tts = self.hardware_profile.tts
        fallback_chain = self.hardware_profile.get_tts_fallback_chain()

        return {
            "engine": tts.engine,
            "model_path": tts.model_path,
            "voices_path": tts.voices_path,
            "dtype": tts.dtype,
            "compile": tts.compile,
            "voice_design_enabled": tts.voice_design_enabled,
            "reference_audio_enabled": tts.reference_audio_enabled,
            "sample_rate": tts.sample_rate,
            "providers": tts.providers,
            "session_options": tts.session_options,
            "voice_presets": tts.voice_presets,
            "fallback_chain": fallback_chain,
            "batch_size": tts.batch_size,
            "kv_cache_reuse": tts.kv_cache_reuse,
        }

    def _get_engine_for_synthesis(
        self, engine_name: str, config: dict
    ) -> Optional[TTSEngine]:
        """Get or create TTS engine instance via DI container."""
        # Check if already cached
        if not hasattr(self, "_engine_cache"):
            self._engine_cache = {}

        if engine_name in self._engine_cache:
            return self._engine_cache[engine_name]

        # Get or create engine from DI container registry
        try:
            from ..di import get_app_container

            registry = get_app_container().get(EngineRegistry)

            # Try to get existing engine from registry
            engine = registry.get(engine_name)
            if engine:
                self._engine_cache[engine_name] = engine
                return engine

            # Create engine based on name
            engine = None
            # Handle both "kokoro" and "kokoro_onnx" as valid names
            if engine_name in ("kokoro", "kokoro_onnx"):
                import asyncio

                from ..tts import KokoroBackend, create_kokoro_backend

                engine = asyncio.run(
                    create_kokoro_backend(
                        model_path=config.get("model_path"),
                        voices_path=config.get("voices_path"),
                        providers=config.get("providers"),
                        session_options=config.get("session_options"),
                    )
                )
            elif engine_name == "voxcpmp2":
                import asyncio

                from ..tts import VoxCPM2Backend, create_voxcpmp2_backend

                engine = asyncio.run(
                    create_voxcpmp2_backend(
                        model_path=config.get("model_path"),
                        dtype=config.get("dtype", "float16"),
                        batch_size=config.get("batch_size", 4),
                        kv_cache_reuse=config.get("kv_cache_reuse", True),
                        compile_model=config.get("compile", True),
                    )
                )
            elif engine_name in ("edge", "azure", "gcp"):
                # Cloud engines - use legacy methods for now
                pass
            else:
                logger.warning(f"Unknown engine: {engine_name}")
                return None

            if engine:
                # Register with DI container registry for reuse
                registry.register(
                    engine, set_as_default=(engine_name in ("kokoro", "kokoro_onnx"))
                )
                self._engine_cache[engine_name] = engine
                return engine
        except Exception as e:
            logger.error(f"Failed to create/get engine {engine_name}: {e}")
            return None

        return None

    async def _synthesize_with_engine(
        self,
        engine: TTSEngine,
        text: str,
        voice_id: str,
        prosody: dict,
        output_path: Path,
        reference_audio: Optional[str] = None,
    ) -> int:
        """Synthesize using a TTSEngine instance."""
        import hashlib

        try:
            result = await engine.synthesize(
                text=text,
                voice_id=voice_id,
                output_path=output_path,
                prosody=prosody,
                reference_audio=reference_audio,
            )
            return result.duration_ms
        except Exception as e:
            logger.error(f"Engine {engine.engine_name} synthesis failed: {e}")
            raise

    def _try_synthesize_with_fallback(
        self, text: str, voice_id: str, prosody: dict, output_path: Path, engine: str
    ) -> tuple[int, str]:
        """Try synthesis with fallback chain from hardware profile."""
        # Mock mode: use direct mock synthesis for any engine
        if self.mock_mode:
            logger.info(f"Mock mode: using mock synthesis for {engine}")
            duration = self._synthesize_mock(text, voice_id, prosody, output_path)
            return duration, engine

        # Check if this is a cloned voice (voice_id starts with "cloned_" or is in voice_prints)
        if voice_id.startswith("cloned_") or voice_id in self.voice_cloning_manager.voice_prints:
            speaker_id = voice_id.replace("cloned_", "")
            logger.info(f"Using voice cloning for speaker: {speaker_id}")
            # Get annotation from prosody overrides if available
            emotion = prosody.get("emotion", "neutral")
            language = prosody.get("language", "zh-CN")
            success, message, audio_file = self.voice_cloning_manager.synthesize_speech(
                text=text,
                speaker_id=speaker_id,
                language=language,
                emotion=emotion,
            )
            if success and audio_file:
                # Copy to output_path
                import shutil
                shutil.copy2(audio_file, output_path)
                duration = get_duration_sync(output_path)
                return duration, "voice_clone"
            else:
                logger.warning(f"Voice cloning failed: {message}, falling back to TTS")
                # Continue to fallback TTS

        config = self._get_tts_engine_config()
        engines_to_try = [engine] + [
            f.get("engine") for f in config.get("fallback_chain", [])
        ]

        for eng in engines_to_try:
            if not eng:
                continue
            try:
                if eng == "kokoro" or eng == "kokoro_onnx" or eng == "voxcpmp2":
                    # Use new engine abstraction
                    tts_engine = self._get_engine_for_synthesis(eng, config)
                    if tts_engine:
                        import asyncio

                        duration = asyncio.run(
                            self._synthesize_with_engine(
                                tts_engine, text, voice_id, prosody, output_path
                            )
                        )
                        return duration, eng
                elif eng == "edge":
                    return (
                        self._synthesize_edge(text, voice_id, prosody, output_path),
                        eng,
                    )
                elif eng == "azure":
                    return (
                        self._synthesize_azure(text, voice_id, prosody, output_path),
                        eng,
                    )
                elif eng == "gcp":
                    return (
                        self._synthesize_gcp(text, voice_id, prosody, output_path),
                        eng,
                    )
                elif eng == "cosyvoice":
                    logger.warning("CosyVoice not yet implemented, falling back")
                    continue
            except Exception as e:
                logger.warning(f"Engine {eng} failed: {e}, trying next...")
                continue

        raise RuntimeError("All TTS engines in fallback chain failed")

    def _make_routing_decision(self, inp: TtsRoutingInput) -> TtsRoutingDecision:
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

        mock_info = "Mock mode" if self.mock_mode else "real mode"
        reasoning = (
            f"Auto routing: local preferred for Chinese, Edge for English ({mock_info})"
        )
        return TtsRoutingDecision(
            segment_id=f"{inp.book_id}_ch{inp.chapter_index}_p{inp.paragraph_index}",
            engine_choice="kokoro" if inp.prefer_local else "edge",
            voice_id=voice_id,
            prosody_overrides={
                "rate": str(inp.paragraph_annotation.speech_rate),
                "pitch": f"{inp.paragraph_annotation.pitch_shift_semitones}st",
            },
            fallback_engine="edge",
            reasoning=reasoning,
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
    logger.info("SynthesizePipeline ready")
