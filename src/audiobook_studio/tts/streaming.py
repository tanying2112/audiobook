"""Streaming TTS - First-byte latency < 500ms.

Supports multiple streaming TTS engines:
- CosyVoice-Stream (Chinese/English, high quality)
- Seed-TTS-Stream (ByteDance, zero-shot cloning)
- MeloTTS-Stream (Multi-language, fast)

Provides WebSocket-compatible chunked audio streaming.
"""

import asyncio
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator, Generator, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class StreamingTTSConfig:
    """Configuration for Streaming TTS Engine."""

    engine: str  # "cosyvoice_stream", "seed_tts_stream", "melotts_stream"
    host: str = "localhost"
    port: int = 5000
    sample_rate: int = 24000
    chunk_size_ms: int = 100  # Size of each audio chunk in ms
    voice_id: str = "default"
    speed: float = 1.0
    timeout: int = 30  # seconds
    # Engine-specific options
    extra_params: dict = field(default_factory=dict)

    @property
    def base_url(self) -> str:
        """Get the base URL for the streaming TTS server."""
        return f"http://{self.host}:{self.port}"

    @property
    def mock_mode(self) -> bool:
        """Check if mock mode is enabled via environment variable."""
        return os.getenv("MOCK_TTS", "false").lower() == "true"

    @property
    def chunk_samples(self) -> int:
        """Calculate number of samples per chunk."""
        return int(self.sample_rate * self.chunk_size_ms / 1000)


@dataclass
class StreamingTTSResult:
    """Result of a streaming TTS chunk."""

    audio_data: bytes  # Raw PCM audio data (16-bit)
    sample_rate: int
    chunk_index: int
    is_final: bool
    latency_ms: int
    text_processed: str = ""
    metadata: dict = field(default_factory=dict)


class BaseStreamingTTSEngine(ABC):
    """Abstract base class for streaming TTS engines."""

    def __init__(self, config: StreamingTTSConfig):
        self.config = config
        self._client = None
        self._init_client()

    @abstractmethod
    def _init_client(self):
        """Initialize the engine-specific client."""
        pass

    @abstractmethod
    def _synthesize_stream_impl(
        self, text: str, voice_id: Optional[str] = None, **kwargs
    ) -> Generator[StreamingTTSResult, None, None]:
        """Implementation-specific streaming synthesis."""
        pass

    @abstractmethod
    async def _synthesize_stream_async_impl(
        self, text: str, voice_id: Optional[str] = None, **kwargs
    ) -> AsyncGenerator[StreamingTTSResult, None]:
        """Implementation-specific async streaming synthesis."""
        pass

    def synthesize_stream(
        self, text: str, voice_id: Optional[str] = None, **kwargs
    ) -> Generator[StreamingTTSResult, None, None]:
        """
        Synthesize text to streaming audio chunks.

        Args:
            text: Text to synthesize
            voice_id: Optional voice identifier
            **kwargs: Additional engine-specific parameters

        Yields:
            StreamingTTSResult chunks
        """
        if self.config.mock_mode:
            yield from self._mock_stream(text, voice_id)
        else:
            yield from self._synthesize_stream_impl(text, voice_id, **kwargs)

    async def synthesize_stream_async(
        self, text: str, voice_id: Optional[str] = None, **kwargs
    ) -> AsyncGenerator[StreamingTTSResult, None]:
        """
        Async version of synthesize_stream.

        Args:
            text: Text to synthesize
            voice_id: Optional voice identifier
            **kwargs: Additional engine-specific parameters

        Yields:
            StreamingTTSResult chunks
        """
        if self.config.mock_mode:
            async for chunk in self._mock_stream_async(text, voice_id):
                yield chunk
        else:
            async for chunk in self._synthesize_stream_async_impl(text, voice_id, **kwargs):
                yield chunk

    def synthesize(self, text: str, voice_id: Optional[str] = None, **kwargs) -> bytes:
        """
        Synthesize full text to audio (non-streaming, for backward compatibility).

        Args:
            text: Text to synthesize
            voice_id: Optional voice identifier
            **kwargs: Additional engine-specific parameters

        Returns:
            Complete audio data as bytes
        """
        chunks = list(self.synthesize_stream(text, voice_id, **kwargs))
        return b"".join(chunk.audio_data for chunk in chunks)

    def _mock_stream(self, text: str, voice_id: Optional[str] = None) -> Generator[StreamingTTSResult, None, None]:
        """Generate mock audio chunks for testing."""
        if not text:
            return

        chunk_samples = self.config.chunk_samples
        # Generate ~2 seconds of audio
        total_samples = self.config.sample_rate * 2
        num_chunks = max(1, total_samples // chunk_samples)

        # Generate sine wave as mock audio
        t = np.linspace(0, 2, total_samples, endpoint=False)
        audio = np.sin(2 * np.pi * 440 * t) * 0.3  # 440Hz tone
        audio_int16 = (audio * 32767).astype(np.int16)
        audio_bytes = audio_int16.tobytes()

        # Split into chunks
        chunk_bytes = chunk_samples * 2  # 16-bit = 2 bytes per sample
        for i in range(num_chunks):
            start = i * chunk_bytes
            end = min(start + chunk_bytes, len(audio_bytes))
            chunk_data = audio_bytes[start:end]

            is_final = i == num_chunks - 1
            yield StreamingTTSResult(
                audio_data=chunk_data,
                sample_rate=self.config.sample_rate,
                chunk_index=i,
                is_final=is_final,
                latency_ms=10 if i == 0 else 5,  # First chunk has higher latency
                text_processed=text[:50] if i == 0 else "",
                metadata={"mock": True, "voice_id": voice_id or self.config.voice_id},
            )

    async def _mock_stream_async(
        self, text: str, voice_id: Optional[str] = None
    ) -> AsyncGenerator[StreamingTTSResult, None]:
        """Async version of mock stream."""
        for chunk in self._mock_stream(text, voice_id):
            yield chunk
            await asyncio.sleep(0.01)  # Simulate network delay


class CosyVoiceStreamEngine(BaseStreamingTTSEngine):
    """CosyVoice Streaming TTS Engine.

    Features:
    - Chinese/English bilingual
    - High quality (24kHz)
    - Low latency streaming
    - Zero-shot voice cloning (optional)
    """

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
            logger.info(f"Initialized CosyVoice-Stream client: {self.config.base_url}")
        except ImportError:
            logger.error("httpx not installed for CosyVoice-Stream")
            raise

    def _synthesize_stream_impl(
        self, text: str, voice_id: Optional[str] = None, **kwargs
    ) -> Generator[StreamingTTSResult, None, None]:
        """Stream synthesis via CosyVoice HTTP API."""
        import httpx

        voice = voice_id or self.config.voice_id

        with httpx.Client(base_url=self.config.base_url, timeout=self.config.timeout) as client:
            response = client.post(
                "/tts/stream",
                json={
                    "text": text,
                    "voice_id": voice,
                    "speed": self.config.speed,
                    "sample_rate": self.config.sample_rate,
                    "chunk_size_ms": self.config.chunk_size_ms,
                    **self.config.extra_params,
                    **kwargs,
                },
            )
            response.raise_for_status()

            # Parse streaming response (assuming chunked transfer encoding)
            chunk_index = 0
            first_chunk = True
            start_time = time.time()

            for line in response.iter_lines():
                if not line:
                    continue

                # Parse JSON chunk
                import json

                chunk_data = json.loads(line)

                audio_bytes = bytes.fromhex(chunk_data["audio_hex"])
                is_final = chunk_data.get("is_final", False)

                latency = int((time.time() - start_time) * 1000) if first_chunk else 0
                first_chunk = False

                yield StreamingTTSResult(
                    audio_data=audio_bytes,
                    sample_rate=chunk_data.get("sample_rate", self.config.sample_rate),
                    chunk_index=chunk_index,
                    is_final=is_final,
                    latency_ms=latency,
                    text_processed=chunk_data.get("text", "") if chunk_index == 0 else "",
                    metadata={"engine": "cosyvoice_stream", "voice_id": voice},
                )
                chunk_index += 1

    async def _synthesize_stream_async_impl(
        self, text: str, voice_id: Optional[str] = None, **kwargs
    ) -> AsyncGenerator[StreamingTTSResult, None]:
        """Async stream synthesis via CosyVoice HTTP API."""
        import json

        voice = voice_id or self.config.voice_id  # noqa: E303

        async with self._client as client:
            async with client.stream(
                "POST",
                "/tts/stream",
                json={
                    "text": text,
                    "voice_id": voice,
                    "speed": self.config.speed,
                    "sample_rate": self.config.sample_rate,
                    "chunk_size_ms": self.config.chunk_size_ms,
                    **self.config.extra_params,
                    **kwargs,
                },
            ) as response:
                response.raise_for_status()

                chunk_index = 0
                first_chunk = True
                start_time = time.time()

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    chunk_data = json.loads(line)
                    audio_bytes = bytes.fromhex(chunk_data["audio_hex"])
                    is_final = chunk_data.get("is_final", False)

                    latency = int((time.time() - start_time) * 1000) if first_chunk else 0
                    first_chunk = False

                    yield StreamingTTSResult(
                        audio_data=audio_bytes,
                        sample_rate=chunk_data.get("sample_rate", self.config.sample_rate),
                        chunk_index=chunk_index,
                        is_final=is_final,
                        latency_ms=latency,
                        text_processed=chunk_data.get("text", "") if chunk_index == 0 else "",
                        metadata={"engine": "cosyvoice_stream", "voice_id": voice},
                    )
                    chunk_index += 1


class SeedTTSStreamEngine(BaseStreamingTTSEngine):
    """Seed-TTS Streaming TTS Engine (ByteDance).

    Features:
    - Zero-shot voice cloning
    - Cross-lingual synthesis
    - High quality streaming
    """

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
            logger.info(f"Initialized Seed-TTS-Stream client: {self.config.base_url}")
        except ImportError:
            logger.error("httpx not installed for Seed-TTS-Stream")
            raise

    def _synthesize_stream_impl(
        self, text: str, voice_id: Optional[str] = None, **kwargs
    ) -> Generator[StreamingTTSResult, None, None]:
        """Stream synthesis via Seed-TTS HTTP API."""
        import json

        import httpx

        voice = voice_id or self.config.voice_id
        reference_audio = kwargs.get("reference_audio")  # For voice cloning

        with httpx.Client(base_url=self.config.base_url, timeout=self.config.timeout) as client:
            payload = {
                "text": text,
                "voice_id": voice,
                "speed": self.config.speed,
                **self.config.extra_params,
                **kwargs,
            }
            if reference_audio:
                payload["reference_audio"] = reference_audio

            response = client.post("/tts/stream", json=payload)
            response.raise_for_status()

            chunk_index = 0
            first_chunk = True
            start_time = time.time()

            for line in response.iter_lines():
                if not line:
                    continue

                chunk_data = json.loads(line)
                audio_bytes = bytes.fromhex(chunk_data["audio_hex"])
                is_final = chunk_data.get("is_final", False)

                latency = int((time.time() - start_time) * 1000) if first_chunk else 0
                first_chunk = False

                yield StreamingTTSResult(
                    audio_data=audio_bytes,
                    sample_rate=chunk_data.get("sample_rate", self.config.sample_rate),
                    chunk_index=chunk_index,
                    is_final=is_final,
                    latency_ms=latency,
                    text_processed=chunk_data.get("text", "") if chunk_index == 0 else "",
                    metadata={"engine": "seed_tts_stream", "voice_id": voice},
                )
                chunk_index += 1

    async def _synthesize_stream_async_impl(
        self, text: str, voice_id: Optional[str] = None, **kwargs
    ) -> AsyncGenerator[StreamingTTSResult, None]:
        """Async stream synthesis via Seed-TTS HTTP API."""
        import json

        voice = voice_id or self.config.voice_id  # noqa: E303
        reference_audio = kwargs.get("reference_audio")

        async with self._client as client:
            payload = {
                "text": text,
                "voice_id": voice,
                "speed": self.config.speed,
                **self.config.extra_params,
                **kwargs,
            }
            if reference_audio:
                payload["reference_audio"] = reference_audio

            async with client.stream("POST", "/tts/stream", json=payload) as response:
                response.raise_for_status()

                chunk_index = 0
                first_chunk = True
                start_time = time.time()

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    chunk_data = json.loads(line)
                    audio_bytes = bytes.fromhex(chunk_data["audio_hex"])
                    is_final = chunk_data.get("is_final", False)

                    latency = int((time.time() - start_time) * 1000) if first_chunk else 0
                    first_chunk = False

                    yield StreamingTTSResult(
                        audio_data=audio_bytes,
                        sample_rate=chunk_data.get("sample_rate", self.config.sample_rate),
                        chunk_index=chunk_index,
                        is_final=is_final,
                        latency_ms=latency,
                        text_processed=chunk_data.get("text", "") if chunk_index == 0 else "",
                        metadata={"engine": "seed_tts_stream", "voice_id": voice},
                    )
                    chunk_index += 1


class MeloTTSStreamEngine(BaseStreamingTTSEngine):
    """MeloTTS Streaming TTS Engine.

    Features:
    - Multi-language (Chinese, English, Japanese, Korean, Spanish, French)
    - Fast inference
    - Low resource usage
    - Good quality for real-time applications
    """

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
            logger.info(f"Initialized MeloTTS-Stream client: {self.config.base_url}")
        except ImportError:
            logger.error("httpx not installed for MeloTTS-Stream")
            raise

    def _synthesize_stream_impl(
        self, text: str, voice_id: Optional[str] = None, **kwargs
    ) -> Generator[StreamingTTSResult, None, None]:
        """Stream synthesis via MeloTTS HTTP API."""
        import json

        import httpx

        voice = voice_id or self.config.voice_id
        language = kwargs.get("language", "ZH")  # ZH, EN, JP, KR, ES, FR

        with httpx.Client(base_url=self.config.base_url, timeout=self.config.timeout) as client:
            response = client.post(
                "/tts/stream",
                json={
                    "text": text,
                    "speaker": voice,
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

                chunk_data = json.loads(line)
                audio_bytes = bytes.fromhex(chunk_data["audio_hex"])
                is_final = chunk_data.get("is_final", False)

                latency = int((time.time() - start_time) * 1000) if first_chunk else 0
                first_chunk = False

                yield StreamingTTSResult(
                    audio_data=audio_bytes,
                    sample_rate=chunk_data.get("sample_rate", self.config.sample_rate),
                    chunk_index=chunk_index,
                    is_final=is_final,
                    latency_ms=latency,
                    text_processed=chunk_data.get("text", "") if chunk_index == 0 else "",
                    metadata={"engine": "melotts_stream", "voice_id": voice, "language": language},
                )
                chunk_index += 1

    async def _synthesize_stream_async_impl(
        self, text: str, voice_id: Optional[str] = None, **kwargs
    ) -> AsyncGenerator[StreamingTTSResult, None]:
        """Async stream synthesis via MeloTTS HTTP API."""
        import json

        voice = voice_id or self.config.voice_id  # noqa: E303
        language = kwargs.get("language", "ZH")

        async with self._client as client:
            async with client.stream(
                "POST",
                "/tts/stream",
                json={
                    "text": text,
                    "speaker": voice,
                    "language": language,
                    "speed": self.config.speed,
                    "sample_rate": self.config.sample_rate,
                    **self.config.extra_params,
                    **kwargs,
                },
            ) as response:
                response.raise_for_status()

                chunk_index = 0
                first_chunk = True
                start_time = time.time()

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    chunk_data = json.loads(line)
                    audio_bytes = bytes.fromhex(chunk_data["audio_hex"])
                    is_final = chunk_data.get("is_final", False)

                    latency = int((time.time() - start_time) * 1000) if first_chunk else 0
                    first_chunk = False

                    yield StreamingTTSResult(
                        audio_data=audio_bytes,
                        sample_rate=chunk_data.get("sample_rate", self.config.sample_rate),
                        chunk_index=chunk_index,
                        is_final=is_final,
                        latency_ms=latency,
                        text_processed=chunk_data.get("text", "") if chunk_index == 0 else "",
                        metadata={"engine": "melotts_stream", "voice_id": voice, "language": language},
                    )
                    chunk_index += 1


class StreamingTTSEngine:
    """Unified Streaming TTS Engine facade.

    Routes to appropriate engine based on config.engine.
    """

    def __init__(self, config: StreamingTTSConfig):
        self.config = config
        self._engine = self._create_engine(config)

    def _create_engine(self, config: StreamingTTSConfig) -> BaseStreamingTTSEngine:
        """Create the appropriate engine instance."""
        engine_map = {
            "cosyvoice_stream": CosyVoiceStreamEngine,
            "seed_tts_stream": SeedTTSStreamEngine,
            "melotts_stream": MeloTTSStreamEngine,
        }

        engine_class = engine_map.get(config.engine)
        if not engine_class:
            raise ValueError(f"Unsupported streaming TTS engine: {config.engine}")

        return engine_class(config)

    # Delegate methods to underlying engine
    def synthesize_stream(
        self, text: str, voice_id: Optional[str] = None, **kwargs
    ) -> Generator[StreamingTTSResult, None, None]:
        return self._engine.synthesize_stream(text, voice_id, **kwargs)

    def synthesize_stream_async(
        self, text: str, voice_id: Optional[str] = None, **kwargs
    ) -> AsyncGenerator[StreamingTTSResult, None]:
        return self._engine.synthesize_stream_async(text, voice_id, **kwargs)

    def synthesize(self, text: str, voice_id: Optional[str] = None, **kwargs) -> bytes:
        return self._engine.synthesize(text, voice_id, **kwargs)


def create_streaming_tts_engine(config: StreamingTTSConfig) -> StreamingTTSEngine:
    """Factory function to create StreamingTTSEngine."""
    return StreamingTTSEngine(config)
