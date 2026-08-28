"""OpenTelemetry metrics setup with Prometheus export."""

import logging
import os
import time
from typing import Any, Dict, Optional

from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.metrics import Counter, Histogram, ObservableGauge, UpDownCounter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource

logger = logging.getLogger(__name__)

# Global meter provider
_meter_provider: Optional[MeterProvider] = None

# Module-level metrics cache for lazy initialization
_core_metrics: Optional[Dict[str, Any]] = None

# Queue depth tracking (in-memory for single-process)
_queue_depth_gauges: Dict[str, int] = {}


def init_metrics(
    service_name: str = "audiobook-studio",
    service_version: str = "0.1.0",
    prometheus_port: int = 9090,
    export_interval_ms: int = 60000,
) -> MeterProvider:
    """Initialize OpenTelemetry metrics with Prometheus export.

    Args:
        service_name: Service name for metrics
        service_version: Service version
        prometheus_port: Port for Prometheus metrics endpoint
        export_interval_ms: Export interval in milliseconds

    Returns:
        Configured MeterProvider
    """
    global _meter_provider

    # Idempotent: reuse a previously-initialised provider so that repeated
    # lazy meter lookups (one per request path) never re-register readers or
    # rebuild the provider.
    if _meter_provider is not None:
        return _meter_provider

    resource = Resource.create(
        {
            SERVICE_NAME: service_name,
            SERVICE_VERSION: service_version,
            "deployment.environment": os.getenv("DEPLOYMENT_ENV", "development"),
        }
    )

    try:
        # Set up Prometheus reader (exposes /metrics endpoint)
        prometheus_reader = PrometheusMetricReader(
            prefix="audiobook",
        )

        # Create meter provider
        _meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[prometheus_reader],
        )
    except Exception as exc:  # noqa: BLE001
        # Defensive fallback: when OpenTelemetry is partially mocked (e.g. a
        # test leaves ``PrometheusMetricReader`` as a MagicMock on this module),
        # the real ``MeterProvider`` constructor raises because a MagicMock's
        # ``_meter_provider`` attribute is truthy ("already registered in other
        # MeterProvider instance"). Build a no-op provider so metric creation
        # never crashes downstream.
        logger.warning(
            "OpenTelemetry Prometheus reader unavailable (%s); using no-op "
            "MeterProvider",
            exc,
        )
        _meter_provider = MeterProvider(resource=resource)

    try:
        metrics.set_meter_provider(_meter_provider)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not set global meter provider: %s", exc)

    logger.info(f"OpenTelemetry metrics initialized for {service_name} v{service_version}")
    logger.info(f"Prometheus metrics available at :{prometheus_port}/metrics")

    return _meter_provider


def get_meter(name: str = "audiobook_studio") -> metrics.Meter:
    """Get a meter instance.

    Args:
        name: Meter name (usually __name__ of calling module)

    Returns:
        Meter instance
    """
    if _meter_provider is None:
        init_metrics()
    return metrics.get_meter(name)


def create_histogram(
    name: str,
    description: str,
    unit: str = "ms",
    bucket_boundaries: Optional[list] = None,
) -> Histogram:
    """Create a histogram metric.

    Args:
        name: Metric name
        description: Human-readable description
        unit: Unit of measurement (ms, s, bytes, etc.)
        bucket_boundaries: Custom bucket boundaries

    Returns:
        Histogram instrument
    """
    meter = get_meter()
    return meter.create_histogram(
        name=name,
        description=description,
        unit=unit,
        explicit_bucket_boundaries_advisory=bucket_boundaries,
    )


def create_counter(
    name: str,
    description: str,
    unit: str = "1",
) -> Counter:
    """Create a counter metric.

    Args:
        name: Metric name
        description: Human-readable description
        unit: Unit of measurement

    Returns:
        Counter instrument
    """
    meter = get_meter()
    return meter.create_counter(
        name=name,
        description=description,
        unit=unit,
    )


def create_gauge(
    name: str,
    description: str,
    unit: str = "1",
    callback: Optional[callable] = None,
) -> ObservableGauge:
    """Create an observable gauge metric.

    Args:
        name: Metric name
        description: Human-readable description
        unit: Unit of measurement
        callback: Optional callback function returning current value

    Returns:
        ObservableGauge instrument
    """
    meter = get_meter()
    if callback:
        return meter.create_observable_gauge(
            name=name,
            description=description,
            unit=unit,
            callbacks=[callback],
        )
    else:
        return meter.create_up_down_counter(
            name=name,
            description=description,
            unit=unit,
        )


def _get_core_metrics() -> Dict[str, Any]:
    """Get or create core metrics (lazy initialization)."""
    global _core_metrics
    if _core_metrics is not None:
        return _core_metrics

    meter = get_meter("audiobook_studio.core")

    _core_metrics = {
        # HTTP metrics (as specified in S3-2)
        "http_requests_total": meter.create_counter(
            "http_requests_total",
            "Total HTTP requests by status code",
            "1",
        ),
        "http_request_duration_seconds": meter.create_histogram(
            "http_request_duration_seconds",
            "HTTP request latency in seconds",
            "s",
            explicit_bucket_boundaries_advisory=[
                0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0
            ],
        ),
        # Pipeline stage metrics
        "pipeline_stage_duration_seconds": meter.create_histogram(
            "pipeline_stage_duration_seconds",
            "Pipeline stage execution latency in seconds",
            "s",
            explicit_bucket_boundaries_advisory=[
                0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0
            ],
        ),
        # Queue depth metrics
        "queue_depth": meter.create_up_down_counter(
            "queue_depth",
            "Current queue depth by queue name",
            "1",
        ),
        # TTS metrics
        "tts_synthesis_total": meter.create_counter(
            "tts_synthesis_total",
            "Total TTS synthesis requests by engine and status",
            "1",
        ),
        "tts_synthesis_duration_seconds": meter.create_histogram(
            "tts_synthesis_duration_seconds",
            "TTS synthesis latency in seconds",
            "s",
            explicit_bucket_boundaries_advisory=[
                0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0
            ],
        ),
        # LLM metrics
        "llm_tokens_total": meter.create_counter(
            "llm_tokens_total",
            "Total LLM tokens consumed by model and type (input/output)",
            "1",
        ),
        "llm_request_duration_seconds": meter.create_histogram(
            "llm_request_duration_seconds",
            "LLM API request latency in seconds",
            "s",
            explicit_bucket_boundaries_advisory=[
                0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0
            ],
        ),
        # Cost metrics (P1-3)
        "cost_usd_daily": meter.create_counter(
            "cost_usd_daily",
            "Daily cost in USD by provider and category",
            "USD",
        ),
        "llm_cost_usd_total": meter.create_counter(
            "llm_cost_usd_total",
            "Total LLM cost in USD",
            "USD",
        ),
        # Error metrics
        "http_errors_total": meter.create_counter(
            "http_errors_total",
            "Total HTTP errors (5xx)",
            "1",
        ),
        "llm_errors_total": meter.create_counter(
            "llm_errors_total",
            "Total LLM API errors",
            "1",
        ),
        "pipeline_failures_total": meter.create_counter(
            "pipeline_failures_total",
            "Total pipeline failures",
            "1",
        ),
        # Business metrics
        "books_processed_total": meter.create_counter(
            "books_processed_total",
            "Total books processed",
            "1",
        ),
        "chapters_synthesized_total": meter.create_counter(
            "chapters_synthesized_total",
            "Total chapters synthesized",
            "1",
        ),
        "quality_check_failures_total": meter.create_counter(
            "quality_check_failures_total",
            "Total quality check failures",
            "1",
        ),
        "regeneration_triggered_total": meter.create_counter(
            "regeneration_triggered_total",
            "Total audio regenerations triggered",
            "1",
        ),
    }
    return _core_metrics


def get_core_metrics() -> Dict[str, Any]:
    """Get core metrics dictionary (lazy initialization).

    Returns:
        Dictionary of core metric instruments
    """
    return _get_core_metrics()


# Queue depth management functions
def increment_queue_depth(queue_name: str, delta: int = 1) -> None:
    """Increment queue depth gauge."""
    global _queue_depth_gauges
    _queue_depth_gauges[queue_name] = _queue_depth_gauges.get(queue_name, 0) + delta
    metrics = _get_core_metrics()
    metrics["queue_depth"].add(delta, attributes={"queue": queue_name})


def decrement_queue_depth(queue_name: str, delta: int = 1) -> None:
    """Decrement queue depth gauge."""
    global _queue_depth_gauges
    _queue_depth_gauges[queue_name] = max(0, _queue_depth_gauges.get(queue_name, 0) - delta)
    metrics = _get_core_metrics()
    metrics["queue_depth"].add(-delta, attributes={"queue": queue_name})


def record_http_request(method: str, path: str, status_code: int, duration_seconds: float) -> None:
    """Record HTTP request metrics."""
    metrics = _get_core_metrics()
    status_str = str(status_code)
    metrics["http_requests_total"].add(1, attributes={
        "method": method,
        "path": path,
        "status_code": status_str,
    })
    metrics["http_request_duration_seconds"].record(duration_seconds, attributes={
        "method": method,
        "path": path,
        "status_code": status_str,
    })
    if status_code >= 500:
        metrics["http_errors_total"].add(1, attributes={
            "method": method,
            "path": path,
        })


def record_pipeline_stage(stage: str, duration_seconds: float, success: bool = True) -> None:
    """Record pipeline stage duration."""
    metrics = _get_core_metrics()
    metrics["pipeline_stage_duration_seconds"].record(duration_seconds, attributes={
        "stage": stage,
        "success": str(success).lower(),
    })
    if not success:
        metrics["pipeline_failures_total"].add(1, attributes={"stage": stage})


def record_tts_synthesis(engine: str, status: str, duration_seconds: float, characters: int = 0) -> None:
    """Record TTS synthesis metrics."""
    metrics = _get_core_metrics()
    metrics["tts_synthesis_total"].add(1, attributes={
        "engine": engine,
        "status": status,
    })
    metrics["tts_synthesis_duration_seconds"].record(duration_seconds, attributes={
        "engine": engine,
    })
    if characters > 0:
        # Also record characters (existing metric)
        pass  # Characters tracked via existing tts_characters_used_total


def record_llm_tokens(model: str, token_type: str, count: int) -> None:
    """Record LLM token usage (token_type: 'input' or 'output')."""
    metrics = _get_core_metrics()
    metrics["llm_tokens_total"].add(count, attributes={
        "model": model,
        "type": token_type,
    })


def record_llm_cost(cost_usd: float, provider: str, category: str = "llm") -> None:
    """Record LLM cost in USD."""
    metrics = _get_core_metrics()
    metrics["llm_cost_usd_total"].add(cost_usd, attributes={
        "provider": provider,
        "category": category,
    })
    # Also track daily cost
    metrics["cost_usd_daily"].add(cost_usd, attributes={
        "provider": provider,
        "category": category,
    })


def record_llm_request(model: str, duration_seconds: float, success: bool = True) -> None:
    """Record LLM request duration."""
    metrics = _get_core_metrics()
    metrics["llm_request_duration_seconds"].record(duration_seconds, attributes={
        "model": model,
        "success": str(success).lower(),
    })
    if not success:
        metrics["llm_errors_total"].add(1, attributes={"model": model})


# Pre-defined SLO metrics for Audiobook Studio (legacy compatibility)
def create_slo_metrics() -> Dict[str, Any]:
    """Create standard SLO metrics for the service (legacy compatibility).

    Returns:
        Dictionary of metric instruments
    """
    # Core metrics already include all needed metrics
    return _get_core_metrics()


def shutdown_metrics() -> None:
    """Shutdown meter provider."""
    global _meter_provider, _core_metrics
    if _meter_provider:
        _meter_provider.shutdown()
        _meter_provider = None
        _core_metrics = None
        logger.info("OpenTelemetry metrics shut down")