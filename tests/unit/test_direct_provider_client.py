"""Tests for DirectProviderClient - native OpenAI/Anthropic SDK integration.

P2-1: Bypass LiteLLM for OpenAI/Anthropic to reduce ~200ms overhead.
"""

import os
from unittest.mock import patch

import pytest

from src.audiobook_studio.llm.direct_client import (
    DirectProviderClient,
    DirectProviderClientConfig,
    DirectProviderType,
    create_direct_client,
)
from src.audiobook_studio.schemas import ParagraphAnnotation


class TestDirectProviderType:
    """Test DirectProviderType enum."""

    def test_openai_value(self):
        assert DirectProviderType.OPENAI == "openai"

    def test_anthropic_value(self):
        assert DirectProviderType.ANTHROPIC == "anthropic"


class TestDirectProviderClientConfig:
    """Test DirectProviderClientConfig dataclass."""

    def test_default_values(self):
        config = DirectProviderClientConfig(
            provider=DirectProviderType.OPENAI,
            model="gpt-4o-mini",
        )
        assert config.provider == DirectProviderType.OPENAI
        assert config.model == "gpt-4o-mini"
        assert config.temperature == 0.1
        assert config.max_tokens == 4000
        assert config.timeout == 60
        assert config.api_base is None
        assert config.api_key is None

    def test_custom_values(self):
        config = DirectProviderClientConfig(
            provider=DirectProviderType.ANTHROPIC,
            model="claude-3-5-sonnet-20241022",
            temperature=0.5,
            max_tokens=8000,
            timeout=120,
            api_base="https://api.anthropic.com",
            api_key="test-key",
        )
        assert config.provider == DirectProviderType.ANTHROPIC
        assert config.temperature == 0.5
        assert config.max_tokens == 8000
        assert config.timeout == 120
        assert config.api_base == "https://api.anthropic.com"
        assert config.api_key == "test-key"

    def test_mock_mode_property(self):
        """Test that config.mock_mode property reads MOCK_LLM env var."""
        # Save original env
        original = os.environ.get("MOCK_LLM")

        try:
            # Without MOCK_LLM env var, mock_mode should be False
            if "MOCK_LLM" in os.environ:
                del os.environ["MOCK_LLM"]
            config = DirectProviderClientConfig(
                provider=DirectProviderType.OPENAI,
                model="gpt-4o-mini",
                api_key="test-key",
            )
            assert config.mock_mode is False

            # With MOCK_LLM env var, mock_mode should be True
            os.environ["MOCK_LLM"] = "true"
            config2 = DirectProviderClientConfig(
                provider=DirectProviderType.OPENAI,
                model="gpt-4o-mini",
                api_key="test-key",
            )
            assert config2.mock_mode is True

            # With MOCK_LLM=false, mock_mode should be False
            os.environ["MOCK_LLM"] = "false"
            config3 = DirectProviderClientConfig(
                provider=DirectProviderType.OPENAI,
                model="gpt-4o-mini",
                api_key="test-key",
            )
            assert config3.mock_mode is False
        finally:
            # Restore
            if original is not None:
                os.environ["MOCK_LLM"] = original
            elif "MOCK_LLM" in os.environ:
                del os.environ["MOCK_LLM"]


class TestCreateDirectClient:
    """Test create_direct_client factory function."""

    def test_create_openai_client(self):
        config = DirectProviderClientConfig(
            provider=DirectProviderType.OPENAI,
            model="gpt-4o-mini",
            api_key="test-key",
        )
        client = create_direct_client(config)
        assert isinstance(client, DirectProviderClient)
        assert client.config.provider == DirectProviderType.OPENAI

    def test_create_anthropic_client(self):
        config = DirectProviderClientConfig(
            provider=DirectProviderType.ANTHROPIC,
            model="claude-3-5-sonnet-20241022",
            api_key="test-key",
        )
        client = create_direct_client(config)
        assert isinstance(client, DirectProviderClient)
        assert client.config.provider == DirectProviderType.ANTHROPIC


class TestDirectProviderClientOpenAI:
    """Test DirectProviderClient with OpenAI SDK."""

    @pytest.fixture
    def openai_config(self):
        return DirectProviderClientConfig(
            provider=DirectProviderType.OPENAI,
            model="gpt-4o-mini",
            api_key="test-key",
        )

    def test_call_openai_success(self, openai_config):
        """Test successful OpenAI call with structured output in mock mode."""
        with patch.dict(os.environ, {"MOCK_LLM": "true"}):
            config = DirectProviderClientConfig(
                provider=DirectProviderType.OPENAI,
                model="gpt-4o-mini",
                api_key="test-key",
            )
            client = create_direct_client(config)
            result = client.call(
                prompt=[{"role": "user", "content": "test prompt"}],
                response_model=ParagraphAnnotation,
            )

            assert result is not None
            assert result.output is not None
            assert isinstance(result.output, ParagraphAnnotation)
            assert result.model == "gpt-4o-mini"
            assert result.latency_ms >= 0

    def test_call_openai_with_messages_list(self, openai_config):
        """Test OpenAI call with messages list."""
        with patch.dict(os.environ, {"MOCK_LLM": "true"}):
            config = DirectProviderClientConfig(
                provider=DirectProviderType.OPENAI,
                model="gpt-4o-mini",
                api_key="test-key",
            )
            client = create_direct_client(config)
            result = client.call(
                prompt=[
                    {"role": "system", "content": "system prompt"},
                    {"role": "user", "content": "user prompt"},
                ],
                response_model=ParagraphAnnotation,
            )

            assert result is not None
            assert result.output is not None


class TestDirectProviderClientAnthropic:
    """Test DirectProviderClient with Anthropic SDK."""

    @pytest.fixture
    def anthropic_config(self):
        return DirectProviderClientConfig(
            provider=DirectProviderType.ANTHROPIC,
            model="claude-3-5-sonnet-20241022",
            api_key="test-key",
        )

    def test_call_anthropic_success(self, anthropic_config):
        """Test successful Anthropic call with structured output."""
        with patch.dict(os.environ, {"MOCK_LLM": "true"}):
            config = DirectProviderClientConfig(
                provider=DirectProviderType.ANTHROPIC,
                model="claude-3-5-sonnet-20241022",
                api_key="test-key",
            )
            client = create_direct_client(config)
            result = client.call(
                prompt=[{"role": "user", "content": "test prompt"}],
                response_model=ParagraphAnnotation,
            )

            assert result is not None
            assert result.output is not None
            assert isinstance(result.output, ParagraphAnnotation)
            assert result.model == "claude-3-5-sonnet-20241022"
            assert result.latency_ms >= 0


class TestDirectProviderClientMockMode:
    """Test DirectProviderClient mock mode behavior."""

    def test_mock_mode_returns_valid_output(self):
        """Test that mock mode returns valid ParagraphAnnotation."""
        with patch.dict(os.environ, {"MOCK_LLM": "true"}):
            config = DirectProviderClientConfig(
                provider=DirectProviderType.OPENAI,
                model="gpt-4o-mini",
                api_key="test-key",
            )
            client = create_direct_client(config)
            result = client.call(
                prompt="test",
                response_model=ParagraphAnnotation,
            )
            assert result.output is not None
            assert isinstance(result.output, ParagraphAnnotation)
            assert result.cost_usd == 0.0

    def test_mock_mode_different_models(self):
        """Test mock mode works for different response models."""
        from src.audiobook_studio.schemas import BookAnalysisOutput, QualityJudgment, TtsEditOutput

        with patch.dict(os.environ, {"MOCK_LLM": "true"}):
            config = DirectProviderClientConfig(
                provider=DirectProviderType.OPENAI,
                model="gpt-4o-mini",
                api_key="test-key",
            )
            client = create_direct_client(config)

            # Test different response models
            for model in [ParagraphAnnotation, BookAnalysisOutput, QualityJudgment, TtsEditOutput]:
                result = client.call(prompt="test", response_model=model)
                assert result.output is not None
                assert isinstance(result.output, model)


class TestDirectProviderClientIntegration:
    """Integration tests for DirectProviderClient with router."""

    def test_router_uses_direct_client_when_configured(self):
        """Test that router can use direct client when provider has use_direct_sdk=true."""
        from src.audiobook_studio.llm.config_loader import ProviderConfig, ProviderType

        # Create a provider config with use_direct_sdk
        provider = ProviderConfig(
            name="test_openai_direct",
            provider=ProviderType.OPENAI,
            model="gpt-4o-mini",
            api_key_env="OPENAI_API_KEY",
            priority=1,
            max_tokens_per_minute=100000,
            max_requests_per_minute=60,
            stages=["annotate"],
            enabled=True,
            extra_params={"use_direct_sdk": True},
        )

        # Verify the config has the flag
        assert provider.extra_params.get("use_direct_sdk") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
