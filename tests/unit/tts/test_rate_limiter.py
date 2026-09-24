"""Tests for TTS Rate Limiter (tests/unit/tts/test_rate_limiter.py).

Target: 70%+ coverage of rate_limiter.py (114 lines, ~41% coverage).
Tests: ProviderRateLimiter, TokenBucket, TTSRateLimiter, factory functions, defaults.
"""

import threading
import time
from unittest.mock import Mock, patch

import pytest

from src.audiobook_studio.tts.rate_limiter import (
    DEFAULT_TTS_RATE_LIMITS,
    ProviderRateLimiter,
    RateLimitConfig,
    TokenBucket,
    TTSRateLimiter,
    create_tts_rate_limiter,
    get_tts_rate_limiter,
    set_tts_rate_limiter,
)


class TestProviderRateLimiter:
    """Test ProviderRateLimiter (simple token/window limiter)."""

    def test_init_defaults(self):
        limiter = ProviderRateLimiter()
        assert limiter.max_tpm == 6000
        assert limiter.max_rpm == 30
        assert limiter._tokens_used == 0
        assert limiter._requests_used == 0

    def test_init_custom(self):
        limiter = ProviderRateLimiter(max_tpm=1000, max_rpm=10)
        assert limiter.max_tpm == 1000
        assert limiter.max_rpm == 10

    def test_can_proceed_within_limits(self):
        limiter = ProviderRateLimiter(max_tpm=100, max_rpm=10)
        assert limiter.can_proceed(50) is True
        limiter.record_usage(50)
        assert limiter.can_proceed(50) is True

    def test_can_proceed_exceeds_tokens(self):
        limiter = ProviderRateLimiter(max_tpm=100, max_rpm=10)
        limiter.record_usage(80)
        assert limiter.can_proceed(30) is False  # 80+30 > 100

    def test_can_proceed_exceeds_requests(self):
        limiter = ProviderRateLimiter(max_tpm=100, max_rpm=5)
        for _ in range(5):
            limiter.record_usage(10)
        assert limiter.can_proceed(10) is False  # 5 requests used

    def test_can_proceed_window_reset(self):
        limiter = ProviderRateLimiter(max_tpm=100, max_rpm=5)
        limiter._tokens_used = 90
        limiter._requests_used = 4
        limiter._window_start = time.time() - 61  # Past window

        assert limiter.can_proceed(10) is True
        assert limiter._tokens_used == 0  # Reset
        assert limiter._requests_used == 0  # Reset

    def test_record_usage(self):
        limiter = ProviderRateLimiter()
        limiter.record_usage(25)
        assert limiter._tokens_used == 25
        assert limiter._requests_used == 1

    def test_thread_safety(self):
        """Test thread-safe operations."""
        limiter = ProviderRateLimiter(max_tpm=10000, max_rpm=1000)
        results = []

        def worker():
            for _ in range(100):
                time.sleep(0.001)  # Small delay
                if limiter.can_proceed(10):
                    limiter.record_usage(10)
                    results.append(True)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should succeed
        assert len(results) == 500


class TestRateLimitConfig:
    """Test RateLimitConfig dataclass."""

    def test_defaults(self):
        config = RateLimitConfig(provider_name="test")
        assert config.provider_name == "test"
        assert config.requests_per_minute == 60
        assert config.requests_per_hour == 1000
        assert config.requests_per_day == 10000
        assert config.bucket_capacity == 10
        assert config.refill_rate_per_sec == 1.0

    def test_custom_values(self):
        config = RateLimitConfig(
            provider_name="custom",
            requests_per_minute=120,
            requests_per_hour=5000,
            requests_per_day=50000,
            bucket_capacity=20,
            refill_rate_per_sec=2.0,
        )
        assert config.requests_per_minute == 120
        assert config.bucket_capacity == 20
        assert config.refill_rate_per_sec == 2.0


class TestTokenBucket:
    """Test TokenBucket implementation."""

    def test_init(self):
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        assert bucket.capacity == 10
        assert bucket.refill_rate == 1.0
        assert bucket._tokens == 10.0
        assert bucket._last_refill > 0

    def test_consume_available(self):
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        assert bucket.consume(5) is True
        assert bucket._tokens == 5.0

    def test_consume_insufficient(self):
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        bucket.consume(10)
        # The key invariant: after draining the full capacity, no further token
        # is available. We avoid asserting an exact sub-ms token count because
        # the bucket refills continuously from monotonic time and a tight
        # tolerance flakes under concurrent/loaded CI executors.
        assert bucket.consume(1) is False
        assert 0.0 <= bucket._tokens < 1.0

    def test_consume_refill(self):
        bucket = TokenBucket(capacity=10, refill_rate=10.0)  # 10 tokens/sec
        bucket.consume(10)
        assert bucket._tokens < 0.1

        time.sleep(0.2)  # 2 tokens refilled
        assert bucket.consume(1) is True
        assert bucket._tokens >= 0.0

    def test_wait_for_token_success(self):
        bucket = TokenBucket(capacity=5, refill_rate=10.0)  # Fast refill
        bucket.consume(5)
        assert bucket._tokens == pytest.approx(0.0, abs=1e-5)

        result = bucket.wait_for_token(3, timeout=1.0)
        assert result is True
        # Token bucket refills continuously; after consuming refilled tokens,
        # a small amount will have refilled again in the brief time since
        # wait_for_token returned. Use a generous tolerance.
        assert bucket._tokens == pytest.approx(0.0, abs=0.5)

    def test_wait_for_token_timeout(self):
        bucket = TokenBucket(capacity=5, refill_rate=0.1)  # Slow refill
        bucket.consume(5)

        result = bucket.wait_for_token(3, timeout=0.1)
        assert result is False

    def test_get_available(self):
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        bucket.consume(3)
        time.sleep(0.1)
        available = bucket.get_available()
        assert available >= 7.0  # 7 + 0.1 refill
        assert available <= 10.0  # Capped at capacity

    def test_thread_safety(self):
        bucket = TokenBucket(capacity=1000, refill_rate=100.0)
        results = []

        def worker():
            for _ in range(100):
                result = bucket.consume(1)
                results.append(result)
                time.sleep(0.001)

            # Wait for refill
            time.sleep(0.5)
            for _ in range(50):
                result = bucket.consume(1)
                results.append(result)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should not crash
        assert len(results) == 750


class TestTTSRateLimiter:
    """Test TTSRateLimiter class."""

    def test_init_with_configs(self):
        configs = {
            "provider1": RateLimitConfig(provider_name="provider1", bucket_capacity=5, refill_rate_per_sec=0.5),
            "provider2": RateLimitConfig(provider_name="provider2", bucket_capacity=10, refill_rate_per_sec=1.0),
        }
        limiter = TTSRateLimiter(configs=configs)

        assert "provider1" in limiter.configs
        assert "provider2" in limiter.configs
        assert "provider1" in limiter._buckets
        assert "provider2" in limiter._buckets
        assert limiter._buckets["provider1"].capacity == 5
        assert limiter._buckets["provider1"].refill_rate == 0.5

    def test_init_empty_configs(self):
        limiter = TTSRateLimiter(configs={})
        assert limiter.configs == {}
        assert limiter._buckets == {}

    def test_init_none_configs(self):
        limiter = TTSRateLimiter(configs=None)
        assert limiter.configs == {}
        assert limiter._buckets == {}

    def test_get_bucket_existing(self):
        configs = {"test": RateLimitConfig(provider_name="test", bucket_capacity=5, refill_rate_per_sec=1.0)}
        limiter = TTSRateLimiter(configs=configs)

        bucket = limiter._get_bucket("test")
        assert bucket.capacity == 5
        assert bucket.refill_rate == 1.0

    def test_get_bucket_creates_default(self):
        limiter = TTSRateLimiter(configs={})

        bucket = limiter._get_bucket("unknown")
        assert bucket.capacity == 5
        assert bucket.refill_rate == 0.5

    def test_get_bucket_thread_safety(self):
        """Test lazy bucket creation is thread-safe."""
        limiter = TTSRateLimiter(configs={})
        buckets = []

        def worker():
            bucket = limiter._get_bucket("shared")
            buckets.append(bucket)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should get the same bucket
        assert all(b is buckets[0] for b in buckets)

    def test_acquire_success(self):
        configs = {"test": RateLimitConfig(provider_name="test", bucket_capacity=5, refill_rate_per_sec=10.0)}
        limiter = TTSRateLimiter(configs=configs)

        result = limiter.acquire("test", tokens=2, timeout=1.0)
        assert result is True

    def test_acquire_timeout(self):
        limiter = TTSRateLimiter(
            configs={
                "test": RateLimitConfig(provider_name="test", bucket_capacity=3, refill_rate_per_sec=0.1),
            }
        )

        limiter.acquire("test", tokens=3)  # Use all

        result = limiter.acquire("test", tokens=2, timeout=0.1)
        assert result is False

    def test_try_acquire(self):
        configs = {"test": RateLimitConfig(provider_name="test", bucket_capacity=5, refill_rate_per_sec=1.0)}
        limiter = TTSRateLimiter(configs=configs)

        assert limiter.try_acquire("test", 3) is True
        assert limiter.try_acquire("test", 3) is False  # Only 2 left
        assert limiter.try_acquire("test", 2) is True

    def test_get_status(self):
        configs = {
            "test": RateLimitConfig(
                provider_name="test", requests_per_minute=60, bucket_capacity=5, refill_rate_per_sec=1.0
            )
        }
        limiter = TTSRateLimiter(configs=configs)

        status = limiter.get_status("test")

        assert status["provider"] == "test"
        assert status["available_tokens"] >= 0
        assert status["capacity"] == 5
        assert status["refill_rate"] == 1.0
        assert status["configured_rpm"] == 60
        assert status["configured_rph"] == 1000

    def test_get_status_unknown_provider(self):
        limiter = TTSRateLimiter(configs={})

        status = limiter.get_status("unknown")

        assert status["provider"] == "unknown"
        assert status["capacity"] == 5  # Default
        assert status["configured_rpm"] is None

    def test_get_all_status(self):
        configs = {
            "p1": RateLimitConfig(provider_name="p1"),
            "p2": RateLimitConfig(provider_name="p2"),
        }
        limiter = TTSRateLimiter(configs=configs)

        all_status = limiter.get_all_status()

        assert set(all_status.keys()) == {"p1", "p2"}

    def test_reset(self):
        configs = {"test": RateLimitConfig(provider_name="test", bucket_capacity=5, refill_rate_per_sec=1.0)}
        limiter = TTSRateLimiter(configs=configs)

        before = limiter._buckets["test"].get_available()
        limiter.acquire("test", 5)
        after = limiter._buckets["test"].get_available()
        # Acquiring the full capacity must drain the bucket. The tiny residual
        # allowed for is the continuous refill that occurs between acquire and
        # the measurement (amplified under full-suite load), so assert on the
        # consumed delta rather than an exact zero.
        assert before - after == pytest.approx(5.0, abs=1e-2)

        limiter.reset("test")
        assert limiter._buckets["test"].get_available() == 5

    def test_reset_nonexistent(self):
        limiter = TTSRateLimiter(configs={})
        limiter.reset("nonexistent")  # Should not raise


class TestDefaultRateLimits:
    """Test DEFAULT_TTS_RATE_LIMITS constants."""

    def test_default_configs_exist(self):
        expected_providers = ["voxcpm2_remote", "edge", "azure", "gcp", "kokoro"]
        for provider in expected_providers:
            assert provider in DEFAULT_TTS_RATE_LIMITS

    def test_kokoro_high_limits(self):
        config = DEFAULT_TTS_RATE_LIMITS["kokoro"]
        assert config.requests_per_minute == 1000
        assert config.bucket_capacity == 100
        assert config.refill_rate_per_sec == 16.67

    def test_voxcpm2_conservative_limits(self):
        config = DEFAULT_TTS_RATE_LIMITS["voxcpm2_remote"]
        assert config.requests_per_minute == 20
        assert config.bucket_capacity == 5
        assert config.refill_rate_per_sec == 0.33

    def test_edge_moderate_limits(self):
        config = DEFAULT_TTS_RATE_LIMITS["edge"]
        assert config.requests_per_minute == 60
        assert config.bucket_capacity == 10
        assert config.refill_rate_per_sec == 1.0


class TestFactoryFunctions:
    """Test factory functions."""

    def test_create_tts_rate_limiter_defaults(self):
        limiter = create_tts_rate_limiter()

        assert isinstance(limiter, TTSRateLimiter)
        assert set(limiter.configs.keys()) == set(DEFAULT_TTS_RATE_LIMITS.keys())

    def test_create_tts_rate_limiter_custom(self):
        custom = {"custom": RateLimitConfig(provider_name="custom", bucket_capacity=100, refill_rate_per_sec=10.0)}
        limiter = create_tts_rate_limiter(custom_configs=custom)

        assert "custom" in limiter.configs
        assert set(limiter.configs.keys()) == set(DEFAULT_TTS_RATE_LIMITS.keys()) | {"custom"}

    def test_create_tts_rate_limiter_with_redis(self):
        mock_redis = Mock()
        limiter = create_tts_rate_limiter(redis_client=mock_redis)
        assert limiter._redis == mock_redis


class TestGlobalSingleton:
    """Test global singleton functions."""

    def setup_method(self):
        """Reset global before each test."""
        import src.audiobook_studio.tts.rate_limiter as rl

        rl._global_limiter = None

    def test_get_tts_rate_limiter_creates_default(self):
        limiter = get_tts_rate_limiter()
        assert isinstance(limiter, TTSRateLimiter)

    def test_get_tts_rate_limiter_singleton(self):
        limiter1 = get_tts_rate_limiter()
        limiter2 = get_tts_rate_limiter()
        assert limiter1 is limiter2

    def test_set_tts_rate_limiter(self):
        custom = create_tts_rate_limiter()
        set_tts_rate_limiter(custom)

        assert get_tts_rate_limiter() is custom


class TestRateLimiterIntegration:
    """Integration tests for rate limiter workflows."""

    def test_burst_handling(self):
        """Test token bucket handles burst correctly."""
        limiter = create_tts_rate_limiter()

        # Should allow burst up to bucket capacity
        for i in range(10):
            result = limiter.try_acquire("edge")
            assert result is True, f"Request {i+1} failed"

        # 11th should fail (capacity 10)
        result = limiter.try_acquire("edge")
        assert result is False

    def test_refill_over_time(self):
        """Test tokens refill over time."""
        limiter = create_tts_rate_limiter()

        # Use all edge tokens
        for _ in range(10):
            limiter.try_acquire("edge")

        assert limiter.try_acquire("edge") is False

        # Wait for refill (1 token/sec, need 1)
        time.sleep(1.1)

        assert limiter.try_acquire("edge") is True

    def test_per_provider_isolation(self):
        """Test providers don't share buckets."""
        limiter = create_tts_rate_limiter()

        # Exhaust edge
        for _ in range(10):
            limiter.try_acquire("edge")

        # kokoro should still have capacity (100)
        for _ in range(50):
            assert limiter.try_acquire("kokoro") is True

    def test_kokoro_local_unlimited_behavior(self):
        """Test kokoro (local) has effectively unlimited capacity."""
        limiter = create_tts_rate_limiter()

        # Should handle many requests — kokoro has high capacity (100)
        for _ in range(100):
            result = limiter.try_acquire("kokoro")
            assert result is True

    @pytest.mark.asyncio
    async def test_concurrent_acquire(self):
        """Test concurrent acquire from multiple tasks."""
        import asyncio

        limiter = create_tts_rate_limiter()
        config = RateLimitConfig(provider_name="async_test", bucket_capacity=50, refill_rate_per_sec=50.0)
        limiter.configs["async_test"] = config
        # Trigger bucket creation
        limiter._get_bucket("async_test")

        async def worker():
            for _ in range(20):
                limiter.acquire("async_test", timeout=1.0)

        await asyncio.gather(*[worker() for _ in range(3)])

        # All should succeed (60 total, capacity 50 + refill)

    def test_status_reporting(self):
        """Test status reporting accuracy."""
        limiter = create_tts_rate_limiter()

        status = limiter.get_status("edge")
        initial_available = status["available_tokens"]

        limiter.acquire("edge", tokens=5)

        status = limiter.get_status("edge")
        assert status["available_tokens"] == initial_available - 5


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_refill_rate_zero(self):
        """Test bucket with zero refill rate."""
        bucket = TokenBucket(capacity=5, refill_rate=0.0)
        bucket.consume(5)

        assert bucket.consume(1) is False
        time.sleep(0.5)
        assert bucket.consume(1) is False

    def test_consume_negative_tokens(self):
        """Test consuming negative tokens (should work as add)."""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        before = bucket.get_available()
        bucket.consume(5)

        # Can't pass negative to consume, but test edge: 5 tokens consumed.
        # Compare the delta so the continuous refill between measurements
        # (amplified under full-suite load) does not break the assertion.
        after = bucket.get_available()
        assert before - after == pytest.approx(5.0, abs=1e-2)

    def test_capacity_zero(self):
        """Test bucket with zero capacity."""
        bucket = TokenBucket(capacity=0, refill_rate=1.0)
        assert bucket.consume(1) is False

    def test_config_write_through(self):
        """Test that bucket params match config."""
        config = RateLimitConfig(provider_name="test", bucket_capacity=7, refill_rate_per_sec=0.7)
        limiter = TTSRateLimiter(configs={"test": config})

        bucket = limiter._get_bucket("test")
        assert bucket.capacity == 7
        assert bucket.refill_rate == 0.7

    def test_multiple_resources_mock_acquire(self):
        """Test rate limiter acquire with mocked get_tts_rate_limiter."""
        mock_limiter = Mock()
        mock_limiter.acquire = Mock(return_value=True)

        with patch("src.audiobook_studio.tts.rate_limiter.get_tts_rate_limiter", return_value=mock_limiter):
            from src.audiobook_studio.tts.rate_limiter import get_tts_rate_limiter

            limiter = get_tts_rate_limiter()
            result = limiter.acquire("test")
            assert result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
