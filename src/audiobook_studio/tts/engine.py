"""Unified TTS Engine interface for Audiobook Studio.

Consolidates local engines, remote engines, and scheduling layer
into a single protocol with optional async support.
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol, runtime_checkable


@dataclass
class LicenseMetadata:
    """TTS 引擎商用许可元数据 (P2.11).

    红线#1: commercial_use=None = 未核实 (诚实降级 warn, 非假声明);
    True 仅当官方 license 确允许商用; False 仅当官方明确仅非商用。
    仓库不替任何引擎假声明 (杜绝 P1.9 "True # TODO" 复发) —— 由核实过官方
    model card/license 的维护者填 config/tts_licenses.yaml 后传入。
    """

    commercial_use: Optional[bool] = None  # True=商用OK | False=仅非商用 | None=未核实
    license_name: Optional[str] = None
    note: str = ""
    verified_at: Optional[str] = None


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
    license_metadata: Optional[LicenseMetadata] = None  # P2.11: 商用许可 (缺失→None 诚实降级)


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

    rate: float = 1.0  # Speech rate multiplier (0.5-2.0)
    pitch: float = 0.0  # Pitch shift in semitones (-12 to +12)
    volume: float = 0.0  # Volume gain in dB (-20 to +20)
    emotion: Optional[str] = None  # Emotional tag (happy, sad, neutral, etc.)
    # P2.15 确定性: seed pinning 通道 (打通 VoxCPM2 generate(seed=) 出口)。
    # 红线#1: seed 只是开通道, **不等于**字节级可达 (cudnn/gemm 非确定性可能致不等);
    # None=未指定 (与改造前等价, 零回归); 仅当显式传整数时透传到 backend.generate。
    seed: Optional[int] = None


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
    audio_path: Optional[str] = None  # R2 object key or local path
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    dnsmos_score: Optional[float] = None
    asr_wer: Optional[float] = None
    speaker_similarity: Optional[float] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    engine: str = "unknown"
    text_hash: Optional[str] = None
    voice_id: Optional[str] = None


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

    async def stream(
        self,
        payload: TTSTaskPayload,
    ) -> AsyncIterator[bytes]:
        """Stream audio chunks for real-time playback.

        Args:
            payload: Synthesis specification

        Yields:
            Audio chunks as bytes (raw PCM or encoded format depending on engine)
        """
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

    async def stream(
        self,
        payload: TTSTaskPayload,
    ) -> AsyncIterator[bytes]:
        """Stream audio chunks for real-time playback.

        Default implementation raises NotImplementedError.
        Engines that support streaming should override this method.
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support streaming")


# ---------------------------------------------------------------------------
# Tenacity-based retry utilities (replaces CircuitBreaker + RateLimiter classes)
# ---------------------------------------------------------------------------

from tenacity import (
    after_log,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
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
        active_profile: Optional[str] = None,
    ) -> None:
        """Register an engine instance.

        P2.11 许可守门: 当传入 active_profile (非商用档触发严格守门) 时,
        经 license_guard 校验引擎商用许可。被标注 commercial_use=False 的引擎
        在商用路径被阻断 (诚实噪止, 不假装注册成功);
        commercial_use=None (未核实) 降级 warn 但放行 (红线#1: 不假声明也不误杀)。
        active_profile=None (调用方未提供) → 守门不触发, 行为同改造前 (零回归)。
        """
        if active_profile is not None:
            from .license_guard import register_guard

            if not register_guard(name or engine.engine_name, active_profile):
                logger.warning(
                    "license_guard 阻断引擎 %s 注册 (商用档 %s 下 commercial_use=False)",
                    name or engine.engine_name,
                    active_profile,
                )
                return
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
        from .edge_tts_engine import create_edge_tts_engine
        from .kokoro_backend import create_kokoro_backend
        from .piper_backend import create_piper_backend

        # from .voxcpm2_backend import create_voxcpm2_engine

        engine_factories = {
            "kokoro": create_kokoro_backend,
            "edge": create_edge_tts_engine,
            "piper": create_piper_backend,  # S2-4: preferred local engine (priority 0)
            # "voxcpm2": create_voxcpm2_engine,
        }

        # Merge plugin-registered TTS engine factories
        from ..plugins import get_plugin_manager

        plugin_mgr = get_plugin_manager()
        plugin_factories = plugin_mgr.get_tts_engine_factories()
        for engine_name, record in plugin_factories.items():
            engine_factories[engine_name] = record.factory

        for engine_name, engine_config in self._config.items():
            if engine_name in engine_factories:
                # P0 no-GPU safety: skip GPU-only engines when GPU backends are
                # disabled (free/no-GPU hosts must never instantiate an engine
                # they cannot run). Capability is read from the provider config;
                # unknown engines are assumed CPU and are not skipped.
                if _should_skip_engine(engine_name, _gpu_backends_enabled()):
                    logger.info(
                        "Skipping GPU engine %s (ENABLE_GPU_BACKENDS=false)",
                        engine_name,
                    )
                    continue
                factory = engine_factories[engine_name]
                # Factories are async coroutines (create + initialize the engine)
                engine = await factory(**engine_config)
                await self.register(engine, engine_name)  # register acquires self._lock internally
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


# ---------------------------------------------------------------------------
# S1-6: Real TTS readiness probe
# ---------------------------------------------------------------------------

#: Canonical engine list surfaced by /health/ready (audit S1-6 return shape).
TTS_HEALTH_ENGINES: tuple[str, ...] = ("kokoro", "voxcpm2", "edge", "piper")


def _gpu_backends_enabled() -> bool:
    """Local mirror of ``providers_config.gpu_backends_enabled`` (no import cycle).

    Returns True only when ``ENABLE_GPU_BACKENDS`` is set, so GPU-only engines
    (F5/CosyVoice2/Dia, Track B) are skipped on free/no-GPU hosts.
    """
    return os.environ.get("ENABLE_GPU_BACKENDS", "false").lower() in ("1", "true", "yes", "on")


def _should_skip_engine(engine_name: str, gpu_enabled: bool) -> bool:
    """P0 no-GPU safety: skip GPU-only engines when GPU backends are disabled.

    Returns True when ``engine_name``'s capability declares ``min_compute='gpu'``
    but ``gpu_enabled`` is False. Unknown engines are never skipped (CPU assumed).
    """
    if gpu_enabled:
        return False
    try:
        from .providers_config import capability_matrix

        cap = capability_matrix().get(engine_name)
        return cap is not None and cap.min_compute == "gpu"
    except Exception:  # noqa: BLE001 — never block engine init on config errors
        return False


async def cleanup_all_engines(registry: Optional["EngineRegistry"] = None) -> None:
    """Cleanup all registered engines from the given registry or the default one."""
    if registry is None:
        from ..di import get_app_container

        registry = get_app_container().get(EngineRegistry)
    await registry.close_all()


async def initialize_all_engines(registry: Optional["EngineRegistry"] = None) -> None:
    """Initialize all registered engines from the given registry or the default one."""
    if registry is None:
        from ..di import get_app_container

        registry = get_app_container().get(EngineRegistry)
    for engine in registry._engines.values():
        await engine.initialize()


async def probe_tts_engines(
    timeout: float = 5.0,
    *,
    registry: Optional["EngineRegistry"] = None,
) -> Dict[str, Any]:
    """Real TTS engine readiness probe (S1-6).

    Returns a normalized per-engine map plus the flattened boolean map the audit
    requires — ``{"kokoro": bool, "voxcpm2": bool, "edge": bool, "piper": bool}``.

    Probes (each bounded by ``timeout`` and never raising — a failure degrades to
    ``healthy=False`` instead of propagating):

      - ``kokoro``: real warmup via ``KokoroBackend.warmup()`` with 100ms budget
        (S1-6). Prefers registered engine; falls back to temporary engine.
      - ``voxcpm2``: real ``GET {VOXCPM2_ENDPOINT}/health`` when an endpoint is
        configured (remote pool); otherwise ``not_configured``.
      - ``edge``: real network reachability probe against the Edge speech host.
      - ``piper``: not implemented yet (S2-4) -> ``healthy=False``.

    Engines already loaded/registered are consulted via their real
    ``health_check()`` (e.g. remote VoxCPM2 does a pass-through ``/health`` call)
    and take precedence over the static probes above.

    Returns:
        {
          "engines": {"kokoro": bool, "voxcpm2": bool, "edge": bool, "piper": bool},
          "details": {name: {"healthy": bool, "detail": {...}}},
        }
    """
    import os

    import httpx

    result: Dict[str, Dict[str, Any]] = {}

    def _set(name: str, healthy: bool, detail: Dict[str, Any]) -> None:
        result[name] = {"healthy": healthy, "detail": detail}

    # 1) kokoro — real warmup probe (S1-6): call KokoroBackend.warmup() with 100ms budget.
    # Prefer registered engine's warmup; otherwise create a temporary one for the probe.
    kokoro_warmed_up = False
    kokoro_detail: Dict[str, Any] = {}

    # Try registered engine first
    kokoro_engine = None
    if registry is not None:
        kokoro_engine = registry.get("kokoro")

    if kokoro_engine is not None:
        # Use registered engine's warmup
        try:
            kokoro_warmed_up = await asyncio.wait_for(kokoro_engine.warmup(), timeout=0.1)  # 100ms
            kokoro_detail = {"source": "registered_engine", "warmed_up": kokoro_warmed_up}
        except asyncio.TimeoutError:
            kokoro_warmed_up = False
            kokoro_detail = {"source": "registered_engine", "error": "warmup timeout (>100ms)"}
        except Exception as e:
            kokoro_warmed_up = False
            kokoro_detail = {"source": "registered_engine", "error": str(e)}
        _set("kokoro", kokoro_warmed_up, kokoro_detail)
    else:
        # Fallback: create temporary engine for probe
        kokoro_path = os.getenv("KOKORO_MODEL_PATH", "")
        require_local = os.getenv("ENABLE_LOCAL_TTS", "true").lower() not in ("false", "0")
        if not require_local or not kokoro_path:
            _set("kokoro", False, {"reason": "not_configured"})
        else:
            present = Path(kokoro_path).exists()
            if present:
                # Create temporary engine and warmup
                try:
                    from .kokoro_backend import KokoroBackend

                    temp_engine = KokoroBackend(model_path=kokoro_path)
                    kokoro_warmed_up = await asyncio.wait_for(temp_engine.warmup(), timeout=0.1)  # 100ms
                    kokoro_detail = {
                        "source": "temporary_engine",
                        "warmed_up": kokoro_warmed_up,
                        "model_path": kokoro_path,
                    }
                    await temp_engine.close()
                except asyncio.TimeoutError:
                    kokoro_warmed_up = False
                    kokoro_detail = {
                        "source": "temporary_engine",
                        "error": "warmup timeout (>100ms)",
                        "model_path": kokoro_path,
                    }
                except Exception as e:
                    kokoro_warmed_up = False
                    kokoro_detail = {"source": "temporary_engine", "error": str(e), "model_path": kokoro_path}
            else:
                kokoro_detail = {"reason": "model_not_found", "model_path": kokoro_path}
            _set("kokoro", kokoro_warmed_up, kokoro_detail)

    # 2) voxcpm2 — real /health probe when an endpoint is configured.
    v2_endpoint = os.getenv("VOXCPM2_ENDPOINT", "").rstrip("/")
    if not v2_endpoint:
        _set("voxcpm2", False, {"reason": "not_configured"})
    else:
        probe_timeout = min(timeout, 2.0)
        try:
            async with httpx.AsyncClient(timeout=probe_timeout, follow_redirects=True) as client:
                resp = await client.get(f"{v2_endpoint}/health")
            _set("voxcpm2", resp.status_code < 500, {"status_code": resp.status_code, "url": f"{v2_endpoint}/health"})
        except Exception as e:  # noqa: BLE001 — degrade not propagate
            _set("voxcpm2", False, {"error": str(e)})

    # 3) edge — real network reachability probe. Any HTTP response (even 4xx/5xx)
    #    proves the host is reachable; only connect/timeout errors mean "down".
    edge_host = os.getenv("EDGE_TTS_HOST", "https://speech.platform.bing.com")
    probe_timeout = min(timeout, 2.0)
    try:
        async with httpx.AsyncClient(timeout=probe_timeout, follow_redirects=True) as client:
            resp = await client.get(edge_host)
        _set("edge", True, {"status_code": resp.status_code, "host": edge_host})
    except Exception as e:  # noqa: BLE001
        _set("edge", False, {"error": str(e)})

    # 4) piper — real local detection (S2-4): available only when BOTH a runnable
    #    `piper` binary AND at least one `.onnx` model are present (never falsely happy).
    try:
        from .piper_models import detect_piper_availability

        available, detail = detect_piper_availability()
        _set("piper", bool(available), detail)
    except Exception as e:  # noqa: BLE001 — degrade not propagate
        _set("piper", False, {"reason": "detection_error", "error": str(e)})

    # Overlay any engines actually loaded/registered: prefer their real health_check()
    # (e.g. RemoteVoxCPM2Engine does a pass-through GET /health) over static probes.
    # Skip kokoro since we already did a real warmup probe above.
    if registry is not None:
        for name, engine in registry._engines.items():
            if name == "kokoro":
                continue  # Already probed via warmup()
            if name not in result:
                _set(name, False, {"reason": "unknown_engine"})
            try:
                health = await asyncio.wait_for(engine.health_check(), timeout=timeout)
                healthy = bool(health.get("healthy", False))
                result[name] = {"healthy": healthy, "detail": health}
            except (
                asyncio.TimeoutError,
                RuntimeError,
                OSError,
            ):  # noqa: BLE001 — degrade not propagate (incl. timeout)
                _set(name, False, {"error": "health_check timeout or failed"})

    bool_map: Dict[str, bool] = {name: result.get(name, {}).get("healthy", False) for name in TTS_HEALTH_ENGINES}
    return {"engines": bool_map, "details": result}


# ════════════════════════════════════════════════════════════════════════════
# Backward-compatibility shims
#
# The DI container is the canonical home of the EngineRegistry singleton
# (``get_engine_registry`` lives in ``src.audiobook_studio.di``). Older
# integration tests imported these names from ``tts.engine``; re-export them
# here (with lazy imports) so those tests collect cleanly after the TTS
# registry refactor.
# ════════════════════════════════════════════════════════════════════════════


def get_engine_registry() -> "EngineRegistry":
    """Return the app-wide EngineRegistry singleton (delegates to the DI container)."""
    from ..di import get_engine_registry as _get

    return _get()


def set_engine_registry(registry: "EngineRegistry") -> None:
    """Replace the app-wide EngineRegistry singleton in the DI container."""
    from ..di import get_app_container

    container = get_app_container()
    try:
        container.unregister(EngineRegistry)
    except Exception:
        pass
    container.register_singleton(EngineRegistry, registry)
