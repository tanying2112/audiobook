"""Kokoro-ONNX TTS Backend (Issue 1.1).

Local CPU-based TTS using Kokoro-ONNX model (~82M params).
Optimized for cloud_hybrid and potato hardware profiles.
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .engine import SynthesisResult, TTSEngine, VoiceInfo

logger = logging.getLogger(__name__)


# Kokoro voice presets (from kokoro-onnx voice list)
KOKORO_VOICES = {
    "af": {
        "name": "af",
        "language": "en",
        "gender": "female",
        "description": "American Female",
    },
    "af_bella": {
        "name": "af_bella",
        "language": "en",
        "gender": "female",
        "description": "American Female - Bella",
    },
    "af_nicole": {
        "name": "af_nicole",
        "language": "en",
        "gender": "female",
        "description": "American Female - Nicole",
    },
    "af_sarah": {
        "name": "af_sarah",
        "language": "en",
        "gender": "female",
        "description": "American Female - Sarah",
    },
    "af_sky": {
        "name": "af_sky",
        "language": "en",
        "gender": "female",
        "description": "American Female - Sky",
    },
    "am_adam": {
        "name": "am_adam",
        "language": "en",
        "gender": "male",
        "description": "American Male - Adam",
    },
    "am_michael": {
        "name": "am_michael",
        "language": "en",
        "gender": "male",
        "description": "American Male - Michael",
    },
    "bf_emma": {
        "name": "bf_emma",
        "language": "en",
        "gender": "female",
        "description": "British Female - Emma",
    },
    "bf_isabella": {
        "name": "bf_isabella",
        "language": "en",
        "gender": "female",
        "description": "British Female - Isabella",
    },
    "bm_george": {
        "name": "bm_george",
        "language": "en",
        "gender": "male",
        "description": "British Male - George",
    },
    "bm_lewis": {
        "name": "bm_lewis",
        "language": "en",
        "gender": "male",
        "description": "British Male - Lewis",
    },
    "zf_xiaoxiao": {
        "name": "zf_xiaoxiao",
        "language": "zh",
        "gender": "female",
        "description": "中文女声 - Xiaoxiao",
    },
    "zf_xiaobei": {
        "name": "zf_xiaobei",
        "language": "zh",
        "gender": "female",
        "description": "中文女声 - Xiaobei",
    },
    "zf_xiaoni": {
        "name": "zf_xiaoni",
        "language": "zh",
        "gender": "female",
        "description": "中文女声 - Xiaoni",
    },
    "zf_xiaoxuan": {
        "name": "zf_xiaoxuan",
        "language": "zh",
        "gender": "female",
        "description": "中文女声 - Xiaoxuan",
    },
    "zm_yunjian": {
        "name": "zm_yunjian",
        "language": "zh",
        "gender": "male",
        "description": "中文男声 - Yunjian",
    },
    "zm_yunxi": {
        "name": "zm_yunxi",
        "language": "zh",
        "gender": "male",
        "description": "中文男声 - Yunxi",
    },
    "zm_yunxia": {
        "name": "zm_yunxia",
        "language": "zh",
        "gender": "male",
        "description": "中文男声 - Yunxia",
    },
    "zm_yunyang": {
        "name": "zm_yunyang",
        "language": "zh",
        "gender": "male",
        "description": "中文男声 - Yunyang",
    },
}


class KokoroBackend(TTSEngine):
    """Kokoro-ONNX TTS Backend for local CPU synthesis."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        voices_path: Optional[str] = None,
        device: str = "cpu",
        sample_rate: int = 24000,
        providers: Optional[List[str]] = None,
        session_options: Optional[Dict] = None,
        mock_mode: bool = False,
        **kwargs,
    ):
        super().__init__(model_path, device, sample_rate, mock_mode=mock_mode, **kwargs)
        self.voices_path = voices_path
        self.providers = providers or ["CPUExecutionProvider"]
        self.session_options = session_options or {
            "intra_op_num_threads": 4,
            "inter_op_num_threads": 2,
        }
        self._session = None
        self._phonemizer = None
        self._voice_embeddings = KOKORO_VOICES  # Use predefined voices

    @property
    def engine_name(self) -> str:
        return "kokoro"

    @property
    def supports_streaming(self) -> bool:
        return False  # Kokoro-ONNX doesn't support streaming yet

    @property
    def supports_batch(self) -> bool:
        return False  # Single utterance at a time

    async def initialize(self) -> None:
        """Initialize Kokoro-ONNX session and phonemizer."""
        # Mock mode: skip actual model loading
        if self.mock_mode:
            self._initialized = True
            logger.info("KokoroBackend initialized in mock mode")
            return

        try:
            import onnxruntime as ort

            # Resolve model path
            if self.model_path is None:
                self.model_path = str(Path("models/kokoro-v1.0.onnx").absolute())

            if not Path(self.model_path).exists():
                raise FileNotFoundError(f"Kokoro model not found: {self.model_path}")

            # Resolve voices path
            if self.voices_path is None:
                self.voices_path = str(Path("models/voices-v1.0.bin").absolute())

            if not Path(self.voices_path).exists():
                raise FileNotFoundError(f"Kokoro voices not found: {self.voices_path}")

            # Create ONNX session
            sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = self.session_options.get("intra_op_num_threads", 4)
            sess_options.inter_op_num_threads = self.session_options.get("inter_op_num_threads", 2)

            self._session = ort.InferenceSession(
                self.model_path,
                sess_options=sess_options,
                providers=self.providers,
            )

            # Initialize phonemizer (misaki for English, espeak-ng for Chinese)
            try:
                from misaki import en, zh

                self._phonemizer_en = en.G2P()
                self._phonemizer_zh = zh.G2P()
            except ImportError:
                logger.warning("misaki not installed, using fallback phonemization")
                self._phonemizer_en = None
                self._phonemizer_zh = None

            # Load voice embeddings
            self._voice_embeddings = np.load(self.voices_path, allow_pickle=True).item()

            self._initialized = True
            logger.info(f"Kokoro-ONNX initialized: model={self.model_path}, voices={len(self._voice_embeddings)}")

        except ImportError:
            logger.error("onnxruntime not installed. Run: pip install onnxruntime")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize Kokoro backend: {e}")
            raise

    def _phonemize(self, text: str, voice_id: str) -> Tuple[np.ndarray, np.ndarray]:
        """Convert text to phonemes and return (phoneme IDs for Kokoro."""
        # Determine language from voice_id
        lang = KOKORO_VOICES.get(voice_id, {}).get("language", "en")

        if lang == "zh" and self._phonemizer_zh:
            phonemes = self._phonemizer_zh(text)
        elif lang == "en" and self._phonemizer_en:
            phonemes = self._phonemizer_en(text)
        else:
            # Fallback: simple character-based phonemization
            logger.warning(f"No phonemizer for lang={lang}, using fallback")
            phonemes = list(text)

        # Convert phonemes to Kokoro token IDs
        # This is simplified - real implementation uses Kokoro's tokenizer
        token_ids = [ord(p) % 256 for p in phonemes]  # Placeholder
        return np.array([token_ids], dtype=np.int64), np.array([len(token_ids)], dtype=np.int64)

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        prosody: Optional[Dict] = None,
        reference_audio: Optional[str] = None,
        embedding: Optional[np.ndarray] = None,
        **kwargs,
    ) -> SynthesisResult:
        """Synthesize text using Kokoro-ONNX."""
        if not self._initialized:
            await self.initialize()

        # Mock mode: create empty audio file
        if self.mock_mode:
            # Create a dummy audio file for testing
            import numpy as np
            import soundfile as sf

            dummy_audio = np.zeros(48000, dtype=np.float32)  # 1 second silence
            sf.write(str(output_path), dummy_audio, self.sample_rate)
            text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
            return SynthesisResult(
                audio_path=str(output_path),
                duration_ms=1000,
                engine="kokoro",
                voice_id=voice_id,
                text_hash=text_hash,
                sample_rate=self.sample_rate,
            )

        # Get voice embedding - support custom embedding from voice cloning
        if embedding is not None:
            # Use custom embedding from voice cloning
            voice_embedding = np.array(embedding, dtype=np.float32).reshape(1, -1)
            logger.info(f"Using custom voice embedding with shape {voice_embedding.shape}")
        elif voice_id not in self._voice_embeddings:
            logger.warning(f"Voice {voice_id} not found, using default 'zf_xiaoxiao'")
            voice_id = "zf_xiaoxiao"

            voice_embedding = self._voice_embeddings[voice_id]
            if isinstance(voice_embedding, dict):
                voice_embedding = voice_embedding.get("embedding", list(voice_embedding.values())[0])
            voice_embedding = np.array(voice_embedding, dtype=np.float32).reshape(1, -1)
        else:
            voice_embedding = self._voice_embeddings[voice_id]
            if isinstance(voice_embedding, dict):
                voice_embedding = voice_embedding.get("embedding", list(voice_embedding.values())[0])
            voice_embedding = np.array(voice_embedding, dtype=np.float32).reshape(1, -1)

        # Phonemize text
        tokens, token_lengths = self._phonemize(text, voice_id)

        # Prepare inputs for ONNX
        speed = prosody.get("rate", 1.0) if prosody else 1.0
        # Kokoro expects: tokens, token_lengths, voice_embedding, speed
        inputs = {
            "tokens": tokens,
            "token_lengths": token_lengths,
            "style": voice_embedding,
            "speed": np.array([speed], dtype=np.float32),
        }

        # Run inference
        outputs = self._session.run(None, inputs)
        audio = outputs[0].squeeze()  # (samples,)

        # Apply prosody adjustments
        if prosody:
            pitch_shift = prosody.get("pitch", 0)  # semitones
            volume = prosody.get("volume", 0)  # dB
            if pitch_shift != 0:
                # Simple pitch shift via resampling (placeholder)
                pass
            if volume != 0:
                audio = audio * (10 ** (volume / 20.0))

        # Save as WAV then convert to MP3
        import soundfile as sf

        wav_path = output_path.with_suffix(".wav")
        sf.write(str(wav_path), audio, self.sample_rate)

        # Convert to MP3 if needed
        if output_path.suffix == ".mp3":
            import subprocess

            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(wav_path),
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    "128k",
                    str(output_path),
                ],
                capture_output=True,
                check=True,
            )
            wav_path.unlink(missing_ok=True)

        duration_ms = int(len(audio) / self.sample_rate * 1000)
        text_hash = hashlib.md5(text.encode()).hexdigest()[:12]

        return SynthesisResult(
            audio_path=str(output_path),
            duration_ms=duration_ms,
            engine=self.engine_name,
            voice_id=voice_id,
            text_hash=text_hash,
            sample_rate=self.sample_rate,
            metadata={"speed": speed, "voice_embedding_shape": voice_embedding.shape},
        )

    def get_voices(self) -> List[VoiceInfo]:
        """Get available Kokoro voices."""
        voices = []
        for voice_id, info in KOKORO_VOICES.items():
            voices.append(
                VoiceInfo(
                    voice_id=voice_id,
                    name=info["name"],
                    language=info["language"],
                    gender=info["gender"],
                    description=info["description"],
                    sample_rate=self.sample_rate,
                    supports_prosody=True,
                    supports_reference_audio=False,
                    engine=self.engine_name,
                )
            )
        return voices

    def estimate_duration(self, text: str, voice_id: str, **kwargs) -> int:
        """Estimate duration based on text length and average speech rate."""
        # Kokoro average: ~150 chars/sec for Chinese, ~100 chars/sec for English
        lang = KOKORO_VOICES.get(voice_id, {}).get("language", "en")
        chinese_chars = sum(1 for c in text if "一" <= c <= "鿿")
        english_chars = len(text) - chinese_chars

        if lang == "zh":
            # Chinese: ~5 chars/sec natural speed, Kokoro slightly faster
            est_sec = chinese_chars / 5.0 + english_chars / 10.0
        else:
            # English: ~150 words/min = ~750 chars/min = ~12.5 chars/sec
            est_sec = chinese_chars / 5.0 + english_chars / 12.5

        speed = kwargs.get("prosody", {}).get("rate", 1.0) if "prosody" in kwargs else 1.0
        est_sec = est_sec / speed

        return max(500, int(est_sec * 1000))

    async def cleanup(self) -> None:
        """Clean up ONNX session."""
        self._session = None
        self._voice_embeddings = None
        self._initialized = False
        logger.info("Kokoro backend cleaned up")


async def create_kokoro_backend(
    model_path: Optional[str] = None,
    voices_path: Optional[str] = None,
    device: str = "cpu",
    **kwargs,
) -> KokoroBackend:
    """Factory function to create and initialize Kokoro backend."""
    backend = KokoroBackend(model_path=model_path, voices_path=voices_path, device=device, **kwargs)
    await backend.initialize()
    return backend
