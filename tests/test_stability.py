"""Tests for CircuitBreaker, HealthProbe, ApiKeyPool, and enhanced Router."""

import time
import threading
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.llm.circuit_breaker import CircuitBreaker
from src.audiobook_studio.llm.health_probe import HealthProbe, HealthStatus
from src.audiobook_studio.llm.key_pool import ApiKeyPool, KeyPoolManager


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker(provider_name="test", failure_threshold=3)
        assert cb.state == "closed"
        assert cb.can_proceed() is True

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(provider_name="test", failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "open"
        assert cb.can_proceed() is False

    def test_transitions_to_half_open_after_cooldown(self):
        cb = CircuitBreaker(
            provider_name="test", failure_threshold=2, recovery_timeout_s=0.1
        )
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        time.sleep(0.15)
        assert cb.can_proceed() is True
        assert cb.state == "half_open"

    def test_half_open_closes_on_success(self):
        cb = CircuitBreaker(
            provider_name="test", failure_threshold=2, recovery_timeout_s=0.1
        )
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        cb.can_proceed()  # transition to half_open
        cb.record_success()
        assert cb.state == "closed"
        assert cb.failure_count == 0

    def test_half_open_opens_on_failure(self):
        cb = CircuitBreaker(
            provider_name="test", failure_threshold=2, recovery_timeout_s=0.1
        )
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        cb.can_proceed()  # transition to half_open
        cb.record_failure()
        assert cb.state == "open"

    def test_success_decreases_failure_count(self):
        cb = CircuitBreaker(provider_name="test", failure_threshold=5)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 1

    def test_reset(self):
        cb = CircuitBreaker(provider_name="test", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        cb.reset()
        assert cb.state == "closed"
        assert cb.failure_count == 0

    def test_get_status(self):
        cb = CircuitBreaker(provider_name="test", failure_threshold=3)
        status = cb.get_status()
        assert status["provider"] == "test"
        assert status["state"] == "closed"
        assert status["failure_count"] == 0


class TestHealthProbe:
    def test_initial_status_healthy(self):
        provider = MagicMock()
        provider.name = "test_provider"
        probe = HealthProbe(providers=[provider])
        status = probe.get_status("test_provider")
        assert status.is_healthy is True

    def test_get_all_statuses(self):
        providers = [MagicMock(name=f"p{i}") for i in range(3)]
        for i, p in enumerate(providers):
            p.name = f"provider_{i}"
        probe = HealthProbe(providers=providers)
        statuses = probe.get_all_statuses()
        assert len(statuses) == 3

    def test_healthy_providers_list(self):
        providers = [MagicMock(name=f"p{i}") for i in range(3)]
        for i, p in enumerate(providers):
            p.name = f"provider_{i}"
        probe = HealthProbe(providers=providers)
        healthy = probe.get_healthy_providers()
        assert len(healthy) == 3

    def test_is_healthy_unknown_provider(self):
        probe = HealthProbe(providers=[])
        assert probe.is_healthy("unknown") is True


class TestApiKeyPool:
    def test_primary_key_only(self):
        pool = ApiKeyPool(
            provider_name="test",
            primary_key_env="TEST_KEY",
            pool_key_envs=[],
        )
        assert pool.size == 0  # No env var set

    def test_round_robin_rotation(self):
        import os
        os.environ["POOL_KEY_1"] = "key1"
        os.environ["POOL_KEY_2"] = "key2"
        os.environ["POOL_KEY_3"] = "key3"
        try:
            pool = ApiKeyPool(
                provider_name="test",
                primary_key_env="POOL_KEY_1",
                pool_key_envs=["POOL_KEY_2", "POOL_KEY_3"],
                strategy="round_robin",
            )
            assert pool.size == 3
            key1 = pool.get_key()
            key2 = pool.get_key()
            key3 = pool.get_key()
            key4 = pool.get_key()  # Should wrap around
            assert key1 == "key1"
            assert key2 == "key2"
            assert key3 == "key3"
            assert key4 == "key1"
        finally:
            del os.environ["POOL_KEY_1"]
            del os.environ["POOL_KEY_2"]
            del os.environ["POOL_KEY_3"]

    def test_get_stats(self):
        pool = ApiKeyPool(provider_name="test", primary_key_env="NONEXISTENT")
        stats = pool.get_stats()
        assert stats["provider"] == "test"
        assert stats["total_keys"] == 0


class TestKeyPoolManager:
    def test_register_and_get_key(self):
        import os
        os.environ["MGR_TEST_KEY"] = "test_key_value"
        try:
            manager = KeyPoolManager()
            manager.register(
                provider_name="test",
                primary_key_env="MGR_TEST_KEY",
            )
            key = manager.get_key("test")
            assert key == "test_key_value"
        finally:
            del os.environ["MGR_TEST_KEY"]

    def test_get_all_stats(self):
        manager = KeyPoolManager()
        manager.register(provider_name="p1", primary_key_env="NONEXISTENT")
        manager.register(provider_name="p2", primary_key_env="NONEXISTENT")
        stats = manager.get_all_stats()
        assert "p1" in stats
        assert "p2" in stats


class TestEnhancedRouter:
    def test_router_initialization(self):
        from src.audiobook_studio.llm.router import LLMRouter
        router = LLMRouter(mock_mode=True)
        assert len(router.circuit_breakers) > 0
        assert len(router.key_pool._pools) > 0

    def test_free_tier_health(self):
        from src.audiobook_studio.llm.router import LLMRouter
        router = LLMRouter(mock_mode=True)
        health = router.get_free_tier_health()
        assert "total_free_providers" in health
        assert "overall_health" in health
        assert health["overall_health"] in ["green", "yellow", "red"]

    def test_mock_call_annotation(self):
        from src.audiobook_studio.llm.router import LLMRouter
        from src.audiobook_studio.schemas import ParagraphAnnotation
        router = LLMRouter(mock_mode=True)
        result = router.call(
            "annotate",
            ParagraphAnnotation,
            [{"role": "user", "content": "test"}],
        )
        assert result.schema_compliance is True
        assert result.output.speaker_canonical_name == "旁白"

    def test_heuristic_fallback(self):
        from src.audiobook_studio.llm.router import LLMRouter
        from src.audiobook_studio.schemas import ParagraphAnnotation
        router = LLMRouter(mock_mode=True)
        fallback = router._heuristic_fallback("annotate", ParagraphAnnotation)
        assert fallback is not None
        assert fallback.speaker_canonical_name == "_narrator_"
        assert fallback.confidence == 0.2

    def test_heuristic_fallback_edit(self):
        from src.audiobook_studio.llm.router import LLMRouter
        from src.audiobook_studio.schemas import TtsEditOutput
        router = LLMRouter(mock_mode=True)
        fallback = router._heuristic_fallback("edit", TtsEditOutput)
        assert fallback is not None
        assert "heuristic_fallback" in fallback.changes_made[0]

    def test_heuristic_fallback_judge(self):
        from src.audiobook_studio.llm.router import LLMRouter
        from src.audiobook_studio.schemas import QualityJudgment
        router = LLMRouter(mock_mode=True)
        fallback = router._heuristic_fallback("judge", QualityJudgment)
        assert fallback is not None
        assert fallback.needs_regeneration is True
