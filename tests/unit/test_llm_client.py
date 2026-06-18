"""Tests for LLM client module."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audiobook_studio.llm.client import (
    LLMCallResult,
    LLMClient,
    LLMClientConfig,
    MODEL_PRICING,
    create_client,
)


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
        assert config.mock_mode is False
        assert config.mock_data_dir == "tests/golden"
        assert config.api_base is None

    def test_custom_config(self):
        """Test creating config with custom values."""
        config = LLMClientConfig(
            model="custom-model",
            temperature=0.5,
            max_tokens=2000,
            mock_mode=True,
            mock_data_dir="/custom/path",
        )
        assert config.model == "custom-model"
        assert config.temperature == 0.5
        assert config.max_tokens == 2000
        assert config.mock_mode is True
        assert config.mock_data_dir == "/custom/path"


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


class TestLLMClientMockMode:
    """Tests for LLMClient in mock mode."""

    def test_init_mock_mode(self):
        """Test initializing client in mock mode."""
        client = create_client("test-model", mock_mode=True)
        assert client.config.mock_mode is True
        assert client._client is None

    def test_load_mock_data(self):
        """Test loading mock data from golden dataset."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a mock few_shot.jsonl file
            stage_dir = Path(tmpdir) / "prompts" / "analyze"
            stage_dir.mkdir(parents=True)
            few_shot = stage_dir / "few_shot.jsonl"
            few_shot.write_text(
                '{"input": {"test": "data"}, "expected_output": {"value": "mock"}}\n',
                encoding="utf-8",
            )

            config = LLMClientConfig(model="test-model", mock_mode=True, mock_data_dir=tmpdir)
            client = LLMClient(config)
            # Check that mock cache was populated
            assert len(client._mock_cache) >= 1

    def test_call_mock_mode_analyze(self):
        """Test call in mock mode for analyze stage."""
        client = create_client("test-model", mock_mode=True)

        from src.audiobook_studio.schemas import BookAnalysisOutput

        messages = [{"role": "user", "content": "Analyze this book"}]
        result = client.call(BookAnalysisOutput, messages, stage="analyze")

        assert isinstance(result, LLMCallResult)
        assert isinstance(result.output, BookAnalysisOutput)
        assert result.tokens_in == 0
        assert result.tokens_out == 0
        assert result.cost_usd == 0.0
        assert result.schema_compliance is True

    def test_call_mock_mode_judge(self):
        """Test call in mock mode for judge stage."""
        client = create_client("test-model", mock_mode=True)

        from src.audiobook_studio.schemas import QualityJudgment

        messages = [{"role": "user", "content": "Judge this audio"}]
        result = client.call(QualityJudgment, messages, stage="judge")

        assert isinstance(result.output, QualityJudgment)

    def test_call_mock_mode_annotate(self):
        """Test call in mock mode for annotate stage."""
        client = create_client("test-model", mock_mode=True)

        from src.audiobook_studio.schemas import ParagraphAnnotation

        messages = [{"role": "user", "content": "Annotate this paragraph"}]
        result = client.call(ParagraphAnnotation, messages, stage="annotate")

        assert isinstance(result.output, ParagraphAnnotation)

    def test_call_mock_mode_edit(self):
        """Test call in mock mode for edit stage."""
        client = create_client("test-model", mock_mode=True)

        from src.audiobook_studio.schemas import TtsEditOutput

        messages = [{"role": "user", "content": "Edit this text"}]
        result = client.call(TtsEditOutput, messages, stage="edit")

        assert isinstance(result.output, TtsEditOutput)

    def test_call_mock_mode_route(self):
        """Test call in mock mode for route stage."""
        client = create_client("test-model", mock_mode=True)

        from src.audiobook_studio.schemas import TtsRoutingDecision

        messages = [{"role": "user", "content": "Route this TTS"}]
        result = client.call(TtsRoutingDecision, messages, stage="route")

        assert isinstance(result.output, TtsRoutingDecision)

    def test_call_mock_mode_extract(self):
        """Test call in mock mode for extract stage."""
        client = create_client("test-model", mock_mode=True)

        from src.audiobook_studio.schemas import ExtractionResult

        messages = [{"role": "user", "content": "Extract this text"}]
        result = client.call(ExtractionResult, messages, stage="extract")

        # In mock mode, output might be a dict from golden cache or an ExtractionResult
        assert result is not None
        assert result.output is not None
        assert result.tokens_in == 0
        assert result.tokens_out == 0
        assert result.cost_usd == 0.0
        assert result.schema_compliance is True

    def test_call_mock_mode_unknown_stage(self):
        """Test call in mock mode for unknown stage raises error."""
        client = create_client("test-model", mock_mode=True)

        from pydantic import BaseModel

        class UnknownModel(BaseModel):
            value: str

        messages = [{"role": "user", "content": "Test"}]
        # Unknown stage - the mock returns None, then tries real API which fails in mock mode
        with pytest.raises(AttributeError):
            client.call(UnknownModel, messages, stage="unknown")

    def test_calculate_cost(self):
        """Test cost calculation."""
        client = create_client("gemini-2.0-flash", mock_mode=True)

        # gemini-2.0-flash: input=$0.075/M, output=$0.30/M
        cost = client._calculate_cost("gemini-2.0-flash", 1_000_000, 1_000_000)
        assert cost == pytest.approx(0.375)  # 0.075 + 0.30

        # Unknown model uses defaults
        cost = client._calculate_cost("unknown-model", 1_000_000, 1_000_000)
        assert cost == pytest.approx(4.0)  # 1.0 + 3.0

    def test_calculate_cost_zero(self):
        """Test cost calculation for free models."""
        client = create_client("cerebras/llama-3.3-70b", mock_mode=True)

        cost = client._calculate_cost("cerebras/llama-3.3-70b", 1_000_000, 1_000_000)
        assert cost == 0.0


class TestLLMClientRealMode:
    """Tests for LLMClient in real mode (mocked)."""

    @patch("src.audiobook_studio.llm.client.instructor.from_litellm")
    @patch("src.audiobook_studio.llm.client.completion")
    def test_init_real_mode(self, mock_completion, mock_instructor):
        """Test initializing client in real mode."""
        mock_client = MagicMock()
        mock_instructor.return_value = mock_client

        config = LLMClientConfig(model="gpt-4o", mock_mode=False)
        client = LLMClient(config)

        assert client._client == mock_client
        assert mock_instructor.called

    @patch("src.audiobook_studio.llm.client.instructor.from_litellm")
    @patch("src.audiobook_studio.llm.client.completion")
    def test_call_real_mode_success(self, mock_completion, mock_instructor):
        """Test successful real mode call."""
        # Setup mock
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
        mock_raw = MagicMock()
        mock_raw.usage.prompt_tokens = 100
        mock_raw.usage.completion_tokens = 50
        mock_response._raw_response = mock_raw

        mock_client.chat.completions.create.return_value = mock_response

        client = create_client("gpt-4o", mock_mode=False)

        messages = [{"role": "user", "content": "Test"}]
        result = client.call(QualityJudgment, messages, stage="judge")

        assert isinstance(result, LLMCallResult)
        assert result.output == mock_response
        assert result.tokens_in == 100
        assert result.tokens_out == 50
        assert result.cost_usd > 0
        assert result.latency_ms >= 0  # Can be 0 in fast mocks
        assert result.schema_compliance is True

    @patch("src.audiobook_studio.llm.client.instructor.from_litellm")
    @patch("src.audiobook_studio.llm.client.completion")
    def test_call_real_mode_exception(self, mock_completion, mock_instructor):
        """Test real mode call exception handling."""
        mock_client = MagicMock()
        mock_instructor.return_value = mock_client

        mock_client.chat.completions.create.side_effect = Exception("API Error")

        client = create_client("gpt-4o", mock_mode=False)

        from src.audiobook_studio.schemas import QualityJudgment

        messages = [{"role": "user", "content": "Test"}]
        with pytest.raises(Exception, match="API Error"):
            client.call(QualityJudgment, messages, stage="judge")

    @patch("src.audiobook_studio.llm.client.instructor.from_litellm")
    @patch("src.audiobook_studio.llm.client.completion")
    def test_call_real_mode_with_api_base(self, mock_completion, mock_instructor):
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
        mock_raw = MagicMock()
        mock_raw.usage.prompt_tokens = 100
        mock_raw.usage.completion_tokens = 50
        mock_response._raw_response = mock_raw

        mock_client.chat.completions.create.return_value = mock_response

        client = create_client("gpt-4o", mock_mode=False, api_base="https://custom.api/v1")

        messages = [{"role": "user", "content": "Test"}]
        result = client.call(QualityJudgment, messages, stage="judge")

        # Check api_base was passed
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs.get("api_base") == "https://custom.api/v1"


class TestCreateClient:
    """Tests for create_client factory function."""

    def test_create_client_mock(self):
        """Test creating mock client."""
        client = create_client("test-model", mock_mode=True)
        assert isinstance(client, LLMClient)
        assert client.config.mock_mode is True

    def test_create_client_real(self):
        """Test creating real client."""
        with patch("src.audiobook_studio.llm.client.instructor.from_litellm"):
            client = create_client("gpt-4o", mock_mode=False)
            assert isinstance(client, LLMClient)
            assert client.config.mock_mode is False

    def test_create_client_with_params(self):
        """Test creating client with custom parameters."""
        with patch("src.audiobook_studio.llm.client.instructor.from_litellm"):
            client = create_client(
                "gpt-4o",
                mock_mode=False,
                temperature=0.5,
                max_tokens=2000,
                api_base="https://custom.api",
            )
            assert client.config.temperature == 0.5
            assert client.config.max_tokens == 2000
            assert client.config.api_base == "https://custom.api"

    def test_create_client_langfuse(self):
        """Test creating client with Langfuse config."""
        with patch("src.audiobook_studio.llm.client.instructor.from_litellm"):
            with patch("src.audiobook_studio.llm.client.LANGFUSE_AVAILABLE", True):
                with patch("src.audiobook_studio.llm.client.Langfuse"):
                    client = create_client(
                        "gpt-4o",
                        mock_mode=False,
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])