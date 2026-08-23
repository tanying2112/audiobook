"""TTS Engine Factory and Registry.

Provides a simple, config-driven way to create and manage TTS engines.
Replaces the old PortFactory with a unified engine registry.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from .engine import EngineRegistry, get_engine_registry, set_engine_registry
from .fake_port import FakeRemoteTTSPort, MockRemoteTTSPort
from .port import RemoteTTSPort, TTSStatus, TTSTaskPayload

logger = logging.getLogger(__name__)

# Global registry (lazy initialization)
_global_registry: Optional[EngineRegistry] = None
_registry_lock = os.threading.Lock() if hasattr(os, "threading") else None


def _get_lock():
    """Get threading lock (handles async contexts)."""
    return os.threading.Lock() if hasattr(os, "threading") else None


def create_engine(
    engine_type: str = "auto",
    **kwargs,
) -> "TTSEngine":
    """Create a new TTS engine instance.

    Args:
        engine_type: One of "auto", "kokoro", "edge", "voxcpm2", "fake", "mock".
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
        return create_remote_voxcpm2_port(**kwargs)
    elif impl == "auto":
        # Auto-detect based on environment
        if os.environ.get("MOCK_LLM", "false").lower() == "true":
            kwargs.pop("mock_mode", None)
            return FakeRemoteTTSPort(**kwargs)
        elif os.environ.get("TEST_MODE", "false").lower() == "true":
            kwargs.pop("mock_mode", None)
            return FakeRemoteTTSPort(**kwargs)
        elif os.environ.get("VOXCPM2_ENDPOINT"):
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

    return config


def get_engine_registry() -> EngineRegistry:
    """Get the global engine registry (lazy initialization)."""
    global _global_registry
    if _global_registry is None:
        lock = _get_lock()
        if lock:
            with lock:
                if _global_registry is None:
                    _global_registry = EngineRegistry()
        else:
            if _global_registry is None:
                _global_registry = EngineRegistry()
    return _global_registry


async def get_default_engine(
    registry: Optional[EngineRegistry] = None,
) -> "TTSEngine":
    """Get the default TTS engine from the registry."""
    reg = registry or get_engine_registry()
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
