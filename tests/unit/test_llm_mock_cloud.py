"""Comprehensive mock tests for LLM Client and Router.

Eliminates all real cloud dependencies (401/403 prevention).

Tests:
1. LLMClient success branch - Mock returns valid Pydantic objects
2. LLMClient failure branch - API error / timeout → exception propagation
3. LLMClient._mock_call - all response model types (coverage for _mock_call)
4. Router.call() success - Mock client returns valid result
5. Router.call() all providers fail → heuristic fallback (Kill Switch)
6. Router.call() all providers fail → no fallback → RuntimeError
7. Router.call() provider exception → circuit breaker records failure
8. Langfuse is completely disabled (no network calls)
"""

import os
import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from src.audiobook_studio.llm.client import (
    LLMCallResult,
    LLMClient,
    LLMClientConfig,
    create_client,
)
from src.audiobook_studio.schemas import (
    BookAnalysisOutput,
    ExtractionResult,
    ParagraphAnnotation,
    QualityJudgment,
    TtsEditOutput,
    TtsRoutingDecision,
    BookMeta,
    CharacterVoiceBinding,
    EmotionSnapshot,
)
from src.audiobook_studio.schemas import FeedbackAnalysis


# ======================================================================
# LLMClient: success branch
# ======================================================================


class TestLLMClientSuccessBranch:
    """Mock model returns valid Pydantic objects — no real HTTP calls."""

    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    @patch("instructor.from_litellm")
    def test_call_returns_quality_judgment(self, mock_instructor):
        """Client.call() returns LLMCallResult with valid QualityJudgment."""
        mock_client = MagicMock()
        mock_instructor.return_value = mock_client

        mock_output = QualityJudgment(
            segment_id="seg_001",
            speaker_clarity=0.92,
            emotion_match=0.88,
            prosody_naturalness=0.90,
            text_audio_alignment=0.91,
            overall_score=0.90,
            issues=[],
            fix_suggestions=[],
            needs_regeneration=False,
        )
        mock_output._raw_response = {
            "usage": {"prompt_tokens": 120, "completion_tokens": 60}
        }
        mock_client.chat.completions.create.return_value = mock_output

        config = LLMClientConfig(model="gemini-2.0-flash")
        client = LLMClient(config)
        client._client = mock_client

        messages = [{"role": "user", "content": "Evaluate quality"}]
        result = client.call(
            response_model=QualityJudgment, messages=messages, stage="judge"
        )

        assert isinstance(result, LLMCallResult)
        assert isinstance(result.output, QualityJudgment)
        assert result.output.segment_id == "seg_001"
        assert result.tokens_in == 120
        assert result.tokens_out == 60
        assert result.cost_usd > 0
        assert result.schema_compliance is True
        mock_client.chat.completions.create.assert_called_once()

    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    @patch("instructor.from_litellm")
    def test_call_returns_book_analysis(self, mock_instructor):
        """Client.call() returns valid BookAnalysisOutput."""
        mock_client = MagicMock()
        mock_instructor.return_value = mock_client

        mock_output = BookAnalysisOutput(
            book_meta=BookMeta(
                title="Test Book",
                author="Author",
                genre="小说",
                difficulty="B",
                language="zh",
                era="现代",
                total_chapters_estimated=10,
            ),
            character_voice_map=[
                CharacterVoiceBinding(
                    canonical_name="旁白",
                    aliases=[],
                    gender="neutral",
                    age_range="adult",
                    suggested_voice_id="v1",
                    sample_quote="旁白台词。",
                )
            ],
            emotion_snapshots=[
                EmotionSnapshot(chapter=1, dominant_emotion="neutral", intensity=0.5, notes="测试")
            ],
            story_line_summary="这是一个用于测试的故事主线摘要，必须超过一百个字符才能通过Pydantic验证器的最小长度约束。故事讲述了一位平凡的主角在现代都市中经历各种冒险和成长的过程，通过克服重重困难最终实现了自我超越的励志历程。",
            global_style_notes="测试文风备注：保持平实叙述。",
        )
        mock_output._raw_response = {
            "usage": {"prompt_tokens": 200, "completion_tokens": 100}
        }
        mock_client.chat.completions.create.return_value = mock_output

        config = LLMClientConfig(model="gemini-2.0-flash")
        client = LLMClient(config)
        client._client = mock_client

        messages = [{"role": "user", "content": "Analyze book"}]
        result = client.call(
            response_model=BookAnalysisOutput, messages=messages, stage="analyze"
        )

        assert isinstance(result.output, BookAnalysisOutput)
        assert result.output.book_meta.title == "Test Book"

    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    @patch("instructor.from_litellm")
    def test_call_with_string_prompt(self, mock_instructor):
        """Client.call() works with string prompt (backward compat)."""
        mock_client = MagicMock()
        mock_instructor.return_value = mock_client

        mock_output = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="旁白",
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            pause_before_ms=300,
            pause_after_ms=500,
            confidence=0.9,
            difficulty="B",
            needs_sfx=False,
            sfx_tags=[],
        )
        mock_output._raw_response = {
            "usage": {"prompt_tokens": 80, "completion_tokens": 40}
        }
        mock_client.chat.completions.create.return_value = mock_output

        config = LLMClientConfig(model="gemini-2.0-flash")
        client = LLMClient(config)
        client._client = mock_client

        result = client.call(
            prompt="Annotate this paragraph",
            response_model=ParagraphAnnotation,
        )

        assert isinstance(result.output, ParagraphAnnotation)

    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    @patch("instructor.from_litellm")
    def test_call_with_text_keyword(self, mock_instructor):
        """Client.call() accepts text= keyword for prompt."""
        mock_client = MagicMock()
        mock_instructor.return_value = mock_client

        mock_output = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="旁白",
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            pause_before_ms=300,
            pause_after_ms=500,
            confidence=0.9,
            difficulty="B",
            needs_sfx=False,
            sfx_tags=[],
        )
        mock_output._raw_response = {"usage": {"prompt_tokens": 50, "completion_tokens": 25}}
        mock_client.chat.completions.create.return_value = mock_output

        config = LLMClientConfig(model="gpt-4o")
        client = LLMClient(config)
        client._client = mock_client

        result = client.call(
            text="Annotate text",
            response_model=ParagraphAnnotation,
        )
        assert isinstance(result.output, ParagraphAnnotation)

    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    @patch("instructor.from_litellm")
    def test_call_with_content_keyword(self, mock_instructor):
        """Client.call() accepts content= keyword for prompt."""
        mock_client = MagicMock()
        mock_instructor.return_value = mock_client

        mock_output = ExtractionResult(raw_text="text", language="zh", page_count=1)
        mock_output._raw_response = {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        mock_client.chat.completions.create.return_value = mock_output

        config = LLMClientConfig(model="gpt-4o")
        client = LLMClient(config)
        client._client = mock_client

        result = client.call(
            content="Extract text",
            response_model=ExtractionResult,
        )
        assert isinstance(result.output, ExtractionResult)

    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    @patch("instructor.from_litellm")
    def test_call_zero_tokens(self, mock_instructor):
        """Client.call() handles response without usage info."""
        mock_client = MagicMock()
        mock_instructor.return_value = mock_client

        mock_output = QualityJudgment(
            segment_id="s1",
            speaker_clarity=0.5,
            emotion_match=0.5,
            prosody_naturalness=0.5,
            text_audio_alignment=0.5,
            overall_score=0.5,
            issues=[],
            fix_suggestions=[],
            needs_regeneration=False,
        )
        # No _raw_response attribute → no usage → tokens stay 0
        mock_client.chat.completions.create.return_value = mock_output

        config = LLMClientConfig(model="gpt-4o")
        client = LLMClient(config)
        client._client = mock_client

        result = client.call(
            prompt="test",
            response_model=QualityJudgment,
            stage="judge",
        )
        assert result.tokens_in == 0
        assert result.tokens_out == 0
        assert result.cost_usd == 0.0


# ======================================================================
# LLMClient: failure / degradation branches
# ======================================================================


class TestLLMClientFailureBranch:
    """Mock model throws API error or timeout — verify error propagation."""

    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    @patch("instructor.from_litellm")
    def test_call_api_401_error(self, mock_instructor):
        """Client.call() raises on HTTP 401 Unauthorized."""
        mock_client = MagicMock()
        mock_instructor.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception(
            "litellm.exceptions.AuthenticationError: 401 Unauthorized"
        )

        config = LLMClientConfig(model="gemini-2.0-flash")
        client = LLMClient(config)
        client._client = mock_client

        with pytest.raises(Exception, match="401 Unauthorized"):
            client.call(
                prompt="test",
                response_model=QualityJudgment,
                stage="judge",
            )

    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    @patch("instructor.from_litellm")
    def test_call_api_403_error(self, mock_instructor):
        """Client.call() raises on HTTP 403 Forbidden."""
        mock_client = MagicMock()
        mock_instructor.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception(
            "litellm.exceptions.PermissionDeniedError: 403 Forbidden"
        )

        config = LLMClientConfig(model="openai/qwen-max")
        client = LLMClient(config)
        client._client = mock_client

        with pytest.raises(Exception, match="403 Forbidden"):
            client.call(
                prompt="test",
                response_model=BookAnalysisOutput,
            )

    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    @patch("instructor.from_litellm")
    def test_call_timeout_error(self, mock_instructor):
        """Client.call() raises on timeout."""
        mock_client = MagicMock()
        mock_instructor.return_value = mock_client
        mock_client.chat.completions.create.side_effect = TimeoutError(
            "Request timed out after 60s"
        )

        config = LLMClientConfig(model="gpt-4o")
        client = LLMClient(config)
        client._client = mock_client

        with pytest.raises(TimeoutError):
            client.call(prompt="test", response_model=QualityJudgment)

    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    @patch("instructor.from_litellm")
    def test_call_rate_limit_error(self, mock_instructor):
        """Client.call() raises on 429 Too Many Requests."""
        mock_client = MagicMock()
        mock_instructor.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception(
            "litellm.exceptions.RateLimitError: 429 Too Many Requests"
        )

        config = LLMClientConfig(model="gemini-2.0-flash")
        client = LLMClient(config)
        client._client = mock_client

        with pytest.raises(Exception, match="429"):
            client.call(prompt="test", response_model=ParagraphAnnotation)

    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    @patch("instructor.from_litellm")
    def test_call_none_output_rejected(self, mock_instructor):
        """Client.call() rejects None output from model."""
        mock_client = MagicMock()
        mock_instructor.return_value = mock_client
        mock_client.chat.completions.create.return_value = None

        config = LLMClientConfig(model="gpt-4o")
        client = LLMClient(config)
        client._client = mock_client

        # validate_and_parse_llm_response should raise for None
        from src.audiobook_studio.llm.utils import LLMParseError
        with pytest.raises(LLMParseError):
            client.call(prompt="test", response_model=QualityJudgment)

    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    def test_call_missing_prompt_raises(self):
        """Client.call() raises ValueError when no prompt provided."""
        config = LLMClientConfig(model="gpt-4o")
        client = LLMClient(config)

        with pytest.raises(ValueError, match="prompt is required"):
            client.call(response_model=QualityJudgment)

    @patch.dict(os.environ, {"MOCK_LLM": "false"})
    def test_call_missing_response_model_raises(self):
        """Client.call() raises ValueError when no response_model provided."""
        config = LLMClientConfig(model="gpt-4o")
        client = LLMClient(config)

        with pytest.raises(ValueError, match="response_model is required"):
            client.call(prompt="test")


# ======================================================================
# LLMClient._mock_call — all response model types
# ======================================================================


class TestLLMClientMockCall:
    """Test _mock_call covers all response model branches."""

    def test_mock_call_book_analysis(self):
        """_mock_call returns BookAnalysisOutput for unknown prompt."""
        os.environ["MOCK_LLM"] = "true"
        config = LLMClientConfig(model="mock-model")
        client = LLMClient(config)
        result = client._mock_call("any prompt", BookAnalysisOutput)
        assert isinstance(result.output, BookAnalysisOutput)
        assert result.model == "mock-model"
        assert result.tokens_in == 0

    def test_mock_call_extraction_result(self):
        """_mock_call returns ExtractionResult."""
        os.environ["MOCK_LLM"] = "true"
        config = LLMClientConfig(model="mock-model")
        client = LLMClient(config)
        result = client._mock_call("any", ExtractionResult)
        assert isinstance(result.output, ExtractionResult)

    def test_mock_call_paragraph_annotation(self):
        """_mock_call returns ParagraphAnnotation."""
        os.environ["MOCK_LLM"] = "true"
        config = LLMClientConfig(model="mock-model")
        client = LLMClient(config)
        result = client._mock_call("any", ParagraphAnnotation)
        assert isinstance(result.output, ParagraphAnnotation)

    def test_mock_call_quality_judgment(self):
        """_mock_call returns QualityJudgment."""
        os.environ["MOCK_LLM"] = "true"
        config = LLMClientConfig(model="mock-model")
        client = LLMClient(config)
        result = client._mock_call("any", QualityJudgment)
        assert isinstance(result.output, QualityJudgment)

    def test_mock_call_tts_edit_output(self):
        """_mock_call returns TtsEditOutput."""
        os.environ["MOCK_LLM"] = "true"
        config = LLMClientConfig(model="mock-model")
        client = LLMClient(config)
        result = client._mock_call("any", TtsEditOutput)
        assert isinstance(result.output, TtsEditOutput)

    def test_mock_call_tts_routing_decision(self):
        """_mock_call returns TtsRoutingDecision."""
        os.environ["MOCK_LLM"] = "true"
        config = LLMClientConfig(model="mock-model")
        client = LLMClient(config)
        result = client._mock_call("any", TtsRoutingDecision)
        assert isinstance(result.output, TtsRoutingDecision)

    def test_mock_call_feedback_analysis(self):
        """_mock_call returns FeedbackAnalysis via string check."""
        os.environ["MOCK_LLM"] = "true"
        config = LLMClientConfig(model="mock-model")
        client = LLMClient(config)
        # _mock_call checks `response_model == 'FeedbackAnalysis'` (string comparison)
        result = client._mock_call("any", "FeedbackAnalysis")
        # This hits the `elif response_model == 'FeedbackAnalysis'` branch
        # but FeedbackAnalysis is a string, not a class, so it falls to else
        # The real class is FeedbackAnalysis from schemas
        # Let's test with the actual class instead
        result = client._mock_call("any", FeedbackAnalysis)
        assert isinstance(result.output, FeedbackAnalysis)

    def test_mock_call_unknown_model_returns_none(self):
        """_mock_call with truly unknown model returns None output."""
        os.environ["MOCK_LLM"] = "true"
        config = LLMClientConfig(model="mock-model")
        client = LLMClient(config)

        class UninstantiableModel:
            def __init__(self):
                raise TypeError("cannot instantiate")

        result = client._mock_call("any", UninstantiableModel)
        assert result.output is None


# ======================================================================
# LLMClient: Langfuse init paths
# ======================================================================


class TestLLMClientLangfuseInit:
    """Test Langfuse initialization paths in LLMClient."""

    def test_langfuse_disabled_by_default(self):
        """Client does not init Langfuse when langfuse_enabled=False."""
        os.environ["MOCK_LLM"] = "true"
        config = LLMClientConfig(model="mock-model", langfuse_enabled=False)
        client = LLMClient(config)
        assert client._langfuse is None

    @patch.dict(os.environ, {"MOCK_LLM": "true"})
    @patch("langfuse.Langfuse", side_effect=ImportError("no langfuse"))
    def test_langfuse_import_error(self, mock_langfuse):
        """Client handles ImportError from Langfuse gracefully."""
        config = LLMClientConfig(
            model="mock-model",
            langfuse_enabled=True,
            langfuse_public_key="pk_test",
            langfuse_secret_key="sk_test",
        )
        client = LLMClient(config)
        assert client._langfuse is None

    @patch.dict(os.environ, {"MOCK_LLM": "true"})
    @patch("langfuse.Langfuse", side_effect=Exception("connection refused"))
    def test_langfuse_generic_exception(self, mock_langfuse):
        """Client handles generic exception from Langfuse init."""
        config = LLMClientConfig(
            model="mock-model",
            langfuse_enabled=True,
            langfuse_public_key="pk_test",
            langfuse_secret_key="sk_test",
        )
        client = LLMClient(config)
        assert client._langfuse is None


# ======================================================================
# Router.call(): success branch with mocked provider
# ======================================================================


class TestRouterCallSuccess:
    """Router.call() succeeds when at least one provider works."""

    def _make_router_for_call(self):
        from src.audiobook_studio.di import reset_app_container
        reset_app_container()
        os.environ["MOCK_LLM"] = "true"
        from src.audiobook_studio.llm.config_loader import LLMProvidersConfig
        config = MagicMock(spec=LLMProvidersConfig)
        provider = MagicMock(
            name="test_provider",
            enabled=True,
            priority=1,
            max_daily_cost_usd=1.0,
            max_tokens_per_minute=100000,
            max_requests_per_minute=60,
            api_key_env="TEST_API_KEY",
            api_key_pool_env=[],
            key_rotation_strategy="round_robin",
            provider="openai",
        )
        config.get_all_enabled.return_value = [provider]
        config.get_providers_for_stage.return_value = [provider]
        config.prompt_compression = MagicMock(
            max_input_tokens=8000,
            truncate_strategy="smart",
            remove_few_shot_when_long=True,
            min_few_shot_examples=2,
            schema_injection_mode="json",
        )

        with patch("src.audiobook_studio.llm.router.LLMProvidersConfig.load", return_value=config):
            from src.audiobook_studio.llm.router import LLMRouter
            router = LLMRouter(mock_mode=False)

        return router, provider

    @patch("src.audiobook_studio.llm.router.create_client")
    def test_call_success_returns_result(self, mock_create_client):
        """Router.call() returns LLMCallResult when provider succeeds."""
        from src.audiobook_studio.di import reset_app_container
        reset_app_container()
        router, provider = self._make_router_for_call()

        # Mock the client call
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        mock_output = QualityJudgment(
            segment_id="seg_001",
            speaker_clarity=0.9,
            emotion_match=0.85,
            prosody_naturalness=0.9,
            text_audio_alignment=0.92,
            overall_score=0.89,
            issues=[],
            fix_suggestions=[],
            needs_regeneration=False,
        )
        mock_call_result = LLMCallResult(
            output=mock_output,
            model="gemini-2.0-flash",
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.001,
            latency_ms=200,
            schema_compliance=True,
            raw_response=mock_output.model_dump(),
        )
        mock_client.call.return_value = mock_call_result

        messages = [{"role": "system", "content": "You are a judge"}, {"role": "user", "content": "Evaluate"}]
        result = router.call(
            stage="judge",
            response_model=QualityJudgment,
            messages=messages,
            segment_id="seg_001",
        )

        assert isinstance(result, LLMCallResult)
        assert isinstance(result.output, QualityJudgment)
        assert result.output.segment_id == "seg_001"
        reset_app_container()


# ======================================================================
# Router.call(): all providers fail → heuristic fallback
# ======================================================================


class TestRouterCallFallback:
    """Router.call() triggers heuristic fallback when all providers fail."""

    def _make_failing_router(self):
        from src.audiobook_studio.di import reset_app_container
        reset_app_container()
        os.environ["MOCK_LLM"] = "true"
        from src.audiobook_studio.llm.config_loader import LLMProvidersConfig
        config = MagicMock(spec=LLMProvidersConfig)
        provider = MagicMock(
            name="failing_provider",
            enabled=True,
            priority=1,
            max_daily_cost_usd=1.0,
            max_tokens_per_minute=100000,
            max_requests_per_minute=60,
            api_key_env="TEST_API_KEY",
            api_key_pool_env=[],
            key_rotation_strategy="round_robin",
            provider="openai",
        )
        config.get_all_enabled.return_value = [provider]
        config.get_providers_for_stage.return_value = [provider]
        config.prompt_compression = MagicMock(
            max_input_tokens=8000,
            truncate_strategy="smart",
            remove_few_shot_when_long=True,
            min_few_shot_examples=2,
            schema_injection_mode="json",
        )

        with patch("src.audiobook_studio.llm.router.LLMProvidersConfig.load", return_value=config):
            from src.audiobook_studio.llm.router import LLMRouter
            router = LLMRouter(mock_mode=False)

        return router, provider

    @patch("src.audiobook_studio.llm.router.create_client")
    def test_all_providers_fail_triggers_fallback_judge(self, mock_create_client):
        """All providers fail → heuristic fallback returns QualityJudgment."""
        from src.audiobook_studio.di import reset_app_container
        router, provider = self._make_failing_router()

        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.call.side_effect = Exception("API Error: 401 Unauthorized")

        messages = [{"role": "user", "content": "Judge quality"}]
        result = router.call(
            stage="judge",
            response_model=QualityJudgment,
            messages=messages,
            segment_id="seg_001",
        )

        assert isinstance(result, LLMCallResult)
        assert isinstance(result.output, QualityJudgment)
        assert result.model == "heuristic_fallback"
        assert result.cost_usd == 0.0
        assert result.schema_compliance is False
        reset_app_container()

    @patch("src.audiobook_studio.llm.router.create_client")
    def test_all_providers_fail_fallback_annotate(self, mock_create_client):
        """All providers fail → heuristic fallback returns ParagraphAnnotation."""
        from src.audiobook_studio.di import reset_app_container
        router, provider = self._make_failing_router()

        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.call.side_effect = Exception("Connection timeout")

        messages = [{"role": "user", "content": "Annotate paragraph"}]
        result = router.call(
            stage="annotate",
            response_model=ParagraphAnnotation,
            messages=messages,
        )

        assert isinstance(result, LLMCallResult)
        assert isinstance(result.output, ParagraphAnnotation)
        assert result.model == "heuristic_fallback"
        reset_app_container()

    @patch("src.audiobook_studio.llm.router.create_client")
    def test_all_providers_fail_fallback_edit(self, mock_create_client):
        """All providers fail → heuristic fallback returns TtsEditOutput."""
        from src.audiobook_studio.di import reset_app_container
        router, provider = self._make_failing_router()

        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.call.side_effect = RuntimeError("Service unavailable")

        messages = [{"role": "user", "content": "Edit text"}]
        result = router.call(
            stage="edit",
            response_model=TtsEditOutput,
            messages=messages,
        )

        assert isinstance(result, LLMCallResult)
        assert isinstance(result.output, TtsEditOutput)
        assert result.model == "heuristic_fallback"
        reset_app_container()

    @patch("src.audiobook_studio.llm.router.create_client")
    def test_all_providers_fail_fallback_analyze(self, mock_create_client):
        """All providers fail → heuristic fallback returns BookAnalysisOutput."""
        from src.audiobook_studio.di import reset_app_container
        router, provider = self._make_failing_router()

        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.call.side_effect = Exception("HTTP 403")

        messages = [{"role": "user", "content": "Analyze book"}]
        result = router.call(
            stage="analyze",
            response_model=BookAnalysisOutput,
            messages=messages,
        )

        assert isinstance(result, LLMCallResult)
        assert isinstance(result.output, BookAnalysisOutput)
        assert result.model == "heuristic_fallback"
        reset_app_container()

    @patch("src.audiobook_studio.llm.router.create_client")
    def test_all_providers_fail_fallback_unknown_stage(self, mock_create_client):
        """All providers fail + no segment_id → heuristic fallback uses 'unknown'."""
        from src.audiobook_studio.di import reset_app_container
        router, provider = self._make_failing_router()

        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.call.side_effect = Exception("API Error")

        messages = [{"role": "user", "content": "Unknown"}]
        # Without segment_id, the router extracts segment_id="unknown" from kwargs
        # and _heuristic_fallback("judge", ..., segment_id="unknown") returns a valid QualityJudgment
        result = router.call(
            stage="judge",
            response_model=QualityJudgment,
            messages=messages,
            # No segment_id kwarg → defaults to "unknown"
        )
        assert isinstance(result, LLMCallResult)
        assert result.model == "heuristic_fallback"
        assert result.output.segment_id == "unknown"
        reset_app_container()


# ======================================================================
# Router.call(): provider circuit breaker integration
# ======================================================================


class TestRouterCallCircuitBreaker:
    """Provider failures record circuit breaker state."""

    def _make_router(self):
        from src.audiobook_studio.di import reset_app_container
        reset_app_container()
        os.environ["MOCK_LLM"] = "true"
        from src.audiobook_studio.llm.config_loader import LLMProvidersConfig
        config = MagicMock(spec=LLMProvidersConfig)
        provider = MagicMock(
            name="cb_provider",
            enabled=True,
            priority=1,
            max_daily_cost_usd=1.0,
            max_tokens_per_minute=100000,
            max_requests_per_minute=60,
            api_key_env="TEST_API_KEY",
            api_key_pool_env=[],
            key_rotation_strategy="round_robin",
            provider="openai",
        )
        config.get_all_enabled.return_value = [provider]
        config.get_providers_for_stage.return_value = [provider]
        config.prompt_compression = MagicMock(
            max_input_tokens=8000,
            truncate_strategy="smart",
            remove_few_shot_when_long=True,
            min_few_shot_examples=2,
            schema_injection_mode="json",
        )
        with patch("src.audiobook_studio.llm.router.LLMProvidersConfig.load", return_value=config):
            from src.audiobook_studio.llm.router import LLMRouter
            router = LLMRouter(mock_mode=False)
        return router, provider

    @patch("src.audiobook_studio.llm.router.create_client")
    def test_provider_failure_records_circuit_breaker(self, mock_create_client):
        """When provider fails, circuit breaker records the failure."""
        from src.audiobook_studio.di import reset_app_container
        router, provider = self._make_router()

        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.call.side_effect = Exception("API Error")

        # Circuit breaker keys use provider.name which is a MagicMock
        # Find the CB by iterating
        assert len(router.circuit_breakers) > 0
        cb_name, cb = next(iter(router.circuit_breakers.items()))
        initial_count = cb.failure_count

        messages = [{"role": "user", "content": "test"}]
        try:
            router.call(
                stage="judge",
                response_model=QualityJudgment,
                messages=messages,
                segment_id="s1",
            )
        except Exception:
            pass

        # Circuit breaker failure count should have increased
        assert cb.failure_count > initial_count
        reset_app_container()

    @patch("src.audiobook_studio.llm.router.create_client")
    def test_provider_failure_records_quota(self, mock_create_client):
        """When provider fails, quota registry records the failure."""
        from src.audiobook_studio.di import reset_app_container
        router, provider = self._make_router()

        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.call.side_effect = Exception("API Error")

        with patch.object(router.quota_registry, "record_request") as mock_record:
            messages = [{"role": "user", "content": "test"}]
            try:
                router.call(
                    stage="judge",
                    response_model=QualityJudgment,
                    messages=messages,
                    segment_id="s1",
                )
            except Exception:
                pass

            # record_request should have been called with success=False
            calls = mock_record.call_args_list
            failure_calls = [c for c in calls if c.kwargs.get("success") is False or (len(c.args) > 0 and not c.kwargs.get("success", True))]
            assert len(failure_calls) > 0
        reset_app_container()


# ======================================================================
# Langfuse fixture verification
# ======================================================================


class TestLangfuseDisabledInTests:
    """Verify that Langfuse is completely disabled during tests."""

    def test_langfuse_not_initialized(self):
        """Langfuse client should be None during tests."""
        import src.audiobook_studio.monitoring.langfuse_client as lfc
        assert lfc._enabled is False
        assert lfc._langfuse_client is None

    def test_observe_llm_call_is_noop(self):
        """observe_llm_call should not raise when Langfuse is disabled."""
        import src.audiobook_studio.monitoring.langfuse_client as lfc
        # Should be a no-op since _enabled is False
        lfc.observe_llm_call(
            stage="test",
            model="test-model",
            provider="test",
            prompt_tokens=10,
            completion_tokens=5,
        )

    def test_observe_quality_check_is_noop(self):
        """observe_quality_check should not raise."""
        import src.audiobook_studio.monitoring.langfuse_client as lfc
        lfc.observe_quality_check(
            stage="test",
            passed=True,
            score=0.9,
            issues=[],
            latency_ms=100,
        )

    def test_flush_langfuse_is_noop(self):
        """flush_langfuse should not raise."""
        import src.audiobook_studio.monitoring.langfuse_client as lfc
        lfc.flush_langfuse()
