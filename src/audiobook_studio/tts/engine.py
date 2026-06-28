"""TTS Engine Abstraction Layer (Issue 1.1).

Provides abstract base class TTSEngine with standardized interface for all TTS backends:
- Kokoro-ONNX (local CPU)
- VoxCPM2 (GPU with INT8/FP16 quantization)
- Edge-TTS, Azure TTS, GCP TTS (cloud)
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class VoiceInfo:
    """Information about a TTS voice."""

    voice_id: str
    name: str
    language: str
    gender: str = "neutral"
    age_range: str = "adult"
    description: str = ""
    sample_rate: int = 24000
    supports_prosody: bool = True
    supports_reference_audio: bool = False
    engine: str = ""


@dataclass
class SynthesisResult:
    """Result of TTS synthesis operation."""

    audio_path: str
    duration_ms: int
    engine: str
    voice_id: str
    text_hash: str
    sample_rate: int = 24000
    channels: int = 1
    metadata: Optional[Dict] = None


class TTSEngine(ABC):
    """Abstract base class for TTS engines.

    All TTS backends must implement this interface.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cpu",
        sample_rate: int = 24000,
        mock_mode: bool = False,
        **kwargs,
    ):
        self.model_path = model_path
        self.device = device
        self.sample_rate = sample_rate
        self.mock_mode = mock_mode
        self.kwargs = kwargs
        self._voices_cache: Optional[List[VoiceInfo]] = None
        self._initialized = False

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Unique identifier for this engine (e.g., 'kokoro', 'voxcpmp2', 'edge')."""
        pass

    @property
    @abstractmethod
    def supports_streaming(self) -> bool:
        """Whether this engine supports streaming synthesis."""
        pass

    @property
    @abstractmethod
    def supports_batch(self) -> bool:
        """Whether this engine supports batch synthesis."""
        pass

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the engine (load models, warm up, etc.)."""
        pass

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        prosody: Optional[Dict] = None,
        reference_audio: Optional[str] = None,
        **kwargs,
    ) -> SynthesisResult:
        """Synthesize text to speech.

        Args:
            text: Text to synthesize
            voice_id: Voice identifier
            output_path: Output file path
            prosody: Prosody parameters (rate, pitch, volume)
            reference_audio: Optional reference audio for voice cloning/anchoring
            **kwargs: Engine-specific parameters

        Returns:
            SynthesisResult with audio file path and metadata
        """
        pass

    @abstractmethod
    def get_voices(self) -> List[VoiceInfo]:
        """Get list of available voices for this engine."""
        pass

    @abstractmethod
    def estimate_duration(self, text: str, voice_id: str, **kwargs) -> int:
        """Estimate audio duration in milliseconds for given text.

        Args:
            text: Text to synthesize
            voice_id: Voice identifier
            **kwargs: Engine-specific parameters

        Returns:
            Estimated duration in milliseconds
        """
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """Clean up resources (unload models, close connections)."""
        pass

    def is_available(self) -> bool:
        """Check if engine is available (models loaded, dependencies met)."""
        return self._initialized

    def get_engine_info(self) -> Dict:
        """Get engine metadata for routing decisions."""
        return {
            "engine": self.engine_name,
            "device": self.device,
            "sample_rate": self.sample_rate,
            "supports_streaming": self.supports_streaming,
            "supports_batch": self.supports_batch,
            "voice_count": len(self.get_voices()),
            "initialized": self._initialized,
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(engine={self.engine_name}, device={self.device}, initialized={self._initialized})>"


class EngineRegistry:
    """Registry for managing TTS engine instances."""

    def __init__(self):
        self._engines: Dict[str, TTSEngine] = {}
        self._default_engine: Optional[str] = None

    def register(self, engine: TTSEngine, set_as_default: bool = False) -> None:
        """Register a TTS engine."""
        self._engines[engine.engine_name] = engine
        if set_as_default or self._default_engine is None:
            self._default_engine = engine.engine_name
        logger.info(f"Registered TTS engine: {engine.engine_name}")

    def unregister(self, engine_name: str) -> None:
        """Unregister a TTS engine."""
        if engine_name in self._engines:
            del self._engines[engine_name]
            if self._default_engine == engine_name:
                self._default_engine = (
                    next(iter(self._engines)) if self._engines else None
                )
            logger.info(f"Unregistered TTS engine: {engine_name}")

    def get(self, engine_name: str) -> Optional[TTSEngine]:
        """Get engine by name."""
        return self._engines.get(engine_name)

    def get_default(self) -> Optional[TTSEngine]:
        """Get default engine."""
        if self._default_engine:
            return self._engines.get(self._default_engine)
        return next(iter(self._engines.values())) if self._engines else None

    def list_engines(self) -> List[Dict]:
        """List all registered engines with their info."""
        return [engine.get_engine_info() for engine in self._engines.values()]

    def get_available_engines(self) -> List[str]:
        """Get names of available (initialized) engines."""
        return [name for name, engine in self._engines.items() if engine.is_available()]

    async def initialize_all(self) -> None:
        """Initialize all registered engines."""
        for engine in self._engines.values():
            try:
                await engine.initialize()
            except Exception as e:
                logger.error(f"Failed to initialize engine {engine.engine_name}: {e}")

    async def cleanup_all(self) -> None:
        """Clean up all registered engines."""
        for engine in self._engines.values():
            try:
                await engine.cleanup()
            except Exception as e:
                logger.error(f"Failed to cleanup engine {engine.engine_name}: {e}")


# Backward compatibility shims (DEPRECATED)
# Use get_app_container().get(EngineRegistry) instead
def get_engine_registry() -> EngineRegistry:
    """Deprecated: use get_app_container().get(EngineRegistry)"""
    from ..di import get_app_container

    return get_app_container().get(EngineRegistry)


def register_engine(engine: TTSEngine, set_as_default: bool = False) -> None:
    """Deprecated: use get_app_container().get(EngineRegistry).register()"""
    get_engine_registry().register(engine, set_as_default)


def get_engine(engine_name: str) -> Optional[TTSEngine]:
    """Deprecated: use get_app_container().get(EngineRegistry).get()"""
    return get_engine_registry().get(engine_name)


async def initialize_all_engines() -> None:
    """Deprecated: use get_app_container().get(EngineRegistry).initialize_all()"""
    await get_engine_registry().initialize_all()


async def cleanup_all_engines() -> None:
    """Deprecated: use get_app_container().get(EngineRegistry).cleanup_all()"""
    await get_engine_registry().cleanup_all()
