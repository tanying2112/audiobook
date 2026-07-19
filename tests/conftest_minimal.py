"""Minimal pytest configuration - only indispensable mocks.

This file contains ONLY mocks that are absolutely required for test collection
to succeed in environments where heavy optional dependencies are not installed.

DO NOT add test fixtures here - they belong in tests/conftest.py
"""

import os
import sys
from unittest.mock import MagicMock

# ═══════════════════════════════════════════════════════════════════════════
# Only mock dspy if it's not available - this is an optional dependency
# ═══════════════════════════════════════════════════════════════════════════

try:
    import dspy  # noqa: F401
    DSPY_AVAILABLE = True
except ImportError:
    DSPY_AVAILABLE = False

if not DSPY_AVAILABLE:
    # Create minimal mock classes only needed for bootstrap_fewshot imports
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
            self._store = {}

        def with_inputs(self, *keys):
            self._inputs = set(keys)
            return self

        def outputs(self, key=None):
            if key:
                return self._store.get(key)
            return self._store

    class MockPrediction:
        """Mock Prediction that stores outputs in a dict-like way."""

        def __init__(self, **kwargs):
            self._store = kwargs
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
            result = MagicMock()
            for key, value in kwargs.items():
                setattr(result, key, value)
            return result

    class MockModule:
        """Mock base Module for CharacterRecognitionModule etc."""

        def __init__(self):
            pass

    # Inject mocks into sys.modules BEFORE any imports
    mock_gepa_utils = MagicMock()
    mock_gepa_utils.ScoreWithFeedback = MockScoreWithFeedback
    sys.modules["dspy"] = MagicMock()
    sys.modules["dspy.Signature"] = MagicMock
    sys.modules["dspy.teleprompt"] = MagicMock()
    sys.modules["dspy.teleprompt.gepa"] = MagicMock()
    sys.modules["dspy.teleprompt.gepa.gepa_utils"] = mock_gepa_utils
    sys.modules["dspy.teleprompt.gepa.gepa_logprob"] = MagicMock()

    # Patch dspy classes after mock setup
    def _patch_dspy_classes():
        dspy = sys.modules["dspy"]
        dspy.Example = MockExample
        dspy.Prediction = MockPrediction
        dspy.Signature = MockSignature
        dspy.Predict = MockPredict
        dspy.Module = MockModule

    _patch_dspy_classes()

# ═══════════════════════════════════════════════════════════════════════════
# Environment setup for all tests
# ═══════════════════════════════════════════════════════════════════════════

# Set MOCK_LLM=true for all tests to prevent real API calls and health probe startup
os.environ["MOCK_LLM"] = "true"

# Speed up LiteLLM imports by using local model cost map
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"

# ═══════════════════════════════════════════════════════════════════════════
# Mock soundfile for tests that use it in mock mode
# This mock actually writes files (with zero bytes) so file existence checks pass
# ═══════════════════════════════════════════════════════════════════════════

def _mock_sf_write(path, data, sr):
    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(b"\x00" * len(data))


mock_sf = MagicMock()
mock_sf.write = _mock_sf_write
sys.modules["soundfile"] = mock_sf

# ═══════════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════════════════

import logging
import warnings
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.exc import SAWarning

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

    with (
        patch.object(lfc, "observe_llm_call", return_value=None),
        patch.object(lfc, "observe_tts_synthesis", return_value=None),
        patch.object(lfc, "observe_quality_check", return_value=None),
        patch.object(lfc, "flush_langfuse", return_value=None),
        patch.object(lfc, "score_trace", return_value=None),
    ):
        yield

    lfc._enabled = original_enabled
    lfc._langfuse_client = original_client


@pytest.fixture(scope="session", autouse=True)
def ensure_tmp_repo():
    os.makedirs("/tmp/repo", exist_ok=True)


# Ignore SAWarning about foreign key cycles in SQLite drop_all
warnings.filterwarnings(
    "ignore",
    message="Can't sort tables for DROP; an unresolvable foreign key dependency exists between tables:.*",
    category=SAWarning,
)