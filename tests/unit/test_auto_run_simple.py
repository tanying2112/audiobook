"""Simple test for auto_run.py to increase coverage."""

from unittest.mock import MagicMock

from src.audiobook_studio.api.auto_run import (
    AutoRunConfig,
    AutoRunStatusResponse,
    StagePausePoint,
    _generate_run_id,
    _stage_order,
)


def test_auto_run_imports():
    """Test that we can import from auto_run module."""
    assert AutoRunConfig is not None
    assert AutoRunStatusResponse is not None
    assert StagePausePoint is not None
    assert _generate_run_id is not None
    assert _stage_order is not None


def test_auto_run_config_creation():
    """Test creating a config."""
    config = AutoRunConfig()
    assert config.target_difficulty == "B"


def test_generate_run_id():
    """Test generating a run ID."""
    rid = _generate_run_id(123)
    assert isinstance(rid, str)
    assert "123" in rid


def test_stage_order():
    """Test stage order."""
    assert len(_stage_order) == 7
    assert _stage_order[0] == "extract"
    assert _stage_order[-1] == "quality"
