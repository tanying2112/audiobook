"""
Commercial Telemetry Collector for Audiobook Pipeline

Generates metrics_summary.json at pipeline completion capturing:
1. Cost Accounting: Prompt/Completion tokens per provider, calculated billing
2. Latency Profiles: Wall time per stage, synthesis rate ratio
3. Resilience Metrics: Retry counts, fallback occurrences
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from src.audiobook_studio.storage import reports_dir

if TYPE_CHECKING:
    from ..llm import LLMRouter
    from ..pipeline.orchestrator import PipelineHooks, PipelineStage
else:
    # Runtime: use string references to avoid circular imports
    PipelineHooks = object
    PipelineStage = str
    LLMRouter = object

from ..llm import create_router

logger = logging.getLogger(__name__)


@dataclass
class StageTiming:
    """Wall-clock timing for a pipeline stage."""

    stage: str
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None

    @property
    def is_complete(self) -> bool:
        return self.end_time > 0


@dataclass
class ProviderMetrics:
    """Aggregated metrics per LLM/TTS provider."""

    provider: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    call_count: int = 0
    total_latency_ms: float = 0.0
    retry_count: int = 0
    fallback_count: int = 0
    fallback_from: list[str] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0

    def record_call(
        self,
        tokens_in: int,
        tokens_out: int,
        cost: float,
        latency_ms: float,
        success: bool,
        is_retry: bool = False,
        is_fallback: bool = False,
        fallback_from: Optional[str] = None,
    ) -> None:
        """Record a single API call."""
        self.prompt_tokens += tokens_in
        self.completion_tokens += tokens_out
        self.total_tokens += tokens_in + tokens_out
        self.cost_usd += cost
        self.call_count += 1
        self.total_latency_ms += latency_ms
        if is_retry:
            self.retry_count += 1
        if is_fallback and fallback_from:
            self.fallback_count += 1
            self.fallback_from.append(fallback_from)
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.call_count if self.call_count > 0 else 0.0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0


@dataclass
class TTSMetrics:
    """Aggregated TTS synthesis metrics."""

    total_audio_duration_ms: float = 0.0
    total_synthesis_latency_ms: float = 0.0
    total_segments: int = 0
    successful_segments: int = 0
    failed_segments: int = 0
    retry_count: int = 0
    fallback_count: int = 0
    fallback_from: list[str] = field(default_factory=list)
    provider_breakdown: dict[str, dict] = field(default_factory=dict)
    quality_checks_passed: int = 0
    quality_checks_failed: int = 0

    def record_segment(
        self,
        duration_ms: float,
        latency_ms: float,
        provider: str,
        success: bool,
        is_retry: bool = False,
        is_fallback: bool = False,
        fallback_from: Optional[str] = None,
    ) -> None:
        """Record a synthesized segment."""
        self.total_audio_duration_ms += duration_ms
        self.total_synthesis_latency_ms += latency_ms
        self.total_segments += 1
        if success:
            self.successful_segments += 1
        else:
            self.failed_segments += 1
        if is_retry:
            self.retry_count += 1
        if is_fallback and fallback_from:
            self.fallback_count += 1
            self.fallback_from.append(fallback_from)

        # Track per-provider
        if provider not in self.provider_breakdown:
            self.provider_breakdown[provider] = {
                "segments": 0,
                "audio_duration_ms": 0.0,
                "synthesis_latency_ms": 0.0,
                "cost_usd": 0.0,
                "retries": 0,
                "fallbacks": 0,
            }
        pb = self.provider_breakdown[provider]
        pb["segments"] += 1
        pb["audio_duration_ms"] += duration_ms
        pb["synthesis_latency_ms"] += latency_ms

    @property
    def synthesis_rate_ratio(self) -> float:
        """Audio Duration / Processing Time ratio. Higher is better (real-time factor)."""
        if self.total_synthesis_latency_ms <= 0:
            return 0.0
        return self.total_audio_duration_ms / self.total_synthesis_latency_ms

    @property
    def real_time_factor(self) -> float:
        """Processing Time / Audio Duration. < 1.0 means faster than real-time."""
        if self.total_audio_duration_ms <= 0:
            return 0.0
        return self.total_synthesis_latency_ms / self.total_audio_duration_ms


@dataclass
class PipelineTelemetry:
    """Complete pipeline telemetry snapshot."""

    project_id: str
    pipeline_id: str
    started_at: float
    ended_at: float = 0.0
    duration_ms: float = 0.0
    success: bool = False
    error: Optional[str] = None

    # Stage timings
    stage_timings: dict[str, StageTiming] = field(default_factory=dict)

    # LLM Provider metrics
    llm_providers: dict[str, ProviderMetrics] = field(default_factory=dict)

    # TTS metrics
    tts_metrics: TTSMetrics = field(default_factory=TTSMetrics)

    # Cost summary
    total_llm_cost_usd: float = 0.0
    total_tts_cost_usd: float = 0.0

    @property
    def total_cost_usd(self) -> float:
        return self.total_llm_cost_usd + self.total_tts_cost_usd

    @property
    def stage_order(self) -> list[str]:
        """Stages in execution order."""
        return [
            "extract",
            "analyze",
            "annotate",
            "edit",
            "synthesize",
            "quality_check",
            "export",
        ]


class TelemetryCollector(PipelineHooks):
    """
    Pipeline telemetry collector that hooks into the orchestrator lifecycle.

    Registers as a PipelineHooks implementation to capture:
    - pipeline_start / pipeline_end
    - stage_enter / stage_exit for wall-clock timing
    - Aggregates LLM metrics from LLMRouter
    - Aggregates TTS metrics from SynthesizePipeline
    - Computes synthesis rate ratio (audio_duration / processing_time)
    - Tracks retries and fallbacks from both LLM router and TTS circuit breaker
    - Writes metrics_summary.json at pipeline completion
    """

    def __init__(
        self,
        project_id: str,
        pipeline_id: Optional[str] = None,
        output_dir: Optional[str] = None,
        llm_router: Optional[LLMRouter] = None,
        synthesize_pipeline: Optional[Any] = None,
    ):
        """
        Initialize telemetry collector.

        Args:
            project_id: Project/book identifier
            pipeline_id: Unique pipeline run ID (auto-generated if not provided)
            output_dir: Output directory for metrics_summary.json (defaults to project output)
            llm_router: Optional LLMRouter instance to pull metrics from
            synthesize_pipeline: Optional SynthesizePipeline instance to pull TTS metrics from
        """
        self.project_id = project_id
        self.pipeline_id = pipeline_id or f"{project_id}_{int(time.time() * 1000)}"
        self.output_dir = Path(output_dir) if output_dir else None
        self.llm_router = llm_router or create_router()
        self.synthesize_pipeline = synthesize_pipeline

        # Pipeline telemetry state
        self.telemetry = PipelineTelemetry(
            project_id=project_id,
            pipeline_id=self.pipeline_id,
            started_at=time.time(),
        )

        # Active stage tracking
        self._current_stage: Optional[str] = None
        self._stage_start_time: float = 0.0

        # Thread safety
        self._lock = threading.Lock()

        # TTS retry/fallback tracking (from synthesize pipeline)
        self._tts_retry_count = 0
        self._tts_fallback_count = 0
        self._tts_fallback_from: list[str] = []

        logger.info(f"TelemetryCollector initialized for project={project_id}, pipeline={self.pipeline_id}")

    # ========== PipelineHooks Implementation ==========

    def on_pipeline_start(
        self, event: str, context: dict[str, Any], result: Any = None, error: Exception | None = None
    ) -> None:
        """Called when pipeline starts. Matches orchestrator hook signature."""
        if event != "pipeline_start":
            return
        with self._lock:
            self.telemetry.started_at = time.time()
            # Update project_id from context if available
            if context.get("project_id"):
                self.telemetry.project_id = context["project_id"]
                self.project_id = context["project_id"]
            # Always use canonical reports directory (aligned with monitoring API)
            # Ignore context["output_dir"] to prevent path mismatch
            self.output_dir = reports_dir(int(self.project_id), ensure=True)
            logger.debug(f"Pipeline started: {self.pipeline_id}")

    def on_pipeline_end(
        self, event: str, context: dict[str, Any], result: Any = None, error: Exception | None = None
    ) -> None:
        """Called when pipeline completes (success or failure). Matches orchestrator hook signature."""
        if event != "pipeline_end":
            return
        with self._lock:
            self.telemetry.ended_at = time.time()
            self.telemetry.duration_ms = (self.telemetry.ended_at - self.telemetry.started_at) * 1000
            self.telemetry.success = error is None
            self.telemetry.error = str(error) if error else None

            # Aggregate LLM metrics from router
            self._aggregate_llm_metrics()

            # Aggregate TTS metrics from synthesize pipeline
            self._aggregate_tts_metrics()

            # Write metrics summary
            self._write_metrics_summary()

            logger.info(
                f"Pipeline completed: {self.pipeline_id}, "
                f"success={self.telemetry.success}, "
                f"duration={self.telemetry.duration_ms:.0f}ms, "
                f"cost=${self.telemetry.total_cost_usd:.4f}"
            )

    def on_stage_enter(
        self, event: str, stage: str, context: dict[str, Any], result: Any = None, error: Exception | None = None
    ) -> None:
        """Called when a pipeline stage starts. Matches orchestrator hook signature."""
        if event != "stage_enter":
            return
        with self._lock:
            self._current_stage = stage
            self._stage_start_time = time.time()

            # Initialize stage timing
            self.telemetry.stage_timings[stage] = StageTiming(
                stage=stage,
                start_time=self._stage_start_time,
            )
            logger.debug(f"Stage entered: {stage}")

    def on_stage_exit(
        self, event: str, stage: str, context: dict[str, Any], result: Any = None, error: Exception | None = None
    ) -> None:
        """Called when a pipeline stage completes. Matches orchestrator hook signature."""
        if event != "stage_exit":
            return
        with self._lock:
            end_time = time.time()
            duration_ms = (end_time - self._stage_start_time) * 1000

            if stage in self.telemetry.stage_timings:
                timing = self.telemetry.stage_timings[stage]
                timing.end_time = end_time
                timing.duration_ms = duration_ms
                timing.success = error is None
                timing.error = str(error) if error else None

            self._current_stage = None
            self._stage_start_time = 0.0
            logger.debug(f"Stage exited: {stage}, duration={duration_ms:.0f}ms")

    # ========== Metrics Aggregation ==========

    def _aggregate_llm_metrics(self) -> None:
        """Aggregate LLM metrics from the router's CostTracker."""
        try:
            cost_tracker = getattr(self.llm_router, "cost_tracker", None)
            if not cost_tracker:
                logger.debug("No cost tracker available on router")
                return

            # Get daily costs per model (this tracks daily totals)
            # We also need per-call metrics - check if router has call history
            call_history = getattr(self.llm_router, "_call_history", [])
            if not call_history:
                # Check if CostTracker has more detailed data - use get_status()
                status = cost_tracker.get_status()
                for model, info in status.items():
                    cost = info.get("daily_cost_usd", 0.0)
                    # We can't break down per-provider from daily totals alone
                    # But we can at least record the total
                    provider = self._provider_from_model(model)
                    if provider not in self.telemetry.llm_providers:
                        self.telemetry.llm_providers[provider] = ProviderMetrics(provider=provider, model=model)
                    self.telemetry.llm_providers[provider].cost_usd += cost
                return

            # If we have call history, aggregate detailed metrics
            for call in call_history:
                provider = call.get("provider", "unknown")
                model = call.get("model", "unknown")
                tokens_in = call.get("tokens_in", 0)
                tokens_out = call.get("tokens_out", 0)
                cost = call.get("cost_usd", 0.0)
                latency = call.get("latency_ms", 0.0)
                success = call.get("success", True)
                is_retry = call.get("is_retry", False)
                is_fallback = call.get("is_fallback", False)
                fallback_from = call.get("fallback_from")

                key = f"{provider}:{model}"
                if key not in self.telemetry.llm_providers:
                    self.telemetry.llm_providers[key] = ProviderMetrics(provider=provider, model=model)

                self.telemetry.llm_providers[key].record_call(
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost=cost,
                    latency_ms=latency,
                    success=success,
                    is_retry=is_retry,
                    is_fallback=is_fallback,
                    fallback_from=fallback_from,
                )

            # Sum up total LLM cost
            self.telemetry.total_llm_cost_usd = sum(p.cost_usd for p in self.telemetry.llm_providers.values())

        except Exception as e:
            logger.warning(f"Failed to aggregate LLM metrics: {e}")

    def _aggregate_tts_metrics(self) -> None:
        """Aggregate TTS metrics from the synthesize pipeline."""
        try:
            if not self.synthesize_pipeline:
                # Try to get from context if available
                logger.debug("No synthesize pipeline available for TTS metrics")
                return

            # Check for quality report which has segment info
            output_dir = getattr(self.synthesize_pipeline, "output_dir", None)
            if output_dir:
                quality_report_path = Path(output_dir) / "quality_report.json"
                if quality_report_path.exists():
                    import json

                    with open(quality_report_path, "r") as f:
                        quality_report = json.load(f)

                    self.telemetry.tts_metrics.quality_checks_passed = quality_report.get("passed_segments", 0)
                    self.telemetry.tts_metrics.quality_checks_failed = quality_report.get("failed_segments", 0)

            # Aggregate from existing segments
            existing_segments = getattr(self.synthesize_pipeline, "existing_segments", {})
            for segment in existing_segments.values():
                provider = getattr(segment, "engine", "unknown")
                duration_ms = getattr(segment, "duration_ms", 0)
                # We don't have latency per segment unless tracked separately
                # Estimate from synthesis time if available
                self.telemetry.tts_metrics.record_segment(
                    duration_ms=duration_ms,
                    latency_ms=duration_ms * 0.1,  # rough estimate
                    provider=provider,
                    success=True,
                )

            # Try to get cost from TTS metrics if available
            # (synthesize.py already records cost estimates in record_stage_performance)

        except Exception as e:
            logger.warning(f"Failed to aggregate TTS metrics: {e}")

    def _provider_from_model(self, model: str) -> str:
        """Infer provider from model name."""
        model_lower = model.lower()
        if "gpt" in model_lower or "openai" in model_lower:
            return "openai"
        elif "deepseek" in model_lower:
            return "deepseek"
        elif "claude" in model_lower or "anthropic" in model_lower:
            return "anthropic"
        elif "gemma" in model_lower or "ollama" in model_lower:
            return "ollama"
        elif "kokoro" in model_lower:
            return "kokoro"
        elif "edge" in model_lower:
            return "edge"
        elif "azure" in model_lower:
            return "azure"
        elif "gcp" in model_lower or "google" in model_lower:
            return "gcp"
        elif "voxcpm" in model_lower:
            return "voxcpm2"
        return "unknown"

    def _write_metrics_summary(self) -> None:
        """Write metrics_summary.json to output directory."""
        try:
            if not self.output_dir:
                # Use canonical reports directory (aligned with monitoring API)
                self.output_dir = reports_dir(int(self.project_id), ensure=True)

            self.output_dir.mkdir(parents=True, exist_ok=True)
            output_path = self.output_dir / "metrics_summary.json"

            # Build summary dict
            summary = {
                "metadata": {
                    "project_id": self.telemetry.project_id,
                    "pipeline_id": self.telemetry.pipeline_id,
                    "started_at": datetime.fromtimestamp(self.telemetry.started_at).isoformat(),
                    "ended_at": (
                        datetime.fromtimestamp(self.telemetry.ended_at).isoformat() if self.telemetry.ended_at else None
                    ),
                    "duration_ms": self.telemetry.duration_ms,
                    "success": self.telemetry.success,
                    "error": self.telemetry.error,
                },
                "cost_accounting": {
                    "total_cost_usd": round(self.telemetry.total_cost_usd, 6),
                    "llm_cost_usd": round(self.telemetry.total_llm_cost_usd, 6),
                    "tts_cost_usd": round(self.telemetry.total_tts_cost_usd, 6),
                    "providers": {},
                },
                "latency_profiles": {
                    "stage_wall_times_ms": {},
                    "synthesis_rate_ratio": round(self.telemetry.tts_metrics.synthesis_rate_ratio, 4),
                    "real_time_factor": round(self.telemetry.tts_metrics.real_time_factor, 4),
                    "total_audio_duration_ms": self.telemetry.tts_metrics.total_audio_duration_ms,
                    "total_synthesis_latency_ms": self.telemetry.tts_metrics.total_synthesis_latency_ms,
                },
                "resilience_metrics": {
                    "llm": {
                        "total_calls": sum(p.call_count for p in self.telemetry.llm_providers.values()),
                        "total_retries": sum(p.retry_count for p in self.telemetry.llm_providers.values()),
                        "total_fallbacks": sum(p.fallback_count for p in self.telemetry.llm_providers.values()),
                        "fallback_details": [],
                    },
                    "tts": {
                        "total_segments": self.telemetry.tts_metrics.total_segments,
                        "successful_segments": self.telemetry.tts_metrics.successful_segments,
                        "failed_segments": self.telemetry.tts_metrics.failed_segments,
                        "retries": self.telemetry.tts_metrics.retry_count,
                        "fallbacks": self.telemetry.tts_metrics.fallback_count,
                        "fallback_from": self.telemetry.tts_metrics.fallback_from,
                    },
                },
                "stage_timings": {},
            }

            # Provider breakdown
            for key, provider in self.telemetry.llm_providers.items():
                summary["cost_accounting"]["providers"][key] = {
                    "provider": provider.provider,
                    "model": provider.model,
                    "prompt_tokens": provider.prompt_tokens,
                    "completion_tokens": provider.completion_tokens,
                    "total_tokens": provider.total_tokens,
                    "cost_usd": round(provider.cost_usd, 6),
                    "call_count": provider.call_count,
                    "avg_latency_ms": round(provider.avg_latency_ms, 2),
                    "retry_count": provider.retry_count,
                    "fallback_count": provider.fallback_count,
                    "fallback_from": provider.fallback_from,
                    "success_rate": round(provider.success_rate, 4),
                }
                # Add fallback details
                for fb in provider.fallback_from:
                    summary["resilience_metrics"]["llm"]["fallback_details"].append(
                        {
                            "from": fb,
                            "to": provider.provider,
                            "model": provider.model,
                        }
                    )

            # TTS provider breakdown
            for provider, metrics in self.telemetry.tts_metrics.provider_breakdown.items():
                if provider not in summary["cost_accounting"]["providers"]:
                    summary["cost_accounting"]["providers"][provider] = {}
                summary["cost_accounting"]["providers"][provider].update(
                    {
                        "tts_segments": metrics.get("segments", 0),
                        "tts_audio_duration_ms": metrics.get("audio_duration_ms", 0),
                        "tts_synthesis_latency_ms": metrics.get("synthesis_latency_ms", 0),
                        "tts_retries": metrics.get("retries", 0),
                        "tts_fallbacks": metrics.get("fallbacks", 0),
                    }
                )

            # Stage timings
            for stage in self.telemetry.stage_order:
                if stage in self.telemetry.stage_timings:
                    timing = self.telemetry.stage_timings[stage]
                    summary["latency_profiles"]["stage_wall_times_ms"][stage] = {
                        "duration_ms": round(timing.duration_ms, 2),
                        "success": timing.success,
                        "error": timing.error,
                    }

            # Write JSON
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)

            logger.info(f"Metrics summary written to {output_path}")

        except Exception as e:
            logger.error(f"Failed to write metrics summary: {e}")

    # ========== Public API for External Metric Recording ==========

    def record_llm_call(
        self,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        latency_ms: float,
        success: bool = True,
        is_retry: bool = False,
        is_fallback: bool = False,
        fallback_from: Optional[str] = None,
    ) -> None:
        """Record an LLM API call (can be called directly from router)."""
        with self._lock:
            key = f"{provider}:{model}"
            if key not in self.telemetry.llm_providers:
                self.telemetry.llm_providers[key] = ProviderMetrics(provider=provider, model=model)

            self.telemetry.llm_providers[key].record_call(
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost=cost_usd,
                latency_ms=latency_ms,
                success=success,
                is_retry=is_retry,
                is_fallback=is_fallback,
                fallback_from=fallback_from,
            )

    def record_tts_segment(
        self,
        duration_ms: float,
        latency_ms: float,
        provider: str,
        cost_usd: float = 0.0,
        success: bool = True,
        is_retry: bool = False,
        is_fallback: bool = False,
        fallback_from: Optional[str] = None,
    ) -> None:
        """Record a TTS synthesis segment (can be called directly from synthesize pipeline)."""
        with self._lock:
            self.telemetry.tts_metrics.record_segment(
                duration_ms=duration_ms,
                latency_ms=latency_ms,
                provider=provider,
                success=success,
                is_retry=is_retry,
                is_fallback=is_fallback,
                fallback_from=fallback_from,
            )
            if cost_usd > 0:
                self.telemetry.total_tts_cost_usd += cost_usd
                # Update provider breakdown
                if provider not in self.telemetry.tts_metrics.provider_breakdown:
                    self.telemetry.tts_metrics.provider_breakdown[provider] = {
                        "segments": 0,
                        "audio_duration_ms": 0.0,
                        "synthesis_latency_ms": 0.0,
                        "cost_usd": 0.0,
                        "retries": 0,
                        "fallbacks": 0,
                    }
                self.telemetry.tts_metrics.provider_breakdown[provider]["cost_usd"] += cost_usd

    def record_tts_quality_check(self, passed: bool) -> None:
        """Record a TTS quality check result."""
        with self._lock:
            if passed:
                self.telemetry.tts_metrics.quality_checks_passed += 1
            else:
                self.telemetry.tts_metrics.quality_checks_failed += 1

    def record_tts_retry(self, fallback_from: Optional[str] = None) -> None:
        """Record a TTS retry (e.g., quality gate retry)."""
        with self._lock:
            self.telemetry.tts_metrics.retry_count += 1
            if fallback_from:
                self.telemetry.tts_metrics.fallback_from.append(fallback_from)

    def record_tts_fallback(self, fallback_from: str) -> None:
        """Record a TTS fallback (e.g., circuit breaker triggered)."""
        with self._lock:
            self.telemetry.tts_metrics.fallback_count += 1
            self.telemetry.tts_metrics.fallback_from.append(fallback_from)

    def get_summary(self) -> dict[str, Any]:
        """Get current telemetry summary (without writing to disk)."""
        with self._lock:
            # Create a summary similar to _write_metrics_summary but without writing
            return {
                "project_id": self.telemetry.project_id,
                "pipeline_id": self.telemetry.pipeline_id,
                "duration_ms": (
                    (time.time() - self.telemetry.started_at) * 1000
                    if self.telemetry.ended_at == 0
                    else self.telemetry.duration_ms
                ),
                "total_cost_usd": self.telemetry.total_cost_usd,
                "stage_timings": {
                    stage: {
                        "duration_ms": timing.duration_ms,
                        "success": timing.success,
                    }
                    for stage, timing in self.telemetry.stage_timings.items()
                    if timing.is_complete
                },
                "synthesis_rate_ratio": self.telemetry.tts_metrics.synthesis_rate_ratio,
            }


# ========== Convenience Functions ==========

_global_collector: Optional[TelemetryCollector] = None
_global_lock = threading.Lock()


def get_telemetry_collector() -> Optional[TelemetryCollector]:
    """Get the global telemetry collector instance."""
    global _global_collector
    with _global_lock:
        return _global_collector


def init_telemetry_collector(
    project_id: str,
    pipeline_id: Optional[str] = None,
    output_dir: Optional[str] = None,
    llm_router: Optional[LLMRouter] = None,
    synthesize_pipeline: Optional[Any] = None,
) -> TelemetryCollector:
    """Initialize the global telemetry collector."""
    global _global_collector
    with _global_lock:
        _global_collector = TelemetryCollector(
            project_id=project_id,
            pipeline_id=pipeline_id,
            output_dir=output_dir,
            llm_router=llm_router,
            synthesize_pipeline=synthesize_pipeline,
        )
        return _global_collector


def record_llm_call(
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    latency_ms: float,
    success: bool = True,
    is_retry: bool = False,
    is_fallback: bool = False,
    fallback_from: Optional[str] = None,
) -> None:
    """Record an LLM call to the global telemetry collector."""
    collector = get_telemetry_collector()
    if collector:
        collector.record_llm_call(
            provider=provider,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            success=success,
            is_retry=is_retry,
            is_fallback=is_fallback,
            fallback_from=fallback_from,
        )


def record_tts_segment(
    duration_ms: float,
    latency_ms: float,
    provider: str,
    cost_usd: float = 0.0,
    success: bool = True,
    is_retry: bool = False,
    is_fallback: bool = False,
    fallback_from: Optional[str] = None,
) -> None:
    """Record a TTS segment to the global telemetry collector."""
    collector = get_telemetry_collector()
    if collector:
        collector.record_tts_segment(
            duration_ms=duration_ms,
            latency_ms=latency_ms,
            provider=provider,
            cost_usd=cost_usd,
            success=success,
            is_retry=is_retry,
            is_fallback=is_fallback,
            fallback_from=fallback_from,
        )


def record_tts_retry(fallback_from: Optional[str] = None) -> None:
    """Record a TTS retry to the global telemetry collector."""
    collector = get_telemetry_collector()
    if collector:
        collector.record_tts_retry(fallback_from=fallback_from)


def record_tts_fallback(fallback_from: str) -> None:
    """Record a TTS fallback to the global telemetry collector."""
    collector = get_telemetry_collector()
    if collector:
        collector.record_tts_fallback(fallback_from=fallback_from)


def record_tts_quality_check(passed: bool) -> None:
    """Record a TTS quality check result to the global telemetry collector."""
    collector = get_telemetry_collector()
    if collector:
        collector.record_tts_quality_check(passed=passed)


def shutdown_telemetry() -> None:
    """Shutdown the global telemetry collector."""
    global _global_collector
    with _global_lock:
        if _global_collector:
            _global_collector = None
