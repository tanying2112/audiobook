"""TTS Engine Factory and Registry.

Provides a simple, config-driven way to create and manage TTS engines.
Replaces the old PortFactory with a unified engine registry.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .engine import EngineRegistry
from .fake_port import FakeRemoteTTSPort, MockRemoteTTSPort
from .port import RemoteTTSPort, TTSStatus, TTSTaskPayload

logger = logging.getLogger(__name__)

# Config classes for new v0.4 engines (mirroring the ones in streaming.py and zero_shot_clone.py)
# These are duplicated here to avoid circular imports
@dataclass
class StreamingTTSConfig:
    engine: str
    host: str = "localhost"
    port: int = 5000
    sample_rate: int = 24000
    chunk_size_ms: int = 100
    voice_id: str = "default"
    speed: float = 1.0
    timeout: int = 30
    extra_params: dict = field(default_factory=dict)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def mock_mode(self) -> bool:
        return os.getenv("MOCK_TTS", "false").lower() == "true"

    @property
    def chunk_samples(self) -> int:
        return int(self.sample_rate * self.chunk_size_ms / 1000)


@dataclass
class ZeroShotCloneConfig:
    engine: str
    host: str = "localhost"
    port: int = 5010
    sample_rate: int = 24000
    language: str = "auto"
    speed: float = 1.0
    timeout: int = 60
    extra_params: dict = field(default_factory=dict)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def mock_mode(self) -> bool:
        return os.getenv("MOCK_TTS", "false").lower() == "true"


def _get_lock():
    """Get threading lock (handles async contexts)."""
    return threading.Lock()


def create_engine(
    engine_type: str = "auto",
    **kwargs,
) -> "TTSEngine":
    """Create a new TTS engine instance.

    Args:
        engine_type: One of "auto", "kokoro", "edge", "voxcpm2", "fake", "mock".
        Also supports v0.4 engines: "cosyvoice_stream", "seed_tts_stream", "melotts_stream",
        "xtts_v2", "openvoice_v2", "cosyvoice_clone".
        **kwargs: Arguments passed to the engine constructor.

    Returns:
        New TTSEngine instance.
    """
    from .edge_tts_engine import create_edge_tts_engine
    from .kokoro_backend import create_kokoro_backend
    from .remote_voxcpm2_port import create_remote_voxcpm2_port

    impl = engine_type.lower()

    # Check for mock mode (only for engines that support it)
    mock_mode = os.environ.get("MOCK_TTS", "false").lower() == "true"
    if mock_mode:
        kwargs.setdefault("mock_mode", True)

    if impl == "fake":
        # FakeRemoteTTSPort doesn't use mock_mode parameter
        kwargs.pop("mock_mode", None)
        return FakeRemoteTTSPort(**kwargs)
    elif impl == "mock":
        # MockRemoteTTSPort doesn't use mock_mode parameter
        kwargs.pop("mock_mode", None)
        return MockRemoteTTSPort(**kwargs)
    elif impl == "voxcpm2":
        # voxcpm2 remote port does not support mock_mode parameter
        kwargs.pop("mock_mode", None)
        return create_remote_voxcpm2_port(**kwargs)
    elif impl == "auto":
        # Check for v0.4 streaming engines
        if impl in ("cosyvoice_stream", "seed_tts_stream", "melotts_stream"):
            kwargs["engine"] = impl
            return create_streaming_tts_engine(**kwargs)
        # Check for v0.4 zero-shot clone engines
        if impl in ("xtts_v2", "openvoice_v2", "cosyvoice_clone"):
            kwargs["engine"] = impl
            return create_zero_shot_clone_engine(**kwargs)
        # Auto-detect based on environment
        if os.environ.get("MOCK_LLM", "false").lower() == "true":
            kwargs.pop("mock_mode", None)
            return FakeRemoteTTSPort(**kwargs)
        elif os.environ.get("TEST_MODE", "false").lower() == "true":
            kwargs.pop("mock_mode", None)
            return FakeRemoteTTSPort(**kwargs)
        elif os.environ.get("VOXCPM2_ENDPOINT"):
            # Note: voxcpm2 is handled above in explicit check
            return create_remote_voxcpm2_port(**kwargs)
        else:
            enable_local = os.environ.get("ENABLE_LOCAL_TTS", "true").lower() == "true"
            if enable_local:
                return create_kokoro_port(**kwargs)
            else:
                return create_edge_tts_port(**kwargs)
    elif impl == "kokoro":
        return create_kokoro_port(**kwargs)
    elif impl == "edge":
        return create_edge_tts_port(**kwargs)
    elif impl == "cosyvoice_stream":
        kwargs["engine"] = impl
        return create_streaming_tts_engine(**kwargs)
    elif impl == "seed_tts_stream":
        kwargs["engine"] = impl
        return create_streaming_tts_engine(**kwargs)
    elif impl == "melotts_stream":
        kwargs["engine"] = impl
        return create_streaming_tts_engine(**kwargs)
    elif impl == "xtts_v2":
        kwargs["engine"] = impl
        return create_zero_shot_clone_engine(**kwargs)
    elif impl == "openvoice_v2":
        kwargs["engine"] = impl
        return create_zero_shot_clone_engine(**kwargs)
    elif impl == "cosyvoice_clone":
        kwargs["engine"] = impl
        return create_zero_shot_clone_engine(**kwargs)
    else:
        raise ValueError(f"Unknown engine type: {engine_type}")


def create_kokoro_port(**kwargs):
    """Create a Kokoro TTS port (engine wrapper)."""
    from .kokoro_port import create_kokoro_port as _create_kokoro_port

    return _create_kokoro_port(**kwargs)


def create_edge_tts_port(**kwargs):
    """Create an Edge TTS port (engine wrapper)."""
    from .edge_tts_port import create_edge_tts_port as _create_edge_tts_port

    return _create_edge_tts_port(**kwargs)


def create_streaming_tts_engine(**kwargs) -> "StreamingTTSEngine":
    """Create a Streaming TTS engine instance."""
    from .streaming import StreamingTTSConfig, create_streaming_tts_engine as _create_streaming_tts_engine

    # Build config from kwargs (remove mock_mode as it's a property, not a field)
    kwargs.pop("mock_mode", None)
    config = StreamingTTSConfig(**kwargs)
    return _create_streaming_tts_engine(config)


def create_zero_shot_clone_engine(**kwargs) -> "ZeroShotCloneEngine":
    """Create a Zero-Shot Voice Cloning engine instance."""
    from .zero_shot_clone import ZeroShotCloneConfig, create_zero_shot_clone_engine as _create_zero_shot_clone_engine

    # Build config from kwargs (remove mock_mode as it's a property, not a field)
    kwargs.pop("mock_mode", None)
    config = ZeroShotCloneConfig(**kwargs)
    return _create_zero_shot_clone_engine(config)


async def create_configured_registry(
    config: Optional[dict] = None,
) -> EngineRegistry:
    """Create and initialize an EngineRegistry from config.

    Config format:
        {
            "kokoro": {"output_dir": "./output", "max_concurrent": 2, "model_path": "..."},
            "edge": {"output_dir": "./output", "max_concurrent": 4},
        }

    Args:
        config: Engine configuration dict. If None, reads from environment.

    Returns:
        Initialized EngineRegistry.
    """
    registry = EngineRegistry()
    if config is None:
        config = _build_config_from_env()
    registry.config = config
    await registry.initialize()
    return registry


def _build_config_from_env() -> dict:
    """Build engine config from environment variables."""
    config = {}

    # Kokoro config
    if os.environ.get("ENABLE_LOCAL_TTS", "true").lower() == "true":
        config["kokoro"] = {
            "output_dir": os.environ.get("AUDIO_OUTPUT_DIR", "./output"),
            "max_concurrent": int(os.environ.get("KOKORO_MAX_CONCURRENT", "2")),
        }
        if os.environ.get("KOKORO_MODEL_PATH"):
            config["kokoro"]["model_path"] = os.environ["KOKORO_MODEL_PATH"]

    # Edge-TTS config
    enable_edge = os.environ.get("EDGE_TTS_ENABLED", "false").lower() == "true"
    if enable_edge or not config:
        config["edge"] = {
            "output_dir": os.environ.get("AUDIO_OUTPUT_DIR", "./output"),
            "max_concurrent": int(os.environ.get("EDGE_MAX_CONCURRENT", "4")),
            "voice": os.environ.get("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural"),
        }

    # VoxCPM2 config
    if os.environ.get("VOXCPM2_ENDPOINT"):
        config["voxcpm2"] = {
            "endpoint": os.environ["VOXCPM2_ENDPOINT"],
            "timeout_sec": int(os.environ.get("VOXCPM2_TIMEOUT_SEC", "60")),
        }
    # VoxCPM2 remote URL (v0.4 - Modal free GPU)
    elif os.environ.get("VOXCPM2_REMOTE_URL"):
        config["voxcpm2"] = {
            "endpoint": os.environ["VOXCPM2_REMOTE_URL"],
            "timeout_sec": int(os.environ.get("VOXCPM2_TIMEOUT_SEC", "60")),
        }

    # Streaming TTS configs (v0.4)
    streaming_engines = {
        "cosyvoice_stream": ("COSYVOICE_STREAM_ENDPOINT", 5000),
        "seed_tts_stream": ("SEED_TTS_STREAM_ENDPOINT", 5001),
        "melotts_stream": ("MELOTTS_STREAM_ENDPOINT", 5002),
    }
    for engine_name, (env_var, default_port) in streaming_engines.items():
        endpoint = os.environ.get(env_var)
        if endpoint:
            host = endpoint.replace("http://", "").replace("https://", "").split(":")[0]
            port = int(endpoint.split(":")[-1]) if ":" in endpoint else default_port
            config[engine_name] = {
                "host": host,
                "port": port,
                "sample_rate": 24000,
            }

    # Zero-shot clone configs (v0.4)
    clone_engines = {
        "xtts_v2": ("XTTS_V2_ENDPOINT", 5010),
        "openvoice_v2": ("OPENVOICE_V2_ENDPOINT", 5011),
        "cosyvoice_clone": ("COSYVOICE_CLONE_ENDPOINT", 5012),
    }
    for engine_name, (env_var, default_port) in clone_engines.items():
        endpoint = os.environ.get(env_var)
        if endpoint:
            host = endpoint.replace("http://", "").replace("https://", "").split(":")[0]
            port = int(endpoint.split(":")[-1]) if ":" in endpoint else default_port
            config[engine_name] = {
                "host": host,
                "port": port,
                "sample_rate": 24000,
            }

    return config


async def get_default_engine(
    registry: Optional[EngineRegistry] = None,
) -> "TTSEngine":
    """Get the default TTS engine from the registry."""
    reg = registry
    if reg is None:
        from ..di import get_app_container
        reg = get_app_container().get(EngineRegistry)
    if reg.get_default() is None:
        # Initialize from env if not already done
        await reg.initialize(_build_config_from_env())
    return reg.get_default()


# Backward compatibility: Port interface
async def get_port() -> RemoteTTSPort:
    """Get the default port (backward compatibility).

    This wraps the default engine in a RemoteTTSPort adapter.
    """
    from .port import RemoteTTSPort, TTSTaskResult, TTSTaskStatus
    from ..di import get_app_container

    class EnginePortAdapter:
        """Adapter to make TTSEngine look like RemoteTTSPort."""

        def __init__(self, engine):
            self.engine = engine
            self._tasks = {}

        async def submit(self, task_id: str, payload: TTSTaskPayload) -> bool:
            if task_id in self._tasks:
                return False
            self._tasks[task_id] = {"status": "RUNNING", "payload": payload}
            # Use create_task to run in background
            import asyncio

            asyncio.create_task(self._run_synthesis(task_id, payload))
            return True

        async def _run_synthesis(self, task_id: str, payload: TTSTaskPayload):
            try:
                output_path = Path(self.engine.output_dir) / f"{task_id}.wav"
                result = await self.engine.synthesize(payload, output_path)
                # Engine ``synthesize`` catches internal errors and returns a
                # TTSTaskResult with status=FAILED rather than raising. Honour
                # that signal so the scheduler (and synthesize.py poller) sees
                # the real outcome instead of a DONE-with-empty-path phantom.
                if result.status == TTSStatus.FAILED:
                    self._tasks[task_id] = {
                        "status": "FAILED",
                        "error": result.error_message or "Synthesis failed",
                    }
                    return
                # Prefer the engine's audio_path (may point to the wav it wrote);
                # fall back to our expected output_path if the engine left it blank.
                audio_path = result.audio_path or str(output_path)
                if not Path(audio_path).exists():
                    # Engine reported success but the file isn't where we
                    # expected: surface this as a real failure, not DONE.
                    self._tasks[task_id] = {
                        "status": "FAILED",
                        "error": f"Audio file not found at {audio_path}",
                    }
                    return
                self._tasks[task_id] = {
                    "status": "DONE",
                    "result": TTSTaskResult(
                        task_id=task_id,
                        status=TTSStatus.DONE,
                        audio_path=audio_path,
                        duration_ms=result.duration_ms,
                    ),
                }
            except Exception as e:
                self._tasks[task_id] = {
                    "status": "FAILED",
                    "error": str(e),
                }

        async def get_status(self, task_id: str) -> TTSTaskStatus:
            task = self._tasks.get(task_id)
            if not task:
                return TTSTaskStatus(task_id=task_id, status=TTSStatus.PENDING, error_message="Not found")
            return TTSTaskStatus(
                task_id=task_id,
                status=TTSStatus(task.get("status", "PENDING")),
                progress=task.get("progress"),
                error_message=task.get("error"),
            )

        async def get_result(self, task_id: str) -> TTSTaskResult:
            task = self._tasks.get(task_id)
            if not task or "result" not in task:
                raise KeyError(f"Task {task_id} not found or not ready")
            return task["result"]

        async def cancel(self, task_id: str) -> bool:
            if task_id not in self._tasks:
                return False
            if self._tasks[task_id]["status"] in ("DONE", "FAILED"):
                return False
            self._tasks[task_id]["status"] = "FAILED"
            self._tasks[task_id]["error"] = "Cancelled"
            return True

        async def health_check(self) -> dict:
            return await self.engine.health_check()

        async def close(self):
            await self.engine.close()

    # Get engine from DI container
    engine = await get_default_engine()
    return EnginePortAdapter(engine)


@asynccontextmanager
async def engine_context(
    registry: Optional[EngineRegistry] = None,
) -> EngineRegistry:
    """Context manager for engine registry lifecycle.

    Usage:
        async with engine_context() as registry:
            engine = registry.get("kokoro")
            result = await engine.synthesize(...)
    """
    reg = registry or await create_configured_registry()
    try:
        yield reg
    finally:
        await reg.close_all()
