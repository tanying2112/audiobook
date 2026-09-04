"""Phase B tests for the Telemetry & Cost Tracking layer.

Targets previously-uncovered branches: TelemetryCollector construction,
failed-record Prometheus emission, cost summaries with failed/since filters,
CostTelemetry aggregation/scheduler, and the module-level track_* /
record_cost_event helpers (including their exception paths).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.audiobook_studio.core import telemetry as telemetry_mod
from src.audiobook_studio.core.telemetry import (
    CostRecord,
    CostSummary,
    OperationType,
    ProviderType,
    TelemetryCollector,
    get_telemetry,
    record_cost_event,
    reset_telemetry,
    track_llm_call,
    track_pipeline_stage,
    track_tts_synthesis,
)


def _record(provider=ProviderType.OPENAI, model="gpt-4o", success=True, ts=None, **kw):
    return CostRecord(
        operation=OperationType.LLM_CHAT,
        provider=provider,
        model=model,
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        cost_usd=kw.pop("cost_usd", 0.001),
        latency_ms=5.0,
        success=success,
        error=None if success else "boom",
        timestamp=ts or datetime.now(),
        **kw,
    )


@pytest.fixture(autouse=True)
def _reset_global():
    reset_telemetry()
    yield
    reset_telemetry()


# ── TelemetryCollector ───────────────────────────────────────────────────────


def test_collector_initialization():
    c = TelemetryCollector()
    assert c._records == []
    assert c._lock is not None


def test_record_llm_usage():
    c = TelemetryCollector()
    r = c.record_llm_usage(ProviderType.OPENAI, "gpt-4o", 100, 200, 10.0)
    assert r.total_tokens == 300
    assert len(c._records) == 1


def test_record_embedding_usage():
    c = TelemetryCollector()
    r = c.record_embedding_usage(ProviderType.OPENAI, "text-embedding", 50, 1.0)
    assert r.operation == OperationType.LLM_EMBEDDING
    assert r.completion_tokens == 0


def test_record_tts_synthesis_success_and_failure():
    c = TelemetryCollector()
    ok = c.record_tts_synthesis(ProviderType.EDGE_TTS, "edge", 1000, 5.0, success=True, voice="v")
    bad = c.record_tts_synthesis(ProviderType.EDGE_TTS, "edge", 500, 5.0, success=False, voice="v")
    assert ok.success and not bad.success
    assert len(c._records) == 2


def test_record_pipeline_stage_failure_emits_error():
    c = TelemetryCollector()
    r = c.record_pipeline_stage("synthesize", 3.0, success=False, error="x")
    assert r.success is False


def test_record_export():
    c = TelemetryCollector()
    r = c.record_export("mp3", 7.0)
    assert r.operation == OperationType.EXPORT


def test_record_quality_check():
    c = TelemetryCollector()
    good = c.record_quality_check("loudness", 1.0, passed=True)
    bad = c.record_quality_check("loudness", 1.0, passed=False)
    assert good.success and not bad.success


def test_record_book_and_chapter_and_regeneration():
    c = TelemetryCollector()
    c.record_book_processed(1)
    c.record_chapter_synthesized(1, 2)
    c.record_regeneration("retry")
    assert len(c._records) == 0  # counters only, no records


def test_record_retry_updates_metadata():
    c = TelemetryCollector()
    c.record_llm_usage(ProviderType.OPENAI, "gpt-4o", 1, 1, 1.0, success=False)
    c.record_retry(OperationType.LLM_CHAT, ProviderType.OPENAI)
    rec = c._records[0]
    assert rec.metadata.get("retries") == 1


def test_calculate_llm_cost_paths():
    c = TelemetryCollector()
    # Unknown provider -> 0.0 (line 458)
    assert c._calculate_llm_cost("totallyunknown", "m", 100, 100) == 0.0
    # Provider-level flat pricing (groq) -> computes (pass branch 455-456)
    assert c._calculate_llm_cost("groq", "llama-3", 1_000_000, 1_000_000) == 0.0
    # Known model with explicit per-model pricing
    val = c._calculate_llm_cost("openai", "gpt-4o", 1_000_000, 1_000_000)
    assert isinstance(val, float)


def test_calculate_tts_cost():
    c = TelemetryCollector()
    assert c._calculate_tts_cost("edge_tts", 2_000_000) == 0.0
    assert isinstance(c._calculate_tts_cost("unknown", 1_000_000), float)


def test_get_summary_with_failed_record():
    c = TelemetryCollector()
    c._add_record(_record(success=True))
    c._add_record(_record(success=False))
    s = c.get_summary()
    assert s.errors == 1
    assert s.total_operations == 2


def test_get_summary_with_since_filter():
    c = TelemetryCollector()
    old = _record(ts=datetime.now() - timedelta(days=5))
    new = _record(ts=datetime.now())
    c._add_record(old)
    c._add_record(new)
    since = datetime.now() - timedelta(days=1)
    s = c.get_summary(since=since)
    assert s.total_operations == 1


def test_get_records_since_and_limit():
    c = TelemetryCollector()
    base = datetime.now()
    for i in range(5):
        c._add_record(_record(ts=base - timedelta(days=i)))
    since = base - timedelta(days=2)
    recs = c.get_records(since=since)
    assert len(recs) == 3
    limited = c.get_records(limit=2)
    assert len(limited) == 2


def test_export_prometheus():
    c = TelemetryCollector()
    c.record_llm_usage(ProviderType.OPENAI, "gpt-4o", 1, 1, 1.0)
    out = c.export_prometheus()
    assert isinstance(out, str)
    assert "audiobook_llm_tokens_total" in out


def test_reset():
    c = TelemetryCollector()
    c.record_llm_usage(ProviderType.OPENAI, "gpt-4o", 1, 1, 1.0)
    c.reset()
    assert c._records == []


# ── CostTelemetry (aggregation + scheduler) ──────────────────────────────────


def test_cleanup_old_records():
    ct = TelemetryCollector()
    ct._records.append(_record(ts=datetime.now() - timedelta(days=40)))
    ct._records.append(_record(ts=datetime.now()))
    removed = ct.cleanup_old_records(retention_days=30)
    assert removed == 1
    assert len(ct._records) == 1


def test_aggregate_to_summary(tmp_path):
    ct = TelemetryCollector()
    ct._records.append(_record(ts=datetime.now() - timedelta(days=40), cost_usd=0.5))
    ct._records.append(_record(ts=datetime.now(), cost_usd=0.1))
    out = tmp_path / "summary.json"
    merged = ct.aggregate_to_summary(output_path=out, retention_days=30)
    assert merged["records_aggregated_this_run"] == 1
    assert out.exists()
    data = __import__("json").loads(out.read_text())
    assert data["total_cost_usd"] == 0.5


def test_aggregate_to_summary_merges_existing(tmp_path):
    ct = TelemetryCollector()
    old = _record(ts=datetime.now() - timedelta(days=40), cost_usd=0.5)
    ct._records.append(old)
    out = tmp_path / "summary.json"
    out.write_text(__import__("json").dumps({"total_cost_usd": 1.0, "by_provider": {}}), encoding="utf-8")
    merged = ct.aggregate_to_summary(output_path=out, retention_days=30)
    assert merged["total_cost_usd"] == 1.5


def test_merge_summaries_empty_input():
    ct = TelemetryCollector()
    s = CostSummary(total_cost_usd=2.0, total_tokens=10, total_operations=1)
    merged = ct._merge_summaries({}, s)
    assert merged["total_cost_usd"] == 2.0


def test_merge_summaries_deep_merge():
    ct = TelemetryCollector()
    existing = {
        "total_cost_usd": 1.0,
        "total_tokens": 5,
        "total_operations": 1,
        "errors": 0,
        "retries": 0,
        "by_provider": {"openai": {"cost": 1.0, "tokens": 5, "ops": 1}},
        "by_operation": {},
        "by_model": {},
    }
    new = CostSummary(total_cost_usd=1.0, total_tokens=5, total_operations=1, errors=1)
    new.by_provider = {"openai": {"cost": 1.0, "tokens": 5, "ops": 1}}
    new.by_operation = {"llm_chat": {"cost": 1.0, "tokens": 5, "ops": 1}}
    new.by_model = {"gpt-4o": {"cost": 1.0, "tokens": 5, "ops": 1}}
    merged = ct._merge_summaries(existing, new)
    assert merged["total_cost_usd"] == 2.0
    assert merged["errors"] == 1
    assert merged["by_provider"]["openai"]["cost"] == 2.0


def test_run_daily_aggregation(tmp_path):
    ct = TelemetryCollector()
    ct._records.append(_record(ts=datetime.now() - timedelta(days=40), cost_usd=0.3))
    result = ct.run_daily_aggregation()
    assert "aggregation" in result
    assert result["cleanup_removed"] == 0


class FakeScheduler:
    def __init__(self, *a, **k):
        self.running = False
        self.jobs = []

    def add_job(self, *a, **k):
        self.jobs.append(a)

    def start(self):
        self.running = True

    def shutdown(self, wait=False):
        self.running = False


@pytest.fixture
def _fake_scheduler(monkeypatch):
    monkeypatch.setattr(telemetry_mod, "BackgroundScheduler", FakeScheduler)


def test_scheduler_start_stop(_fake_scheduler):
    ct = TelemetryCollector()
    assert ct.is_scheduler_running() is False
    ct.start_scheduler(retention_days=30, summary_path=__import__("pathlib").Path("/tmp/x.json"))
    try:
        assert ct.is_scheduler_running() is True
    finally:
        ct.stop_scheduler()
    assert ct.is_scheduler_running() is False


def test_scheduler_already_running_noop(_fake_scheduler):
    ct = TelemetryCollector()
    ct.start_scheduler()
    try:
        # Second start should be a no-op (warning) and not raise
        ct.start_scheduler()
        assert ct.is_scheduler_running() is True
    finally:
        ct.stop_scheduler()


# ── Module-level helpers ─────────────────────────────────────────────────────


def test_get_telemetry_singleton():
    a = get_telemetry()
    b = get_telemetry()
    assert a is b


def test_track_llm_call_success():
    with track_llm_call(ProviderType.OPENAI, "gpt-4o-mini", project_id=1) as ctx:
        ctx["prompt_tokens"] = 100
        ctx["completion_tokens"] = 50
    recs = get_telemetry().get_records()
    assert recs and recs[0].total_tokens == 150


def test_track_llm_call_exception():
    with pytest.raises(ValueError):
        with track_llm_call(ProviderType.OPENAI, "gpt-4o-mini"):
            raise ValueError("fail")
    recs = get_telemetry().get_records()
    assert recs and recs[0].success is False


def test_track_tts_synthesis_exception():
    with pytest.raises(RuntimeError):
        with track_tts_synthesis(ProviderType.EDGE_TTS, "edge", 1000, voice="v"):
            raise RuntimeError("boom")
    recs = get_telemetry().get_records()
    assert recs and recs[0].success is False


def test_track_pipeline_stage_exception():
    with pytest.raises(KeyError):
        with track_pipeline_stage("synthesize", project_id=1):
            raise KeyError("nope")
    recs = get_telemetry().get_records()
    assert recs and recs[0].success is False


def test_record_cost_event_llm():
    r = record_cost_event(OperationType.LLM_CHAT, ProviderType.OPENAI, "gpt-4o")
    assert r.operation == OperationType.LLM_CHAT


def test_record_cost_event_tts():
    r = record_cost_event(
        OperationType.TTS_SYNTHESIS,
        ProviderType.EDGE_TTS,
        "edge",
        metadata={"characters": 100, "voice": "v"},
    )
    assert r.operation == OperationType.TTS_SYNTHESIS


def test_record_cost_event_pipeline():
    r = record_cost_event(OperationType.PIPELINE_STAGE, ProviderType.LOCAL, "stage")
    assert r.operation == OperationType.PIPELINE_STAGE
