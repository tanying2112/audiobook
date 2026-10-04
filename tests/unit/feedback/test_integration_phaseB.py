"""Phase B structural tests for feedback/integration.py (mocking DB/collector boundaries)."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import src.audiobook_studio.feedback.integration as imod
from src.audiobook_studio.feedback.integration import (
    _log_self_iteration_event,
    collect_pipeline_feedback,
    create_self_iteration_loop,
    save_quality_feedback,
    save_user_rating_feedback,
)


class _FakeCapture:
    def __init__(self):
        self.llm = self.cor = self.rat = self.src = None
        self.saved = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def set_llm_output(self, x):
        self.llm = x

    def set_corrected_output(self, x):
        self.cor = x

    def set_rationale(self, x):
        self.rat = x

    def set_source(self, x):
        self.src = x

    def save_feedback(self):
        self.saved = True
        return Path("/tmp/fake_feedback.json")


class _FakeCollector:
    def capture_stage(self, **kwargs):
        return _FakeCapture()

    def save_feedback(self, capture):
        capture.saved = True
        return Path("/tmp/fake_feedback.json")


def test_log_self_iteration_event(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _log_self_iteration_event("test_event", {"k": "v"})
    log_file = tmp_path / "logs" / "self_iteration.jsonl"
    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    rec = json.loads(lines[0])
    assert rec["event_type"] == "test_event"
    assert rec["k"] == "v"


def test_create_self_iteration_loop():
    factory = MagicMock()
    loop = create_self_iteration_loop(factory, project_id=7, min_feedback_count=5)
    assert loop.project_id == 7
    assert loop.auto_processor.min_feedback_count == 5
    assert loop.db_session_factory is factory


def test_collect_pipeline_feedback():
    collector = _FakeCollector()
    with collect_pipeline_feedback(collector, "annotate", 1, paragraph_index=2) as cap:
        cap.set_llm_output({"x": 1})
    assert cap.llm == {"x": 1}


def test_save_quality_feedback():
    collector = _FakeCollector()
    out = save_quality_feedback(
        collector,
        "quality_judge",
        1,
        2,
        3,
        4,
        quality_judgment={"overall_score": 0.5},
        corrected_judgment={"overall_score": 0.9},
        rationale="fixed",
    )
    assert isinstance(out, Path)
    assert out == Path("/tmp/fake_feedback.json")


def test_save_user_rating_feedback():
    collector = _FakeCollector()
    out = save_user_rating_feedback(
        collector,
        "user_rating",
        1,
        2,
        3,
        4,
        user_rating={"rating": 5},
        rationale="ok",
    )
    assert isinstance(out, Path)


# ---------------------------------------------------------------------------
# SelfIterationLoop: status / lifecycle / manual trigger
# ---------------------------------------------------------------------------


def _make_loop(project_id=7):
    loop = create_self_iteration_loop(MagicMock(), project_id=project_id)
    loop.auto_processor = MagicMock()
    loop.auto_processor.get_status.return_value = {"unprocessed_feedback_count": 0}
    return loop


def test_get_status():
    loop = _make_loop()
    status = loop.get_status()
    assert status["project_id"] == 7
    assert status["running"] is False
    assert status["iteration_count"] == 0
    assert status["last_analysis"] is None
    assert status["pr_results"] == []
    assert status["merge_results"] == []
    assert "canary_percentage" in status["config"]

    # with a last analysis present
    loop._last_analysis_result = MagicMock(total_analyzed=9, top_patterns=["a", "b"])
    status2 = loop.get_status()
    assert status2["last_analysis"]["total_analyzed"] == 9


def test_start_and_stop(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # event log goes to tmp logs dir
    loop = _make_loop()
    loop.start()
    try:
        assert loop._worker_thread is not None
        assert loop._worker_thread.is_alive() or loop._iteration_count >= 0
    finally:
        loop.stop()
    assert not loop._worker_thread.is_alive()


def test_trigger_iteration_now_no_result():
    loop = _make_loop()
    loop.auto_processor.trigger_now.return_value = None
    assert loop.trigger_iteration_now() is None


def test_trigger_iteration_now_no_upgrades(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(imod, "batch_upgrade", lambda analysis, min_pattern_threshold=0: {})

    loop = _make_loop()
    fake_analysis = MagicMock(total_analyzed=4, top_patterns=["p1"])
    loop.auto_processor.trigger_now.return_value = fake_analysis

    result = loop.trigger_iteration_now()
    assert result is fake_analysis
    assert loop.get_status()["last_analysis"]["total_analyzed"] == 4
