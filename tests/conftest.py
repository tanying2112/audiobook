"""Pytest configuration and fixtures for Audiobook Studio tests."""

import os
import pytest
from unittest.mock import patch, MagicMock


# Set MOCK_LLM=true for all tests to prevent real API calls and health probe startup
os.environ["MOCK_LLM"] = "true"


@pytest.fixture(autouse=True)
def mock_health_probe():
    """Mock health probe to prevent background HTTP calls during tests."""
    with patch("src.audiobook_studio.llm.health_probe.HealthProbe.start") as mock_start:
        mock_start.return_value = None
        yield mock_start


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset global singletons between tests."""
    # Reset cost tracker
    from src.audiobook_studio.llm.router import reset_cost_tracker
    reset_cost_tracker()

    # Reset kill switch singleton
    import src.audiobook_studio.feedback.kill_switch as ks_module
    ks_module._kill_switch = None

    yield

    # Cleanup after test
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
