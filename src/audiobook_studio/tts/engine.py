"""Unified TTS Engine interface for Audiobook Studio.

Consolidates local engines, remote engines, and scheduling layer
into a single protocol with optional async support.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


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


@dataclass(frozen=True)
class TTSVoiceAnchor:
    """Reference to a pre-trained voice profile."""

    voice_id: str
    speaker_name: Optional[str] = None
    language: str = "zh-CN"
    reference_audio_path: Optional[str] = None

    def __post_init__(self):
        if not self.voice_id or not self.voice_id.strip():
            raise ValueError("voice_id must be non-empty")


@dataclass(frozen=True)
class TTSProsody:
    """Prosody controls for TTS synthesis."""

    rate: float = 1.0      # Speech rate multiplier (0.5-2.0)
    pitch: float = 0.0     # Pitch shift in semitones (-12 to +12)
    volume: float = 0.0    # Volume gain in dB (-20 to +20)
    emotion: Optional[str] = None  # Emotional tag (happy, sad, neutral, etc.)


@dataclass(frozen=True)
class TTSTaskPayload:
    """Payload for TTS synthesis request."""

    text: str
    voice_anchor: TTSVoiceAnchor
    prosody: Optional[TTSProsody] = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.text or not self.text.strip():
            raise ValueError("text must be non-empty")
        if not isinstance(self.voice_anchor, TTSVoiceAnchor):
            raise TypeError("voice_anchor must be TTSVoiceAnchor instance")


@dataclass
class TTSTaskResult:
    """Result of TTS synthesis."""

    task_id: str
    status: str  # PENDING, RUNNING, DONE, FAILED
    audio_path: Optional[str] = None          # R2 object key or local path
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    dnsmos_score: Optional[float] = None
    asr_wer: Optional[float] = None
    speaker_similarity: Optional[float] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    engine: str = "unknown"
    text_hash: Optional[str] = None


@dataclass
class TTSTaskStatus:
    """Status snapshot for polling."""

    task_id: str
    status: str
    progress: Optional[float] = None
    error_message: Optional[str] = None
    dnsmos_score: Optional[float] = None


@runtime_checkable
class TTSEngine(Protocol):
    """Unified TTS Engine protocol.

    Supports:
    - Local synthesis (Kokoro, Edge-TTS, VoxCPM2 local)
    - Remote scheduling (Hermes layer via submit/status/result)
    - Both sync and async operations

    Implementations should provide at least `synthesize()` or `submit()`.
    """

    @property
    def engine_name(self) -> str:
        """Unique identifier for this engine (e.g., 'kokoro', 'edge', 'voxcpm2')."""
        ...

    @property
    def is_available(self) -> bool:
        """Check if engine is ready (model loaded, connection healthy)."""
        ...

    async def synthesize(
        self,
        payload: TTSTaskPayload,
        output_path: Path,
    ) -> TTSTaskResult:
        """Synthesize text to speech synchronously (local engines).

        Args:
            payload: Synthesis specification
            output_path: Where to save the audio file

        Returns:
            TTSTaskResult with audio_path and metadata
        """
        ...

    async def submit(self, task_id: str, payload: TTSTaskPayload) -> bool:
        """Submit a task to remote scheduler (async engines).

        Args:
            task_id: Unique task identifier
            payload: Synthesis specification

        Returns:
            True if accepted for scheduling
        """
        ...

    async def get_status(self, task_id: str) -> TTSTaskStatus:
        """Poll for task status (async engines)."""
        ...

    async def get_result(self, task_id: str) -> TTSTaskResult:
        """Get full result when task is DONE/FAILED (async engines)."""
        ...

    async def cancel(self, task_id: str) -> bool:
        """Cancel a pending/running task (async engines)."""
        ...

    async def health_check(self) -> dict[str, Any]:
        """Check engine health and return status info."""
        ...

    async def close(self) -> None:
        """Release resources (connections, models, etc.)."""
        ...


# ---------------------------------------------------------------------------
# Base implementation with common utilities
# ---------------------------------------------------------------------------

import hashlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

logger = logging.getLogger(__name__)


class BaseTTSEngine:
    """Base class with common functionality for TTS engines."""

    def __init__(
        self,
        output_dir: str = "./output",
        max_concurrent: int = 2,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    def _generate_task_id(self) -> str:
        return f"tts_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{hashlib.md5(str(datetime.now()).encode()).hexdigest()[:8]}"

    def _build_output_path(self, task_id: str, voice_id: str) -> Path:
        return self.output_dir / f"{task_id}_{voice_id}.mp3"

    def _map_prosody(self, prosody: Optional[TTSProsody]) -> Optional[dict]:
        if prosody is None:
            return None
        return {
            "rate": prosody.rate,
            "pitch": prosody.pitch,
            "volume": prosody.volume,
            "emotion": prosody.emotion,
        }

    def _create_result(
        self,
        task_id: str,
        status: str,
        audio_path: Optional[str] = None,
        duration_ms: Optional[int] = None,
        error_message: Optional[str] = None,
        engine: str = "unknown",
        started_at: Optional[str] = None,
        text_hash: Optional[str] = None,
        **kwargs,
    ) -> TTSTaskResult:
        return TTSTaskResult(
            task_id=task_id,
            status=status,
            audio_path=audio_path,
            duration_ms=duration_ms,
            error_message=error_message,
            engine=engine,
            started_at=started_at,
            completed_at=datetime.now(UTC).isoformat() if status in ("DONE", "FAILED") else None,
            text_hash=text_hash,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Tenacity-based retry utilities (replaces CircuitBreaker + RateLimiter classes)
# ---------------------------------------------------------------------------

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception_type,
    before_sleep_log,
    after_log,
)

# Common retry policy for external engines
def tts_retry_policy(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 10.0,
):
    """Apply to async methods for automatic retry with exponential backoff."""
    return retry(
        reraise=True,
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential_jitter(initial=min_wait, max=max_wait),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, IOError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        after=after_log(logger, logging.INFO),
    )


def rate_limiter(max_calls: int, period: float = 60.0):
    """Decorator for rate limiting (simple token bucket).

    Usage:
        @rate_limiter(max_calls=60, period=60.0)
        async def synthesize(self, ...):
            ...
    """
    import time
    from functools import wraps

    calls_made = 0
    window_start = time.time()
    lock = asyncio.Lock()

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            nonlocal calls_made, window_start
            async with lock:
                now = time.time()
                if now - window_start >= period:
                    calls_made = 0
                    window_start = now
                if calls_made >= max_calls:
                    wait_time = period - (now - window_start)
                    if wait_time > 0:
                        logger.warning(f"Rate limit hit, waiting {wait_time:.1f}s")
                        await asyncio.sleep(wait_time)
                    calls_made = 0
                    window_start = time.time()
                calls_made += 1
            return await func(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Engine Registry (replaces PortFactory + PortContext + Global Port)
# ---------------------------------------------------------------------------

class EngineRegistry:
    """Simple registry for TTS engines with config-driven loading.

    Usage:
        registry = EngineRegistry()
        registry.config = {"kokoro": {"output_dir": "./output", "max_concurrent": 2}}
        await registry.initialize()

        engine = registry.get("kokoro")
        result = await engine.synthesize(payload, Path("out.mp3"))
    """

    def __init__(self):
        self._engines: dict[str, TTSEngine] = {}
        self._config: dict = {}
        self._lock = asyncio.Lock()
        self._default_engine: Optional[str] = None

    @property
    def config(self) -> dict:
        return self._config

    @config.setter
    def config(self, value: dict):
        self._config = value

    async def register(
        self,
        engine: TTSEngine,
        name: Optional[str] = None,
        set_as_default: bool = False,
    ) -> None:
        """Register an engine instance."""
        async with self._lock:
            engine_name = name or engine.engine_name
            self._engines[engine_name] = engine
            if set_as_default or self._default_engine is None:
                self._default_engine = engine_name

    async def initialize(self, config: Optional[dict] = None) -> None:
        """Initialize engines from config dict.

        Config format:
            {
                "kokoro": {"output_dir": "./output", "max_concurrent": 2, "model_path": "..."},
                "edge": {"output_dir": "./output", "max_concurrent": 4, "voice": "zh-CN-XiaoxiaoNeural"},
            }
        """
        if config:
            self._config = config

        # Import backend factories here to avoid circular imports
        from .kokoro_backend import create_kokoro_engine
        from .edge_tts_engine import create_edge_tts_engine
        # from .voxcpm2_backend import create_voxcpm2_engine

        engine_factories = {
            "kokoro": create_kokoro_engine,
            "edge": create_edge_tts_engine,
            # "voxcpm2": create_voxcpm2_engine,
        }

        async with self._lock:
            for engine_name, engine_config in self._config.items():
                if engine_name in engine_factories:
                    factory = engine_factories[engine_name]
                    engine = factory(**engine_config)
                    await self.register(engine, engine_name)
                else:
                    logger.warning(f"Unknown engine type: {engine_name}")

        # PERF-001: Do NOT eagerly initialize engines here.
        # Each engine auto-initializes on first synthesize() call.
        # Use warmup() to pre-load explicitly before serving traffic.

    async def warmup(self) -> dict[str, bool]:
        """Pre-initialize all registered engines (for warmup endpoint)."""
        results: dict[str, bool] = {}
        for name, engine in self._engines.items():
            if not getattr(engine, "_loaded", False):
                try:
                    await engine.initialize()
                    results[name] = True
                    logger.info(f"Engine {name} warmed up successfully")
                except Exception as e:
                    results[name] = False
                    logger.error(f"Failed to warm up engine {name}: {e}")
            else:
                results[name] = True
        return results

    @property
    def is_ready(self) -> bool:
        """True when all registered engines have been loaded."""
        if not self._engines:
            return False
        return all(getattr(e, "_loaded", False) for e in self._engines.values())

    @property
    def ready_status(self) -> dict[str, bool]:
        """Per-engine load status for /health/ready reporting."""
        return {name: getattr(e, "_loaded", False) for name, e in self._engines.items()}

    def get(self, name: str) -> Optional[TTSEngine]:
        """Get engine by name."""
        return self._engines.get(name)

    def get_default(self) -> Optional[TTSEngine]:
        """Get default engine."""
        if self._default_engine:
            return self._engines.get(self._default_engine)
        return next(iter(self._engines.values())) if self._engines else None

    def list_engines(self) -> list[str]:
        """List registered engine names."""
        return list(self._engines.keys())

    async def close_all(self) -> None:
        """Close all engines."""
        async with self._lock:
            for engine in self._engines.values():
                try:
                    await engine.close()
                except Exception as e:
                    logger.error(f"Error closing engine {engine.engine_name}: {e}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close_all()


def get_engine_registry() -> EngineRegistry:
    """Get global engine registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = EngineRegistry()
    return _global_registry


def set_engine_registry(registry: EngineRegistry) -> EngineRegistry:
    """Set global engine registry."""
    global _global_registry
    _global_registry = registry
    return _global_registry


def get_engine(name: str) -> Optional[TTSEngine]:
    """Get an engine by name from the global registry."""
    registry = get_engine_registry()
    return registry.get(name)


def register_engine(engine: TTSEngine, set_as_default: bool = False) -> None:
    """Register an engine in the global registry."""
    registry = get_engine_registry()
    registry.register(engine, set_as_default=set_as_default)


async def initialize_all_engines() -> None:
    """Initialize all registered engines."""
    registry = get_engine_registry()
    for engine in registry._engines.values():
        await engine.initialize()


async def cleanup_all_engines() -> None:
    """Cleanup all registered engines."""
    registry = get_engine_registry()
    await registry.close_all()