"""Tests for dependency injection container."""

from typing import Protocol

import pytest

from src.audiobook_studio.di import (
    DIContainer,
    app_request_scope,
    get_app_container,
    reset_app_container,
    set_app_container,
)


class IService(Protocol):
    """Test service interface."""

    def process(self) -> str: ...


class ServiceA:
    """Test service A."""

    def process(self) -> str:
        return "ServiceA"


class ServiceB:
    """Test service B with dependency."""

    def __init__(self, service_a: ServiceA):
        self.service_a = service_a

    def process(self) -> str:
        return f"ServiceB({self.service_a.process()})"


class TestDIContainer:
    """Tests for DIContainer class."""

    def setup_method(self):
        self.container = DIContainer()

    def teardown_method(self):
        self.container.clear()

    def test_register_and_get_singleton(self):
        """Test registering and retrieving a singleton."""
        service = ServiceA()
        self.container.register_singleton(ServiceA, service)
        retrieved = self.container.get(ServiceA)
        assert retrieved is service

    def test_register_factory_lazy_creation(self):
        """Test factory creates instance on first get."""
        created = []

        def factory() -> ServiceA:
            created.append(True)
            return ServiceA()

        self.container.register_factory(ServiceA, factory)
        assert len(created) == 0  # Not created yet

        retrieved = self.container.get(ServiceA)
        assert len(created) == 1  # Created on first get
        assert isinstance(retrieved, ServiceA)

        # Second get returns same instance (singleton behavior)
        again = self.container.get(ServiceA)
        assert again is retrieved

    def test_register_type(self):
        """Test register_type convenience method."""
        self.container.register_type(ServiceA, ServiceA)
        result = self.container.get(ServiceA)
        assert isinstance(result, ServiceA)

    def test_get_raises_if_not_registered(self):
        """Test get raises KeyError for unregistered type."""
        with pytest.raises(KeyError, match="No registration"):
            self.container.get(ServiceA)

    def test_get_or_none_returns_none_if_missing(self):
        """Test get_or_none returns None for unregistered type."""
        result = self.container.get_or_none(ServiceA)
        assert result is None

    def test_has_checker(self):
        """Test has method checks registration."""
        assert not self.container.has(ServiceA)
        self.container.register_singleton(ServiceA, ServiceA())
        assert self.container.has(ServiceA)

    def test_unregister(self):
        """Test unregister removes registration."""
        self.container.register_singleton(ServiceA, ServiceA())
        assert self.container.has(ServiceA)

        removed = self.container.unregister(ServiceA)
        assert removed is True
        assert not self.container.has(ServiceA)

    def test_unregister_not_found(self):
        """Test unregister returns False if not registered."""
        removed = self.container.unregister(ServiceA)
        assert removed is False

    def test_clear(self):
        """Test clear removes all registrations."""
        self.container.register_singleton(ServiceA, ServiceA())
        self.container.register_singleton(ServiceB, ServiceB(ServiceA()))

        self.container.clear()

        assert not self.container.has(ServiceA)
        assert not self.container.has(ServiceB)

    def test_request_scope_override(self):
        """Test request scope overrides for testing."""
        real_service = ServiceA()
        mock_service = ServiceA()  # Different instance as mock

        self.container.register_singleton(ServiceA, real_service)

        with self.container.request_scope({ServiceA: mock_service}) as scoped:
            retrieved = scoped.get(ServiceA)
            assert retrieved is mock_service
            assert retrieved is not real_service

        # After scope, original returns real service
        retrieved = self.container.get(ServiceA)
        assert retrieved is real_service

    def test_nested_request_scope(self):
        """Test nested request scopes."""
        outer_mock = ServiceA()
        inner_mock = ServiceA()

        self.container.register_singleton(ServiceA, ServiceA())

        with self.container.request_scope({ServiceA: outer_mock}) as outer:
            assert outer.get(ServiceA) is outer_mock

            with outer.request_scope({ServiceA: inner_mock}) as inner:
                assert inner.get(ServiceA) is inner_mock

            assert outer.get(ServiceA) is outer_mock

    def test_parent_delegation(self):
        """Test child delegates to parent."""
        parent = DIContainer()
        parent.register_singleton(ServiceA, ServiceA())

        child = DIContainer(parent=parent)

        # Child can get parent's singleton
        result = child.get(ServiceA)
        assert isinstance(result, ServiceA)

    def test_double_initialize_ignored(self):
        """Test initialize_defaults is idempotent."""
        self.container.initialize_defaults()
        self.container.initialize_defaults()
        assert self.container._initialized


class TestResetForTesting:
    """Tests for reset_for_testing method."""

    def test_reset_clears_singletons(self):
        """Test reset clears singleton state."""
        container = DIContainer()
        container.register_singleton(ServiceA, ServiceA())

        container.reset_for_testing()

        assert not container.has(ServiceA)

    def test_reset_clears_factories(self):
        """Test reset clears factory state."""
        container = DIContainer()
        container.register_factory(ServiceA, lambda: ServiceA())

        container.reset_for_testing()

        assert not container.has(ServiceA)

    def test_reset_clears_initialized_flag(self):
        """Test reset clears initialized flag."""
        container = DIContainer()
        container.initialize_defaults()
        assert container._initialized is True

        container.reset_for_testing()
        assert container._initialized is False


class TestGlobalContainer:
    """Tests for global application container functions."""

    def teardown_method(self):
        reset_app_container()

    def test_get_app_container_initializes_on_first_call(self):
        """Test get_app_container auto-initializes."""
        container = get_app_container()
        assert container is not None
        assert container._initialized

    def test_set_app_container_replace(self):
        """Test set_app_container replaces global."""
        custom = DIContainer()
        set_app_container(custom)

        retrieved = get_app_container()
        assert retrieved is custom

    def test_reset_app_container(self):
        """Test reset_app_container clears global."""
        get_app_container()  # Initialize
        reset_app_container()

        # Should be able to initialize fresh again
        fresh = get_app_container()
        assert fresh._initialized

    def test_app_request_scope_convenience(self):
        """Test app_request_scope context manager."""
        mock_service = ServiceA()

        with app_request_scope({ServiceA: mock_service}) as scoped:
            retrieved = scoped.get(ServiceA)
            assert retrieved is mock_service


class TestContainerWithDefaults:
    """Tests for initialize_defaults method."""

    def test_initialize_defaults_registrations(self):
        """Test initialize_defaults registers expected components."""
        from src.audiobook_studio.llm.quota_registry import QuotaRegistry

        container = DIContainer()
        container.initialize_defaults()

        # Should be able to get QuotaRegistry
        quota = container.get(QuotaRegistry)
        assert isinstance(quota, QuotaRegistry)

    def test_initialize_defaults_with_custom_config(self):
        """Test initialize_defaults accepts custom configs."""
        from src.audiobook_studio.config.hardware_profile import HardwareProfile
        from src.audiobook_studio.llm.config_loader import LLMProvidersConfig

        container = DIContainer()
        custom_hardware = HardwareProfile()
        custom_hardware.name = "custom_test"

        container.initialize_defaults(hardware_profile=custom_hardware)

        retrieved = container.get(HardwareProfile)
        assert retrieved.name == "custom_test"
