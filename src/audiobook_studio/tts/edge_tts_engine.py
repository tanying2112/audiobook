"""Edge-TTS Engine Implementation.

Cloud-based TTS using Microsoft Edge's free TTS service via edge_tts package.
No GPU required, works via HTTP to Microsoft's TTS endpoints.
"""

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import edge_tts
except ImportError:
    edge_tts = None

from .engine import BaseTTSEngine, SynthesisResult, TTSTaskPayload, TTSTaskResult, TTSTaskStatus, VoiceInfo

logger = logging.getLogger(__name__)


# Edge-TTS voice mapping (subset of available voices)
EDGE_VOICES: Dict[str, VoiceInfo] = {
    "zh-CN-XiaoxiaoNeural": VoiceInfo(
        voice_id="zh-CN-XiaoxiaoNeural",
        name="Xiaoxiao",
        language="zh-CN",
        gender="female",
        age_range="adult",
        description="Microsoft Edge Chinese Female - Xiaoxiao",
        sample_rate=24000,
        supports_prosody=True,
        engine="edge",
    ),
    "zh-CN-YunxiNeural": VoiceInfo(
        voice_id="zh-CN-YunxiNeural",
        name="Yunxi",
        language="zh-CN",
        gender="male",
        age_range="adult",
        description="Microsoft Edge Chinese Male - Yunxi",
        sample_rate=24000,
        supports_prosody=True,
        engine="edge",
    ),
    "zh-CN-YunjianNeural": VoiceInfo(
        voice_id="zh-CN-YunjianNeural",
        name="Yunjian",
        language="zh-CN",
        gender="male",
        age_range="adult",
        description="Microsoft Edge Chinese Male - Yunjian",
        sample_rate=24000,
        supports_prosody=True,
        engine="edge",
    ),
    "zh-CN-XiaoyiNeural": VoiceInfo(
        voice_id="zh-CN-XiaoyiNeural",
        name="Xiaoyi",
        language="zh-CN",
        gender="female",
        age_range="adult",
        description="Microsoft Edge Chinese Female - Xiaoyi",
        sample_rate=24000,
        supports_prosody=True,
        engine="edge",
    ),
    "zh-CN-XiaochenNeural": VoiceInfo(
        voice_id="zh-CN-XiaochenNeural",
        name="Xiaochen",
        language="zh-CN",
        gender="female",
        age_range="adult",
        description="Microsoft Edge Chinese Female - Xiaochen",
        sample_rate=24000,
        supports_prosody=True,
        engine="edge",
    ),
    "en-US-JennyNeural": VoiceInfo(
        voice_id="en-US-JennyNeural",
        name="Jenny",
        language="en-US",
        gender="female",
        age_range="adult",
        description="Microsoft Edge US English Female - Jenny",
        sample_rate=24000,
        supports_prosody=True,
        engine="edge",
    ),
    "en-US-GuyNeural": VoiceInfo(
        voice_id="en-US-GuyNeural",
        name="Guy",
        language="en-US",
        gender="male",
        age_range="adult",
        description="Microsoft Edge US English Male - Guy",
        sample_rate=24000,
        supports_prosody=True,
        engine="edge",
    ),
    "en-US-AriaNeural": VoiceInfo(
        voice_id="en-US-AriaNeural",
        name="Aria",
        language="en-US",
        gender="female",
        age_range="adult",
        description="Microsoft Edge US English Female - Aria",
        sample_rate=24000,
        supports_prosody=True,
        engine="edge",
    ),
    "en-US-DavisNeural": VoiceInfo(
        voice_id="en-US-DavisNeural",
        name="Davis",
        language="en-US",
        gender="male",
        age_range="adult",
        description="Microsoft Edge US English Male - Davis",
        sample_rate=24000,
        supports_prosody=True,
        engine="edge",
    ),
}


class EdgeTTSEngine(BaseTTSEngine):
    """Edge-TTS Engine for cloud-based free TTS synthesis."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cloud",
        sample_rate: int = 24000,
        mock_mode: bool = False,
        output_dir: str = "./output",
        max_concurrent: int = 2,
        **kwargs: Any,
    ):
        super().__init__(output_dir=output_dir, max_concurrent=max_concurrent)
        self.device = device
        self.sample_rate = sample_rate
        self.mock_mode = mock_mode
        self._voices_cache: Optional[List[VoiceInfo]] = None
        self._loaded = False
        self._initialized = False

    @property
    def engine_name(self) -> str:
        return "edge"

    @property
    def is_available(self) -> bool:
        return self._loaded

    async def initialize(self) -> None:
        """Initialize Edge-TTS engine (verify connectivity)."""
        if self.mock_mode:
            self._loaded = True
            self._initialized = True
            logger.info("EdgeTTSEngine initialized in mock mode")
            return

        if edge_tts is None:
            logger.error("edge_tts package not installed. Run: pip install edge-tts")
            raise ImportError("edge_tts package not installed")

        try:
            # Skip list_voices() connectivity check — known to hang on some networks.
            # Edge-TTS availability is verified on first synthesize() call.
            logger.info("EdgeTTS engine initialized (connectivity check deferred to first synthesis)")
            self._loaded = True
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize EdgeTTS engine: {e}")
            raise

    async def _synthesize_internal(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        prosody: Optional[Dict[str, Any]] = None,
        reference_audio: Optional[str] = None,
        **kwargs: Any,
    ) -> SynthesisResult:
        """Internal synthesis method with original signature."""
        if not self._initialized:
            await self.initialize()

        if self.mock_mode:
            import numpy as np
            import soundfile as sf

            # Validate voice - fallback to default if unknown (consistent with real mode)
            if voice_id not in EDGE_VOICES:
                logger.warning(f"Voice {voice_id} not in Edge voice map, using default 'zh-CN-XiaoxiaoNeural'")
                voice_id = "zh-CN-XiaoxiaoNeural"

            dummy_audio = np.zeros(48000, dtype=np.float32)
            sf.write(str(output_path), dummy_audio, self.sample_rate)
            text_hash = hashlib.sha256(text.encode(), usedforsecurity=False).hexdigest()[:12]
            return SynthesisResult(
                audio_path=str(output_path),
                duration_ms=1000,
                engine="edge",
                voice_id=voice_id,
                text_hash=text_hash,
                sample_rate=self.sample_rate,
                metadata={"prosody": prosody},
            )

        # Validate voice
        if voice_id not in EDGE_VOICES:
            list(EDGE_VOICES.keys())
            logger.warning(f"Voice {voice_id} not in Edge voice map, using default 'zh-CN-XiaoxiaoNeural'")
            voice_id = "zh-CN-XiaoxiaoNeural"

        # NOTE(H4 fix): the edge-tts library does NOT accept raw SSML — it
        # speaks the markup literally (a 2s sentence came out as 31.7s of
        # spoken tags). Prosody must be passed via Communicate kwargs instead.
        comm_kwargs = self._communicate_kwargs(prosody)
        communicate = edge_tts.Communicate(text, voice_id, **comm_kwargs)
        await communicate.save(str(output_path))

        # Measure the real duration instead of the old len(text) * 80 guess.
        duration_ms = self._measure_duration_ms(output_path, fallback_text=text)
        text_hash = hashlib.sha256(text.encode(), usedforsecurity=False).hexdigest()[:12]

        return SynthesisResult(
            audio_path=str(output_path),
            duration_ms=duration_ms,
            engine="edge",
            voice_id=voice_id,
            text_hash=text_hash,
            sample_rate=self.sample_rate,
            metadata={"prosody": prosody},
        )

    @staticmethod
    def _communicate_kwargs(prosody: Optional[Dict[str, Any]]) -> Dict[str, str]:
        """Convert our prosody dict into edge_tts.Communicate kwargs.

        edge-tts accepts relative rate/volume percentages and pitch in Hz.
        Emotion styles (mstts:express-as) are NOT supported by the free
        endpoint, so emotion is intentionally dropped here (logged upstream).
        """
        if not prosody:
            return {}
        rate = float(prosody.get("rate", 1.0) or 1.0)
        pitch_st = float(prosody.get("pitch", 0.0) or 0.0)
        volume_db = float(prosody.get("volume", 0.0) or 0.0)
        rate_pct = int(round((rate - 1.0) * 100))
        rate_pct = max(-50, min(50, rate_pct))
        # rough semitone -> Hz mapping (1st ~= 6Hz, clamped to edge limits)
        pitch_hz = max(-50, min(50, int(round(pitch_st * 6))))
        # dB -> linear amplitude percent: pct = (10^(dB/20) - 1) * 100
        import math as _math

        vol_pct = int(round((_math.pow(10.0, volume_db / 20.0) - 1.0) * 100))
        vol_pct = max(-100, min(100, vol_pct))
        return {
            "rate": f"{rate_pct:+d}%",
            "pitch": f"{pitch_hz:+d}Hz",
            "volume": f"{vol_pct:+d}%",
        }

    @staticmethod
    def _measure_duration_ms(output_path: Path, fallback_text: str = "") -> int:
        """Measure real audio duration (mutagen); fall back to text heuristic."""
        try:
            from mutagen.mp3 import MP3

            audio = MP3(str(output_path))
            return int(audio.info.length * 1000)
        except Exception:
            return max(1000, len(fallback_text) * 80)

    def _build_ssml(self, text: str, voice_id: str, prosody: Optional[Dict]) -> str:
        """Build SSML with prosody controls and emotion support."""
        if not prosody:
            return text

        rate = prosody.get("rate", 1.0)
        pitch = prosody.get("pitch", 0.0)
        volume = prosody.get("volume", 0.0)
        emotion = prosody.get("emotion")

        # Emotion-based SSML templates
        emotion_templates = {
            "happy": {
                "rate": "+15%",
                "pitch": "+2st",
                "volume": "+3dB",
                "style": "cheerful",
            },
            "sad": {
                "rate": "-10%",
                "pitch": "-2st",
                "volume": "-3dB",
                "style": "sad",
            },
            "angry": {
                "rate": "+20%",
                "pitch": "+3st",
                "volume": "+6dB",
                "style": "angry",
            },
            "fearful": {
                "rate": "+25%",
                "pitch": "+4st",
                "volume": "+2dB",
                "style": "fearful",
            },
            "surprised": {
                "rate": "+30%",
                "pitch": "+5st",
                "volume": "+4dB",
                "style": "surprised",
            },
            "calm": {
                "rate": "-15%",
                "pitch": "-1st",
                "volume": "-2dB",
                "style": "gentle",
            },
            "neutral": {
                "rate": "0%",
                "pitch": "0st",
                "volume": "0dB",
                "style": "neutral",
            },
        }

        # Only apply emotion template if explicit "emotion" key is provided
        if emotion and emotion in emotion_templates:
            template = emotion_templates[emotion]
            rate_str = template["rate"]
            pitch_str = template["pitch"]
            volume_str = template["volume"]
            # Use mstts:express-as for Microsoft voices that support it
            style = template.get("style", "neutral")
            ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="zh-CN">
    <voice name="{voice_id}">
        <mstts:express-as style="{style}">
            <prosody rate="{rate_str}" pitch="{pitch_str}" volume="{volume_str}">
                {text}
            </prosody>
        </mstts:express-as>
    </voice>
</speak>"""
            return ssml

        # Fallback to manual prosody controls (explicit rate/pitch/volume)
        rate_str = f"{int((rate - 1.0) * 100):+d}%"
        pitch_str = f"{pitch:+.1f}st"
        volume_str = f"{volume:+.1f}dB"

        ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">
    <voice name="{voice_id}">
        <prosody rate="{rate_str}" pitch="{pitch_str}" volume="{volume_str}">
            {text}
        </prosody>
    </voice>
</speak>"""
        return ssml

    # --- TTSEngine Protocol Implementation ---

    async def synthesize(
        self,
        payload: TTSTaskPayload,
        output_path: Path,
    ) -> TTSTaskResult:
        """Synthesize text to speech using TTSTaskPayload."""
        text = payload.text
        voice_anchor = payload.voice_anchor
        prosody = payload.prosody

        voice_id = voice_anchor.voice_id

        prosody_dict = None
        if prosody:
            prosody_dict = {
                "rate": prosody.rate,
                "pitch": prosody.pitch,
                "volume": prosody.volume,
                "emotion": prosody.emotion,
            }

        try:
            result = await self._synthesize_internal(
                text=text,
                voice_id=voice_id,
                output_path=output_path,
                prosody=prosody_dict,
            )
            return TTSTaskResult(
                task_id=self._generate_task_id(),
                status="DONE",
                audio_path=result.audio_path,
                duration_ms=result.duration_ms,
                engine=result.engine,
                text_hash=result.text_hash,
                voice_id=result.voice_id,
                started_at=None,
            )
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return TTSTaskResult(
                task_id=self._generate_task_id(),
                status="FAILED",
                error_message=str(e),
                engine=self.engine_name,
            )

    async def submit(self, task_id: str, payload: TTSTaskPayload) -> bool:
        """Submit a task for async processing."""
        if task_id in self._tasks:
            return False
        self._tasks[task_id] = {"status": "PENDING", "payload": payload}

        asyncio.create_task(self._run_task(task_id, payload))
        return True

    async def _run_task(self, task_id: str, payload: TTSTaskPayload) -> None:
        """Background task runner."""
        try:
            self._tasks[task_id]["status"] = "RUNNING"
            output_path = self._build_output_path(task_id, payload.voice_anchor.voice_id)
            result = await self.synthesize(payload, output_path)
            self._tasks[task_id] = {"status": "DONE", "result": result}
        except Exception as e:
            self._tasks[task_id] = {"status": "FAILED", "error": str(e)}

    async def get_status(self, task_id: str) -> TTSTaskStatus:
        """Poll for task status."""
        task = self._tasks.get(task_id)
        if not task:
            return TTSTaskStatus(
                task_id=task_id,
                status="PENDING",
                error_message=f"Task {task_id} not found",
            )
        return TTSTaskStatus(
            task_id=task_id,
            status=task["status"],
            error_message=task.get("error"),
        )

    async def get_result(self, task_id: str) -> TTSTaskResult:
        """Get full task result."""
        task = self._tasks.get(task_id)
        if not task or "result" not in task:
            raise KeyError(f"Task {task_id} not found or not ready")
        return task["result"]

    async def cancel(self, task_id: str) -> bool:
        """Cancel a pending/running task."""
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task["status"] in ("DONE", "FAILED"):
            return False
        task["status"] = "FAILED"
        task["error"] = "Cancelled"
        return True

    async def health_check(self) -> Dict[str, Any]:
        """Check engine health."""
        return {
            "healthy": self._loaded,
            "engine": self.engine_name,
            "loaded": self._loaded,
            "mock_mode": self.mock_mode,
            "sample_rate": self.sample_rate,
        }

    async def close(self) -> None:
        """Clean up resources."""
        self._loaded = False
        self._initialized = False
        self._voices_cache = None
        logger.info("EdgeTTS engine cleaned up")

    def get_voices(self) -> List[VoiceInfo]:
        """Get available Edge-TTS voices."""
        if self._voices_cache is None:
            self._voices_cache = list(EDGE_VOICES.values())
        return self._voices_cache

    def estimate_duration(self, text: str, voice_id: str, **kwargs: Any) -> int:
        """Estimate audio duration based on text length."""
        if voice_id.startswith("zh"):
            chars_per_sec = 5.0
        else:
            chars_per_sec = 12.5
        speed = kwargs.get("prosody", {}).get("rate", 1.0) if "prosody" in kwargs else 1.0
        est_sec = len(text) / chars_per_sec / speed
        return max(500, int(est_sec * 1000))

    async def stream(
        self,
        payload: TTSTaskPayload,
    ):
        """Stream audio chunks for real-time playback using edge_tts.Communicate.stream()."""
        if not self._initialized:
            await self.initialize()

        if self.mock_mode:
            # Mock: yield empty chunks
            import numpy as np

            yield np.zeros(4800, dtype=np.int16).tobytes()  # ~100ms silence
            return

        text = payload.text
        voice_anchor = payload.voice_anchor
        prosody = payload.prosody

        voice_id = voice_anchor.voice_id

        # Validate voice
        if voice_id not in EDGE_VOICES:
            voice_id = "zh-CN-XiaoxiaoNeural"

        # Build SSML for prosody control. ``prosody`` is a TTSProsody dataclass here;
        # _build_ssml expects a plain dict, so convert it (mirrors synthesize()).
        prosody_dict = None
        if prosody:
            prosody_dict = {
                "rate": prosody.rate,
                "pitch": prosody.pitch,
                "volume": prosody.volume,
                "emotion": prosody.emotion,
            }
        # H4 fix: plain text + Communicate kwargs (never raw SSML, see above).
        comm_kwargs = self._communicate_kwargs(prosody_dict)
        communicate = edge_tts.Communicate(text, voice_id, **comm_kwargs)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]


async def create_edge_tts_engine(**kwargs: Any) -> EdgeTTSEngine:
    """Factory function to create and initialize EdgeTTS engine."""
    engine = EdgeTTSEngine(**kwargs)
    await engine.initialize()
    return engine
