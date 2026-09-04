"""Extended tests for stage_registry.py - additional branch coverage.

These tests cover branch paths in StageRegistry and StageHandler that are
not already exercised by test_stage_registry_coverage.py. They intentionally
avoid running real pipelines (covered there via the patch_pipelines fixture)
and avoid destructively mutating built-in stage registration.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from src.audiobook_studio.pipeline.stage_registry import (
    AnalyzeStage,
    ExtractStage,
    StageHandler,
    StageRegistry,
    register_stage,
)
from src.audiobook_studio.schemas import ParagraphAnnotation


class _DummyHandler(StageHandler):
    """Dummy stage handler for testing."""

    async def run(self, **kwargs: Any) -> Any:
        return "ran"


def test_register_multiple() -> None:
    """Test registering multiple custom stages without touching built-ins."""
    StageRegistry.register("ext_first", _DummyHandler)
    StageRegistry.register("ext_second", _DummyHandler)
    StageRegistry.register("ext_third", _DummyHandler)
    assert StageRegistry.has("ext_first")
    assert StageRegistry.has("ext_second")
    assert StageRegistry.has("ext_third")
    assert len(StageRegistry.list_stages()) >= 3
    StageRegistry.unregister("ext_first")
    StageRegistry.unregister("ext_second")
    StageRegistry.unregister("ext_third")
    assert not StageRegistry.has("ext_first")
    assert not StageRegistry.has("ext_second")
    assert not StageRegistry.has("ext_third")


def test_unregister_twice_returns_false() -> None:
    """Test unregistering a stage twice returns False second time."""
    StageRegistry.register("ext_temp", _DummyHandler)
    assert StageRegistry.unregister("ext_temp") is True
    assert StageRegistry.unregister("ext_temp") is False


def test_list_stages_after_registration() -> None:
    """Test list_stages returns registered stages."""
    StageRegistry.register("ext_alpha", _DummyHandler)
    StageRegistry.register("ext_beta", _DummyHandler)
    stages = StageRegistry.list_stages()
    assert "ext_alpha" in stages
    assert "ext_beta" in stages
    StageRegistry.unregister("ext_alpha")
    StageRegistry.unregister("ext_beta")


def test_get_returns_new_instance() -> None:
    """Test that get() returns a new instance each time."""
    StageRegistry.register("ext_factory", _DummyHandler)
    inst1 = StageRegistry.get("ext_factory")
    inst2 = StageRegistry.get("ext_factory")
    assert inst1 is not inst2
    assert isinstance(inst1, _DummyHandler)
    assert isinstance(inst2, _DummyHandler)
    StageRegistry.unregister("ext_factory")


def test_get_unknown_raises() -> None:
    """Test get() raises ValueError for unknown stage."""
    try:
        StageRegistry.get("does_not_exist_xyz")
        raise AssertionError("Should have raised ValueError")
    except ValueError as e:
        assert "does_not_exist_xyz" in str(e)


def test_clear_cache_noop() -> None:
    """Test clear_cache is a backward-compat no-op."""
    assert StageRegistry.clear_cache() is None


def test_register_stage_decorator() -> None:
    """Test @register_stage decorator registers the stage."""

    @register_stage("ext_decorated_test")
    class _Dec(_DummyHandler):
        pass

    assert StageRegistry.has("ext_decorated_test")
    StageRegistry.unregister("ext_decorated_test")


def test_register_stage_decorator_with_class() -> None:
    """Test @register_stage decorator works with class-based handler."""

    @register_stage("ext_decorated_test2")
    class _DecHandler(_DummyHandler):
        pass

    assert StageRegistry.has("ext_decorated_test2")
    inst = StageRegistry.get("ext_decorated_test2")
    assert isinstance(inst, _DummyHandler)
    StageRegistry.unregister("ext_decorated_test2")


def test_snapshot_model_dump() -> None:
    """Test get_result_snapshot with model_dump."""
    ann = ParagraphAnnotation(
        paragraph_index=1,
        speaker_canonical_name="_narrator_",
        is_dialogue=False,
        emotion="neutral",
        emotion_intensity=0.5,
        confidence=0.9,
    )
    out = StageHandler.get_result_snapshot(ExtractStage(), ann)
    assert isinstance(out, dict)
    assert out["paragraph_index"] == 1


def test_snapshot_dict_attr() -> None:
    """Test get_result_snapshot with dict-like attr access."""

    class Plain:
        def __init__(self):
            self.a = 1
            self.b = 2

    out = StageHandler.get_result_snapshot(ExtractStage(), Plain())
    assert out == {"a": 1, "b": 2}


def test_snapshot_list() -> None:
    """Test get_result_snapshot with list input."""
    out = StageHandler.get_result_snapshot(ExtractStage(), [1, 2, 3])
    assert out == {"items": [1, 2, 3]}


def test_snapshot_dict() -> None:
    """Test get_result_snapshot with dict input."""
    out = StageHandler.get_result_snapshot(ExtractStage(), {"x": 9})
    assert out == {"x": 9}


def test_snapshot_scalar() -> None:
    """Test get_result_snapshot with scalar inputs."""
    out = StageHandler.get_result_snapshot(ExtractStage(), 42)
    assert out == {"result": "42"}


def test_snapshot_none() -> None:
    """Test get_result_snapshot with None input."""
    out = StageHandler.get_result_snapshot(ExtractStage(), None)
    assert out == {"result": "None"}


def test_snapshot_boolean() -> None:
    """Test get_result_snapshot with boolean input."""
    out = StageHandler.get_result_snapshot(ExtractStage(), True)
    assert out == {"result": "True"}


def test_snapshot_zero() -> None:
    """Test get_result_snapshot with zero input."""
    out = StageHandler.get_result_snapshot(ExtractStage(), 0)
    assert out == {"result": "0"}


def test_stage_handler_persist_default_noop() -> None:
    """Test default persist is no-op when no chapter."""
    handler = AnalyzeStage()
    handler.persist(db=MagicMock(), project_id=1, chapter=None, paragraph=None, result=MagicMock())


def test_builtin_stages_registered() -> None:
    """Test all built-in stages remain registered."""
    for name in [
        "extract",
        "segment",
        "analyze",
        "annotate",
        "edit",
        "audio_postprocess",
        "review",
        "synthesize",
        "quality",
        "translate",
    ]:
        assert StageRegistry.has(name), name
