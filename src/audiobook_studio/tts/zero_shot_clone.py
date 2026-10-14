"""Zero-Shot Voice Cloning - Cross-lingual voice transfer.

Supports multiple zero-shot cloning engines:
- XTTS-v2 (Coqui) - 17 languages, high quality, Apache 2.0
- OpenVoice V2 (MyShell) - Fast, tone color cloning, multi-lingual
- CosyVoice Clone (FunAudioLLM) - Chinese/English, streaming, zero-shot

Provides unified interface for voice cloning with reference audio.
"""

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Generator, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ZeroShotCloneConfig:
    """Configuration for Zero-Shot Voice Cloning Engine."""

    engine: str  # "xtts_v2", "openvoice_v2", "cosyvoice_clone"
    host: str = "localhost"
    port: int = 5010
    sample_rate: int = 24000
    language: str = "auto"  # auto, zh, en, ja, ko, fr, de, es, etc.
    speed: float = 1.0
    timeout: int = 60  # seconds
    # Engine-specific options
    extra_params: dict = field(default_factory=dict)

    @property
    def base_url(self) -> str:
        """Get the base URL for the cloning server."""
        return f"http://{self.host}:{self.port}"

    @property
    def mock_mode(self) -> bool:
        """Check if mock mode is enabled via environment variable."""
        return os.getenv("MOCK_TTS", "false").lower() == "true"


@dataclass
class ZeroShotCloneResult:
    """Result of a zero-shot voice cloning operation."""

    audio_data: bytes  # Raw PCM audio data (16-bit)
    sample_rate: int
    latency_ms: int
    text_processed: str = ""
    language_detected: str = ""
    voice_similarity: float = 0.0  # 0-1, estimated similarity to reference
    metadata: dict = field(default_factory=dict)


class BaseZeroShotCloneEngine(ABC):
    """Abstract base class for zero-shot cloning engines."""

    def __init__(self, config: ZeroShotCloneConfig):
        self.config = config
        self._client = None
        self._init_client()

    @abstractmethod
    def _init_client(self):
        """Initialize the engine-specific client."""
        pass

    @abstractmethod
    def _clone_impl(
        self, text: str, reference_audio: bytes, language: Optional[str] = None, **kwargs
    ) -> ZeroShotCloneResult:
        """Implementation-specific cloning."""
        pass

    @abstractmethod
    async def _clone_async_impl(
        self, text: str, reference_audio: bytes, language: Optional[str] = None, **kwargs
    ) -> ZeroShotCloneResult:
        """Implementation-specific async cloning."""
        pass

    @abstractmethod
    def _clone_stream_impl(
        self, text: str, reference_audio: bytes, language: Optional[str] = None, **kwargs
    ) -> Generator[ZeroShotCloneResult, None, None]:
        """Implementation-specific streaming cloning."""
        pass

    def clone(self, text: str, reference_audio: bytes, language: Optional[str] = None, **kwargs) -> ZeroShotCloneResult:
        """
        Clone voice from reference audio.

        Args:
            text: Text to synthesize in cloned voice
            reference_audio: Reference audio bytes (WAV/MP3/PCM)
            language: Target language (auto-detect if not specified)
            **kwargs: Additional engine-specific parameters

        Returns:
            ZeroShotCloneResult with cloned audio
        """
        if self.config.mock_mode:
            return self._mock_clone(text, reference_audio, language)

        lang = language or self.config.language
        return self._clone_impl(text, reference_audio, lang, **kwargs)

    async def clone_async(
        self, text: str, reference_audio: bytes, language: Optional[str] = None, **kwargs
    ) -> ZeroShotCloneResult:
        """Async version of clone."""
        if self.config.mock_mode:
            return self._mock_clone(text, reference_audio, language)

        lang = language or self.config.language
        return await self._clone_async_impl(text, reference_audio, lang, **kwargs)

    def clone_stream(
        self, text: str, reference_audio: bytes, language: Optional[str] = None, **kwargs
    ) -> Generator[ZeroShotCloneResult, None, None]:
        """
        Stream cloned audio in chunks.

        Args:
            text: Text to synthesize in cloned voice
            reference_audio: Reference audio bytes
            language: Target language
            **kwargs: Additional engine-specific parameters

        Yields:
            ZeroShotCloneResult chunks
        """
        if self.config.mock_mode:
            yield from self._mock_clone_stream(text, reference_audio, language)
        else:
            lang = language or self.config.language
            yield from self._clone_stream_impl(text, reference_audio, lang, **kwargs)

    def _mock_clone(self, text: str, reference_audio: bytes, language: Optional[str] = None) -> ZeroShotCloneResult:
        """Generate mock cloned audio for testing."""
        if not text:
            return ZeroShotCloneResult(
                audio_data=b"",
                sample_rate=self.config.sample_rate,
                latency_ms=1,
                text_processed="",
                metadata={"mock": True, "engine": self.config.engine},
            )

        # Generate ~3 seconds of mock audio
        duration = 3.0
        total_samples = int(self.config.sample_rate * duration)
        t = np.linspace(0, duration, total_samples, endpoint=False)
        # Slightly different frequency to simulate "cloned" voice
        audio = np.sin(2 * np.pi * 330 * t) * 0.3  # 330Hz (different from 440Hz)
        audio_int16 = (audio * 32767).astype(np.int16)
        audio_bytes = audio_int16.tobytes()

        return ZeroShotCloneResult(
            audio_data=audio_bytes,
            sample_rate=self.config.sample_rate,
            latency_ms=150,  # Simulated cloning latency
            text_processed=text[:100],
            language_detected=language or "zh",
            voice_similarity=0.85,
            metadata={
                "mock": True,
                "engine": self.config.engine,
                "reference_length": len(reference_audio),
            },
        )

    def _mock_clone_stream(
        self, text: str, reference_audio: bytes, language: Optional[str] = None
    ) -> Generator[ZeroShotCloneResult, None, None]:
        """Generate mock streaming cloned audio."""
        result = self._mock_clone(text, reference_audio, language)
        chunk_size = len(result.audio_data) // 4
        for i in range(4):
            start = i * chunk_size
            end = start + chunk_size if i < 3 else len(result.audio_data)
            yield ZeroShotCloneResult(
                audio_data=result.audio_data[start:end],
                sample_rate=result.sample_rate,
                latency_ms=result.latency_ms if i == 0 else 20,
                text_processed=result.text_processed if i == 0 else "",
                language_detected=result.language_detected,
                voice_similarity=result.voice_similarity,
                metadata={**result.metadata, "chunk": i, "is_final": i == 3},
            )


class XTTSv2Engine(BaseZeroShotCloneEngine):
    """XTTS-v2 Zero-Shot Cloning Engine (Coqui).

    Features:
    - 17 languages: EN, ES, FR, DE, IT, PT, PL, TR, RU, NL, CS, AR, ZH, JP, HU, KO, HI
    - High quality voice cloning
    - Apache 2.0 license
    - Supports long-form synthesis
    """

    SUPPORTED_LANGUAGES = {
        "en",
        "es",
        "fr",
        "de",
        "it",
        "pt",
        "pl",
        "tr",
        "ru",
        "nl",
        "cs",
        "ar",
        "zh",
        "ja",
        "hu",
        "ko",
        "hi",
    }

    def _init_client(self):
        if self.config.mock_mode:
            self._client = None
            return

        try:
            import httpx

            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
            )
            logger.info(f"Initialized XTTS-v2 client: {self.config.base_url}")
        except ImportError:
            logger.error("httpx not installed for XTTS-v2")
            raise

    def _clone_impl(self, text: str, reference_audio: bytes, language: str, **kwargs) -> ZeroShotCloneResult:
        import base64

        import httpx

        # Detect language if auto
        if language == "auto":
            language = "zh"  # Default to Chinese for this project

        if language not in self.SUPPORTED_LANGUAGES:
            logger.warning(f"Language {language} not officially supported by XTTS-v2, trying anyway")

        with httpx.Client(base_url=self.config.base_url, timeout=self.config.timeout) as client:
            # Encode reference audio as base64
            ref_audio_b64 = base64.b64encode(reference_audio).decode("utf-8")

            start_time = time.time()
            response = client.post(
                "/clone",
                json={
                    "text": text,
                    "reference_audio": ref_audio_b64,
                    "language": language,
                    "speed": self.config.speed,
                    "sample_rate": self.config.sample_rate,
                    **self.config.extra_params,
                    **kwargs,
                },
            )
            response.raise_for_status()
            latency_ms = int((time.time() - start_time) * 1000)

            result_data = response.json()
            audio_bytes = base64.b64decode(result_data["audio_base64"])

            return ZeroShotCloneResult(
                audio_data=audio_bytes,
                sample_rate=result_data.get("sample_rate", self.config.sample_rate),
                latency_ms=latency_ms,
                text_processed=text,
                language_detected=result_data.get("language", language),
                voice_similarity=result_data.get("similarity", 0.0),
                metadata={"engine": "xtts_v2", "language": language},
            )

    async def _clone_async_impl(
        self, text: str, reference_audio: bytes, language: str, **kwargs
    ) -> ZeroShotCloneResult:
        import base64

        if language == "auto":  # noqa: E303
            language = "zh"

        ref_audio_b64 = base64.b64encode(reference_audio).decode("utf-8")

        start_time = time.time()
        async with self._client as client:
            response = await client.post(
                "/clone",
                json={
                    "text": text,
                    "reference_audio": ref_audio_b64,
                    "language": language,
                    "speed": self.config.speed,
                    "sample_rate": self.config.sample_rate,
                    **self.config.extra_params,
                    **kwargs,
                },
            )
            response.raise_for_status()
            latency_ms = int((time.time() - start_time) * 1000)

            result_data = response.json()
            audio_bytes = base64.b64decode(result_data["audio_base64"])

            return ZeroShotCloneResult(
                audio_data=audio_bytes,
                sample_rate=result_data.get("sample_rate", self.config.sample_rate),
                latency_ms=latency_ms,
                text_processed=text,
                language_detected=result_data.get("language", language),
                voice_similarity=result_data.get("similarity", 0.0),
                metadata={"engine": "xtts_v2", "language": language},
            )

    def _clone_stream_impl(
        self, text: str, reference_audio: bytes, language: str, **kwargs
    ) -> Generator[ZeroShotCloneResult, None, None]:
        """Stream cloning via XTTS-v2 (if server supports streaming)."""
        import base64

        import httpx

        if language == "auto":
            language = "zh"

        ref_audio_b64 = base64.b64encode(reference_audio).decode("utf-8")

        with httpx.Client(base_url=self.config.base_url, timeout=self.config.timeout) as client:
            response = client.post(
                "/clone/stream",
                json={
                    "text": text,
                    "reference_audio": ref_audio_b64,
                    "language": language,
                    "speed": self.config.speed,
                    "sample_rate": self.config.sample_rate,
                    **self.config.extra_params,
                    **kwargs,
                },
            )
            response.raise_for_status()

            chunk_index = 0
            first_chunk = True
            start_time = time.time()

            for line in response.iter_lines():
                if not line:
                    continue

                import json

                chunk_data = json.loads(line)
                audio_bytes = base64.b64decode(chunk_data["audio_base64"])
                is_final = chunk_data.get("is_final", False)

                latency = int((time.time() - start_time) * 1000) if first_chunk else 20
                first_chunk = False

                yield ZeroShotCloneResult(
                    audio_data=audio_bytes,
                    sample_rate=chunk_data.get("sample_rate", self.config.sample_rate),
                    latency_ms=latency,
                    text_processed=chunk_data.get("text", "") if chunk_index == 0 else "",
                    language_detected=chunk_data.get("language", language),
                    voice_similarity=chunk_data.get("similarity", 0.0),
                    metadata={"engine": "xtts_v2", "language": language, "chunk": chunk_index, "is_final": is_final},
                )
                chunk_index += 1


class OpenVoiceV2Engine(BaseZeroShotCloneEngine):
    """OpenVoice V2 Zero-Shot Cloning Engine (MyShell).

    Features:
    - Fast inference (~real-time)
    - Tone color cloning (preserves reference speaker style)
    - Multi-lingual: EN, ZH, JA, KO, FR, DE, ES, etc.
    - MIT license
    """

    SUPPORTED_LANGUAGES = {"en", "zh", "ja", "ko", "fr", "de", "es", "it", "pt", "ru"}

    def _init_client(self):
        if self.config.mock_mode:
            self._client = None
            return

        try:
            import httpx

            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
            )
            logger.info(f"Initialized OpenVoice V2 client: {self.config.base_url}")
        except ImportError:
            logger.error("httpx not installed for OpenVoice V2")
            raise

    def _clone_impl(self, text: str, reference_audio: bytes, language: str, **kwargs) -> ZeroShotCloneResult:
        import base64

        import httpx

        if language == "auto":
            language = "zh"

        with httpx.Client(base_url=self.config.base_url, timeout=self.config.timeout) as client:
            ref_audio_b64 = base64.b64encode(reference_audio).decode("utf-8")

            start_time = time.time()
            response = client.post(
                "/clone",
                json={
                    "text": text,
                    "reference_audio": ref_audio_b64,
                    "language": language,
                    "speed": self.config.speed,
                    **self.config.extra_params,
                    **kwargs,
                },
            )
            response.raise_for_status()
            latency_ms = int((time.time() - start_time) * 1000)

            result_data = response.json()
            audio_bytes = base64.b64decode(result_data["audio_base64"])

            return ZeroShotCloneResult(
                audio_data=audio_bytes,
                sample_rate=result_data.get("sample_rate", self.config.sample_rate),
                latency_ms=latency_ms,
                text_processed=text,
                language_detected=result_data.get("language", language),
                voice_similarity=result_data.get("similarity", 0.0),
                metadata={"engine": "openvoice_v2", "language": language},
            )

    async def _clone_async_impl(
        self, text: str, reference_audio: bytes, language: str, **kwargs
    ) -> ZeroShotCloneResult:
        import base64

        if language == "auto":  # noqa: E303
            language = "zh"

        ref_audio_b64 = base64.b64encode(reference_audio).decode("utf-8")

        start_time = time.time()
        async with self._client as client:
            response = await client.post(
                "/clone",
                json={
                    "text": text,
                    "reference_audio": ref_audio_b64,
                    "language": language,
                    "speed": self.config.speed,
                    **self.config.extra_params,
                    **kwargs,
                },
            )
            response.raise_for_status()
            latency_ms = int((time.time() - start_time) * 1000)

            result_data = response.json()
            audio_bytes = base64.b64decode(result_data["audio_base64"])

            return ZeroShotCloneResult(
                audio_data=audio_bytes,
                sample_rate=result_data.get("sample_rate", self.config.sample_rate),
                latency_ms=latency_ms,
                text_processed=text,
                language_detected=result_data.get("language", language),
                voice_similarity=result_data.get("similarity", 0.0),
                metadata={"engine": "openvoice_v2", "language": language},
            )

    def _clone_stream_impl(
        self, text: str, reference_audio: bytes, language: str, **kwargs
    ) -> Generator[ZeroShotCloneResult, None, None]:
        """Stream cloning via OpenVoice V2."""
        import base64

        import httpx

        if language == "auto":
            language = "zh"

        ref_audio_b64 = base64.b64encode(reference_audio).decode("utf-8")

        with httpx.Client(base_url=self.config.base_url, timeout=self.config.timeout) as client:
            response = client.post(
                "/clone/stream",
                json={
                    "text": text,
                    "reference_audio": ref_audio_b64,
                    "language": language,
                    "speed": self.config.speed,
                    **self.config.extra_params,
                    **kwargs,
                },
            )
            response.raise_for_status()

            chunk_index = 0
            first_chunk = True
            start_time = time.time()

            for line in response.iter_lines():
                if not line:
                    continue

                import json

                chunk_data = json.loads(line)
                audio_bytes = base64.b64decode(chunk_data["audio_base64"])
                is_final = chunk_data.get("is_final", False)

                latency = int((time.time() - start_time) * 1000) if first_chunk else 15
                first_chunk = False

                yield ZeroShotCloneResult(
                    audio_data=audio_bytes,
                    sample_rate=chunk_data.get("sample_rate", self.config.sample_rate),
                    latency_ms=latency,
                    text_processed=chunk_data.get("text", "") if chunk_index == 0 else "",
                    language_detected=chunk_data.get("language", language),
                    voice_similarity=chunk_data.get("similarity", 0.0),
                    metadata={
                        "engine": "openvoice_v2",
                        "language": language,
                        "chunk": chunk_index,
                        "is_final": is_final,
                    },
                )
                chunk_index += 1


class CosyVoiceCloneEngine(BaseZeroShotCloneEngine):
    """CosyVoice Zero-Shot Cloning Engine (FunAudioLLM).

    Features:
    - Chinese/English bilingual
    - Streaming cloning support
    - In-context learning for voice cloning
    - High quality (24kHz)
    """

    SUPPORTED_LANGUAGES = {"zh", "en"}

    def _init_client(self):
        if self.config.mock_mode:
            self._client = None
            return

        try:
            import httpx

            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
            )
            logger.info(f"Initialized CosyVoice Clone client: {self.config.base_url}")
        except ImportError:
            logger.error("httpx not installed for CosyVoice Clone")
            raise

    def _clone_impl(self, text: str, reference_audio: bytes, language: str, **kwargs) -> ZeroShotCloneResult:
        import base64

        import httpx

        if language == "auto":
            language = "zh"

        with httpx.Client(base_url=self.config.base_url, timeout=self.config.timeout) as client:
            ref_audio_b64 = base64.b64encode(reference_audio).decode("utf-8")

            start_time = time.time()
            response = client.post(
                "/clone",
                json={
                    "text": text,
                    "prompt_audio": ref_audio_b64,  # CosyVoice uses prompt_audio
                    "language": language,
                    "speed": self.config.speed,
                    "sample_rate": self.config.sample_rate,
                    **self.config.extra_params,
                    **kwargs,
                },
            )
            response.raise_for_status()
            latency_ms = int((time.time() - start_time) * 1000)

            result_data = response.json()
            audio_bytes = base64.b64decode(result_data["audio_base64"])

            return ZeroShotCloneResult(
                audio_data=audio_bytes,
                sample_rate=result_data.get("sample_rate", self.config.sample_rate),
                latency_ms=latency_ms,
                text_processed=text,
                language_detected=result_data.get("language", language),
                voice_similarity=result_data.get("similarity", 0.0),
                metadata={"engine": "cosyvoice_clone", "language": language},
            )

    async def _clone_async_impl(
        self, text: str, reference_audio: bytes, language: str, **kwargs
    ) -> ZeroShotCloneResult:
        import base64

        if language == "auto":  # noqa: E303
            language = "zh"

        ref_audio_b64 = base64.b64encode(reference_audio).decode("utf-8")

        start_time = time.time()
        async with self._client as client:
            response = await client.post(
                "/clone",
                json={
                    "text": text,
                    "prompt_audio": ref_audio_b64,
                    "language": language,
                    "speed": self.config.speed,
                    "sample_rate": self.config.sample_rate,
                    **self.config.extra_params,
                    **kwargs,
                },
            )
            response.raise_for_status()
            latency_ms = int((time.time() - start_time) * 1000)

            result_data = response.json()
            audio_bytes = base64.b64decode(result_data["audio_base64"])

            return ZeroShotCloneResult(
                audio_data=audio_bytes,
                sample_rate=result_data.get("sample_rate", self.config.sample_rate),
                latency_ms=latency_ms,
                text_processed=text,
                language_detected=result_data.get("language", language),
                voice_similarity=result_data.get("similarity", 0.0),
                metadata={"engine": "cosyvoice_clone", "language": language},
            )

    def _clone_stream_impl(
        self, text: str, reference_audio: bytes, language: str, **kwargs
    ) -> Generator[ZeroShotCloneResult, None, None]:
        """Stream cloning via CosyVoice."""
        import base64

        import httpx

        if language == "auto":
            language = "zh"

        ref_audio_b64 = base64.b64encode(reference_audio).decode("utf-8")

        with httpx.Client(base_url=self.config.base_url, timeout=self.config.timeout) as client:
            response = client.post(
                "/clone/stream",
                json={
                    "text": text,
                    "prompt_audio": ref_audio_b64,
                    "language": language,
                    "speed": self.config.speed,
                    "sample_rate": self.config.sample_rate,
                    **self.config.extra_params,
                    **kwargs,
                },
            )
            response.raise_for_status()

            chunk_index = 0
            first_chunk = True
            start_time = time.time()

            for line in response.iter_lines():
                if not line:
                    continue

                import json

                chunk_data = json.loads(line)
                audio_bytes = base64.b64decode(chunk_data["audio_base64"])
                is_final = chunk_data.get("is_final", False)

                latency = int((time.time() - start_time) * 1000) if first_chunk else 15
                first_chunk = False

                yield ZeroShotCloneResult(
                    audio_data=audio_bytes,
                    sample_rate=chunk_data.get("sample_rate", self.config.sample_rate),
                    latency_ms=latency,
                    text_processed=chunk_data.get("text", "") if chunk_index == 0 else "",
                    language_detected=chunk_data.get("language", language),
                    voice_similarity=chunk_data.get("similarity", 0.0),
                    metadata={
                        "engine": "cosyvoice_clone",
                        "language": language,
                        "chunk": chunk_index,
                        "is_final": is_final,
                    },
                )
                chunk_index += 1


class ZeroShotCloneEngine:
    """Unified Zero-Shot Voice Cloning Engine facade."""

    def __init__(self, config: ZeroShotCloneConfig):
        self.config = config
        self._engine = self._create_engine(config)

    def _create_engine(self, config: ZeroShotCloneConfig) -> BaseZeroShotCloneEngine:
        """Create the appropriate engine instance."""
        engine_map = {
            "xtts_v2": XTTSv2Engine,
            "openvoice_v2": OpenVoiceV2Engine,
            "cosyvoice_clone": CosyVoiceCloneEngine,
            # Batch 2.2: 本地 CPU 近似克隆 (不受 ENABLE_GPU_BACKENDS 门控)
            "kokoro_zeroshot": KokoroZeroShotCloneEngine,
        }

        engine_class = engine_map.get(config.engine)
        if not engine_class:
            raise ValueError(f"Unsupported zero-shot clone engine: {config.engine}")

        return engine_class(config)

    # Delegate methods to underlying engine
    def clone(self, text: str, reference_audio: bytes, language: Optional[str] = None, **kwargs) -> ZeroShotCloneResult:
        return self._engine.clone(text, reference_audio, language, **kwargs)

    async def clone_async(
        self, text: str, reference_audio: bytes, language: Optional[str] = None, **kwargs
    ) -> ZeroShotCloneResult:
        return await self._engine.clone_async(text, reference_audio, language, **kwargs)

    def clone_stream(
        self, text: str, reference_audio: bytes, language: Optional[str] = None, **kwargs
    ) -> Generator[ZeroShotCloneResult, None, None]:
        return self._engine.clone_stream(text, reference_audio, language, **kwargs)


def create_zero_shot_clone_engine(config: ZeroShotCloneConfig) -> ZeroShotCloneEngine:
    """Factory function to create ZeroShotCloneEngine."""
    return ZeroShotCloneEngine(config)


# ═════════════════════════════════════════════════════════════════════════════
# Batch 2.2 — KokoroZeroShotCloneEngine: 本地 CPU 近似零样本克隆
# ═════════════════════════════════════════════════════════════════════════════
# 设计: 参考音频声学分析 (F0/音节速率/频谱质心) → Kokoro blend 音色 +
# pitch_st (ffmpeg 带式移位, v6 验证) + speed → 本地 CPU 合成。
# 与云端引擎不同: 不受 ENABLE_GPU_BACKENDS 门控 (纯 CPU, kokoro-onnx)。

import asyncio
import tempfile
import threading
from pathlib import Path as _Path


class KokoroZeroShotCloneEngine(BaseZeroShotCloneEngine):
    """本地近似零样本克隆: 参考音频 → Kokoro 参数映射 → CPU 合成.

    引擎链路:
      reference_audio bytes → tempfile → analyze_reference() 声学画像
      → suggest_kokoro_params() → (blend_voice, pitch_st, speed)
      → KokoroBackend._synthesize_internal() (chunked, blend-aware)
      → shift_semitones_path() ffmpeg 带式 pitch 移位
      → PCM int16 bytes + voice_similarity 估计
    """

    def __init__(self, config: ZeroShotCloneConfig):
        self._kokoro_backend = None
        self._backend_lock = threading.Lock()
        self._model_path = config.extra_params.get("model_path", "models/kokoro-v1.0.onnx")
        self._voices_path = config.extra_params.get("voices_path", "models/voices-v1.0.bin")
        super().__init__(config)

    # ── ABC 实现 ────────────────────────────────────────────────────────────

    def _init_client(self):
        """惰性校验: 只在实例化时确认模型文件路径, 真正加载推迟到首次克隆."""
        if self.config.mock_mode:
            return
        model_p = _Path(self._model_path)
        voices_p = _Path(self._voices_path)
        if not model_p.exists():
            logger.warning(
                f"[KokoroZeroShot] 模型文件不存在: {model_p} — 首次克隆时将回退 mock"
            )
        if not voices_p.exists():
            logger.warning(f"[KokoroZeroShot] 音色文件不存在: {voices_p}")

    def _ensure_backend(self):
        """惰性创建并初始化 KokoroBackend (线程安全)."""
        if self._kokoro_backend is not None:
            return self._kokoro_backend
        with self._backend_lock:
            if self._kokoro_backend is not None:
                return self._kokoro_backend
            from .kokoro_backend import KokoroBackend

            backend = KokoroBackend(
                model_path=self._model_path if _Path(self._model_path).exists() else None,
                voices_path=self._voices_path if _Path(self._voices_path).exists() else None,
                sample_rate=24000,
                mock_mode=False,
            )
            # initialize() 是 async — 经 _run_async_safely 兼容三种上下文:
            # 无 loop (纯同步) / 已有运行中 loop (async 协程内调用, 如
            # _clone_core → _synthesize_with_backend) / 专用线程。
            # 直接裸 asyncio.run 在协程内会 RuntimeError (loop 已在跑)。
            self._run_async_safely(backend.initialize())
            self._kokoro_backend = backend
            logger.info("[KokoroZeroShot] KokoroBackend 已初始化 (本地 CPU)")
        return self._kokoro_backend

    # ── 核心合成 ────────────────────────────────────────────────────────────

    async def _synthesize_with_backend(
        self,
        text: str,
        blend_voice: str,
        speed: float,
        output_path: _Path,
    ) -> None:
        """经 KokoroBackend 合成 (chunked + blend 解析 + 语言映射)."""
        backend = self._ensure_backend()
        await backend._synthesize_internal(
            text=text,
            voice_id=blend_voice,
            output_path=output_path,
            prosody={"rate": speed},
        )

    def _estimate_similarity(self, profile, suggestion) -> float:
        """估计克隆相似度: pitch 邻近度 × 分析置信度.

        |pitch_st| 越小 → 参考音高与合成音色越近 (8st 邻域线性衰减到 0);
        再乘分析置信度 (短/低 voiced 样本打折)。首次合成后可用
        quality.audio_metrics speaker cosine 复核 (调用方自行做)。
        """
        if profile.f0_median_hz is not None:
            delta_st = abs(suggestion.pitch_st)
            return max(0.0, 1.0 - delta_st / 8.0) * suggestion.confidence
        return suggestion.confidence * 0.5  # F0 缺失 → 保守估计

    def _clone_impl(
        self, text: str, reference_audio: bytes, language: Optional[str] = None, **kwargs
    ) -> ZeroShotCloneResult:
        """同步克隆入口 — 在无事件循环上下文中运行."""
        return self._run_async_safely(
            self._clone_core(text, reference_audio, language, **kwargs)
        )

    async def _clone_async_impl(
        self, text: str, reference_audio: bytes, language: Optional[str] = None, **kwargs
    ) -> ZeroShotCloneResult:
        """异步克隆入口."""
        return await self._clone_core(text, reference_audio, language, **kwargs)

    def _clone_stream_impl(
        self, text: str, reference_audio: bytes, language: Optional[str] = None, **kwargs
    ) -> Generator[ZeroShotCloneResult, None, None]:
        """流式克隆: 先完整合成, 再分块产出 (近似流式)."""
        result = self._run_async_safely(
            self._clone_core(text, reference_audio, language, **kwargs)
        )
        chunk_size = 24000 * 2 * 2  # ~2s int16 bytes per chunk
        audio = result.audio_data
        n_chunks = max(1, len(audio) // chunk_size)
        for i in range(n_chunks):
            start = i * chunk_size
            end = min(start + chunk_size, len(audio))
            is_final = i == n_chunks - 1
            yield ZeroShotCloneResult(
                audio_data=audio[start:end],
                sample_rate=result.sample_rate,
                latency_ms=result.latency_ms if i == 0 else 20,
                text_processed=result.text_processed if i == 0 else "",
                language_detected=result.language_detected,
                voice_similarity=result.voice_similarity,
                metadata={**result.metadata, "chunk": i, "is_final": is_final},
            )

    @staticmethod
    def _run_async_safely(coro):
        """安全运行协程: 无运行中 loop → asyncio.run; 有 → 专用线程跑."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        # 已在事件循环内 (误从 async 上下文调同步接口): 借线程跑
        box = {}

        def _runner():
            box["result"] = asyncio.run(coro)

        t = threading.Thread(target=_runner)
        t.start()
        t.join()
        if "result" not in box:
            raise RuntimeError("KokoroZeroShot 同步克隆线程失败")
        return box["result"]

    async def _clone_core(
        self,
        text: str,
        reference_audio: bytes,
        language: Optional[str],
        **kwargs,
    ) -> ZeroShotCloneResult:
        """核心克隆流程: 分析 → 参数映射 → 合成 → pitch 移位 → 结果."""
        import time
        from .reference_analysis import analyze_reference, suggest_kokoro_params
        from ..utils.pitch_shift import shift_semitones_path

        t0 = time.time()
        lang = language or self.config.language or "zh"

        # 1) 参考音频分析
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            ref_path = _Path(tmp.name)
            ref_path.write_bytes(reference_audio)
        try:
            profile = analyze_reference(ref_path)
        finally:
            ref_path.unlink(missing_ok=True)

        if profile.f0_median_hz is None:
            logger.warning("[KokoroZeroShot] 参考音频 F0 全空, 回退默认参数")
            profile = ReferenceAudioProfile()  # type: ignore

        # 2) Kokoro 参数映射 (gender_hint 从 config.extra_params 透传)
        gender_hint = self.config.extra_params.get("gender_hint")
        suggestion = suggest_kokoro_params(profile, lang, gender_hint=gender_hint)

        # 3) 合成到临时 wav
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out_wav = _Path(tmp.name)
        try:
            await self._synthesize_with_backend(text, suggestion.blend_voice, suggestion.speed, out_wav)

            # 4) pitch 移位 (ffmpeg 带式, v6 验证)
            final_wav = out_wav
            if abs(suggestion.pitch_st) >= 0.001:
                shifted_wav = _Path(str(out_wav).replace(".wav", "_pitch.wav"))
                ok = shift_semitones_path(out_wav, shifted_wav, suggestion.pitch_st, 24000)
                if ok:
                    final_wav = shifted_wav
                    out_wav.unlink(missing_ok=True)
                else:
                    logger.warning("[KokoroZeroShot] pitch 移位失败, 使用原始合成")

            # 5) 读 PCM int16 bytes
            import soundfile as sf
            audio_f32, sr = sf.read(str(final_wav), dtype="float32", always_2d=True)
            if audio_f32.shape[1] > 1:
                audio_f32 = audio_f32.mean(axis=1, keepdims=True)
            audio_i16 = np.clip(audio_f32 * 32767, -32768, 32767).astype(np.int16)
            audio_bytes = audio_i16.tobytes()

            # 6) 相似度估计
            sim = self._estimate_similarity(profile, suggestion)

            latency_ms = int((time.time() - t0) * 1000)
            return ZeroShotCloneResult(
                audio_data=audio_bytes,
                sample_rate=sr,
                latency_ms=latency_ms,
                text_processed=text[:100],
                language_detected=lang,
                voice_similarity=round(sim, 3),
                metadata={
                    "engine": "kokoro_zeroshot",
                    "blend_voice": suggestion.blend_voice,
                    "pitch_st": suggestion.pitch_st,
                    "speed": suggestion.speed,
                    "ref_f0_hz": round(profile.f0_median_hz or 0, 1),
                    "ref_syl_rate": round(profile.syllable_rate or 0, 2),
                    "analysis_confidence": profile.confidence,
                    "warnings": profile.warnings,
                },
            )
        finally:
            out_wav.unlink(missing_ok=True)
            _Path(str(out_wav).replace(".wav", "_pitch.wav")).unlink(missing_ok=True)


# 导入 ReferenceAudioProfile 用于类型注解 (避免循环)
from .reference_analysis import ReferenceAudioProfile, KokoroCloneSuggestion
import numpy as np
