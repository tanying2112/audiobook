"""Pytest configuration and fixtures for Audiobook Studio tests."""

import os
import sys
from unittest.mock import MagicMock

# Mock numpy/torchaudio which have module-level initialization that can conflict
# when loaded multiple times during test collection
import numpy as np

# ═══════════════════════════════════════════════════════════════════════════
# Mock heavy dependencies BEFORE any imports to avoid collection errors
# These modules have import-time side effects that can fail in test environments
# ═══════════════════════════════════════════════════════════════════════════


if not hasattr(np, "_claude_mock_mode"):
    np._claude_mock_mode = True
    # Ensure numpy works correctly with lists in division operations
    # (prevents "ufunc type promotion" issues in Python 3.14)


# Create proper mock classes for DSPy components
class MockScoreWithFeedback:
    """Mock ScoreWithFeedback with proper attribute access."""

    def __init__(self, score: float, feedback: str):
        self.score = score
        self.feedback = feedback


class MockExample:
    """Mock Example with proper attribute storage."""

    def __init__(self, **kwargs):
        self._inputs = set()
        for key, value in kwargs.items():
            setattr(self, key, value)
        self._store = {}  # For prediction-like storage

    def with_inputs(self, *keys):
        """Mark keys as inputs (returns self unchanged)."""
        self._inputs = set(keys)
        return self

    def outputs(self, key=None):
        """Return outputs dict or specific value."""
        if key:
            return self._store.get(key)
        return self._store


class MockPrediction:
    """Mock Prediction that stores outputs in a dict-like way."""

    def __init__(self, **kwargs):
        self._store = kwargs
        # Also set attributes for __dict__ access
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __getitem__(self, key):
        return self._store.get(key)


class MockSignature:
    """Mock Signature for DSPy module definitions."""

    def __init__(self, *args, **kwargs):
        self._signature = args[0] if args else ""
        self._instructions = kwargs.get("instructions", "")


class MockPredict:
    """Mock Predict that returns a result with expected attributes."""

    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, **kwargs):
        # Return a mock result that has character_name, voice_design etc
        result = MagicMock()
        for key, value in kwargs.items():
            setattr(result, key, value)
        return result


class MockModule:
    """Mock base Module for CharacterRecognitionModule etc."""

    def __init__(self):
        pass


# Mock heavy dependencies BEFORE any imports to avoid collection errors
# These modules have import-time side effects that can fail in test environments
mock_gepa_utils = MagicMock()
mock_gepa_utils.ScoreWithFeedback = MockScoreWithFeedback
sys.modules["dspy"] = MagicMock()
sys.modules["dspy.Signature"] = MagicMock
sys.modules["dspy.teleprompt"] = MagicMock()
sys.modules["dspy.teleprompt.gepa"] = MagicMock()
sys.modules["dspy.teleprompt.gepa.gepa_utils"] = mock_gepa_utils
sys.modules["dspy.teleprompt.gepa.gepa_logprob"] = MagicMock()


# Mock soundfile to actually write files in mock mode
def _mock_sf_write(path, data, sr):
    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(b"\x00" * len(data))


mock_sf = MagicMock()
mock_sf.write = _mock_sf_write
sys.modules["soundfile"] = mock_sf

# Speed up LiteLLM imports by using local model cost map (must be set before litellm import)
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"

import logging
from unittest.mock import patch

import pytest

# Set MOCK_LLM=true for all tests to prevent real API calls and health probe startup
# This must be set before any modules that check it are imported
os.environ["MOCK_LLM"] = "true"

logger = logging.getLogger(__name__)


# Patch dspy.Example and dspy.Prediction after mocks are set up
def _patch_dspy_classes():
    """Patch dspy classes after first import."""
    import sys

    dspy = sys.modules["dspy"]

    # Make dspy.Example and dspy.Prediction use our mock classes
    dspy.Example = MockExample
    dspy.Prediction = MockPrediction
    dspy.Signature = MockSignature
    dspy.Predict = MockPredict
    dspy.Module = MockModule


# Apply patches after module is loaded
_patch_dspy_classes()


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

    # Reset upload module state
    import src.audiobook_studio.api.upload as upload_module

    upload_module.upload_sessions.clear()
    upload_module.extraction_jobs.clear()

    yield

    reset_cost_tracker()
    ks_module._kill_switch = None

    # Ensure upload module state is clean after test
    upload_module.upload_sessions.clear()
    upload_module.extraction_jobs.clear()

    # Ensure MOCK_LLM stays set for subsequent tests
    os.environ["MOCK_LLM"] = "true"


@pytest.fixture
def mock_voice_mapping(tmp_path):
    """Create a temporary voice_mapping.yaml for tests."""
    voice_mapping = tmp_path / "voice_mapping.yaml"
    voice_mapping.write_text(
        """
voice_mapping:
  test_voice:
    voice_id: "test_voice_id"
    description: "Test voice"
    language: "zh-CN"
"""
    )
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", return_value=voice_mapping.read_text()):
            yield voice_mapping


@pytest.fixture(autouse=True)
def disable_langfuse(monkeypatch):
    """Comprehensively disable Langfuse in ALL tests.

    This fixture:
    1. Removes Langfuse env vars so no real keys are used
    2. Sets the global _enabled flag to False
    3. Patches all observe_* functions to be no-ops
    4. Patches flush_langfuse to be a no-op

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

    with patch.object(lfc, "observe_llm_call", return_value=None), patch.object(
        lfc, "observe_tts_synthesis", return_value=None
    ), patch.object(lfc, "observe_quality_check", return_value=None), patch.object(
        lfc, "flush_langfuse", return_value=None
    ), patch.object(
        lfc, "score_trace", return_value=None
    ):
        yield

    lfc._enabled = original_enabled
    lfc._langfuse_client = original_client
