"""OpenTelemetry observability setup for Audiobook Studio.

Provides distributed tracing, metrics, and logging instrumentation.
"""

from .tracing import init_tracing, get_tracer
from .metrics import init_metrics, get_meter, create_histogram, create_counter, create_gauge
from .instrumentation import instrument_app

__all__ = [
    "init_tracing",
    "get_tracer",
    "init_metrics",
    "get_meter",
    "create_histogram",
    "create_counter",
    "create_gauge",
    "instrument_app",
]