"""Smoke/unit tests for monitoring/telemetry.py (raises real coverage).

Targets the pure dataclasses and TelemetryCollector hook surface that were
previously excluded by the broad coverage omit.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from audiobook_studio.monitoring.telemetry import (
    PipelineTelemetry,
    ProviderMetrics,
    StageTiming,
    TTSMetrics,
    TelemetryCollector,
)


def test_stage_timing_is_complete():
    st = StageTiming(stage="tts")
    assert st.is_complete is False
    st.end_time = 1.0
    assert st.is_complete is True


def test_provider_metrics_record_call_and_aggregates():
    pm = ProviderMetrics(provider="openai", model="gpt-4o")
    pm.record_call(10, 20, 0.01, 100.0, success=True)
    pm.record_call(5, 5, 0.005, 50.0, success=False, is_retry=True, is_fallback=True, fallback_from="azure")
    assert pm.call_count == 2
    assert pm.total_tokens == 40
    assert pm.cost_usd == 0.015
    assert pm.retry_count == 1
    assert pm.fallback_count == 1
    assert pm.fallback_from == ["azure"]
    assert pm.success_count == 1
    assert pm.failure_count == 1
    assert pm.avg_latency_ms == 75.0
    assert pm.success_rate == 0.5
    # empty -> safe zero divisions
    empty = ProviderMetrics(provider="x")
    assert empty.avg_latency_ms == 0.0
    assert empty.success_rate == 0.0


def test_tts_metrics_record_segment_and_ratios():
    tm = TTSMetrics()
    tm.record_segment(duration_ms=1000.0, latency_ms=200.0, provider="openai", success=True)
    tm.record_segment(duration_ms=500.0, latency_ms=100.0, provider="openai", success=False, is_retry=True)
    assert tm.total_segments == 2
    assert tm.successful_segments == 1
    assert tm.failed_segments == 1
    assert tm.total_audio_duration_ms == 1500.0
    assert tm.total_synthesis_latency_ms == 300.0
    assert tm.retry_count == 1
    assert tm.synthesis_rate_ratio == 1500.0 / 300.0
    assert tm.real_time_factor == 300.0 / 1500.0


def test_pipeline_telemetry_cost_and_stage_order():
    pt = PipelineTelemetry(project_id="1", pipeline_id="p1", started_at=0.0)
    pt.total_llm_cost_usd = 0.1
    pt.total_tts_cost_usd = 0.2
    assert pt.total_cost_usd == pytest.approx(0.3)
    assert isinstance(pt.stage_order, list)
    assert len(pt.stage_order) > 0


def test_telemetry_collector_hooks_and_summary(tmp_path: Path):
    router = MagicMock()
    collector = TelemetryCollector(
        project_id="123",
        output_dir=str(tmp_path),
        llm_router=router,
        synthesize_pipeline=MagicMock(),
    )
    collector.on_stage_enter("stage_enter", "tts", {})
    collector.on_stage_exit("stage_exit", "tts", {}, result=None, error=None)
    collector.record_llm_call(provider="openai", model="gpt-4o", tokens_in=10, tokens_out=5, cost_usd=0.01, latency_ms=50.0, success=True)
    collector.record_tts_segment(duration_ms=1000.0, latency_ms=100.0, success=True, provider="openai")
    collector.on_pipeline_end("pipeline_end", {"project_id": "123"})
    # summary file written to the configured output_dir (no on_pipeline_start redirect)
    summary = tmp_path / "metrics_summary.json"
    assert summary.exists()
    assert collector.telemetry.total_cost_usd >= 0.0
    # idempotent end guard
    collector.on_pipeline_end("pipeline_end", {"project_id": "123"})


def test_telemetry_collector_ignores_unrelated_events(tmp_path: Path):
    collector = TelemetryCollector(project_id="123", output_dir=str(tmp_path), llm_router=MagicMock())
    before = collector.telemetry.started_at
    collector.on_pipeline_start("something_else", {})
    assert collector.telemetry.started_at == before
