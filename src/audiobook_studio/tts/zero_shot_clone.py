"""Zero-Shot Voice Cloning - Cross-lingual voice transfer.

Supports multiple zero-shot cloning engines:
- XTTS-v2 (Coqui) - 17 languages, high quality, Apache 2.0
- OpenVoice V2 (MyShell) - Fast, tone color cloning, multi-lingual
- CosyVoice Clone (FunAudioLLM) - Chinese/English, streaming, zero-shot

Provides unified interface for voice cloning with reference audio.
"""

import asyncio
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator, Generator, List, Optional

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

    def clone(
        self, text: str, reference_audio: bytes, language: Optional[str] = None, **kwargs
    ) -> ZeroShotCloneResult:
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

    def _mock_clone(
        self, text: str, reference_audio: bytes, language: Optional[str] = None
    ) -> ZeroShotCloneResult:
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
        "en", "es", "fr", "de", "it", "pt", "pl", "tr",
        "ru", "nl", "cs", "ar", "zh", "ja", "hu", "ko", "hi"
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

    def _clone_impl(
        self, text: str, reference_audio: bytes, language: str, **kwargs
    ) -> ZeroShotCloneResult:
        import httpx
        import base64

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
        import httpx
        import base64

        if language == "auto":
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
        import httpx
        import base64

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

    SUPPORTED_LANGUAGES = {
        "en", "zh", "ja", "ko", "fr", "de", "es", "it", "pt", "ru"
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
            logger.info(f"Initialized OpenVoice V2 client: {self.config.base_url}")
        except ImportError:
            logger.error("httpx not installed for OpenVoice V2")
            raise

    def _clone_impl(
        self, text: str, reference_audio: bytes, language: str, **kwargs
    ) -> ZeroShotCloneResult:
        import httpx
        import base64

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
        import httpx
        import base64

        if language == "auto":
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
        import httpx
        import base64

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
                    metadata={"engine": "openvoice_v2", "language": language, "chunk": chunk_index, "is_final": is_final},
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

    def _clone_impl(
        self, text: str, reference_audio: bytes, language: str, **kwargs
    ) -> ZeroShotCloneResult:
        import httpx
        import base64

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
        import httpx
        import base64

        if language == "auto":
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
        import httpx
        import base64

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
                    metadata={"engine": "cosyvoice_clone", "language": language, "chunk": chunk_index, "is_final": is_final},
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
        }

        engine_class = engine_map.get(config.engine)
        if not engine_class:
            raise ValueError(f"Unsupported zero-shot clone engine: {config.engine}")

        return engine_class(config)

    # Delegate methods to underlying engine
    def clone(
        self, text: str, reference_audio: bytes, language: Optional[str] = None, **kwargs
    ) -> ZeroShotCloneResult:
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
