"""Tests for LLM client module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audiobook_studio.llm.client import MODEL_PRICING, LLMCallResult, LLMClient, LLMClientConfig, create_client


class TestLLMClientConfig:
    """Tests for LLMClientConfig dataclass."""

    def test_default_config(self):
        """Test creating config with defaults."""
        config = LLMClientConfig(model="test-model")
        assert config.model == "test-model"
        assert config.temperature == 0.1
        assert config.max_tokens == 4000
        assert config.max_retries == 3
        assert config.timeout == 60
        assert config.api_base is None

    def test_custom_config(self):
        """Test creating config with custom values."""
        config = LLMClientConfig(
            model="custom-model",
            temperature=0.5,
            max_tokens=2000,
        )
        assert config.model == "custom-model"
        assert config.temperature == 0.5
        assert config.max_tokens == 2000


class TestLLMCallResult:
    """Tests for LLMCallResult dataclass."""

    def test_create_result(self):
        """Test creating a call result."""
        from pydantic import BaseModel

        class TestModel(BaseModel):
            value: str

        output = TestModel(value="test")
        result = LLMCallResult(
            output=output,
            model="test-model",
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.001,
            latency_ms=500,
            schema_compliance=True,
            contract_version=1,
            raw_response=output,
        )
        assert result.output.value == "test"
        assert result.model == "test-model"
        assert result.tokens_in == 100
        assert result.tokens_out == 50
        assert result.cost_usd == 0.001
        assert result.latency_ms == 500
        assert result.schema_compliance is True


class TestLLMClientRealMode:
    """Tests for LLMClient in real mode (mocked)."""

    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    @patch("instructor.from_litellm")
    def test_init_real_mode(self, mock_instructor):
        """Test initializing client in real mode."""
        mock_client = MagicMock()
        mock_instructor.return_value = mock_client

        config = LLMClientConfig(model="gpt-4o")
        client = LLMClient(config)

        assert client._client == mock_client
        assert mock_instructor.called

    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    @patch("instructor.from_litellm")
    def test_call_real_mode_success(self, mock_instructor):
        """Test successful real mode call."""
        mock_client = MagicMock()
        mock_instructor.return_value = mock_client

        from src.audiobook_studio.schemas import QualityJudgment

        mock_response = QualityJudgment(
            segment_id="test",
            speaker_clarity=0.9,
            emotion_match=0.85,
            prosody_naturalness=0.88,
            text_audio_alignment=0.92,
            overall_score=0.88,
            issues=[],
            fix_suggestions=[],
            needs_regeneration=False,
        )
        mock_response._raw_response = {"usage": {"prompt_tokens": 100, "completion_tokens": 50}}

        mock_client.chat.completions.create.return_value = mock_response

        client = create_client("gpt-4o")

        messages = [{"role": "user", "content": "Test"}]
        result = client.call(response_model=QualityJudgment, messages=messages, stage="judge")

        assert isinstance(result, LLMCallResult)
        assert result.output == mock_response
        assert result.tokens_in == 100
        assert result.tokens_out == 50
        assert result.cost_usd > 0
        assert result.latency_ms >= 0
        assert result.schema_compliance is True

    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    @patch("instructor.from_litellm")
    def test_call_real_mode_exception(self, mock_instructor):
        """Test real mode call exception handling."""
        mock_client = MagicMock()
        mock_instructor.return_value = mock_client

        mock_client.chat.completions.create.side_effect = Exception("API Error")

        config = LLMClientConfig(model="gpt-4o")
        client = LLMClient(config)
        client._client = mock_client

        from src.audiobook_studio.schemas import QualityJudgment

        messages = [{"role": "user", "content": "Test"}]
        with pytest.raises(Exception, match="API Error"):
            client.call(response_model=QualityJudgment, messages=messages, stage="judge")

    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    @patch("instructor.from_litellm")
    def test_call_real_mode_with_api_base(self, mock_instructor):
        """Test call with custom api_base."""
        mock_client = MagicMock()
        mock_instructor.return_value = mock_client

        from src.audiobook_studio.schemas import QualityJudgment

        mock_response = QualityJudgment(
            segment_id="test",
            speaker_clarity=0.9,
            emotion_match=0.85,
            prosody_naturalness=0.88,
            text_audio_alignment=0.92,
            overall_score=0.88,
            issues=[],
            fix_suggestions=[],
            needs_regeneration=False,
        )
        mock_response._raw_response = {"usage": {"prompt_tokens": 100, "completion_tokens": 50}}

        mock_client.chat.completions.create.return_value = mock_response

        config = LLMClientConfig(model="gpt-4o", api_base="https://custom.api/v1")
        client = LLMClient(config)
        client._client = mock_client

        messages = [{"role": "user", "content": "Test"}]
        result = client.call(response_model=QualityJudgment, messages=messages, stage="judge")

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs.get("api_base") == "https://custom.api/v1"


class TestCreateClient:
    """Tests for create_client factory function."""

    def test_create_client(self):
        """Test creating client."""
        client = create_client("test-model")
        assert isinstance(client, LLMClient)

    def test_create_client_with_params(self):
        """Test creating client with custom parameters."""
        with patch("instructor.from_litellm"):
            client = create_client(
                "gpt-4o",
                temperature=0.5,
                max_tokens=2000,
                api_base="https://custom.api",
            )
            assert client.config.temperature == 0.5
            assert client.config.max_tokens == 2000
            assert client.config.api_base == "https://custom.api"

    def test_create_client_langfuse(self):
        """Test creating client with Langfuse config."""
        with patch("instructor.from_litellm"):
            with patch("langfuse.Langfuse"):
                client = create_client(
                    "gpt-4o",
                    langfuse_public_key="pk_test",
                    langfuse_secret_key="sk_test",
                    langfuse_enabled=True,
                )
                assert client.config.langfuse_enabled is True


class TestModelPricing:
    """Tests for MODEL_PRICING constant."""

    def test_known_models_have_pricing(self):
        """Test that known models have pricing entries."""
        assert "gemini-2.0-flash" in MODEL_PRICING
        assert "gpt-4o" in MODEL_PRICING
        assert "claude-3-5-sonnet" in MODEL_PRICING

    def test_free_models_have_zero_pricing(self):
        """Test that free tier models have zero pricing."""
        free_models = [
            "cerebras/llama-3.3-70b",
            "openai/qwen-max",
            "openai/glm-4-flash",
            "openrouter/meta-llama/llama-3.1-8b-instruct:free",
        ]
        for model in free_models:
            pricing = MODEL_PRICING.get(model)
            assert pricing is not None, f"Missing pricing for {model}"
            assert pricing["input"] == 0.0
            assert pricing["output"] == 0.0
