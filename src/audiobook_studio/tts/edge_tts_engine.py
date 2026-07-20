"""Edge-TTS Engine Implementation.

Cloud-based TTS using Microsoft Edge's free TTS service via edge_tts package.
No GPU required, works via HTTP to Microsoft's TTS endpoints.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

try:
    import edge_tts
except ImportError:
    edge_tts = None

from .engine import SynthesisResult, TTSEngine, VoiceInfo

logger = logging.getLogger(__name__)


class EdgeTTSEngine(TTSEngine):
    """Edge-TTS Engine for cloud-based free TTS synthesis."""

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

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cloud",
        sample_rate: int = 24000,
        mock_mode: bool = False,
        **kwargs,
    ):
        super().__init__(model_path, device, sample_rate, mock_mode=mock_mode, **kwargs)
        self._voices_cache: Optional[List[VoiceInfo]] = None

    @property
    def engine_name(self) -> str:
        return "edge"

    @property
    def supports_streaming(self) -> bool:
        return True  # edge_tts supports streaming

    @property
    def supports_batch(self) -> bool:
        return False  # Single utterance at a time

    async def initialize(self) -> None:
        """Initialize Edge-TTS engine (verify connectivity)."""
        if self.mock_mode:
            self._initialized = True
            logger.info("EdgeTTSEngine initialized in mock mode")
            return

        if edge_tts is None:
            logger.error("edge_tts package not installed. Run: pip install edge-tts")
            raise ImportError("edge_tts package not installed")

        try:
            # Test connectivity by listing voices
            voices = await edge_tts.list_voices()
            if not voices:
                raise RuntimeError("No Edge-TTS voices available (network issue?)")

            logger.info(f"EdgeTTS engine initialized: {len(voices)} voices available")
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize EdgeTTS engine: {e}")
            raise

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        prosody: Optional[Dict] = None,
        reference_audio: Optional[str] = None,
        **kwargs,
    ) -> SynthesisResult:
        """Synthesize text using Edge-TTS."""
        if not self._initialized:
            await self.initialize()

        # Mock mode: create empty audio file
        if self.mock_mode:
            import numpy as np
            import soundfile as sf

            dummy_audio = np.zeros(48000, dtype=np.float32)  # 1 second silence
            sf.write(str(output_path), dummy_audio, self.sample_rate)
            text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
            return SynthesisResult(
                audio_path=str(output_path),
                duration_ms=1000,
                engine="edge",
                voice_id=voice_id,
                text_hash=text_hash,
                sample_rate=self.sample_rate,
            )

        # Validate voice
        if voice_id not in self.EDGE_VOICES:
            available = list(self.EDGE_VOICES.keys())
            logger.warning(f"Voice {voice_id} not in Edge voice map, using default 'zh-CN-XiaoxiaoNeural'")
            voice_id = "zh-CN-XiaoxiaoNeural"

        # Build SSML for prosody control
        ssml = self._build_ssml(text, voice_id, prosody)

        # Synthesize
        communicate = edge_tts.Communicate(ssml, voice_id)
        await communicate.save(str(output_path))

        # Calculate duration (approximate)
        duration_ms = len(text) * 80  # ~80ms per char estimate
        text_hash = hashlib.md5(text.encode()).hexdigest()[:12]

        return SynthesisResult(
            audio_path=str(output_path),
            duration_ms=duration_ms,
            engine="edge",
            voice_id=voice_id,
            text_hash=text_hash,
            sample_rate=self.sample_rate,
            metadata={"prosody": prosody},
        )

    def _build_ssml(self, text: str, voice_id: str, prosody: Optional[Dict]) -> str:
        """Build SSML with prosody controls."""
        if not prosody:
            return text

        rate = prosody.get("rate", 1.0)
        pitch = prosody.get("pitch", 0.0)  # semitones
        volume = prosody.get("volume", 0.0)  # dB
        emotion = prosody.get("emotion")

        # Convert to Edge-TTS prosody format
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

    def get_voices(self) -> List[VoiceInfo]:
        """Get available Edge-TTS voices."""
        if self._voices_cache is None:
            self._voices_cache = list(self.EDGE_VOICES.values())
        return self._voices_cache

    def estimate_duration(self, text: str, voice_id: str, **kwargs) -> int:
        """Estimate audio duration based on text length."""
        # Edge-TTS average: ~150 words/min = ~750 chars/min = ~12.5 chars/sec
        if voice_id.startswith("zh"):
            # Chinese: ~5 chars/sec
            chars_per_sec = 5.0
        else:
            chars_per_sec = 12.5
        speed = kwargs.get("prosody", {}).get("rate", 1.0) if "prosody" in kwargs else 1.0
        est_sec = len(text) / chars_per_sec / speed
        return max(500, int(est_sec * 1000))

    async def cleanup(self) -> None:
        """Clean up resources (nothing to clean for Edge-TTS)."""
        self._initialized = False
        logger.info("EdgeTTS engine cleaned up")


async def create_edge_tts_engine(**kwargs) -> EdgeTTSEngine:
    """Factory function to create and initialize EdgeTTS engine."""
    engine = EdgeTTSEngine(**kwargs)
    await engine.initialize()
    return engine
