"""Pytest configuration and fixtures for Audiobook Studio tests."""

import os

# Speed up LiteLLM imports by using local model cost map (must be set before litellm import)
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"

# Set MOCK_LLM=true for all tests to prevent real API calls and health probe startup
os.environ["MOCK_LLM"] = "true"

import logging
import pytest
from unittest.mock import patch, MagicMock

logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def mock_health_probe():
    """Mock health probe to prevent background HTTP calls during tests."""
    with patch("src.audiobook_studio.llm.health_probe.HealthProbe.start") as mock_start:
        mock_start.return_value = None
        yield mock_start


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset global singletons between tests."""
    from src.audiobook_studio.llm.router import reset_cost_tracker
    reset_cost_tracker()

    import src.audiobook_studio.feedback.kill_switch as ks_module
    ks_module._kill_switch = None

    yield

    reset_cost_tracker()
    ks_module._kill_switch = None


@pytest.fixture
def mock_voice_mapping(tmp_path):
    """Create a temporary voice_mapping.yaml for tests."""
    voice_mapping = tmp_path / "voice_mapping.yaml"
    voice_mapping.write_text("""
voice_mapping:
  test_voice:
    voice_id: "test_voice_id"
    description: "Test voice"
    language: "zh-CN"
""")
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", return_value=voice_mapping.read_text()):
            yield voice_mapping


@pytest.fixture(autouse=True)
def disable_langfuse(monkeypatch):
    """Comprehensively disable Langfuse in ALL tests.

    This fixture:
    1. Removes Langfuse env vars so no real keys are used
    2. Sets the global _enabled flag to False
    3. Patches init_langfuse to always return False
    4. Patches all observe_* functions to be no-ops
    5. Patches flush_langfuse to be a no-op

    This prevents "Failed to export span batch" errors and 401/403 from
    Langfuse cloud during unit tests.
    """
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)

    import src.audiobook_studio.monitoring.langfuse_client as lfc
    original_enabled = lfc._enabled
    original_client = lfc._langfuse_client
    lfc._enabled = False
    lfc._langfuse_client = None

    with patch.object(lfc, "init_langfuse", return_value=False), \
         patch.object(lfc, "observe_llm_call", return_value=None), \
         patch.object(lfc, "observe_tts_synthesis", return_value=None), \
         patch.object(lfc, "observe_quality_check", return_value=None), \
         patch.object(lfc, "flush_langfuse", return_value=None), \
         patch.object(lfc, "score_trace", return_value=None):
        yield

    lfc._enabled = original_enabled
    lfc._langfuse_client = original_client
