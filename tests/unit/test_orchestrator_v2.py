"""Comprehensive tests for pipeline/orchestrator.py — hook system, sanitize, run_stage, run_pipeline."""
import json
from unittest.mock import MagicMock, patch, call

import pytest

from src.audiobook_studio.pipeline.orchestrator import (
    register_stage_hook,
    register_pipeline_hook,
    _emit_stage_enter,
    _emit_stage_exit,
    _emit_pipeline_start,
    _emit_pipeline_end,
    _default_stage_hook,
    _sanitize_kwargs,
    run_stage,
    run_pipeline,
    _stage_hooks,
    _pipeline_hooks,
)
from src.audiobook_studio.exceptions import (
    AudiobookError,
    StageExecutionError,
)


# ── Hook Registration ────────────────────────────────────────────────────────

class TestHookRegistration:
    def test_register_stage_hook(self):
        fn = lambda *a, **k: None
        before = len(_stage_hooks)
        register_stage_hook(fn)
        assert fn in _stage_hooks
        # Duplicate should not add
        register_stage_hook(fn)
        assert len(_stage_hooks) == before + 1

    def test_register_pipeline_hook(self):
        fn = lambda *a, **k: None
        before = len(_pipeline_hooks)
        register_pipeline_hook(fn)
        assert fn in _pipeline_hooks
        register_pipeline_hook(fn)
        assert len(_pipeline_hooks) == before + 1


# ── Emit Functions ───────────────────────────────────────────────────────────

class TestEmitFunctions:
    def test_emit_stage_enter(self):
        called = []
        def hook(event, stage, context, result, error):
            called.append(event)
        _stage_hooks.append(hook)
        try:
            _emit_stage_enter("test_stage", {"key": "val"})
            assert "stage_enter" in called
        finally:
            _stage_hooks.remove(hook)

    def test_emit_stage_exit(self):
        called = []
        def hook(event, stage, context, result, error):
            called.append(event)
        _stage_hooks.append(hook)
        try:
            _emit_stage_exit("test_stage", {"k": "v"}, result="ok", error=None)
            assert "stage_exit" in called
        finally:
            _stage_hooks.remove(hook)

    def test_emit_stage_exit_with_error(self):
        called_with_err = []
        def hook(event, stage, context, result, error):
            called_with_err.append(error)
        _stage_hooks.append(hook)
        try:
            err = Exception("fail")
            _emit_stage_exit("test", {}, error=err)
            assert called_with_err[-1] is err
        finally:
            _stage_hooks.remove(hook)

    def test_emit_pipeline_start(self):
        called = []
        def hook(event, context, result, error):
            called.append(event)
        _pipeline_hooks.append(hook)
        try:
            _emit_pipeline_start({"stages": []})
            assert "pipeline_start" in called
        finally:
            _pipeline_hooks.remove(hook)

    def test_emit_pipeline_end(self):
        called = []
        def hook(event, context, result, error):
            called.append(event)
        _pipeline_hooks.append(hook)
        try:
            _emit_pipeline_end({}, result=[], error=None)
            assert "pipeline_end" in called
        finally:
            _pipeline_hooks.remove(hook)

    def test_hook_exception_swallowed(self):
        def bad_hook(*a, **k):
            raise RuntimeError("boom")
        _stage_hooks.append(bad_hook)
        try:
            # Should not raise
            _emit_stage_enter("s", {})
            _emit_stage_exit("s", {})
        finally:
            _stage_hooks.remove(bad_hook)

    def test_pipeline_hook_exception_swallowed(self):
        def bad_hook(*a, **k):
            raise RuntimeError("boom")
        _pipeline_hooks.append(bad_hook)
        try:
            _emit_pipeline_start({})
            _emit_pipeline_end({})
        finally:
            _pipeline_hooks.remove(bad_hook)


# ── _default_stage_hook ─────────────────────────────────────────────────────

class TestDefaultStageHook:
    def test_enter(self):
        _default_stage_hook("stage_enter", "test_stage", {"key": "val"}, None, None)

    def test_exit_ok(self):
        _default_stage_hook("stage_exit", "test_stage", {}, "result", None)

    def test_exit_error(self):
        _default_stage_hook("stage_exit", "test_stage", {}, None, Exception("err"))

    def test_unknown_event(self):
        _default_stage_hook("unknown", "stage", {}, None, None)


# ── _sanitize_kwargs ─────────────────────────────────────────────────────────

class TestSanitizeKwargs:
    def test_empty(self):
        assert _sanitize_kwargs({}) == {}

    def test_string(self):
        assert _sanitize_kwargs({"a": "hello"}) == {"a": "hello"}

    def test_int(self):
        assert _sanitize_kwargs({"a": 42}) == {"a": 42}

    def test_pydantic_model(self):
        m = MagicMock()
        m.model_dump.return_value = {"field": "value"}
        result = _sanitize_kwargs({"a": m})
        assert result["a"] == {"field": "value"}

    def test_generic_object(self):
        class MyObj:
            pass
        result = _sanitize_kwargs({"a": MyObj()})
        assert isinstance(result["a"], str)

    def test_nested_dict(self):
        result = _sanitize_kwargs({"a": {"b": [1, 2]}})
        assert result["a"] == {"b": [1, 2]}


# ── run_stage ────────────────────────────────────────────────────────────────

class TestRunStage:
    def _mock_db(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        return db

    @patch("src.audiobook_studio.pipeline.orchestrator.StageRegistry")
    def test_unknown_stage_raises(self, mock_registry, tmp_path):
        mock_registry.get.side_effect = ValueError("Unknown stage: foo")
        db = MagicMock()
        with pytest.raises(StageExecutionError) as exc_info:
            run_stage("foo", db, project_id=1)
        assert "foo" in str(exc_info.value)

    @patch("src.audiobook_studio.pipeline.orchestrator.StageRegistry")
    def test_stage_execution_error(self, mock_registry, tmp_path):
        class FakeHandler:
            @staticmethod
            def run(**kwargs):
                raise AudiobookError(stage="test", reason="provider failed", provider="gpt-4")
            @staticmethod
            def persist(*a): pass
            @staticmethod
            def get_result_snapshot(r): return {}
        mock_registry.get.return_value = FakeHandler()
        db = MagicMock()
        with pytest.raises(AudiobookError):
            run_stage("test_stage", db, project_id=1)

    @patch("src.audiobook_studio.pipeline.orchestrator.StageRegistry")
    def test_generic_exception_wrapped(self, mock_registry):
        class FakeHandler:
            @staticmethod
            def run(**kwargs):
                raise RuntimeError("unexpected")
            @staticmethod
            def persist(*a): pass
            @staticmethod
            def get_result_snapshot(r): return {}
        mock_registry.get.return_value = FakeHandler()
        db = MagicMock()
        with pytest.raises(StageExecutionError):
            run_stage("test", db, project_id=1)

    @patch("src.audiobook_studio.pipeline.orchestrator.StageRegistry")
    def test_success(self, mock_registry):
        class FakeHandler:
            @staticmethod
            def run(**kwargs):
                return {"result": "ok"}
            @staticmethod
            def persist(*a): pass
            @staticmethod
            def get_result_snapshot(r): return r
        mock_registry.get.return_value = FakeHandler()
        db = MagicMock()
        result = run_stage("extract", db, project_id=1, chapter_index=1)
        assert result == {"result": "ok"}

    @patch("src.audiobook_studio.pipeline.orchestrator.StageRegistry")
    def test_with_chapter_and_paragraph(self, mock_registry):
        class FakeHandler:
            @staticmethod
            def run(**kwargs):
                return "done"
            @staticmethod
            def persist(*a): pass
            @staticmethod
            def get_result_snapshot(r): return {"snap": r}
        mock_registry.get.return_value = FakeHandler()
        db = MagicMock()
        chapter = MagicMock(); chapter.id = 10
        para = MagicMock(); para.id = 20
        db.query.return_value.filter.return_value.first.side_effect = [chapter, para]
        result = run_stage("annotate", db, project_id=1, chapter_index=1, paragraph_index=1)
        assert result == "done"

    @patch("src.audiobook_studio.pipeline.orchestrator.StageRegistry")
    def test_with_feedback_collector(self, mock_registry):
        class FakeHandler:
            @staticmethod
            def run(**kwargs):
                return "done"
            @staticmethod
            def persist(*a): pass
            @staticmethod
            def get_result_snapshot(r): return {"snap": r}
        mock_registry.get.return_value = FakeHandler()
        db = MagicMock()
        fc = MagicMock()
        mock_capture = MagicMock()
        fc.capture_stage.return_value = mock_capture
        result = run_stage("quality", db, project_id=1, feedback_collector=fc)
        assert result == "done"
        fc.capture_stage.assert_called_once()
        mock_capture.set_source.assert_called_once_with("quality_judge")

    @patch("src.audiobook_studio.pipeline.orchestrator.StageRegistry")
    def test_with_feedback_no_project_id(self, mock_registry):
        class FakeHandler:
            @staticmethod
            def run(**kwargs): return "ok"
            @staticmethod
            def persist(*a): pass
            @staticmethod
            def get_result_snapshot(r): return {}
        mock_registry.get.return_value = FakeHandler()
        db = MagicMock()
        fc = MagicMock()
        # No project_id → feedback_capture should be None
        result = run_stage("extract", db, chapter_index=1, feedback_collector=fc)
        assert result == "ok"

    @patch("src.audiobook_studio.pipeline.orchestrator.StageRegistry")
    def test_error_writes_to_feedback(self, mock_registry):
        class FakeHandler:
            @staticmethod
            def run(**kwargs):
                raise ValueError("bad input")
            @staticmethod
            def persist(*a): pass
            @staticmethod
            def get_result_snapshot(r): return {}
        mock_registry.get.return_value = FakeHandler()
        db = MagicMock()
        fc = MagicMock()
        mock_capture = MagicMock()
        fc.capture_stage.return_value = mock_capture
        with pytest.raises(StageExecutionError):
            run_stage("test", db, project_id=1, feedback_collector=fc)
        mock_capture.set_llm_output.assert_called()


# ── run_pipeline ─────────────────────────────────────────────────────────────

class TestRunPipeline:
    @patch("src.audiobook_studio.pipeline.orchestrator.run_stage")
    def test_sequential(self, mock_run_stage):
        mock_run_stage.side_effect = ["r1", "r2"]
        db = MagicMock()
        results = run_pipeline(["extract", "analyze"], db, project_id=1)
        assert results == ["r1", "r2"]
        assert mock_run_stage.call_count == 2

    @patch("src.audiobook_studio.pipeline.orchestrator.run_stage")
    def test_empty_stages(self, mock_run_stage):
        db = MagicMock()
        results = run_pipeline([], db, project_id=1)
        assert results == []

    @patch("src.audiobook_studio.pipeline.orchestrator.run_stage")
    def test_exception_propagates(self, mock_run_stage):
        mock_run_stage.side_effect = Exception("fail")
        db = MagicMock()
        with pytest.raises(Exception):
            run_pipeline(["extract"], db, project_id=1)

    @patch("src.audiobook_studio.pipeline.orchestrator.run_stage")
    def test_hooks_called(self, mock_run_stage):
        mock_run_stage.return_value = "ok"
        db = MagicMock()
        pipeline_events = []
        def hook(event, ctx, result, error):
            pipeline_events.append(event)
        _pipeline_hooks.append(hook)
        try:
            run_pipeline(["extract"], db, project_id=1)
            assert "pipeline_start" in pipeline_events
            assert "pipeline_end" in pipeline_events
        finally:
            _pipeline_hooks.remove(hook)
