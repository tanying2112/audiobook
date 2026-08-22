"""Tests for vLLM Backend - Local inference with KV cache and speculative decoding.

P2-2: Replace Ollama with vLLM for KV cache + speculative decoding to reduce LLM cost 30-50%.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audiobook_studio.llm.vllm_backend import (
    VLLMBackend,
    VLLMBackendConfig,
    create_vllm_backend,
)
from src.audiobook_studio.schemas import ParagraphAnnotation


class TestVLLMBackendConfig:
    """Test VLLMBackendConfig dataclass."""

    def test_default_values(self):
        config = VLLMBackendConfig(model="qwen2.5:14b")
        assert config.model == "qwen2.5:14b"
        assert config.host == "localhost"
        assert config.port == 8000
        assert config.temperature == 0.1
        assert config.max_tokens == 4000
        assert config.timeout == 60
        assert config.max_model_len == 32768
        assert config.gpu_memory_utilization == 0.9
        assert config.enable_chunked_prefill is True
        assert config.enable_prefix_caching is True
        assert config.speculative_model is None
        assert config.num_speculative_tokens == 5

    def test_custom_values(self):
        config = VLLMBackendConfig(
            model="llama3.1:8b",
            host="127.0.0.1",
            port=8001,
            temperature=0.5,
            max_tokens=8000,
            timeout=120,
            max_model_len=8192,
            gpu_memory_utilization=0.8,
            enable_chunked_prefill=False,
            enable_prefix_caching=False,
            speculative_model="draft-model",
            num_speculative_tokens=3,
        )
        assert config.model == "llama3.1:8b"
        assert config.host == "127.0.0.1"
        assert config.port == 8001
        assert config.temperature == 0.5
        assert config.max_tokens == 8000
        assert config.timeout == 120
        assert config.max_model_len == 8192
        assert config.gpu_memory_utilization == 0.8
        assert config.enable_chunked_prefill is False
        assert config.enable_prefix_caching is False
        assert config.speculative_model == "draft-model"
        assert config.num_speculative_tokens == 3


class TestCreateVLLMBackend:
    """Test create_vllm_backend factory function."""

    def test_create_vllm_backend(self):
        config = VLLMBackendConfig(model="qwen2.5:14b")
        backend = create_vllm_backend(config)
        assert isinstance(backend, VLLMBackend)
        assert backend.config.model == "qwen2.5:14b"


class TestVLLMBackend:
    """Test VLLMBackend functionality."""

    @pytest.fixture
    def vllm_config(self):
        return VLLMBackendConfig(
            model="qwen2.5:14b",
            host="localhost",
            port=8000,
        )

    def test_init_mock_mode(self, vllm_config):
        """Test initialization in mock mode."""
        with patch.dict(os.environ, {"MOCK_LLM": "true"}):
            backend = create_vllm_backend(vllm_config)
            assert backend.config.model == "qwen2.5:14b"

    def test_call_mock_mode(self, vllm_config):
        """Test call in mock mode returns valid output."""
        with patch.dict(os.environ, {"MOCK_LLM": "true"}):
            backend = create_vllm_backend(vllm_config)
            result = backend.call(
                prompt=[{"role": "user", "content": "test prompt"}],
                response_model=ParagraphAnnotation,
            )

            assert result is not None
            assert result.output is not None
            assert isinstance(result.output, ParagraphAnnotation)
            assert result.model == "qwen2.5:14b"
            assert result.latency_ms >= 0

    def test_call_with_messages_list(self, vllm_config):
        """Test call with messages list."""
        with patch.dict(os.environ, {"MOCK_LLM": "true"}):
            backend = create_vllm_backend(vllm_config)
            result = backend.call(
                prompt=[
                    {"role": "system", "content": "system prompt"},
                    {"role": "user", "content": "user prompt"},
                ],
                response_model=ParagraphAnnotation,
            )

            assert result is not None
            assert result.output is not None

    def test_call_mock_mode_different_models(self, vllm_config):
        """Test mock mode works for different response models."""
        from src.audiobook_studio.schemas import BookAnalysisOutput, QualityJudgment, TtsEditOutput
        
        with patch.dict(os.environ, {"MOCK_LLM": "true"}):
            backend = create_vllm_backend(vllm_config)
            
            for model in [ParagraphAnnotation, BookAnalysisOutput, QualityJudgment, TtsEditOutput]:
                result = backend.call(prompt="test", response_model=model)
                assert result.output is not None
                assert isinstance(result.output, model)

    def test_mock_mode_via_config(self, vllm_config):
        """Test that config.mock_mode property works."""
        config = VLLMBackendConfig(model="qwen2.5:14b")
        
        # Without MOCK_LLM env var, mock_mode should be False
        if "MOCK_LLM" in os.environ:
            del os.environ["MOCK_LLM"]
        assert config.mock_mode is False
        
        # With MOCK_LLM env var, mock_mode should be True
        os.environ["MOCK_LLM"] = "true"
        config2 = VLLMBackendConfig(model="qwen2.5:14b")
        assert config2.mock_mode is True
        
        # With MOCK_LLM=false, mock_mode should be False
        os.environ["MOCK_LLM"] = "false"
        config3 = VLLMBackendConfig(model="qwen2.5:14b")
        assert config3.mock_mode is False


class TestVLLMBackendIntegration:
    """Integration tests for VLLMBackend with router."""

    def test_router_can_use_vllm_backend(self):
        """Test that router can be configured to use vLLM backend."""
        from src.audiobook_studio.llm.config_loader import ProviderConfig, ProviderType, StageName
        
        # Create a provider config for vLLM
        provider = ProviderConfig(
            name="vllm_local",
            provider=ProviderType.OLLAMA,  # Reuse OLLAMA type for local
            model="qwen2.5:14b",
            base_url="http://localhost:8000/v1",
            priority=1,
            max_tokens_per_minute=100000,
            max_requests_per_minute=100,
            timeout_seconds=0,
            stages=[StageName.ANNOTATE, StageName.EDIT, StageName.JUDGE],
            enabled=True,
            extra_params={
                "use_vllm": True,
                "vllm_config": {
                    "max_model_len": 32768,
                    "gpu_memory_utilization": 0.9,
                    "enable_chunked_prefill": True,
                    "enable_prefix_caching": True,
                }
            },
        )
        
        # Verify the config has the vLLM flag
        assert provider.extra_params.get("use_vllm") is True
        assert "vllm_config" in provider.extra_params


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
