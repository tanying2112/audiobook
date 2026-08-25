"""Phase 3 isolated coverage tests for ``api/harness.py``.

The HARNESS dashboard endpoints are async FastAPI handlers. Instead of going
through the HTTP layer / real DB, we invoke the coroutine handlers directly
with a fake AsyncSession and monkeypatch the module-level global state
(VersionStore, CanaryRelease, iteration-loop factory, promotion evaluator).
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.audiobook_studio.api import harness as harness_mod


# ── Fake DB ──────────────────────────────────────────────────────────────────

class _DBResult:
    def __init__(self, scalar=0, records=None):
        self._scalar = scalar
        self._records = records or []

    def scalar(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._records

    def scalar_one_or_none(self):
        return self._records[0] if self._records else None


class FakeAsyncDB:
    def __init__(self, scalar=0, records=None):
        self._scalar = scalar
        self._records = records or []

    async def execute(self, *a, **k):
        return _DBResult(self._scalar, self._records)


class FakeRecord:
    def __init__(self, processed=False, promoted=False, stage="extract", pattern_tags=None):
        self.processed = processed
        self.promoted = promoted
        self.stage = stage
        self.pattern_tags = pattern_tags if pattern_tags is not None else []


class FakeParagraph:
    def __init__(self, emotion=0.8, prosody=0.8, alignment=0.8):
        self.quality_emotion_match = emotion
        self.quality_prosody_naturalness = prosody
        self.quality_text_audio_alignment = alignment


# ── Fake global state ────────────────────────────────────────────────────────

class FakeVersionStore:
    def __init__(self, base_path, current_versions, rollback_history=None):
        self.base_path = base_path
        self.current_versions = current_versions
        self._rollback = rollback_history or []

    def get_rollback_history(self, stage=None, limit=50):
        return self._rollback


class FakeGateResult:
    def __init__(self, name, score):
        self.name = name
        self.score = score


class FakeVerdict:
    def __init__(self, passed=True):
        self.passed = passed
        self.gates = [
            FakeGateResult("格式合规率", 0.9),
            FakeGateResult("黄金数据集通过率", 0.8),
            FakeGateResult("质量 ≥ 旧版 102%", 0.7),
            FakeGateResult("人工抽样通过率", 0.6),
        ]


class FakeLoop:
    def __init__(self, result=None):
        self._result = result

    def get_status(self):
        return {"running": True, "iteration_count": 3}

    def trigger_iteration_now(self):
        if self._result == "raise":
            raise RuntimeError("boom")
        if self._result is None:
            return None
        return SimpleNamespace(total_analyzed=5, top_patterns=["p1", "p2"])


class FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *a, **k):
        self.tasks.append((fn, a, k))

    def run(self):
        for fn, a, k in self.tasks:
            fn(*a, **k)


def _setup_version_store(tmp_path, monkeypatch, versions=None, rollback=None):
    versions = versions or {"extract": 2, "analyze": 2}
    vs = FakeVersionStore(base_path=tmp_path, current_versions=versions, rollback_history=rollback)
    monkeypatch.setattr(harness_mod, "_version_store", vs)
    for stage in ("extract", "analyze"):
        d = tmp_path / stage
        d.mkdir(parents=True, exist_ok=True)
        if stage == "extract":
            (d / "v1.j2").write_text("x")
            (d / "v2.j2").write_text("y" * 10000)
        else:
            (d / "v1.j2").write_text("y" * 10000)
            (d / "v2.j2").write_text("x")
        (d / "v3.j2").write_text("z")
    return vs


# ── /status ──────────────────────────────────────────────────────────────────

def test_status_no_project():
    out = asyncio.run(harness_mod.get_harness_status(db=FakeAsyncDB(scalar=0)))
    assert out.running is False
    assert out.unprocessed_feedback_count == 0


def test_status_with_project_loop(monkeypatch):
    monkeypatch.setattr(harness_mod, "get_iteration_loop", lambda pid: FakeLoop())
    out = asyncio.run(harness_mod.get_harness_status(project_id=1, db=FakeAsyncDB(scalar=7)))
    assert out.running is True
    assert out.iteration_count == 3
    assert out.unprocessed_feedback_count == 7


def test_status_with_project_no_loop(monkeypatch):
    monkeypatch.setattr(harness_mod, "get_iteration_loop", lambda pid: None)
    out = asyncio.run(harness_mod.get_harness_status(project_id=1, db=FakeAsyncDB(scalar=2)))
    assert out.running is False


# ── /feedback-funnel ──────────────────────────────────────────────────────────

def test_feedback_funnel_empty():
    out = asyncio.run(harness_mod.get_feedback_funnel(db=FakeAsyncDB(records=[])))
    assert out.total_feedback == 0
    assert out.conversion_rates == {}


def test_feedback_funnel_with_data():
    recs = [
        FakeRecord(processed=True, promoted=True),
        FakeRecord(processed=True, promoted=False),
    ]
    out = asyncio.run(harness_mod.get_feedback_funnel(project_id=1, db=FakeAsyncDB(scalar=2, records=recs)))
    assert out.total_feedback == 2
    assert out.analyzed_count == 2
    assert out.promotion_passed_count == 1
    assert "total_to_analyzed" in out.conversion_rates


# ── /pattern-heatmap ─────────────────────────────────────────────────────────

def test_pattern_heatmap_empty():
    out = asyncio.run(harness_mod.get_pattern_heatmap(db=FakeAsyncDB(records=[])))
    assert out.patterns == []
    assert out.by_stage == {}
    assert out.top_patterns == []


def test_pattern_heatmap_with_data():
    recs = [
        FakeRecord(processed=True, stage="extract", pattern_tags=["t1", "t2"]),
        FakeRecord(processed=True, stage="synthesize", pattern_tags=["t1"]),
    ]
    out = asyncio.run(harness_mod.get_pattern_heatmap(project_id=1, db=FakeAsyncDB(records=recs)))
    assert len(out.patterns) == 2
    assert "t1" in out.top_patterns
    assert out.by_stage  # non-empty


# ── /prompt-timeline ──────────────────────────────────────────────────────────

def test_prompt_timeline_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(harness_mod, "_version_store", FakeVersionStore(tmp_path, {}))
    out = asyncio.run(harness_mod.get_prompt_timeline())
    assert out.stages == {}


def test_prompt_timeline_with_versions(tmp_path, monkeypatch):
    _setup_version_store(tmp_path, monkeypatch)
    out = asyncio.run(harness_mod.get_prompt_timeline())
    assert "extract" in out.stages
    statuses = {it.status for it in out.stages["extract"]}
    assert "promoted" in statuses
    assert "superseded" in statuses


def test_prompt_timeline_single_stage(tmp_path, monkeypatch):
    _setup_version_store(tmp_path, monkeypatch)
    out = asyncio.run(harness_mod.get_prompt_timeline(stage="extract"))
    assert list(out.stages.keys()) == ["extract"]


def test_prompt_timeline_rolled_back(tmp_path, monkeypatch):
    _setup_version_store(
        tmp_path, monkeypatch,
        rollback=[{"to_version": 1, "action": "rollback"}],
    )
    out = asyncio.run(harness_mod.get_prompt_timeline())
    statuses = {it.status for it in out.stages["extract"]}
    assert "rolled_back" in statuses


# ── /promotion-gate ───────────────────────────────────────────────────────────

def test_promotion_gate_empty(monkeypatch):
    monkeypatch.setattr(harness_mod, "_version_store", FakeVersionStore(Path("/tmp"), {}))
    monkeypatch.setattr(harness_mod, "evaluate_promotion", lambda s, c, n: FakeVerdict())
    out = asyncio.run(harness_mod.get_promotion_gate())
    assert out.overall_pass is False


def test_promotion_gate_with_versions(tmp_path, monkeypatch):
    _setup_version_store(tmp_path, monkeypatch)
    monkeypatch.setattr(harness_mod, "evaluate_promotion", lambda s, c, n: FakeVerdict(passed=True))
    out = asyncio.run(harness_mod.get_promotion_gate())
    assert out.overall_pass is True
    assert out.format_compliance_rate == 0.9


def test_promotion_gate_failed(tmp_path, monkeypatch):
    _setup_version_store(tmp_path, monkeypatch)
    monkeypatch.setattr(harness_mod, "evaluate_promotion", lambda s, c, n: FakeVerdict(passed=False))
    out = asyncio.run(harness_mod.get_promotion_gate())
    assert out.overall_pass is False


# ── /canaries ─────────────────────────────────────────────────────────────────

def test_canaries_empty(monkeypatch):
    mgr = MagicMock()
    mgr.get_all_canaries.return_value = {}
    monkeypatch.setattr(harness_mod, "_canary_manager", mgr)
    out = asyncio.run(harness_mod.get_canaries())
    assert out.total_active == 0


def test_canaries_active(monkeypatch):
    mgr = MagicMock()
    now = datetime.now(timezone.utc)
    mgr.get_all_canaries.return_value = {
        "c1": {"status": "running", "started_at": now, "version": "v2", "stage": "extract"},
        "c2": {"status": "completed", "started_at": None, "version": "v1", "stage": "analyze"},
        "c3": {"status": "rolled_back", "started_at": now, "version": "v3", "stage": "synthesize"},
        "c4": {"status": "failed", "started_at": None},
    }
    monkeypatch.setattr(harness_mod, "_canary_manager", mgr)
    out = asyncio.run(harness_mod.get_canaries())
    # Only "running"/"completed" canaries are counted as active (c1, c2).
    assert out.total_active == 2
    rolled = [c for c in out.active_canaries if c.auto_rollback_triggered]
    # c3 (rolled_back) is filtered out of active, so no active canary is flagged.
    assert len(rolled) == 0


# ── /ab-tests ─────────────────────────────────────────────────────────────────

def test_ab_tests_empty(monkeypatch):
    monkeypatch.setattr(harness_mod, "_version_store", FakeVersionStore(Path("/tmp"), {}))
    out = asyncio.run(harness_mod.get_ab_tests(db=FakeAsyncDB(records=[])))
    assert out.total_tests == 0


def test_ab_tests_with_versions(tmp_path, monkeypatch):
    _setup_version_store(tmp_path, monkeypatch)
    out = asyncio.run(harness_mod.get_ab_tests(project_id=1, db=FakeAsyncDB(records=[])))
    winners = {t.winner for t in out.tests}
    assert "B" in winners
    assert "A" in winners


# ── /critics/latest ───────────────────────────────────────────────────────────

def test_critics_no_paragraph():
    out = asyncio.run(harness_mod.get_latest_critic_results(db=FakeAsyncDB(records=[])))
    assert out.verdicts == []
    assert out.weighted_verdict == "accept"


def test_critics_accept():
    para = FakeParagraph(0.9, 0.9, 0.9)
    out = asyncio.run(harness_mod.get_latest_critic_results(db=FakeAsyncDB(records=[para])))
    assert out.weighted_verdict == "accept"
    assert len(out.verdicts) == 3


def test_critics_needs_revision():
    para = FakeParagraph(0.6, 0.6, 0.6)
    out = asyncio.run(harness_mod.get_latest_critic_results(db=FakeAsyncDB(records=[para])))
    assert out.weighted_verdict == "needs_revision"


def test_critics_reject():
    para = FakeParagraph(0.2, 0.2, 0.2)
    out = asyncio.run(harness_mod.get_latest_critic_results(db=FakeAsyncDB(records=[para])))
    assert out.weighted_verdict == "reject"


# ── /trigger-iteration ────────────────────────────────────────────────────────

def test_trigger_iteration_no_loop(monkeypatch):
    monkeypatch.setattr(harness_mod, "get_iteration_loop", lambda pid: None)
    with pytest.raises(Exception):
        asyncio.run(harness_mod.trigger_iteration(project_id=1, background_tasks=FakeBackgroundTasks()))


def test_trigger_iteration_with_result(monkeypatch):
    monkeypatch.setattr(harness_mod, "get_iteration_loop", lambda pid: FakeLoop(result="ok"))
    bg = FakeBackgroundTasks()
    out = asyncio.run(harness_mod.trigger_iteration(project_id=1, background_tasks=bg))
    bg.run()  # exercise _run_trigger
    assert out["status"] == "queued"


def test_trigger_iteration_none_result(monkeypatch):
    monkeypatch.setattr(harness_mod, "get_iteration_loop", lambda pid: FakeLoop(result=None))
    bg = FakeBackgroundTasks()
    asyncio.run(harness_mod.trigger_iteration(project_id=1, background_tasks=bg))
    bg.run()


def test_trigger_iteration_error(monkeypatch):
    monkeypatch.setattr(harness_mod, "get_iteration_loop", lambda pid: FakeLoop(result="raise"))
    bg = FakeBackgroundTasks()
    asyncio.run(harness_mod.trigger_iteration(project_id=1, background_tasks=bg))
    bg.run()  # should swallow the exception


# ── /dashboard ────────────────────────────────────────────────────────────────

def test_full_dashboard(tmp_path, monkeypatch):
    _setup_version_store(tmp_path, monkeypatch)
    monkeypatch.setattr(harness_mod, "get_iteration_loop", lambda pid: None)
    monkeypatch.setattr(harness_mod, "evaluate_promotion", lambda s, c, n: FakeVerdict(passed=True))
    mgr = MagicMock()
    mgr.get_all_canaries.return_value = {
        "c1": {"status": "running", "started_at": datetime.now(timezone.utc), "version": "v2", "stage": "extract"},
    }
    monkeypatch.setattr(harness_mod, "_canary_manager", mgr)
    out = asyncio.run(harness_mod.get_full_dashboard(project_id=1, db=FakeAsyncDB(records=[])))
    assert out.iteration_status is not None
    assert out.feedback_funnel is not None
    assert out.promotion_gate is not None
    assert out.canary_dashboard is not None


# ── /rollback/{stage}/{version} ───────────────────────────────────────────────

def test_rollback_invalid_version(monkeypatch):
    vs = MagicMock()
    vs.get_current_version.return_value = 3
    monkeypatch.setattr(harness_mod, "_version_store", vs)
    with pytest.raises(Exception):
        asyncio.run(harness_mod.rollback_version("extract", "abc"))


def test_rollback_no_history(monkeypatch):
    vs = MagicMock()
    vs.get_current_version.return_value = 0
    monkeypatch.setattr(harness_mod, "_version_store", vs)
    with pytest.raises(Exception):
        asyncio.run(harness_mod.rollback_version("extract", "v1"))


def test_rollback_target_ge_current(monkeypatch):
    vs = MagicMock()
    vs.get_current_version.return_value = 3
    monkeypatch.setattr(harness_mod, "_version_store", vs)
    with pytest.raises(Exception):
        asyncio.run(harness_mod.rollback_version("extract", "v3"))


def test_rollback_target_lt_one(monkeypatch):
    vs = MagicMock()
    vs.get_current_version.return_value = 3
    monkeypatch.setattr(harness_mod, "_version_store", vs)
    with pytest.raises(Exception):
        asyncio.run(harness_mod.rollback_version("extract", "v0"))


def test_rollback_success(monkeypatch):
    vs = MagicMock()
    vs.get_current_version.return_value = 3
    vs.rollback_version.return_value = True
    monkeypatch.setattr(harness_mod, "_version_store", vs)
    out = asyncio.run(harness_mod.rollback_version("extract", "v2"))
    assert out["status"] == "success"


def test_rollback_failure(monkeypatch):
    vs = MagicMock()
    vs.get_current_version.return_value = 3
    vs.rollback_version.return_value = False
    monkeypatch.setattr(harness_mod, "_version_store", vs)
    with pytest.raises(Exception):
        asyncio.run(harness_mod.rollback_version("extract", "v2"))
