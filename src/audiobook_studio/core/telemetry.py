"""Telemetry & Cost Tracking Layer for Audiobook Studio.

Provides centralized cost tracking, token usage monitoring, latency metrics,
and Prometheus export for all LLM/TTS/pipeline operations.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Generator, Optional

from prometheus_client import Counter, Gauge, Histogram, generate_latest

from ..config.settings import get_settings

logger = logging.getLogger(__name__)


class OperationType(str, Enum):
    """Types of operations we track."""

    LLM_CHAT = "llm_chat"
    LLM_EMBEDDING = "llm_embedding"
    TTS_SYNTHESIS = "tts_synthesis"
    PIPELINE_STAGE = "pipeline_stage"
    EXPORT = "export"
    QUALITY_CHECK = "quality_check"


class ProviderType(str, Enum):
    """Provider types for cost tracking."""

    GROQ = "groq"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"
    OPENROUTER = "openrouter"
    NVIDIA = "nvidia"
    EDGE_TTS = "edge_tts"
    KOKORO = "kokoro"
    VOICEPM2 = "voxcpm2"
    LOCAL = "local"


@dataclass
class CostRecord:
    """Record of a single operation's cost and metadata."""

    operation: OperationType
    provider: ProviderType
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    project_id: Optional[int] = None
    chapter_id: Optional[int] = None


@dataclass
class CostSummary:
    """Aggregated cost summary."""

    total_cost_usd: float = 0.0
    total_tokens: int = 0
    total_operations: int = 0
    by_provider: Dict[str, Dict[str, float]] = field(default_factory=dict)
    by_operation: Dict[str, Dict[str, float]] = field(default_factory=dict)
    by_model: Dict[str, Dict[str, float]] = field(default_factory=dict)
    errors: int = 0
    retries: int = 0


# Token pricing per 1M tokens (USD) - update as providers change pricing
TOKEN_PRICING: Dict[str, Dict[str, float]] = {
    "groq": {"input": 0.0, "output": 0.0},  # Free tier
    "openai": {
        "gpt-4o": {"input": 5.0, "output": 15.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.6},
        "gpt-4-turbo": {"input": 10.0, "output": 30.0},
        "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
        "text-embedding-3-small": {"input": 0.02, "output": 0.0},
        "text-embedding-3-large": {"input": 0.13, "output": 0.0},
    },
    "anthropic": {
        "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
        "claude-3-5-haiku": {"input": 0.25, "output": 1.25},
        "claude-3-opus": {"input": 15.0, "output": 75.0},
    },
    "gemini": {
        "gemini-1.5-pro": {"input": 1.25, "output": 5.0},
        "gemini-1.5-flash": {"input": 0.075, "output": 0.3},
        "gemini-2.0-flash": {"input": 0.1, "output": 0.4},
    },
    "deepseek": {
        "deepseek-chat": {"input": 0.14, "output": 0.28},
        "deepseek-coder": {"input": 0.14, "output": 0.28},
    },
    "openrouter": {},  # Varies by model
    "nvidia": {},  # Often free tier
    "edge_tts": {"tts": {"input": 0.0, "output": 0.0}},  # Free
    "kokoro": {"tts": {"input": 0.0, "output": 0.0}},  # Local
    "voxcpm2": {"tts": {"input": 0.0, "output": 0.0}},  # Local/GPU
    "local": {"input": 0.0, "output": 0.0},
}

# TTS pricing per 1M characters
TTS_PRICING: Dict[str, float] = {
    "edge_tts": 0.0,
    "kokoro": 0.0,
    "voxcpm2": 0.0,
    "elevenlabs": 15.0,  # $15 per 1M chars
    "azure_tts": 16.0,
    "google_tts": 16.0,
}


# Prometheus metrics (created lazily)
_prom_metrics: Dict[str, Any] = {}
_metrics_lock = threading.Lock()


def _init_prometheus_metrics() -> None:
    """Initialize Prometheus metrics (thread-safe, idempotent)."""
    global _prom_metrics
    with _metrics_lock:
        if _prom_metrics:
            return

        _prom_metrics = {
            # Cost & Token metrics
            "llm_tokens_total": Counter(
                "audiobook_llm_tokens_total",
                "Total LLM tokens consumed",
                ["provider", "model", "type"],  # type: prompt|completion
            ),
            "llm_cost_usd_total": Counter(
                "audiobook_llm_cost_usd_total",
                "Total LLM cost in USD",
                ["provider", "model"],
            ),
            "tts_characters_total": Counter(
                "audiobook_tts_characters_total",
                "Total TTS characters synthesized",
                ["provider", "model", "voice"],
            ),
            "tts_cost_usd_total": Counter(
                "audiobook_tts_cost_usd_total",
                "Total TTS cost in USD",
                ["provider", "model"],
            ),
            # Latency metrics
            "operation_duration_ms": Histogram(
                "audiobook_operation_duration_ms",
                "Operation duration in milliseconds",
                ["operation", "provider", "model"],
                buckets=[50, 100, 200, 500, 1000, 2000, 5000, 10000, 30000, 60000, 120000],
            ),
            "pipeline_stage_duration_ms": Histogram(
                "audiobook_pipeline_stage_duration_ms",
                "Pipeline stage duration in milliseconds",
                ["stage", "project_id"],
                buckets=[100, 500, 1000, 5000, 10000, 30000, 60000, 120000, 300000],
            ),
            # Error/Success metrics
            "operation_errors_total": Counter(
                "audiobook_operation_errors_total",
                "Total operation errors",
                ["operation", "provider", "error_type"],
            ),
            "operation_retries_total": Counter(
                "audiobook_operation_retries_total",
                "Total operation retries",
                ["operation", "provider"],
            ),
            # Business metrics
            "books_processed_total": Counter(
                "audiobook_books_processed_total",
                "Total books processed",
            ),
            "chapters_synthesized_total": Counter(
                "audiobook_chapters_synthesized_total",
                "Total chapters synthesized",
            ),
            "quality_failures_total": Counter(
                "audiobook_quality_failures_total",
                "Total quality check failures",
                ["check_type"],
            ),
            "regenerations_triggered_total": Counter(
                "audiobook_regenerations_triggered_total",
                "Total audio regenerations triggered",
                ["reason"],
            ),
            # Gauge for current state
            "free_tier_quota_remaining": Gauge(
                "audiobook_free_tier_quota_remaining",
                "Remaining free tier quota percentage",
                ["provider"],
            ),
            "active_pipelines": Gauge(
                "audiobook_active_pipelines",
                "Number of currently active pipelines",
            ),
        }
        logger.debug("Prometheus metrics initialized")


class TelemetryCollector:
    """Central telemetry collector for cost tracking and metrics emission."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._records: list[CostRecord] = []
        self._lock = threading.Lock()
        self._session_start = datetime.now()
        _init_prometheus_metrics()

    def record_llm_usage(
        self,
        provider: ProviderType,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        success: bool = True,
        error: Optional[str] = None,
        project_id: Optional[int] = None,
        chapter_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CostRecord:
        """Record an LLM API call."""
        total_tokens = prompt_tokens + completion_tokens
        cost = self._calculate_llm_cost(provider.value, model, prompt_tokens, completion_tokens)

        record = CostRecord(
            operation=OperationType.LLM_CHAT,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            success=success,
            error=error,
            metadata=metadata or {},
            project_id=project_id,
            chapter_id=chapter_id,
        )

        self._add_record(record)
        self._emit_prometheus_llm(record)
        return record

    def record_embedding_usage(
        self,
        provider: ProviderType,
        model: str,
        tokens: int,
        latency_ms: float,
        success: bool = True,
        error: Optional[str] = None,
        project_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CostRecord:
        """Record an embedding API call."""
        cost = self._calculate_llm_cost(provider.value, model, tokens, 0)

        record = CostRecord(
            operation=OperationType.LLM_EMBEDDING,
            provider=provider,
            model=model,
            prompt_tokens=tokens,
            completion_tokens=0,
            total_tokens=tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            success=success,
            error=error,
            metadata=metadata or {},
            project_id=project_id,
        )

        self._add_record(record)
        self._emit_prometheus_llm(record)
        return record

    def record_tts_synthesis(
        self,
        provider: ProviderType,
        model: str,
        characters: int,
        latency_ms: float,
        success: bool = True,
        error: Optional[str] = None,
        project_id: Optional[int] = None,
        chapter_id: Optional[int] = None,
        voice: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CostRecord:
        """Record a TTS synthesis operation."""
        cost = self._calculate_tts_cost(provider.value, characters)

        record = CostRecord(
            operation=OperationType.TTS_SYNTHESIS,
            provider=provider,
            model=model,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost_usd=cost,
            latency_ms=latency_ms,
            success=success,
            error=error,
            metadata={**(metadata or {}), "characters": characters, "voice": voice},
            project_id=project_id,
            chapter_id=chapter_id,
        )

        self._add_record(record)
        self._emit_prometheus_tts(record, characters, voice)
        return record

    def record_pipeline_stage(
        self,
        stage: str,
        latency_ms: float,
        success: bool = True,
        error: Optional[str] = None,
        project_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CostRecord:
        """Record a pipeline stage execution."""
        record = CostRecord(
            operation=OperationType.PIPELINE_STAGE,
            provider=ProviderType.LOCAL,
            model=stage,
            latency_ms=latency_ms,
            success=success,
            error=error,
            metadata=metadata or {},
            project_id=project_id,
        )

        self._add_record(record)
        self._emit_prometheus_pipeline(record)
        return record

    def record_export(
        self,
        format: str,
        latency_ms: float,
        success: bool = True,
        error: Optional[str] = None,
        project_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CostRecord:
        """Record an export operation."""
        record = CostRecord(
            operation=OperationType.EXPORT,
            provider=ProviderType.LOCAL,
            model=format,
            latency_ms=latency_ms,
            success=success,
            error=error,
            metadata=metadata or {},
            project_id=project_id,
        )

        self._add_record(record)
        return record

    def record_quality_check(
        self,
        check_type: str,
        latency_ms: float,
        passed: bool,
        project_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CostRecord:
        """Record a quality check result."""
        record = CostRecord(
            operation=OperationType.QUALITY_CHECK,
            provider=ProviderType.LOCAL,
            model=check_type,
            latency_ms=latency_ms,
            success=passed,
            error=None if passed else f"Quality check failed: {check_type}",
            metadata=metadata or {},
            project_id=project_id,
        )

        self._add_record(record)
        if not passed:
            _prom_metrics["quality_failures_total"].labels(check_type=check_type).inc()
        return record

    def record_book_processed(self, project_id: int) -> None:
        """Record a book completion."""
        _prom_metrics["books_processed_total"].inc()

    def record_chapter_synthesized(self, project_id: int, chapter_id: int) -> None:
        """Record a chapter synthesis completion."""
        _prom_metrics["chapters_synthesized_total"].inc()

    def record_regeneration(self, reason: str) -> None:
        """Record an audio regeneration trigger."""
        _prom_metrics["regenerations_triggered_total"].labels(reason=reason).inc()

    def record_retry(self, operation: OperationType, provider: ProviderType) -> None:
        """Record a retry attempt."""
        with self._lock:
            # Find and update the last failed record
            for record in reversed(self._records):
                if record.operation == operation and record.provider == provider and not record.success:
                    record.metadata["retries"] = record.metadata.get("retries", 0) + 1
                    break
        _prom_metrics["operation_retries_total"].labels(operation=operation.value, provider=provider.value).inc()

    def _add_record(self, record: CostRecord) -> None:
        with self._lock:
            self._records.append(record)

    def _calculate_llm_cost(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate cost for LLM usage."""
        pricing = TOKEN_PRICING.get(provider, {}).get(model)
        if not pricing:
            # Try provider-level default
            pricing = TOKEN_PRICING.get(provider, {})
            if isinstance(pricing, dict) and "input" in pricing:
                pass  # Use provider-level pricing
            else:
                return 0.0  # Unknown model, assume free/local

        input_cost = (prompt_tokens / 1_000_000) * pricing.get("input", 0)
        output_cost = (completion_tokens / 1_000_000) * pricing.get("output", 0)
        return input_cost + output_cost

    def _calculate_tts_cost(self, provider: str, characters: int) -> float:
        """Calculate cost for TTS synthesis."""
        price_per_million = TTS_PRICING.get(provider, 0.0)
        return (characters / 1_000_000) * price_per_million

    def _emit_prometheus_llm(self, record: CostRecord) -> None:
        """Emit Prometheus metrics for LLM operations."""
        labels = {"provider": record.provider.value, "model": record.model}
        _prom_metrics["llm_tokens_total"].labels(**labels, type="prompt").inc(record.prompt_tokens)
        _prom_metrics["llm_tokens_total"].labels(**labels, type="completion").inc(record.completion_tokens)
        _prom_metrics["llm_cost_usd_total"].labels(**labels).inc(record.cost_usd)
        _prom_metrics["operation_duration_ms"].labels(
            operation=record.operation.value, **labels
        ).observe(record.latency_ms)

        if not record.success:
            _prom_metrics["operation_errors_total"].labels(
                operation=record.operation.value,
                provider=record.provider.value,
                error_type=record.error or "unknown",
            ).inc()

    def _emit_prometheus_tts(self, record: CostRecord, characters: int, voice: Optional[str]) -> None:
        """Emit Prometheus metrics for TTS operations."""
        tts_labels = {"provider": record.provider.value, "model": record.model, "voice": voice or "unknown"}
        op_labels = {"operation": record.operation.value, "provider": record.provider.value, "model": record.model}
        _prom_metrics["tts_characters_total"].labels(**tts_labels).inc(characters)
        _prom_metrics["tts_cost_usd_total"].labels(provider=record.provider.value, model=record.model).inc(record.cost_usd)
        _prom_metrics["operation_duration_ms"].labels(**op_labels).observe(record.latency_ms)

        if not record.success:
            _prom_metrics["operation_errors_total"].labels(
                operation=record.operation.value,
                provider=record.provider.value,
                error_type=record.error or "unknown",
            ).inc()

    def _emit_prometheus_pipeline(self, record: CostRecord) -> None:
        """Emit Prometheus metrics for pipeline stages."""
        _prom_metrics["pipeline_stage_duration_ms"].labels(
            stage=record.model, project_id=str(record.project_id or "unknown")
        ).observe(record.latency_ms)

        if not record.success:
            _prom_metrics["operation_errors_total"].labels(
                operation=record.operation.value,
                provider=record.provider.value,
                error_type=record.error or "unknown",
            ).inc()

    def get_summary(self, since: Optional[datetime] = None) -> CostSummary:
        """Get aggregated cost summary."""
        with self._lock:
            records = self._records
            if since:
                records = [r for r in records if r.timestamp >= since]

        summary = CostSummary()
        for r in records:
            summary.total_cost_usd += r.cost_usd
            summary.total_tokens += r.total_tokens
            summary.total_operations += 1

            if not r.success:
                summary.errors += 1
            summary.retries += r.metadata.get("retries", 0)

            # By provider
            prov_key = r.provider.value
            if prov_key not in summary.by_provider:
                summary.by_provider[prov_key] = {"cost": 0.0, "tokens": 0, "ops": 0}
            summary.by_provider[prov_key]["cost"] += r.cost_usd
            summary.by_provider[prov_key]["tokens"] += r.total_tokens
            summary.by_provider[prov_key]["ops"] += 1

            # By operation
            op_key = r.operation.value
            if op_key not in summary.by_operation:
                summary.by_operation[op_key] = {"cost": 0.0, "tokens": 0, "ops": 0}
            summary.by_operation[op_key]["cost"] += r.cost_usd
            summary.by_operation[op_key]["tokens"] += r.total_tokens
            summary.by_operation[op_key]["ops"] += 1

            # By model
            model_key = r.model
            if model_key not in summary.by_model:
                summary.by_model[model_key] = {"cost": 0.0, "tokens": 0, "ops": 0}
            summary.by_model[model_key]["cost"] += r.cost_usd
            summary.by_model[model_key]["tokens"] += r.total_tokens
            summary.by_model[model_key]["ops"] += 1

        return summary

    def get_records(self, since: Optional[datetime] = None, limit: Optional[int] = None) -> list[CostRecord]:
        """Get raw cost records."""
        with self._lock:
            records = self._records
            if since:
                records = [r for r in records if r.timestamp >= since]
            if limit:
                records = records[-limit:]
            return records.copy()

    def export_prometheus(self) -> str:
        """Export Prometheus metrics in text format."""
        _init_prometheus_metrics()
        return generate_latest().decode("utf-8")

    def reset(self) -> None:
        """Reset collected records (for testing)."""
        with self._lock:
            self._records.clear()
            self._session_start = datetime.now()


# Global collector instance
_collector: Optional[TelemetryCollector] = None
_collector_lock = threading.Lock()


def get_telemetry() -> TelemetryCollector:
    """Get or create the global telemetry collector."""
    global _collector
    with _collector_lock:
        if _collector is None:
            _collector = TelemetryCollector()
        return _collector


def reset_telemetry() -> None:
    """Reset the global telemetry collector (for testing)."""
    global _collector
    with _collector_lock:
        if _collector:
            _collector.reset()
        _collector = None


@contextmanager
def track_llm_call(
    provider: ProviderType,
    model: str,
    project_id: Optional[int] = None,
    chapter_id: Optional[int] = None,
) -> Generator[Dict[str, Any], None, None]:
    """Context manager to track an LLM call automatically.

    Usage:
        with track_llm_call(ProviderType.OPENAI, "gpt-4o-mini") as ctx:
            response = await llm.achat(messages)
            ctx["prompt_tokens"] = response.usage.prompt_tokens
            ctx["completion_tokens"] = response.usage.completion_tokens
    """
    start = time.perf_counter()
    ctx = {"prompt_tokens": 0, "completion_tokens": 0, "success": True, "error": None}
    try:
        yield ctx
    except Exception as e:
        ctx["success"] = False
        ctx["error"] = str(e)
        raise
    finally:
        latency_ms = (time.perf_counter() - start) * 1000
        get_telemetry().record_llm_usage(
            provider=provider,
            model=model,
            prompt_tokens=ctx.get("prompt_tokens", 0),
            completion_tokens=ctx.get("completion_tokens", 0),
            latency_ms=latency_ms,
            success=ctx["success"],
            error=ctx["error"],
            project_id=project_id,
            chapter_id=chapter_id,
        )


@contextmanager
def track_tts_synthesis(
    provider: ProviderType,
    model: str,
    characters: int,
    project_id: Optional[int] = None,
    chapter_id: Optional[int] = None,
    voice: Optional[str] = None,
) -> Generator[Dict[str, Any], None, None]:
    """Context manager to track TTS synthesis."""
    start = time.perf_counter()
    ctx = {"success": True, "error": None}
    try:
        yield ctx
    except Exception as e:
        ctx["success"] = False
        ctx["error"] = str(e)
        raise
    finally:
        latency_ms = (time.perf_counter() - start) * 1000
        get_telemetry().record_tts_synthesis(
            provider=provider,
            model=model,
            characters=characters,
            latency_ms=latency_ms,
            success=ctx["success"],
            error=ctx["error"],
            project_id=project_id,
            chapter_id=chapter_id,
            voice=voice,
        )


@contextmanager
def track_pipeline_stage(
    stage: str,
    project_id: Optional[int] = None,
) -> Generator[Dict[str, Any], None, None]:
    """Context manager to track a pipeline stage."""
    start = time.perf_counter()
    ctx = {"success": True, "error": None, "metadata": {}}
    try:
        yield ctx
    except Exception as e:
        ctx["success"] = False
        ctx["error"] = str(e)
        raise
    finally:
        latency_ms = (time.perf_counter() - start) * 1000
        get_telemetry().record_pipeline_stage(
            stage=stage,
            latency_ms=latency_ms,
            success=ctx["success"],
            error=ctx["error"],
            project_id=project_id,
            metadata=ctx.get("metadata", {}),
        )


def record_cost_event(
    operation: OperationType,
    provider: ProviderType,
    model: str,
    **kwargs,
) -> CostRecord:
    """Convenience function to record a cost event directly.

    Args:
        operation: Type of operation
        provider: Provider used
        model: Model name
        **kwargs: Additional fields for CostRecord

    Returns:
        The created CostRecord
    """
    record = CostRecord(
        operation=operation,
        provider=provider,
        model=model,
        **kwargs,
    )
    get_telemetry()._add_record(record)

    # Emit Prometheus based on operation type
    if operation in (OperationType.LLM_CHAT, OperationType.LLM_EMBEDDING):
        get_telemetry()._emit_prometheus_llm(record)
    elif operation == OperationType.TTS_SYNTHESIS:
        chars = kwargs.get("metadata", {}).get("characters", 0)
        voice = kwargs.get("metadata", {}).get("voice")
        get_telemetry()._emit_prometheus_tts(record, chars, voice)
    elif operation == OperationType.PIPELINE_STAGE:
        get_telemetry()._emit_prometheus_pipeline(record)

    return record


if __name__ == "__main__":  # pragma: no cover
    # Demo usage
    import sys

    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    collector = TelemetryCollector()

    # Simulate some operations
    with track_llm_call(ProviderType.OPENAI, "gpt-4o-mini", project_id=1) as ctx:
        time.sleep(0.01)  # Simulate API call
        ctx["prompt_tokens"] = 100
        ctx["completion_tokens"] = 200

    with track_tts_synthesis(ProviderType.EDGE_TTS, "edge", 5000, project_id=1, voice="zh-CN-XiaoxiaoNeural"):
        time.sleep(0.01)

    with track_pipeline_stage("synthesize", project_id=1):
        time.sleep(0.01)

    summary = collector.get_summary()
    print(f"Total cost: ${summary.total_cost_usd:.6f}")
    print(f"Total tokens: {summary.total_tokens}")
    print(f"By provider: {summary.by_provider}")
    print(f"By operation: {summary.by_operation}")

    # Print Prometheus metrics
    print("\n--- Prometheus Metrics ---")
    print(collector.export_prometheus())