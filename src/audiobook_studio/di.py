"""Dependency Injection Container for Audiobook Studio.

Provides explicit instance management to replace global singletons,
enabling test isolation, multi-tenancy, and cleaner architecture.
"""

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Dict, Optional, Type, TypeVar

from .config.hardware_profile import HardwareProfile
from .llm.config_loader import LLMProvidersConfig
from .llm.quota_registry import QuotaRegistry
from .tts.engine import EngineRegistry
# CostTracker imported lazily in initialize_defaults to avoid circular import

T = TypeVar("T")

# Request-scoped context variable for per-request DI overrides
_request_container: ContextVar[Optional["DIContainer"]] = ContextVar("_request_container", default=None)


class DIContainer:
    """Thread-safe dependency injection container with singleton and factory support.

    Usage:
        container = DIContainer()
        container.register_singleton(QuotaRegistry, lambda: QuotaRegistry())
        container.register_factory(CostTracker, lambda: CostTracker())

        quota = container.get(QuotaRegistry)
        cost = container.get(CostTracker)

    For request-scoped overrides (e.g., in tests):
        with container.request_scope({QuotaRegistry: mock_quota}):
            # Code here sees mock_quota
            pass
    """

    def __init__(self, parent: Optional["DIContainer"] = None):
        self._parent = parent
        self._singletons: Dict[Type, Any] = {}
        self._factories: Dict[Type, Callable[[], Any]] = {}
        self._lock = threading.RLock()
        self._initialized = False

    def register_singleton(self, interface: Type[T], instance: T) -> None:
        """Register a pre-created singleton instance."""
        with self._lock:
            if interface in self._singletons:
                raise ValueError(f"Singleton already registered for {interface}")
            self._singletons[interface] = instance

    def register_factory(self, interface: Type[T], factory: Callable[[], T]) -> None:
        """Register a factory function for lazy singleton creation."""
        with self._lock:
            if interface in self._factories:
                raise ValueError(f"Factory already registered for {interface}")
            self._factories[interface] = factory

    def register_type(self, interface: Type[T], impl: Type[T], *, singleton: bool = True) -> None:
        """Register a type to be instantiated (singleton by default)."""
        if singleton:
            def factory() -> T:
                return impl()
        else:
            def factory() -> T:
                return impl()
        self.register_factory(interface, factory)

    def get(self, interface: Type[T]) -> T:
        """Get an instance, creating via factory if needed."""
        # Check request-scoped override first
        request_override = _request_container.get()
        if request_override and interface in request_override._singletons:
            return request_override._singletons[interface]

        with self._lock:
            # Check local singletons
            if interface in self._singletons:
                return self._singletons[interface]

            # Check local factories
            if interface in self._factories:
                instance = self._factories[interface]()
                self._singletons[interface] = instance
                del self._factories[interface]
                return instance

        # Delegate to parent
        if self._parent:
            return self._parent.get(interface)

        raise KeyError(f"No registration found for {interface}. "
                       f"Call register_singleton/register_factory first, "
                       f"or ensure container is initialized via initialize_defaults().")

    def get_or_none(self, interface: Type[T]) -> Optional[T]:
        """Get instance or return None if not registered."""
        try:
            return self.get(interface)
        except KeyError:
            return None

    def has(self, interface: Type) -> bool:
        """Check if interface is registered (locally or in parent)."""
        with self._lock:
            if interface in self._singletons or interface in self._factories:
                return True
        if self._parent:
            return self._parent.has(interface)
        return False

    def unregister(self, interface: Type) -> bool:
        """Remove a registration. Returns True if was registered."""
        with self._lock:
            if interface in self._singletons:
                del self._singletons[interface]
                return True
            if interface in self._factories:
                del self._factories[interface]
                return True
        return False

    def clear(self) -> None:
        """Clear all local registrations (for test cleanup)."""
        with self._lock:
            self._singletons.clear()
            self._factories.clear()

    @contextmanager
    def request_scope(self, overrides: Dict[Type, Any]):
        """Create a request-scoped context with temporary overrides.

        Usage:
            with container.request_scope({QuotaRegistry: mock_quota}):
                quota = container.get(QuotaRegistry)  # Returns mock_quota
        """
        child = DIContainer(parent=self)
        for interface, instance in overrides.items():
            child.register_singleton(interface, instance)

        token = _request_container.set(child)
        try:
            yield child
        finally:
            _request_container.reset(token)

    def initialize_defaults(self, *, hardware_profile: Optional[HardwareProfile] = None,
                            llm_config: Optional[LLMProvidersConfig] = None) -> "DIContainer":
        """Initialize with production defaults. Idempotent."""
        if self._initialized:
            return self

        with self._lock:
            if self._initialized:
                return self

            # Core infrastructure singletons
            self.register_singleton(QuotaRegistry, QuotaRegistry())
            # Lazy import CostTracker to avoid circular import
            from .llm.router import CostTracker
            self.register_singleton(CostTracker, CostTracker())
            self.register_singleton(EngineRegistry, EngineRegistry())

            # Config singletons (lazy-loaded from files)
            if hardware_profile:
                self.register_singleton(HardwareProfile, hardware_profile)
            else:
                self.register_factory(HardwareProfile, lambda: HardwareProfile.get_hardware_profile())

            if llm_config:
                self.register_singleton(LLMProvidersConfig, llm_config)
            else:
                self.register_factory(LLMProvidersConfig,
                                     lambda: LLMProvidersConfig.load())

            self._initialized = True
            return self

    def reset_for_testing(self) -> None:
        """Full reset for test isolation. Clears all state including parent-delegated singletons."""
        with self._lock:
            self._singletons.clear()
            self._factories.clear()
            self._initialized = False
        # Also clear request-scoped context
        _request_container.set(None)


# Global application container (initialized at startup)
_app_container: Optional[DIContainer] = None
_app_container_lock = threading.Lock()


def get_app_container() -> DIContainer:
    """Get the global application container. Initializes on first call."""
    global _app_container
    if _app_container is None:
        with _app_container_lock:
            if _app_container is None:
                _app_container = DIContainer().initialize_defaults()
    return _app_container


def set_app_container(container: DIContainer) -> None:
    """Replace the global application container (primarily for testing)."""
    global _app_container
    with _app_container_lock:
        _app_container = container


def reset_app_container() -> None:
    """Reset global container for test isolation."""
    global _app_container
    with _app_container_lock:
        if _app_container:
            _app_container.reset_for_testing()
        _app_container = None


@contextmanager
def app_request_scope(overrides: Dict[Type, Any]):
    """Convenience: request scope on the global app container."""
    container = get_app_container()
    with container.request_scope(overrides) as scoped:
        yield scoped


# Backward compatibility shims - DEPRECATED, use get_app_container().get() instead
def get_quota_registry() -> QuotaRegistry:
    """Deprecated: use get_app_container().get(QuotaRegistry)"""
    return get_app_container().get(QuotaRegistry)


def init_quota_registry() -> QuotaRegistry:
    """Deprecated: container manages lifecycle"""
    return get_app_container().get(QuotaRegistry)


def get_cost_tracker():
    """Deprecated: use get_app_container().get(CostTracker)"""
    from .llm.router import CostTracker
    return get_app_container().get(CostTracker)


def reset_cost_tracker() -> None:
    """Deprecated: use container.clear() or reset_app_container()"""
    from .llm.router import CostTracker
    container = get_app_container()
    container.unregister(CostTracker)
    # Re-register fresh instance
    container.register_singleton(CostTracker, CostTracker())


def get_engine_registry() -> EngineRegistry:
    """Deprecated: use get_app_container().get(EngineRegistry)"""
    return get_app_container().get(EngineRegistry)