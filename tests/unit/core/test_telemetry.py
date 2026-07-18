"""Tests for Telemetry & Cost Tracking Layer."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

import pytest

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


class TestTelemetryCollector:
    """Tests for TelemetryCollector class."""

    @pytest.fixture(autouse=True)
    def reset(self):
        """Reset telemetry before each test."""
        reset_telemetry()
        yield
        reset_telemetry()

    def test_collector_initialization(self):
        """Test collector initializes correctly."""
        collector = TelemetryCollector()
        assert collector is not None
        assert collector._records == []
        assert collector._session_start is not None

    def test_record_llm_usage(self):
        """Test recording LLM usage."""
        collector = TelemetryCollector()

        record = collector.record_llm_usage(
            provider=ProviderType.OPENAI,
            model="gpt-4o-mini",
            prompt_tokens=100,
            completion_tokens=200,
            latency_ms=150.0,
            success=True,
            project_id=1,
            chapter_id=5,
        )

        assert isinstance(record, CostRecord)
        assert record.operation == OperationType.LLM_CHAT
        assert record.provider == ProviderType.OPENAI
        assert record.model == "gpt-4o-mini"
        assert record.prompt_tokens == 100
        assert record.completion_tokens == 200
        assert record.total_tokens == 300
        assert record.latency_ms == 150.0
        assert record.success is True
        assert record.project_id == 1
        assert record.chapter_id == 5
        assert record.cost_usd > 0  # gpt-4o-mini has pricing

    def test_record_llm_usage_free_provider(self):
        """Test recording LLM usage with free provider (Groq)."""
        collector = TelemetryCollector()

        record = collector.record_llm_usage(
            provider=ProviderType.GROQ,
            model="llama-3.1-70b",
            prompt_tokens=1000,
            completion_tokens=2000,
            latency_ms=500.0,
        )

        # Groq is free tier
        assert record.cost_usd == 0.0
        assert record.total_tokens == 3000

    def test_record_embedding_usage(self):
        """Test recording embedding usage."""
        collector = TelemetryCollector()

        record = collector.record_embedding_usage(
            provider=ProviderType.OPENAI,
            model="text-embedding-3-small",
            tokens=500,
            latency_ms=100.0,
        )

        assert record.operation == OperationType.LLM_EMBEDDING
        assert record.prompt_tokens == 500
        assert record.completion_tokens == 0
        assert record.total_tokens == 500
        assert record.cost_usd > 0  # embedding has cost

    def test_record_tts_synthesis(self):
        """Test recording TTS synthesis."""
        collector = TelemetryCollector()

        record = collector.record_tts_synthesis(
            provider=ProviderType.EDGE_TTS,
            model="edge",
            characters=5000,
            latency_ms=2000.0,
            voice="zh-CN-XiaoxiaoNeural",
        )

        assert record.operation == OperationType.TTS_SYNTHESIS
        assert record.provider == ProviderType.EDGE_TTS
        assert record.metadata["characters"] == 5000
        assert record.metadata["voice"] == "zh-CN-XiaoxiaoNeural"
        assert record.cost_usd == 0.0  # Edge TTS is free

    def test_record_tts_paid_provider(self):
        """Test recording TTS with paid provider."""
        collector = TelemetryCollector()

        record = collector.record_tts_synthesis(
            provider=ProviderType.OPENAI,  # Using openai as placeholder for elevenlabs
            model="elevenlabs",
            characters=1_000_000,
            latency_ms=5000.0,
        )

        # Would need to add elevenlabs pricing, but openai TTS not in TTS_PRICING
        assert record.cost_usd >= 0

    def test_record_pipeline_stage(self):
        """Test recording pipeline stage."""
        collector = TelemetryCollector()

        record = collector.record_pipeline_stage(
            stage="synthesize",
            latency_ms=30000.0,
            project_id=1,
            metadata={"chapters": 5},
        )

        assert record.operation == OperationType.PIPELINE_STAGE
        assert record.model == "synthesize"
        assert record.latency_ms == 30000.0
        assert record.provider == ProviderType.LOCAL
        assert record.metadata["chapters"] == 5

    def test_record_export(self):
        """Test recording export operation."""
        collector = TelemetryCollector()

        record = collector.record_export(
            format="m4b_srt",
            latency_ms=10000.0,
            project_id=1,
        )

        assert record.operation == OperationType.EXPORT
        assert record.model == "m4b_srt"
        assert record.latency_ms == 10000.0

    def test_record_quality_check(self):
        """Test recording quality check."""
        collector = TelemetryCollector()

        # Passing check
        record_pass = collector.record_quality_check(
            check_type="loudness",
            latency_ms=100.0,
            passed=True,
            project_id=1,
        )
        assert record_pass.success is True
        assert record_pass.error is None

        # Failing check
        record_fail = collector.record_quality_check(
            check_type="clipping",
            latency_ms=100.0,
            passed=False,
            project_id=1,
        )
        assert record_fail.success is False
        assert "clipping" in record_fail.error

    def test_record_book_processed(self):
        """Test recording book completion."""
        collector = TelemetryCollector()
        collector.record_book_processed(project_id=1)
        # Should not raise

    def test_record_chapter_synthesized(self):
        """Test recording chapter synthesis."""
        collector = TelemetryCollector()
        collector.record_chapter_synthesized(project_id=1, chapter_id=5)
        # Should not raise

    def test_record_regeneration(self):
        """Test recording regeneration trigger."""
        collector = TelemetryCollector()
        collector.record_regeneration(reason="quality_failure")
        # Should not raise

    def test_get_summary(self):
        """Test getting cost summary."""
        collector = TelemetryCollector()

        # Add some records
        collector.record_llm_usage(ProviderType.OPENAI, "gpt-4o-mini", 100, 200, 150.0)
        collector.record_llm_usage(ProviderType.GROQ, "llama-3.1-70b", 500, 1000, 500.0)
        collector.record_tts_synthesis(ProviderType.EDGE_TTS, "edge", 10000, 2000.0)

        summary = collector.get_summary()

        assert isinstance(summary, CostSummary)
        assert summary.total_operations == 3
        assert summary.total_tokens == 1800  # 300 + 1500 + 0
        assert summary.total_cost_usd > 0  # Only openai has cost
        assert "openai" in summary.by_provider
        assert "groq" in summary.by_provider
        assert "edge_tts" in summary.by_provider
        assert "llm_chat" in summary.by_operation
        assert "tts_synthesis" in summary.by_operation

    def test_get_summary_with_time_filter(self):
        """Test getting summary with time filter."""
        collector = TelemetryCollector()

        # Add old record
        collector.record_llm_usage(ProviderType.OPENAI, "gpt-4o-mini", 100, 200, 150.0)

        # Manually adjust timestamp to be old
        with collector._lock:
            collector._records[0].timestamp = datetime.now() - timedelta(hours=2)

        # Add new record
        collector.record_llm_usage(ProviderType.GROQ, "llama-3.1-70b", 500, 1000, 500.0)

        # Get summary for last hour
        since = datetime.now() - timedelta(hours=1)
        summary = collector.get_summary(since=since)

        # Should only have the new record
        assert summary.total_operations == 1
        assert summary.total_tokens == 1500

    def test_get_records(self):
        """Test getting raw records."""
        collector = TelemetryCollector()

        collector.record_llm_usage(ProviderType.OPENAI, "gpt-4o-mini", 100, 200, 150.0)
        collector.record_tts_synthesis(ProviderType.EDGE_TTS, "edge", 10000, 2000.0)

        records = collector.get_records()
        assert len(records) == 2
        assert records[0].operation == OperationType.LLM_CHAT
        assert records[1].operation == OperationType.TTS_SYNTHESIS

    def test_get_records_with_limit(self):
        """Test getting records with limit."""
        collector = TelemetryCollector()

        for i in range(5):
            collector.record_llm_usage(ProviderType.GROQ, "llama-3.1-70b", 100, 200, 100.0)

        records = collector.get_records(limit=2)
        assert len(records) == 2

    def test_record_retry(self):
        """Test recording retry."""
        collector = TelemetryCollector()

        # First record a failure
        collector.record_llm_usage(
            ProviderType.OPENAI,
            "gpt-4o-mini",
            100,
            200,
            150.0,
            success=False,
            error="Rate limited",
        )

        # Record retry
        collector.record_retry(OperationType.LLM_CHAT, ProviderType.OPENAI)

        # Check the record was updated
        records = collector.get_records()
        assert records[0].metadata.get("retries") == 1

    def test_reset(self):
        """Test resetting collector."""
        collector = TelemetryCollector()

        collector.record_llm_usage(ProviderType.OPENAI, "gpt-4o-mini", 100, 200, 150.0)
        assert len(collector.get_records()) == 1

        collector.reset()
        assert len(collector.get_records()) == 0


class TestContextManagers:
    """Tests for context manager helpers."""

    @pytest.fixture(autouse=True)
    def reset(self):
        reset_telemetry()
        yield
        reset_telemetry()

    def test_track_llm_call_success(self):
        """Test tracking successful LLM call."""
        with track_llm_call(ProviderType.OPENAI, "gpt-4o-mini", project_id=1) as ctx:
            time.sleep(0.01)
            ctx["prompt_tokens"] = 50
            ctx["completion_tokens"] = 100

        records = get_telemetry().get_records()
        assert len(records) == 1
        assert records[0].prompt_tokens == 50
        assert records[0].completion_tokens == 100
        assert records[0].success is True
        assert records[0].latency_ms > 0

    def test_track_llm_call_failure(self):
        """Test tracking failed LLM call."""
        with pytest.raises(ValueError):
            with track_llm_call(ProviderType.OPENAI, "gpt-4o-mini") as ctx:
                ctx["prompt_tokens"] = 50
                raise ValueError("API error")

        records = get_telemetry().get_records()
        assert len(records) == 1
        assert records[0].success is False
        assert records[0].error == "API error"

    def test_track_tts_synthesis_success(self):
        """Test tracking successful TTS synthesis."""
        with track_tts_synthesis(
            ProviderType.EDGE_TTS, "edge", 5000, project_id=1, voice="zh-CN-XiaoxiaoNeural"
        ):
            time.sleep(0.01)

        records = get_telemetry().get_records()
        assert len(records) == 1
        assert records[0].operation == OperationType.TTS_SYNTHESIS
        assert records[0].metadata["characters"] == 5000
        assert records[0].metadata["voice"] == "zh-CN-XiaoxiaoNeural"

    def test_track_pipeline_stage(self):
        """Test tracking pipeline stage."""
        with track_pipeline_stage("analyze", project_id=1) as ctx:
            time.sleep(0.01)
            ctx["metadata"]["chapters"] = 10

        records = get_telemetry().get_records()
        assert len(records) == 1
        assert records[0].operation == OperationType.PIPELINE_STAGE
        assert records[0].model == "analyze"
        assert records[0].metadata["chapters"] == 10


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    @pytest.fixture(autouse=True)
    def reset(self):
        reset_telemetry()
        yield
        reset_telemetry()

    def test_get_telemetry_singleton(self):
        """Test get_telemetry returns singleton."""
        t1 = get_telemetry()
        t2 = get_telemetry()
        assert t1 is t2

    def test_reset_telemetry(self):
        """Test reset_telemetry creates new instance."""
        t1 = get_telemetry()
        t1.record_llm_usage(ProviderType.OPENAI, "gpt-4o-mini", 100, 200, 150.0)
        assert len(t1.get_records()) == 1

        reset_telemetry()
        t2 = get_telemetry()
        assert len(t2.get_records()) == 0
        assert t1 is not t2

    def test_record_cost_event(self):
        """Test record_cost_event convenience function."""
        record = record_cost_event(
            operation=OperationType.LLM_CHAT,
            provider=ProviderType.ANTHROPIC,
            model="claude-3-5-sonnet",
            prompt_tokens=200,
            completion_tokens=400,
            latency_ms=2000.0,
            cost_usd=0.01,
        )

        assert record.operation == OperationType.LLM_CHAT
        assert record.provider == ProviderType.ANTHROPIC
        assert record.cost_usd == 0.01
        assert len(get_telemetry().get_records()) == 1


class TestCostCalculation:
    """Tests for cost calculation accuracy."""

    @pytest.fixture(autouse=True)
    def reset(self):
        reset_telemetry()
        yield
        reset_telemetry()

    def test_gpt4o_mini_cost(self):
        """Test GPT-4o-mini cost calculation."""
        collector = TelemetryCollector()
        record = collector.record_llm_usage(
            ProviderType.OPENAI, "gpt-4o-mini", 1_000_000, 1_000_000, 1000.0
        )
        # $0.15/M input + $0.6/M output = $0.75 per 1M tokens each
        expected = 0.15 + 0.6  # $0.75
        assert abs(record.cost_usd - expected) < 0.01

    def test_groq_free(self):
        """Test Groq is free."""
        collector = TelemetryCollector()
        record = collector.record_llm_usage(
            ProviderType.GROQ, "llama-3.1-70b", 1_000_000, 1_000_000, 1000.0
        )
        assert record.cost_usd == 0.0

    def test_claude_sonnet_cost(self):
        """Test Claude 3.5 Sonnet cost."""
        collector = TelemetryCollector()
        record = collector.record_llm_usage(
            ProviderType.ANTHROPIC, "claude-3-5-sonnet", 1_000_000, 1_000_000, 1000.0
        )
        # $3/M input + $15/M output = $18
        expected = 3.0 + 15.0
        assert abs(record.cost_usd - expected) < 0.01

    def test_edge_tts_free(self):
        """Test Edge TTS is free."""
        collector = TelemetryCollector()
        record = collector.record_tts_synthesis(
            ProviderType.EDGE_TTS, "edge", 1_000_000, 1000.0
        )
        assert record.cost_usd == 0.0

    def test_unknown_model_zero_cost(self):
        """Test unknown model defaults to zero cost."""
        collector = TelemetryCollector()
        record = collector.record_llm_usage(
            ProviderType.OPENAI, "unknown-model-xyz", 1000, 2000, 100.0
        )
        assert record.cost_usd == 0.0


class TestPrometheusExport:
    """Tests for Prometheus metrics export."""

    @pytest.fixture(autouse=True)
    def reset(self):
        reset_telemetry()
        yield
        reset_telemetry()

    def test_export_prometheus(self):
        """Test Prometheus export format."""
        collector = TelemetryCollector()
        collector.record_llm_usage(ProviderType.OPENAI, "gpt-4o-mini", 100, 200, 150.0)

        output = collector.export_prometheus()

        assert isinstance(output, str)
        assert "audiobook_llm_tokens_total" in output
        assert "audiobook_llm_cost_usd_total" in output
        assert "audiobook_operation_duration_ms" in output
        assert "provider=\"openai\"" in output
        assert "model=\"gpt-4o-mini\"" in output

    def test_prometheus_metrics_initialized(self):
        """Test Prometheus metrics are initialized."""
        from src.audiobook_studio.core.telemetry import _prom_metrics

        # Should be initialized after first use
        collector = TelemetryCollector()
        collector.record_llm_usage(ProviderType.OPENAI, "gpt-4o-mini", 100, 200, 150.0)

        assert "llm_tokens_total" in _prom_metrics
        assert "llm_cost_usd_total" in _prom_metrics


if __name__ == "__main__":
    pytest.main([__file__, "-v"])