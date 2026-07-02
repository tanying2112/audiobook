"""OpenTelemetry observability setup for Audiobook Studio.

Provides distributed tracing, metrics, and logging instrumentation.
"""

from .instrumentation import instrument_app
from .metrics import create_counter, create_gauge, create_histogram, get_meter, init_metrics
from .tracing import get_tracer, init_tracing

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
