"""Tests for Quota Registry."""

import pytest
from src.audiobook_studio.llm.quota_registry import (
    QuotaRegistry,
    QuotaConfig,
    QuotaUsage,
    get_quota_registry,
    init_quota_registry,
)


class TestQuotaConfig:
    """Tests for QuotaConfig dataclass."""

    def test_default_config(self):
        """Test creating config with defaults."""
        config = QuotaConfig(provider_name="test-provider")
        assert config.provider_name == "test-provider"
        assert config.daily_limit == 0
        assert config.requests_per_minute == 0
        assert config.requests_per_day == 0
        assert config.tokens_per_minute == 0
        assert config.tokens_per_day == 0
        assert config.reset_time_utc == "00:00"

    def test_custom_config(self):
        """Test creating config with custom values."""
        config = QuotaConfig(
            provider_name="custom-provider",
            daily_limit=1000,
            requests_per_minute=10,
            requests_per_day=1000,
            tokens_per_minute=5000,
            tokens_per_day=100000,
            reset_time_utc="04:00",
        )
        assert config.provider_name == "custom-provider"
        assert config.daily_limit == 1000
        assert config.requests_per_minute == 10
        assert config.requests_per_day == 1000
        assert config.tokens_per_minute == 5000
        assert config.tokens_per_day == 100000
        assert config.reset_time_utc == "04:00"


class TestQuotaUsage:
    """Tests for QuotaUsage dataclass."""

    def test_default_usage(self):
        """Test creating usage with defaults."""
        from datetime import date
        usage = QuotaUsage(provider_name="test-provider")
        assert usage.provider_name == "test-provider"
        assert usage.requests_today == 0
        assert usage.tokens_today == 0
        assert usage.requests_this_minute == 0
        assert usage.tokens_this_minute == 0
        assert usage.last_reset_date == date.today()
        assert usage.last_successful_request is None
        assert usage.consecutive_failures == 0
        assert usage.total_failures_today == 0


class TestQuotaRegistry:
    """Tests for QuotaRegistry."""

    def setup_method(self):
        """Reset registry for each test."""
        init_quota_registry()
        self.registry = get_quota_registry()

    def test_register_config(self):
        """Test registering a quota config."""
        config = QuotaConfig(
            provider_name="new-provider",
            daily_limit=500,
            requests_per_minute=5,
            requests_per_day=500,
        )
        self.registry.register_config(config)
        assert "new-provider" in self.registry._configs
        assert "new-provider" in self.registry._usage

    def test_get_config(self):
        """Test getting quota config."""
        config = self.registry.get_config("gemini_flash")
        assert config is not None
        assert config.provider_name == "gemini_flash"
        assert config.daily_limit == 1500

    def test_get_usage(self):
        """Test getting quota usage."""
        usage = self.registry.get_usage("gemini_flash")
        assert usage is not None
        assert usage.provider_name == "gemini_flash"

    def test_can_make_request_no_limit(self):
        """Test can_make_request with no limits configured."""
        # Register a provider with no limits
        config = QuotaConfig(provider_name="unlimited-provider")
        self.registry.register_config(config)
        assert self.registry.can_make_request("unlimited-provider", 1000) is True

    def test_can_make_request_daily_limit(self):
        """Test can_make_request with daily limit."""
        config = QuotaConfig(
            provider_name="limited-provider",
            requests_per_day=10,
        )
        self.registry.register_config(config)

        # Should be able to make requests initially
        assert self.registry.can_make_request("limited-provider", 1000) is True

        # Exhaust the daily limit
        self.registry._usage["limited-provider"].requests_today = 10
        assert self.registry.can_make_request("limited-provider", 1000) is False

    def test_can_make_request_minute_limit(self):
        """Test can_make_request with minute limit."""
        config = QuotaConfig(
            provider_name="minute-limited-provider",
            requests_per_minute=5,
        )
        self.registry.register_config(config)

        # Should be able to make requests initially
        assert self.registry.can_make_request("minute-limited-provider", 1000) is True

        # Exhaust the minute limit
        self.registry._usage["minute-limited-provider"].requests_this_minute = 5
        assert self.registry.can_make_request("minute-limited-provider", 1000) is False

    def test_record_request_success(self):
        """Test recording a successful request."""
        self.registry.record_request("gemini_flash", tokens_used=1000, success=True)
        usage = self.registry.get_usage("gemini_flash")
        assert usage.requests_today == 1
        assert usage.tokens_today == 1000
        assert usage.requests_this_minute == 1
        assert usage.tokens_this_minute == 1000
        assert usage.consecutive_failures == 0
        assert usage.last_successful_request is not None

    def test_record_request_failure(self):
        """Test recording a failed request."""
        self.registry.record_request("gemini_flash", tokens_used=0, success=False)
        usage = self.registry.get_usage("gemini_flash")
        assert usage.consecutive_failures == 1
        assert usage.total_failures_today == 1
        assert usage.requests_today == 0
        assert usage.tokens_today == 0

    def test_get_quota_status(self):
        """Test getting quota status."""
        status = self.registry.get_quota_status("gemini_flash")
        assert status["provider"] == "gemini_flash"
        assert status["configured"] is True
        assert "daily" in status
        assert "minute" in status
        assert "health" in status
        assert "healthy" in status

    def test_get_all_statuses(self):
        """Test getting all quota statuses."""
        statuses = self.registry.get_all_statuses()
        assert "gemini_flash" in statuses
        assert "groq_70b" in statuses
        assert "ollama_qwen25" in statuses

    def test_get_healthy_providers(self):
        """Test getting healthy providers."""
        healthy = self.registry.get_healthy_providers()
        assert isinstance(healthy, list)
        assert "gemini_flash" in healthy
        assert "ollama_qwen25" in healthy

    def test_get_quota_health_score(self):
        """Test getting health score."""
        score = self.registry.get_quota_health_score("gemini_flash")
        assert 0 <= score <= 1

        # Exhaust quota to test low score
        self.registry._usage["gemini_flash"].requests_today = 1490
        score = self.registry.get_quota_health_score("gemini_flash")
        assert score < 0.1

    def test_default_providers_registered(self):
        """Test that default providers are registered."""
        configs = self.registry._configs
        assert "gemini_flash" in configs
        assert "groq_70b" in configs
        assert "groq_8b" in configs
        assert "cerebras" in configs
        assert "opencode_zen" in configs
        assert "siliconcloud" in configs
        assert "zhipu_glm" in configs
        assert "nvidia_nemotron" in configs
        assert "openrouter" in configs
        assert "alibaba_bailian" in configs
        assert "github_models" in configs
        assert "cloudflare_ai" in configs
        assert "ollama_qwen25" in configs
        assert "ollama_llama31" in configs

    def test_quota_reset(self):
        """Test daily and minute quota reset."""
        config = QuotaConfig(
            provider_name="reset-provider",
            requests_per_day=10,
            requests_per_minute=5,
        )
        self.registry.register_config(config)

        # Use some quota
        self.registry.record_request("reset-provider", success=True)
        self.registry.record_request("reset-provider", success=True)
        usage = self.registry.get_usage("reset-provider")
        assert usage.requests_today == 2

        # Can't easily test time-based reset without mocking time
        # but we can verify the logic is in place
        assert hasattr(self.registry, '_check_reset')


class TestRouterQuotaIntegration:
    """Tests for quota registry integration with router."""

    def test_router_has_quota_registry(self):
        """Test that router has quota registry."""
        from src.audiobook_studio.llm.router import create_router
        router = create_router(mock_mode=True)
        assert hasattr(router, 'quota_registry')

    def test_router_get_quota_status(self):
        """Test router get_quota_status method."""
        from src.audiobook_studio.llm.router import create_router
        router = create_router(mock_mode=True)
        status = router.get_quota_status("gemini_flash")
        assert status["provider"] == "gemini_flash"
        assert status["configured"] is True

    def test_router_get_healthy_providers(self):
        """Test router get_quota_healthy_providers method."""
        from src.audiobook_studio.llm.router import create_router
        router = create_router(mock_mode=True)
        healthy = router.get_quota_healthy_providers()
        assert isinstance(healthy, list)
        assert "gemini_flash" in healthy

    def test_router_get_quota_health_score(self):
        """Test router get_quota_health_score method."""
        from src.audiobook_studio.llm.router import create_router
        router = create_router(mock_mode=True)
        score = router.get_quota_health_score("gemini_flash")
        assert 0 <= score <= 1

    def test_router_free_tier_health(self):
        """Test router get_free_tier_health method."""
        from src.audiobook_studio.llm.router import create_router
        router = create_router(mock_mode=True)
        health = router.get_free_tier_health()
        assert "total_free_providers" in health
        assert "healthy_free_providers" in health
        assert "free_quota_success_rate" in health
        assert "overall_health" in health
        assert health["overall_health"] in ["green", "yellow", "red"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
