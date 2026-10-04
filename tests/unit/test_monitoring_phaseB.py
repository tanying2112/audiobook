"""Phase B structural tests for monitoring.py (in-memory PerformanceCollector).

NOTE: src/audiobook_studio/monitoring.py is shadowed by the monitoring/ package,
so it is loaded directly from the file path via importlib.
"""

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "audiobook_studio_monitoring_standalone",
    Path(__file__).resolve().parents[2] / "src/audiobook_studio" / "monitoring.py",
)
mon = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mon)

StagePerformanceRecord = mon.StagePerformanceRecord
PerformanceCollector = mon.PerformanceCollector
get_collector = mon.get_collector
record_stage_performance = mon.record_stage_performance
reset_collector = mon.reset_collector


def test_stage_performance_record_defaults():
    r = StagePerformanceRecord(
        stage="edit_for_tts",
        latency_ms=1.0,
        tokens_in=1,
        tokens_out=0,
        cost_usd=0.0,
        success=True,
    )
    assert r.provider == "unknown"
    assert r.model == "unknown"
    assert r.quality_score is None


def test_collector_record_and_stats(tmp_path):
    c = PerformanceCollector(log_dir=tmp_path)
    c.record(
        stage="edit_for_tts",
        latency_ms=100.0,
        tokens_in=10,
        tokens_out=5,
        cost_usd=0.01,
        success=True,
        quality_score=0.9,
    )
    c.record(stage="edit_for_tts", latency_ms=200.0, tokens_in=20, tokens_out=10, cost_usd=0.02, success=False)
    c.record(
        stage="annotate", latency_ms=50.0, tokens_in=5, tokens_out=2, cost_usd=0.005, success=True, quality_score=0.8
    )

    stats = c.get_stage_stats("edit_for_tts")
    assert stats["count"] == 2
    assert stats["success_count"] == 1
    assert stats["success_rate"] == 0.5
    assert stats["avg_latency_ms"] == 150.0
    assert stats["total_cost_usd"] == 0.03
    assert abs(stats["avg_quality_score"] - 0.9) < 1e-9

    missing = c.get_stage_stats("nonexistent")
    assert missing == {"stage": "nonexistent", "count": 0}

    summary = c.get_summary()
    assert summary["total_records"] == 3
    assert "edit_for_tts" in summary["stages"]


def test_collector_no_quality_score_avg_none():
    c = PerformanceCollector()
    c.record(stage="s", latency_ms=10, tokens_in=1, tokens_out=1, cost_usd=0.0, success=True)
    stats = c.get_stage_stats("s")
    assert stats["avg_quality_score"] is None


def test_get_collector_and_reset():
    reset_collector()
    col = get_collector()
    assert isinstance(col, PerformanceCollector)
    col.record(stage="s", latency_ms=1, tokens_in=1, tokens_out=1, cost_usd=0.0, success=True)
    assert len(col.records) == 1
    reset_collector()
    assert len(get_collector().records) == 0


def test_record_stage_performance_global():
    reset_collector()
    rec = record_stage_performance(
        stage="edit_for_tts",
        latency_ms=10,
        tokens_in=1,
        tokens_out=1,
        cost_usd=0.0,
        success=True,
        quality_score=0.7,
        provider="openrouter",
    )
    assert rec.stage == "edit_for_tts"
    assert len(get_collector().records) == 1
