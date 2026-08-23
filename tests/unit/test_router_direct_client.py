"""Test that router uses direct client when provider has use_direct_sdk=True."""

import os
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.llm.config_loader import LLMProvidersConfig, ProviderConfig, ProviderType, StageName
from src.audiobook_studio.llm.router import LLMRouter
from src.audiobook_studio.schemas import ParagraphAnnotation


def _make_direct_config():
    """Create a config with a provider that has use_direct_sdk=True."""
    config = MagicMock(spec=LLMProvidersConfig)
    
    # Provider with use_direct_sdk
    provider = MagicMock(
        name="openai_direct",
        enabled=True,
        priority=1,
        max_daily_cost_usd=10.0,
        max_tokens_per_minute=100000,
        max_requests_per_minute=60,
        api_key_env="OPENAI_API_KEY",
        api_key_pool_env=[],
        key_rotation_strategy="round_robin",
        provider=ProviderType.OPENAI,  # Use actual enum
        model="gpt-4o-mini",
        base_url=None,
        timeout_seconds=60,
        stages=[StageName.ANNOTATE],
        extra_params={"use_direct_sdk": True},
    )
    provider.name = "openai_direct"
    provider.get_api_key.return_value = "test-key"
    provider.get_litellm_model_name.return_value = "openai/gpt-4o-mini"
    
    config.get_all_enabled.return_value = [provider]
    config.get_providers_for_stage.return_value = [provider]
    config.prompt_compression = MagicMock(
        max_input_tokens=8000,
        truncate_strategy="smart",
        remove_few_shot_when_long=True,
        min_few_shot_examples=2,
        schema_injection_mode="json",
    )
    return config


def _make_litellm_config():
    """Create a config with a provider that does NOT have use_direct_sdk."""
    config = MagicMock(spec=LLMProvidersConfig)
    
    # Provider WITHOUT use_direct_sdk
    provider = MagicMock(
        name="openai_litellm",
        enabled=True,
        priority=1,
        max_daily_cost_usd=10.0,
        max_tokens_per_minute=100000,
        max_requests_per_minute=60,
        api_key_env="OPENAI_API_KEY",
        api_key_pool_env=[],
        key_rotation_strategy="round_robin",
        provider=ProviderType.OPENAI,  # Use actual enum
        model="gpt-4o-mini",
        base_url=None,
        timeout_seconds=60,
        stages=[StageName.ANNOTATE],
        extra_params={},  # No use_direct_sdk
    )
    provider.name = "openai_litellm"
    provider.get_api_key.return_value = "test-key"
    provider.get_litellm_model_name.return_value = "openai/gpt-4o-mini"
    
    config.get_all_enabled.return_value = [provider]
    config.get_providers_for_stage.return_value = [provider]
    config.prompt_compression = MagicMock(
        max_input_tokens=8000,
        truncate_strategy="smart",
        remove_few_shot_when_long=True,
        min_few_shot_examples=2,
        schema_injection_mode="json",
    )
    return config


def _make_anthropic_direct_config():
    """Create a config with an Anthropic provider that has use_direct_sdk=True."""
    config = MagicMock(spec=LLMProvidersConfig)
    
    provider = MagicMock(
        name="anthropic_direct",
        enabled=True,
        priority=1,
        max_daily_cost_usd=10.0,
        max_tokens_per_minute=100000,
        max_requests_per_minute=60,
        api_key_env="ANTHROPIC_API_KEY",
        api_key_pool_env=[],
        key_rotation_strategy="round_robin",
        provider=ProviderType.ANTHROPIC,  # Use actual enum
        model="claude-3-5-sonnet-20241022",
        base_url=None,
        timeout_seconds=60,
        stages=[StageName.ANNOTATE],
        extra_params={"use_direct_sdk": True},
    )
    provider.name = "anthropic_direct"
    provider.get_api_key.return_value = "test-key"
    provider.get_litellm_model_name.return_value = "anthropic/claude-3-5-sonnet-20241022"
    
    config.get_all_enabled.return_value = [provider]
    config.get_providers_for_stage.return_value = [provider]
    config.prompt_compression = MagicMock(
        max_input_tokens=8000,
        truncate_strategy="smart",
        remove_few_shot_when_long=True,
        min_few_shot_examples=2,
        schema_injection_mode="json",
    )
    return config


def test_router_creates_direct_client_for_provider_with_flag():
    """Test that router creates direct client when provider has use_direct_sdk=True."""
    from src.audiobook_studio.di import reset_app_container
    reset_app_container()
    
    os.environ["MOCK_LLM"] = "true"
    config = _make_direct_config()
    
    with patch.object(LLMProvidersConfig, "load", return_value=config):
        router = LLMRouter(mock_mode=True)
    
    # Verify direct_clients cache exists
    assert hasattr(router, "direct_clients")
    assert isinstance(router.direct_clients, dict)
    
    # Get the provider
    providers = config.get_providers_for_stage(StageName.ANNOTATE)
    provider = providers[0]
    
    # Verify get_direct_client returns a client
    direct_client = router.get_direct_client(provider)
    assert direct_client is not None
    
    # The key in direct_clients is the provider name
    assert "openai_direct" in router.direct_clients
    
    # Verify it's the right type
    from src.audiobook_studio.llm.direct_client import DirectProviderClient
    assert isinstance(direct_client, DirectProviderClient)
    assert direct_client.config.provider.value == "openai"
    
    reset_app_container()


def test_router_creates_anthropic_direct_client():
    """Test that router creates direct client for Anthropic provider."""
    from src.audiobook_studio.di import reset_app_container
    reset_app_container()
    
    os.environ["MOCK_LLM"] = "true"
    config = _make_anthropic_direct_config()
    
    with patch.object(LLMProvidersConfig, "load", return_value=config):
        router = LLMRouter(mock_mode=True)
    
    providers = config.get_providers_for_stage(StageName.ANNOTATE)
    provider = providers[0]
    
    direct_client = router.get_direct_client(provider)
    assert direct_client is not None
    assert "anthropic_direct" in router.direct_clients
    
    from src.audiobook_studio.llm.direct_client import DirectProviderClient, DirectProviderType
    assert isinstance(direct_client, DirectProviderClient)
    assert direct_client.config.provider == DirectProviderType.ANTHROPIC
    
    reset_app_container()


def test_router_uses_direct_client_in_call():
    """Test that router uses direct client when available."""
    from src.audiobook_studio.di import reset_app_container
    reset_app_container()
    
    os.environ["MOCK_LLM"] = "true"
    config = _make_direct_config()
    
    with patch.object(LLMProvidersConfig, "load", return_value=config):
        router = LLMRouter(mock_mode=True)
    
    # Call the router
    messages = [{"role": "user", "content": "test paragraph"}]
    result = router.call("annotate", ParagraphAnnotation, messages)
    
    # Verify result
    assert result is not None
    assert result.output is not None
    assert isinstance(result.output, ParagraphAnnotation)
    
    reset_app_container()


def test_router_does_not_create_direct_client_without_flag():
    """Test that router does not create direct client when use_direct_sdk is False."""
    from src.audiobook_studio.di import reset_app_container
    reset_app_container()
    
    os.environ["MOCK_LLM"] = "true"
    config = _make_litellm_config()
    
    with patch.object(LLMProvidersConfig, "load", return_value=config):
        router = LLMRouter(mock_mode=True)
    
    providers = config.get_providers_for_stage(StageName.ANNOTATE)
    provider = providers[0]
    
    # Verify get_direct_client returns None
    direct_client = router.get_direct_client(provider)
    assert direct_client is None
    assert "openai_litellm" not in router.direct_clients
    
    reset_app_container()


def test_router_falls_back_to_litellm_when_direct_not_configured():
    """Test that router falls back to LiteLLM when direct client not configured."""
    from src.audiobook_studio.di import reset_app_container
    reset_app_container()
    
    os.environ["MOCK_LLM"] = "true"
    config = _make_litellm_config()
    
    with patch.object(LLMProvidersConfig, "load", return_value=config):
        router = LLMRouter(mock_mode=True)
    
    # Call the router - should work via LiteLLM path
    messages = [{"role": "user", "content": "test paragraph"}]
    result = router.call("annotate", ParagraphAnnotation, messages)
    
    assert result is not None
    assert result.output is not None
    
    reset_app_container()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
