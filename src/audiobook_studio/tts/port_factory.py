"""Port Factory for RemoteTTSPort implementations.

Provides a global default port instance and factory functions for dependency injection.
This allows the pipeline and Celery tasks to use the same Port abstraction
while swapping implementations (real, fake, mock) based on configuration.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Callable, Optional

from .edge_tts_port import EdgeTTSPort, create_edge_tts_port
from .fake_port import FakeRemoteTTSPort, MockRemoteTTSPort
from .kokoro_port import KokoroPort, create_kokoro_port
from .port import PortFactory, RemoteTTSPort
from .remote_voxcpm2_port import RemoteVoxCPM2Port, create_remote_voxcpm2_port

# Global port instance (lazy initialization)
_port_instance: Optional[RemoteTTSPort] = None
_port_lock = threading.Lock()
_port_factory: Optional[PortFactory] = None


def make_port_factory(
    implementation: str = "auto",
    **kwargs,
) -> PortFactory:
    """Create a PortFactory for the given implementation.

    Args:
        implementation: One of "auto", "fake", "mock", "voxcpm2", "hermes".
        **kwargs: Additional arguments passed to the port constructor.

    Returns:
        Callable that creates RemoteTTSPort instances.
    """

    def factory() -> RemoteTTSPort:
        return _create_port(implementation, **kwargs)

    return factory


def _create_port(implementation: str, **kwargs) -> RemoteTTSPort:
    """Create a port instance based on implementation name."""
    impl = implementation.lower()

    # Check for mock mode from environment
    mock_mode = os.environ.get("MOCK_TTS", "false").lower() == "true"
    if mock_mode:
        kwargs.setdefault("mock_mode", True)

    if impl == "fake":
        return FakeRemoteTTSPort(**kwargs)
    elif impl == "mock":
        return MockRemoteTTSPort(**kwargs)
    elif impl == "voxcpm2":
        # Real Remote VoxCPM2 implementation
        return create_remote_voxcpm2_port(**kwargs)
    elif impl == "hermes":
        # Real Hermes implementation (Redis + R2)
        # TODO: Import and return HermesPort when available
        raise NotImplementedError("HermesPort not yet implemented")
    elif impl == "auto":
        # Auto-detect based on environment
        if os.environ.get("MOCK_LLM", "false").lower() == "true":
            return FakeRemoteTTSPort(**kwargs)
        elif os.environ.get("TEST_MODE", "false").lower() == "true":
            return FakeRemoteTTSPort(**kwargs)
        elif os.environ.get("VOXCPM2_ENDPOINT"):
            # Use real Remote VoxCPM2 when endpoint is configured
            return create_remote_voxcpm2_port(**kwargs)
        else:
            # Check ENABLE_LOCAL_TTS for local vs cloud engine selection
            enable_local = os.environ.get("ENABLE_LOCAL_TTS", "true").lower() == "true"
            if enable_local:
                # REAL: Kokoro via local engine port
                return create_kokoro_port(**kwargs)
            else:
                # REAL: Edge-TTS via cloud engine port
                return create_edge_tts_port(**kwargs)
    else:
        raise ValueError(f"Unknown port implementation: {implementation}")


def create_port(
    implementation: str = "auto",
    **kwargs,
) -> RemoteTTSPort:
    """Create a new RemoteTTSPort instance.

    Args:
        implementation: One of "auto", "fake", "mock", "voxcpm2", "hermes".
        **kwargs: Arguments passed to the port constructor.

    Returns:
        New RemoteTTSPort instance.
    """
    return _create_port(implementation, **kwargs)


def get_port() -> RemoteTTSPort:
    """Get the global default port instance (lazy initialization).

    Returns:
        The global RemoteTTSPort instance.
    """
    global _port_instance, _port_factory

    if _port_instance is not None:
        return _port_instance

    with _port_lock:
        if _port_instance is None:
            if _port_factory is not None:
                _port_instance = _port_factory()
            else:
                _port_instance = _create_port("auto")

        return _port_instance


def set_port(port: RemoteTTSPort) -> None:
    """Set the global default port instance.

    Args:
        port: RemoteTTSPort instance to use as default.
    """
    global _port_instance
    with _port_lock:
        _port_instance = port


def set_port_factory(factory: PortFactory) -> None:
    """Set the global port factory.

    Args:
        factory: Callable that creates RemoteTTSPort instances.
    """
    global _port_factory, _port_instance
    with _port_lock:
        _port_factory = factory
        _port_instance = None  # Reset to force re-creation


def reset_port() -> None:
    """Reset the global port instance (for testing)."""
    global _port_instance, _port_factory
    with _port_lock:
        if _port_instance is not None:
            # Don't await close() here as we're not in async context
            # In tests, the fake port will be cleaned up separately
            pass
        _port_instance = None
        _port_factory = None


@contextmanager
def port_context(port: RemoteTTSPort):
    """Context manager to temporarily set the global port.

    Usage:
        with port_context(fake_port):
            # code here uses fake_port
            pass
        # global port restored

    Args:
        port: RemoteTTSPort instance to use within the context.
    """
    global _port_instance
    old_port = _port_instance
    set_port(port)
    try:
        yield port
    finally:
        set_port(old_port)
