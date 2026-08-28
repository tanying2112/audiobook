"""Mock-provider / mock-LLM tests for ``audiobook_studio.llm.client``.

These tests exercise ``LLMClient`` / ``LLMClientConfig`` fully through the
mock provider (enabled via the ``MOCK_LLM=true`` env var) plus crafted
non-mock scenarios with the underlying client monkeypatched, so no network,
API keys, or real model weights are required.
"""

import json
import os
import sys
import types
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from audiobook_studio.llm.client import LLMCallResult, LLMClient, LLMClientConfig, create_client
from audiobook_studio.llm.semantic_cache import get_semantic_cache, reset_semantic_cache
from audiobook_studio.schemas import (
    BookAnalysisOutput,
    ExtractionResult,
    FeedbackAnalysis,
    ParagraphAnnotation,
    QualityJudgment,
    TtsEditOutput,
    TtsRoutingDecision,
)


# --- local pydantic models used as response_model in various branches ----------
class SampleOut(BaseModel):
    a: int


class JsonlOut(BaseModel):
    req: int


class DefaultOut(BaseModel):
    y: int = 5


class RequiredOut(BaseModel):
    z: int  # required -> response_model() raises TypeError


class Out(BaseModel):
    x: int


# ===========================================================================
# Config
# ===========================================================================


class TestLLMClientConfig:
    def test_defaults(self):
        cfg = LLMClientConfig(model="m")
        assert cfg.temperature == 0.1
        assert cfg.max_tokens == 4000
        assert cfg.max_retries == 3
        assert cfg.timeout == 60
        assert cfg.mock_data_dir == "tests/golden"

    def test_custom(self):
        cfg = LLMClientConfig(model="m", temperature=0.5, max_tokens=2000, mock_data_dir="/tmp/x")
        assert cfg.temperature == 0.5
        assert cfg.max_tokens == 2000
        assert cfg.mock_data_dir == "/tmp/x"

    def test_mock_mode_false_by_default(self, monkeypatch):
        monkeypatch.delenv("MOCK_LLM", raising=False)
        cfg = LLMClientConfig(model="m")
        assert cfg.mock_mode is False

    def test_mock_mode_true(self, monkeypatch):
        monkeypatch.setenv("MOCK_LLM", "true")
        cfg = LLMClientConfig(model="m")
        assert cfg.mock_mode is True

    def test_mock_mode_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("MOCK_LLM", "TRUE")
        assert LLMClientConfig(model="m").mock_mode is True


# ===========================================================================
# Construction
# ===========================================================================


class TestLLMClientConstruction:
    def test_construct_mock_mode(self, monkeypatch):
        monkeypatch.setenv("MOCK_LLM", "true")
        client = LLMClient(LLMClientConfig(model="test-model"))
        assert client.config.mock_mode is True
        # In mock mode _client is explicitly None (no real instructor client)
        assert client._client is None
        assert isinstance(client._mock_cache, dict)

    def test_construct_non_mock_mode_initializes_client(self, monkeypatch):
        monkeypatch.delenv("MOCK_LLM", raising=False)
        client = LLMClient(LLMClientConfig(model="test-model"))
        assert client.config.mock_mode is False
        # Non-mock path builds an instructor-wrapped client
        assert client._client is not None

    def test_factory_create_client(self, monkeypatch):
        monkeypatch.setenv("MOCK_LLM", "true")
        client = create_client(model="test", api_base="http://fake", api_key="k")
        assert isinstance(client, LLMClient)
        assert client.config.api_base == "http://fake"
        assert client.config.api_key == "k"

    def test_init_langfuse_disabled(self, monkeypatch):
        monkeypatch.setenv("MOCK_LLM", "true")
        client = LLMClient(LLMClientConfig(model="m", langfuse_enabled=False))
        assert client._langfuse is None

    def test_init_langfuse_import_error(self, monkeypatch):
        monkeypatch.setenv("MOCK_LLM", "true")
        # Force `from langfuse import Langfuse` to raise ImportError
        monkeypatch.setitem(sys.modules, "langfuse", None)
        client = LLMClient(
            LLMClientConfig(
                model="m",
                langfuse_enabled=True,
                langfuse_public_key="pk",
                langfuse_secret_key="sk",
            )
        )
        # Import failed -> client disabled, no exception propagated
        assert client._langfuse is None

    def test_init_langfuse_success(self, monkeypatch):
        monkeypatch.setenv("MOCK_LLM", "true")

        fake = types.ModuleType("langfuse")
        created = {}

        class Langfuse:
            def __init__(self, public_key=None, secret_key=None, host=None):
                created["called"] = (public_key, secret_key, host)

        fake.Langfuse = Langfuse
        monkeypatch.setitem(sys.modules, "langfuse", fake)

        client = LLMClient(
            LLMClientConfig(
                model="m",
                langfuse_enabled=True,
                langfuse_public_key="pk",
                langfuse_secret_key="sk",
                langfuse_host="http://lf",
            )
        )
        assert client._langfuse is not None
        assert created["called"] == ("pk", "sk", "http://lf")

    def test_init_langfuse_init_exception(self, monkeypatch):
        monkeypatch.setenv("MOCK_LLM", "true")

        fake = types.ModuleType("langfuse")

        class Langfuse:
            def __init__(self, **kwargs):
                raise RuntimeError("boom")

        fake.Langfuse = Langfuse
        monkeypatch.setitem(sys.modules, "langfuse", fake)

        client = LLMClient(LLMClientConfig(model="m", langfuse_enabled=True))
        # Constructor should swallow the exception and disable langfuse
        assert client._langfuse is None


# ===========================================================================
# _load_mock_data
# ===========================================================================


class TestLoadMockData:
    def test_load_json_and_jsonl(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MOCK_LLM", "true")
        d = tmp_path / "golden"
        d.mkdir()
        (d / "sample.json").write_text(json.dumps({"a": 1}))
        (d / "other.jsonl").write_text(json.dumps({"expected_output": {"req": 2}}))
        client = LLMClient(LLMClientConfig(model="m", mock_data_dir=str(d)))
        assert client._mock_cache["sample"] == {"a": 1}
        assert client._mock_cache["other"] == {"req": 2}

    def test_load_missing_dir_is_noop(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MOCK_LLM", "true")
        client = LLMClient(LLMClientConfig(model="m", mock_data_dir=str(tmp_path / "nope")))
        assert client._mock_cache == {}

    def test_load_jsonl_without_expected_output_and_blank_lines(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MOCK_LLM", "true")
        d = tmp_path / "golden"
        d.mkdir()
        # A blank line in the jsonl exercises the `if line.strip()` continue branch
        (d / "plain.jsonl").write_text(json.dumps({"req": 9}) + "\n\n")
        client = LLMClient(LLMClientConfig(model="m", mock_data_dir=str(d)))
        # No "expected_output" key -> whole record is stored (else branch)
        assert client._mock_cache["plain"] == {"req": 9}


# ===========================================================================
# call() in mock mode
# ===========================================================================


class TestMockCall:
    def _mock_client(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MOCK_LLM", "true")
        monkeypatch.delenv("LLM_SEMANTIC_CACHE_ENABLED", raising=False)
        reset_semantic_cache()
        # empty golden dir so no cache key ever matches -> exercises the
        # per-model-type branches in _mock_call
        return LLMClient(LLMClientConfig(model="m", mock_data_dir=str(tmp_path)))

    def test_positional_args(self, monkeypatch, tmp_path):
        client = self._mock_client(monkeypatch, tmp_path)
        result = client.call("any prompt", ExtractionResult)
        assert isinstance(result, LLMCallResult)
        assert isinstance(result.output, ExtractionResult)
        assert result.model == "m"
        assert result.latency_ms == 1

    def test_positional_prompt_kwarg_model(self, monkeypatch, tmp_path):
        # Single positional prompt + response_model as keyword -> covers the
        # `if len(args) > 1` False branch.
        client = self._mock_client(monkeypatch, tmp_path)
        result = client.call("x", response_model=ExtractionResult)
        assert isinstance(result.output, ExtractionResult)

    def test_cache_loop_iterates_nonmatching_first(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MOCK_LLM", "true")
        client = LLMClient(LLMClientConfig(model="m", mock_data_dir=str(tmp_path)))
        # Force dict order so a non-matching key precedes the matching key,
        # guaranteeing the `continue` back-edge of the for loop is exercised.
        client._mock_cache = {
            "nomatchkey": {"a": 1},
            "other": {"req": 2},
        }
        result = client.call("use other here", JsonlOut)
        assert result.output.req == 2

    def test_keyword_prompt(self, monkeypatch, tmp_path):
        client = self._mock_client(monkeypatch, tmp_path)
        result = client.call(prompt="hi", response_model=ExtractionResult)
        assert isinstance(result.output, ExtractionResult)

    def test_keyword_text(self, monkeypatch, tmp_path):
        client = self._mock_client(monkeypatch, tmp_path)
        result = client.call(text="hi", response_model=ParagraphAnnotation)
        assert isinstance(result.output, ParagraphAnnotation)

    def test_keyword_content(self, monkeypatch, tmp_path):
        client = self._mock_client(monkeypatch, tmp_path)
        result = client.call(content="hi", response_model=QualityJudgment)
        assert isinstance(result.output, QualityJudgment)

    def test_keyword_messages(self, monkeypatch, tmp_path):
        client = self._mock_client(monkeypatch, tmp_path)
        result = client.call(
            messages=[{"role": "user", "content": "hi"}],
            response_model=TtsEditOutput,
        )
        assert isinstance(result.output, TtsEditOutput)

    def test_temperature_override(self, monkeypatch, tmp_path):
        client = self._mock_client(monkeypatch, tmp_path)
        # Must not raise "got multiple values for keyword argument 'temperature'"
        result = client.call(prompt="hi", response_model=ExtractionResult, temperature=0.9)
        assert result is not None

    def test_max_tokens_override(self, monkeypatch, tmp_path):
        client = self._mock_client(monkeypatch, tmp_path)
        result = client.call(prompt="hi", response_model=ExtractionResult, max_tokens=123)
        assert result is not None

    def test_response_model_book_analysis(self, monkeypatch, tmp_path):
        client = self._mock_client(monkeypatch, tmp_path)
        out = client.call("x", BookAnalysisOutput).output
        assert isinstance(out, BookAnalysisOutput)
        assert out.book_meta.title == "Test Book"

    def test_response_model_extraction(self, monkeypatch, tmp_path):
        out = self._mock_client(monkeypatch, tmp_path).call("x", ExtractionResult).output
        assert out.raw_text == "Mock extracted text"

    def test_response_model_paragraph(self, monkeypatch, tmp_path):
        out = self._mock_client(monkeypatch, tmp_path).call("x", ParagraphAnnotation).output
        assert out.speaker_canonical_name == "旁白"

    def test_response_model_quality(self, monkeypatch, tmp_path):
        out = self._mock_client(monkeypatch, tmp_path).call("x", QualityJudgment).output
        assert out.overall_score == 0.9

    def test_response_model_tts_edit(self, monkeypatch, tmp_path):
        out = self._mock_client(monkeypatch, tmp_path).call("x", TtsEditOutput).output
        assert "模拟编辑" in out.edited_text

    def test_response_model_tts_routing(self, monkeypatch, tmp_path):
        out = self._mock_client(monkeypatch, tmp_path).call("x", TtsRoutingDecision).output
        assert out.engine_choice == "kokoro"

    def test_response_model_feedback_string(self, monkeypatch, tmp_path):
        out = self._mock_client(monkeypatch, tmp_path).call("x", "FeedbackAnalysis").output
        assert isinstance(out, FeedbackAnalysis)
        assert "mock_feedback_tag" in out.pattern_tags

    def test_response_model_default_branch(self, monkeypatch, tmp_path):
        out = self._mock_client(monkeypatch, tmp_path).call("x", DefaultOut).output
        assert isinstance(out, DefaultOut)
        assert out.y == 5
        assert "y" in out.model_dump()

    def test_response_model_default_branch_uninstantiable(self, monkeypatch, tmp_path):
        out = self._mock_client(monkeypatch, tmp_path).call("x", RequiredOut).output
        # response_model() raises -> fallback to None
        assert out is None

    def test_cache_hit(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MOCK_LLM", "true")
        d = tmp_path / "golden"
        d.mkdir()
        (d / "sample.json").write_text(json.dumps({"a": 42}))
        client = LLMClient(LLMClientConfig(model="m", mock_data_dir=str(d)))
        result = client.call("please sample now", SampleOut)
        assert isinstance(result, LLMCallResult)
        assert result.output.a == 42

    def test_cache_hit_jsonl(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MOCK_LLM", "true")
        d = tmp_path / "golden"
        d.mkdir()
        (d / "other.jsonl").write_text(json.dumps({"expected_output": {"req": 7}}))
        client = LLMClient(LLMClientConfig(model="m", mock_data_dir=str(d)))
        result = client.call("mention other here", JsonlOut)
        assert result.output.req == 7

    def test_missing_prompt_raises(self, monkeypatch, tmp_path):
        client = self._mock_client(monkeypatch, tmp_path)
        with pytest.raises(ValueError, match="prompt is required"):
            client.call(response_model=ExtractionResult)

    def test_missing_response_model_raises(self, monkeypatch, tmp_path):
        client = self._mock_client(monkeypatch, tmp_path)
        with pytest.raises(ValueError, match="response_model is required"):
            client.call(prompt="hi")


# ===========================================================================
# call() with semantic cache enabled (covers cache lookup / store branches)
# ===========================================================================


class TestMockCallWithCache:
    def test_cache_store_then_hit(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MOCK_LLM", "true")
        monkeypatch.setenv("LLM_SEMANTIC_CACHE_ENABLED", "true")
        reset_semantic_cache()
        assert get_semantic_cache() is not None

        client = LLMClient(LLMClientConfig(model="m", mock_data_dir=str(tmp_path)))
        r1 = client.call("hello world", ExtractionResult)
        r2 = client.call("hello world", ExtractionResult)
        # Second call served from cache -> identical output
        assert r2.output.raw_text == r1.output.raw_text


# ===========================================================================
# call() non-mock path (client monkeypatched, no network)
# ===========================================================================


class TestNonMockCall:
    def _non_mock_client(self, monkeypatch):
        monkeypatch.delenv("MOCK_LLM", raising=False)
        monkeypatch.delenv("LLM_SEMANTIC_CACHE_ENABLED", raising=False)
        reset_semantic_cache()
        client = LLMClient(
            LLMClientConfig(
                model="m",
                api_base="http://base",
                api_key="secret",
                extra_headers={"X": "1"},
                timeout=30,
            )
        )
        # Replace the real instructor client with a mock
        client._client = MagicMock()
        return client

    def test_string_prompt_no_raw_response(self, monkeypatch):
        client = self._non_mock_client(monkeypatch)
        ret = MagicMock()
        ret._raw_response = None  # explicitly no raw response
        client._client.chat.completions.create = MagicMock(return_value=ret)

        result = client.call(prompt="hi", response_model=Out)
        assert isinstance(result, LLMCallResult)
        # Validation skipped (instructor already validated) -> tokens 0, cost 0
        assert result.tokens_in == 0
        assert result.cost_usd == 0.0

        call_kwargs = client._client.chat.completions.create.call_args.kwargs
        assert call_kwargs["api_base"] == "http://base"
        assert call_kwargs["api_key"] == "secret"
        assert call_kwargs["extra_headers"] == {"X": "1"}
        assert call_kwargs["timeout"] == 30

    def test_list_prompt_branch(self, monkeypatch):
        client = self._non_mock_client(monkeypatch)
        ret = MagicMock()
        ret._raw_response = None
        client._client.chat.completions.create = MagicMock(return_value=ret)

        messages = [{"role": "user", "content": "hi"}]
        client.call(prompt=messages, response_model=Out)
        sent = client._client.chat.completions.create.call_args.kwargs["messages"]
        assert sent is messages  # list prompt used directly as messages

    def test_raw_response_validation_success(self, monkeypatch):
        client = self._non_mock_client(monkeypatch)

        fake_raw = MagicMock()
        fake_raw.usage.model_dump.return_value = {
            "prompt_tokens": 10,
            "completion_tokens": 5,
        }
        inner = MagicMock()
        inner.content = '{"x": 1}'
        choice = MagicMock()
        choice.message = inner
        fake_raw.choices = [choice]

        ret = MagicMock()
        ret._raw_response = fake_raw
        client._client.chat.completions.create = MagicMock(return_value=ret)

        result = client.call(prompt="hi", response_model=Out)
        assert result.tokens_in == 10
        assert result.tokens_out == 5
        assert isinstance(result, LLMCallResult)
        # result.output is the (mocked) create return value; here we only verify
        # the cost/token bookkeeping and that validation did not raise.
        assert result.cost_usd == 0.0

    def test_raw_response_validation_failure_raises(self, monkeypatch):
        from audiobook_studio.llm.utils import LLMParseError

        client = self._non_mock_client(monkeypatch)

        fake_raw = MagicMock()
        fake_raw.usage.model_dump.return_value = {
            "prompt_tokens": 1,
            "completion_tokens": 1,
        }
        inner = MagicMock()
        inner.content = "not json at all"
        choice = MagicMock()
        choice.message = inner
        fake_raw.choices = [choice]

        ret = MagicMock()
        ret._raw_response = fake_raw
        client._client.chat.completions.create = MagicMock(return_value=ret)

        with pytest.raises(LLMParseError):
            client.call(prompt="hi", response_model=Out)

    def test_create_raises_propagates(self, monkeypatch):
        client = self._non_mock_client(monkeypatch)
        client._client.chat.completions.create = MagicMock(side_effect=RuntimeError("down"))
        with pytest.raises(RuntimeError, match="down"):
            client.call(prompt="hi", response_model=Out)

    def test_raw_response_no_usage(self, monkeypatch):
        client = self._non_mock_client(monkeypatch)
        fake_raw = MagicMock()
        fake_raw.usage = None  # no usage -> tokens default to 0
        inner = MagicMock()
        inner.content = '{"x": 1}'
        choice = MagicMock()
        choice.message = inner
        fake_raw.choices = [choice]

        ret = MagicMock()
        ret._raw_response = fake_raw
        client._client.chat.completions.create = MagicMock(return_value=ret)

        result = client.call(prompt="hi", response_model=Out)
        assert result.tokens_in == 0
        assert result.tokens_out == 0

    def test_raw_response_empty_choices(self, monkeypatch):
        from audiobook_studio.llm.utils import LLMParseError

        client = self._non_mock_client(monkeypatch)
        fake_raw = MagicMock()
        fake_raw.usage = None
        fake_raw.choices = []  # no choices -> raw_response becomes "{}"
        ret = MagicMock()
        ret._raw_response = fake_raw
        client._client.chat.completions.create = MagicMock(return_value=ret)

        with pytest.raises(LLMParseError):
            client.call(prompt="hi", response_model=Out)

    def test_timeout_none_no_timeout_passed(self, monkeypatch):
        monkeypatch.delenv("MOCK_LLM", raising=False)
        client = LLMClient(LLMClientConfig(model="m", timeout=0))
        client._client = MagicMock()
        ret = MagicMock()
        ret._raw_response = None
        client._client.chat.completions.create = MagicMock(return_value=ret)
        client.call(prompt="hi", response_model=Out)
        assert client._client.chat.completions.create.call_args.kwargs["timeout"] is None

    def test_cache_store_non_mock(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LLM_SEMANTIC_CACHE_ENABLED", "true")
        reset_semantic_cache()
        assert get_semantic_cache() is not None

        monkeypatch.delenv("MOCK_LLM", raising=False)
        client = LLMClient(LLMClientConfig(model="m", mock_data_dir=str(tmp_path)))
        client._client = MagicMock()
        # Real pydantic model so the result can be serialized into / read from cache
        ret = Out(x=5)
        client._client.chat.completions.create = MagicMock(return_value=ret)

        client.call(prompt="cache me", response_model=Out)
        # store branch executed (no error); second call hits cache
        r2 = client.call(prompt="cache me", response_model=Out)
        assert r2.output is not None
