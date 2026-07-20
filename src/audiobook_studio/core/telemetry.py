"""Telemetry & Cost Tracking Layer for Audiobook Studio.

Provides centralized cost tracking, token usage monitoring, latency metrics,
and Prometheus export for all LLM/TTS/pipeline operations.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Generator, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from prometheus_client import Counter, Gauge, Histogram, generate_latest

from ..config.settings import get_settings

logger = logging.getLogger(__name__)

# Default retention period for telemetry records (30 days)
DEFAULT_RETENTION_DAYS = int(os.getenv("TELEMETRY_RETENTION_DAYS", "30"))
# Default path for aggregated metrics summary
DEFAULT_SUMMARY_PATH = Path(os.getenv("TELEMETRY_SUMMARY_PATH", "storage/metrics_summary.json"))
# Default cron schedule for daily aggregation (02:00 UTC)
DEFAULT_AGGREGATION_CRON = os.getenv("TELEMETRY_AGGREGATION_CRON", "0 2 * * *")


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
                ["provider", "model", "type"],
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
        _prom_metrics["operation_duration_ms"].labels(operation=record.operation.value, **labels).observe(
            record.latency_ms
        )

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
        _prom_metrics["tts_cost_usd_total"].labels(provider=record.provider.value, model=record.model).inc(
            record.cost_usd
        )
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

    # -------------------------------------------------------------------------
    # TTL / Retention Management
    # -------------------------------------------------------------------------

    def cleanup_old_records(self, retention_days: Optional[int] = None) -> int:
        """Remove records older than retention period.

        Args:
            retention_days: Days to retain. Defaults to TELEMETRY_RETENTION_DAYS env var or 30 days.

        Returns:
            Number of records removed.
        """
        retention_days = retention_days or DEFAULT_RETENTION_DAYS
        cutoff = datetime.now() - timedelta(days=retention_days)

        with self._lock:
            original_count = len(self._records)
            self._records = [r for r in self._records if r.timestamp >= cutoff]
            removed = original_count - len(self._records)

        if removed > 0:
            logger.info(f"Telemetry cleanup: removed {removed} records older than {retention_days} days")
        return removed

    def aggregate_to_summary(
        self,
        output_path: Optional[Path] = None,
        retention_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Aggregate records older than retention period into a summary JSON file.

        This performs the TTL aggregation: detailed records older than retention_days
        are summarized into metrics_summary.json and then removed from memory.

        Args:
            output_path: Path for metrics_summary.json. Defaults to TELEMETRY_SUMMARY_PATH env var.
            retention_days: Days to retain detailed records. Defaults to TELEMETRY_RETENTION_DAYS env var.

        Returns:
            Aggregated summary dict (also written to output_path).
        """
        retention_days = retention_days or DEFAULT_RETENTION_DAYS
        output_path = output_path or DEFAULT_SUMMARY_PATH
        cutoff = datetime.now() - timedelta(days=retention_days)

        with self._lock:
            # Split records: old (to aggregate) vs recent (to keep)
            old_records = [r for r in self._records if r.timestamp < cutoff]
            recent_records = [r for r in self._records if r.timestamp >= cutoff]
            self._records = recent_records

        if not old_records:
            logger.info("No old telemetry records to aggregate")
            return {"aggregated": False, "records_aggregated": 0}

        # Aggregate old records
        summary = CostSummary()
        for r in old_records:
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

        # Load existing summary if exists, merge with new
        existing_summary = {}
        if output_path.exists():
            try:
                existing_summary = json.loads(output_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Could not read existing summary at {output_path}: {e}")

        merged_summary = self._merge_summaries(existing_summary, summary)

        # Add aggregation metadata
        merged_summary["last_aggregated"] = datetime.now().isoformat()
        merged_summary["records_aggregated_this_run"] = len(old_records)
        merged_summary["retention_days"] = retention_days

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write merged summary
        output_path.write_text(json.dumps(merged_summary, indent=2, ensure_ascii=False), encoding="utf-8")

        logger.info(f"Telemetry aggregation: {len(old_records)} records aggregated to {output_path}")
        return merged_summary

    def _merge_summaries(self, existing: Dict[str, Any], new: CostSummary) -> Dict[str, Any]:
        """Merge two summary dicts (existing + new aggregation)."""
        if not existing:
            return {
                "total_cost_usd": new.total_cost_usd,
                "total_tokens": new.total_tokens,
                "total_operations": new.total_operations,
                "by_provider": new.by_provider,
                "by_operation": new.by_operation,
                "by_model": new.by_model,
                "errors": new.errors,
                "retries": new.retries,
            }

        # Deep merge
        merged = existing.copy()
        merged["total_cost_usd"] = merged.get("total_cost_usd", 0) + new.total_cost_usd
        merged["total_tokens"] = merged.get("total_tokens", 0) + new.total_tokens
        merged["total_operations"] = merged.get("total_operations", 0) + new.total_operations
        merged["errors"] = merged.get("errors", 0) + new.errors
        merged["retries"] = merged.get("retries", 0) + new.retries

        # Merge by_provider
        for prov, data in new.by_provider.items():
            if prov not in merged["by_provider"]:
                merged["by_provider"][prov] = {"cost": 0.0, "tokens": 0, "ops": 0}
            merged["by_provider"][prov]["cost"] += data["cost"]
            merged["by_provider"][prov]["tokens"] += data["tokens"]
            merged["by_provider"][prov]["ops"] += data["ops"]

        # Merge by_operation
        for op, data in new.by_operation.items():
            if op not in merged["by_operation"]:
                merged["by_operation"][op] = {"cost": 0.0, "tokens": 0, "ops": 0}
            merged["by_operation"][op]["cost"] += data["cost"]
            merged["by_operation"][op]["tokens"] += data["tokens"]
            merged["by_operation"][op]["ops"] += data["ops"]

        # Merge by_model
        for model, data in new.by_model.items():
            if model not in merged["by_model"]:
                merged["by_model"][model] = {"cost": 0.0, "tokens": 0, "ops": 0}
            merged["by_model"][model]["cost"] += data["cost"]
            merged["by_model"][model]["tokens"] += data["tokens"]
            merged["by_model"][model]["ops"] += data["ops"]

        return merged

    def run_daily_aggregation(self) -> Dict[str, Any]:
        """Run the daily aggregation job (cleanup + aggregate to summary).

        This is the main entry point for the daily cron/scheduler job.
        """
        logger.info("Starting daily telemetry aggregation job")
        # First aggregate old records to summary
        summary = self.aggregate_to_summary()
        # Then clean up any remaining old records (belt-and-suspenders)
        removed = self.cleanup_old_records()
        return {
            "aggregation": summary,
            "cleanup_removed": removed,
            "timestamp": datetime.now().isoformat(),
        }

    # -------------------------------------------------------------------------
    # Scheduler Integration (APScheduler)
    # -------------------------------------------------------------------------

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._records: list[CostRecord] = []
        self._lock = threading.Lock()
        self._session_start = datetime.now()
        self._scheduler: Optional[BackgroundScheduler] = None
        _init_prometheus_metrics()

    def start_scheduler(
        self,
        cron_expression: Optional[str] = None,
        retention_days: Optional[int] = None,
        summary_path: Optional[Path] = None,
    ) -> None:
        """Start the background scheduler for daily telemetry aggregation.

        Args:
            cron_expression: Cron expression for daily run. Defaults to TELEMETRY_AGGREGATION_CRON env var or "0 2 * * *" (02:00 UTC).
            retention_days: Retention period. Defaults to TELEMETRY_RETENTION_DAYS env var or 30 days.
            summary_path: Output path for metrics_summary.json. Defaults to TELEMETRY_SUMMARY_PATH env var.
        """
        if self._scheduler and self._scheduler.running:
            logger.warning("Telemetry scheduler already running")
            return

        cron_expression = cron_expression or DEFAULT_AGGREGATION_CRON
        retention_days = retention_days or DEFAULT_RETENTION_DAYS
        summary_path = summary_path or DEFAULT_SUMMARY_PATH

        self._scheduler = BackgroundScheduler(daemon=True)
        self._scheduler.add_job(
            func=lambda: self.aggregate_to_summary(summary_path, retention_days),
            trigger=CronTrigger.from_crontab(cron_expression),
            id="telemetry_daily_aggregation",
            name="Daily Telemetry Aggregation",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            f"Telemetry scheduler started: cron='{cron_expression}', retention={retention_days}d, summary={summary_path}"
        )

    def stop_scheduler(self) -> None:
        """Stop the background scheduler."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("Telemetry scheduler stopped")

    def is_scheduler_running(self) -> bool:
        """Check if scheduler is running."""
        return self._scheduler is not None and self._scheduler.running


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
