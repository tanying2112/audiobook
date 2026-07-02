"""OpenTelemetry metrics setup with Prometheus export."""

import logging
import os
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

    resource = Resource.create(
        {
            SERVICE_NAME: service_name,
            SERVICE_VERSION: service_version,
            "deployment.environment": os.getenv("DEPLOYMENT_ENV", "development"),
        }
    )

    # Set up Prometheus reader (exposes /metrics endpoint)
    prometheus_reader = PrometheusMetricReader(
        prefix="audiobook",
    )

    # Create meter provider
    _meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[prometheus_reader],
    )

    metrics.set_meter_provider(_meter_provider)

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


# Pre-defined SLO metrics for Audiobook Studio
def create_slo_metrics() -> Dict[str, Any]:
    """Create standard SLO metrics for the service.

    Returns:
        Dictionary of metric instruments
    """
    return {
        # Latency SLOs (ms)
        "http_request_duration": create_histogram(
            "http_request_duration_ms",
            "HTTP request latency in milliseconds",
            "ms",
            bucket_boundaries=[50, 100, 200, 500, 1000, 2000, 5000, 10000],
        ),
        "llm_request_duration": create_histogram(
            "llm_request_duration_ms",
            "LLM API request latency in milliseconds",
            "ms",
            bucket_boundaries=[100, 500, 1000, 2000, 5000, 10000, 30000, 60000],
        ),
        "tts_synthesis_duration": create_histogram(
            "tts_synthesis_duration_ms",
            "TTS synthesis latency in milliseconds",
            "ms",
            bucket_boundaries=[500, 1000, 2000, 5000, 10000, 30000],
        ),
        "pipeline_stage_duration": create_histogram(
            "pipeline_stage_duration_ms",
            "Pipeline stage execution latency in milliseconds",
            "ms",
            bucket_boundaries=[100, 500, 1000, 5000, 10000, 30000, 60000, 120000],
        ),
        # Error rate SLOs
        "http_requests_total": create_counter(
            "http_requests_total",
            "Total HTTP requests",
        ),
        "http_errors_total": create_counter(
            "http_errors_total",
            "Total HTTP errors (5xx)",
        ),
        "llm_errors_total": create_counter(
            "llm_errors_total",
            "Total LLM API errors",
        ),
        "pipeline_failures_total": create_counter(
            "pipeline_failures_total",
            "Total pipeline failures",
        ),
        # Quota/Cost SLOs
        "llm_tokens_used": create_counter(
            "llm_tokens_used_total",
            "Total LLM tokens consumed",
        ),
        "llm_cost_usd": create_counter(
            "llm_cost_usd_total",
            "Total LLM cost in USD",
        ),
        "tts_characters_used": create_counter(
            "tts_characters_used_total",
            "Total TTS characters synthesized",
        ),
        "free_tier_quota_remaining": create_gauge(
            "free_tier_quota_remaining",
            "Remaining free tier quota percentage",
            "percent",
        ),
        # Business metrics
        "books_processed_total": create_counter(
            "books_processed_total",
            "Total books processed",
        ),
        "chapters_synthesized_total": create_counter(
            "chapters_synthesized_total",
            "Total chapters synthesized",
        ),
        "quality_check_failures_total": create_counter(
            "quality_check_failures_total",
            "Total quality check failures",
        ),
        "regeneration_triggered_total": create_counter(
            "regeneration_triggered_total",
            "Total audio regenerations triggered",
        ),
    }


def shutdown_metrics() -> None:
    """Shutdown meter provider."""
    global _meter_provider
    if _meter_provider:
        _meter_provider.shutdown()
        _meter_provider = None
        logger.info("OpenTelemetry metrics shut down")
