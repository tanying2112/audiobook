"""Smoke tests for llm/direct_client.py (previously excluded by broad omit)."""

import pytest

from audiobook_studio.llm.direct_client import (
    DirectProviderClient,
    DirectProviderClientConfig,
    DirectProviderType,
    LLMCallResult,
)
from audiobook_studio.schemas import ParagraphAnnotation


@pytest.fixture
def mock_llm(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "true")
    monkeypatch.setattr(
        "audiobook_studio.llm.direct_client.get_semantic_cache", lambda: None
    )


def test_mock_mode_build_messages_and_cost(mock_llm):
    cfg = DirectProviderClientConfig(provider=DirectProviderType.OPENAI, model="gpt-4o")
    assert cfg.mock_mode is True
    client = DirectProviderClient(cfg)
    assert client._client is None
    # pure helpers
    assert client._build_messages("hi") == [{"role": "user", "content": "hi"}]
    assert client._build_messages([{"role": "a", "content": "b"}]) == [
        {"role": "a", "content": "b"}
    ]
    cost = client._calculate_cost(1_000_000, 1_000_000)
    assert isinstance(cost, float)
    assert cost >= 0.0


def test_mock_call_returns_typed_result(mock_llm):
    cfg = DirectProviderClientConfig(provider=DirectProviderType.OPENAI, model="gpt-4o")
    client = DirectProviderClient(cfg)
    result = client.call("some prompt", ParagraphAnnotation)
    assert isinstance(result, LLMCallResult)
    assert isinstance(result.output, ParagraphAnnotation)
    assert result.model == "gpt-4o"
    assert result.schema_compliance is True
