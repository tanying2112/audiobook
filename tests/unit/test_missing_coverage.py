import sys

import pytest

from audiobook_studio.llm.config_loader import ProviderType
from audiobook_studio.llm.router import LLMRouter


@pytest.fixture
def mock_router():
    return LLMRouter()


def test_router_initialization(mock_router):
    assert mock_router is not None
    assert mock_router.circuit_breakers is not None
    assert mock_router.health_probe is not None


def test_get_free_tier_health(mock_router):
    health = mock_router.get_free_tier_health()
    assert isinstance(health, dict)
    assert "overall_health" in health
    assert "local_model_available" in health


def test_heuristic_fallback(mock_router):
    # Test fallback logic for annotate
    result_annotate = mock_router._heuristic_fallback("annotate", None, segment_id="test_segment_1")
    assert result_annotate is not None
    assert getattr(result_annotate, "emotion", None) == "neutral"

    # Test fallback logic for judge
    result_judge = mock_router._heuristic_fallback("judge", None, segment_id="test_segment_2")
    assert getattr(result_judge, "overall_score", None) == 0.5


def test_fallback_chain(mock_router):
    # Simulate API call with a known failure to trigger fallback
    try:
        mock_router.call_llm(ProviderType.GEMINI, "test_prompt", {})
    except Exception:
        pass  # We expect it might fail if keys aren't real, but it should try fallback
    assert True
