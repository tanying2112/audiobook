"""FastAPI instrumentation and middleware for observability."""

import logging
import time
from functools import wraps
from typing import Callable, Optional

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.metrics import Counter, Histogram
from opentelemetry.trace import Status, StatusCode

from .metrics import create_counter, create_histogram, get_meter
from .tracing import get_tracer

logger = logging.getLogger(__name__)

# Global metrics instruments
_http_duration: Optional[Histogram] = None
_http_requests: Optional[Counter] = None
_http_errors: Optional[Counter] = None


def _get_http_metrics():
    """Get or create HTTP metrics instruments."""
    global _http_duration, _http_requests, _http_errors
    if _http_duration is None:
        meter = get_meter("audiobook_studio.http")
        _http_duration = meter.create_histogram(
            "http_request_duration_ms",
            "HTTP request latency in milliseconds",
            "ms",
            explicit_bucket_boundaries_advisory=[
                50,
                100,
                200,
                500,
                1000,
                2000,
                5000,
                10000,
            ],
        )
        _http_requests = meter.create_counter(
            "http_requests_total",
            "Total HTTP requests",
            "1",
        )
        _http_errors = meter.create_counter(
            "http_errors_total",
            "Total HTTP errors (5xx)",
            "1",
        )
    return _http_duration, _http_requests, _http_errors


class ObservabilityMiddleware:
    """Pure ASGI middleware for HTTP request tracing and metrics.

    Replaces the deprecated BaseHTTPMiddleware subclass that is incompatible
    with Python 3.14 + Starlette 0.37+.
    """

    def __init__(self, app, exclude_paths: Optional[list] = None):
        self.app = app
        self.exclude_paths = exclude_paths or [
            "/health",
            "/metrics",
            "/docs",
            "/openapi.json",
            "/redoc",
        ]
        self.tracer = get_tracer("audiobook_studio.http")

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Parse request from scope without slow body consumption
        from starlette.datastructures import Headers as _Headers
        from starlette.requests import Request as _Request

        # Build a lightweight request representation for path/method/header access
        scope_headers = _Headers(scope=scope)
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        scheme = scope.get("scheme", "http")
        server = scope.get("server")
        hostname = (server[0] if server else "") if server else ""

        # Skip excluded paths
        if path in self.exclude_paths:
            await self.app(scope, receive, send)
            return

        # Start trace span
        span_name = f"{method} {path}"
        with self.tracer.start_as_current_span(span_name) as span:
            span.set_attribute("http.method", method)
            span.set_attribute("http.url", f"{scheme}://{hostname}{path}")
            span.set_attribute("http.scheme", scheme)
            span.set_attribute("http.host", hostname)
            span.set_attribute("http.target", path)
            span.set_attribute("http.user_agent", scope_headers.get("user-agent", ""))

            start_time = time.perf_counter()

            # Wrap send to capture response status and body
            status_code: list = []
            body_chunks: list = []

            async def send_wrapper(message: dict) -> None:
                if message["type"] == "http.response.start":
                    status_code.append(message["status"])
                    span.set_attribute("http.status_code", message["status"])
                elif message["type"] == "http.response.body":
                    body_chunks.append(message.get("body", b""))
                await send(message)

            try:
                await self.app(scope, receive, send_wrapper)
                duration_ms = (time.perf_counter() - start_time) * 1000
                http_duration, http_requests, http_errors = _get_http_metrics()
                sc = status_code[0] if status_code else 200

                http_duration.record(duration_ms, attributes={"method": method, "path": path, "status_code": str(sc)})
                http_requests.add(1, attributes={"method": method, "path": path, "status_code": str(sc)})

                if sc >= 400:
                    span.set_status(Status(StatusCode.ERROR, f"HTTP {sc}"))
                    if sc >= 500:
                        http_errors.add(1, attributes={"method": method, "path": path})
                else:
                    span.set_status(Status(StatusCode.OK))

            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                http_duration, http_requests, http_errors = _get_http_metrics()
                sc = status_code[0] if status_code else 500
                http_duration.record(duration_ms, attributes={"method": method, "path": path, "status_code": str(sc)})
                http_requests.add(1, attributes={"method": method, "path": path, "status_code": str(sc)})
                http_errors.add(1, attributes={"method": method, "path": path})
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise


def instrument_app(
    app: FastAPI,
    service_name: str = "audiobook-studio",
    service_version: str = "0.1.0",
    otlp_endpoint: Optional[str] = None,
    enable_console_exporter: bool = False,
    prometheus_port: int = 9090,
    exclude_paths: Optional[list] = None,
) -> None:
    """Instrument FastAPI app with OpenTelemetry.

    Args:
        app: FastAPI application instance
        service_name: Service name for traces/metrics
        service_version: Service version
        otlp_endpoint: OTLP collector endpoint
        enable_console_exporter: Enable console exporter (dev)
        prometheus_port: Prometheus metrics port
        exclude_paths: Paths to exclude from instrumentation
    """
    # Initialize tracing
    from .tracing import init_tracing

    init_tracing(
        service_name=service_name,
        service_version=service_version,
        otlp_endpoint=otlp_endpoint,
        enable_console_exporter=enable_console_exporter,
    )

    # Initialize metrics
    from .metrics import create_slo_metrics, init_metrics

    init_metrics(
        service_name=service_name,
        service_version=service_version,
        prometheus_port=prometheus_port,
    )

    # Create SLO metrics
    create_slo_metrics()

    # Add middleware
    app.add_middleware(ObservabilityMiddleware, exclude_paths=exclude_paths)

    # Add Prometheus metrics endpoint
    from prometheus_client import make_asgi_app

    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    logger.info(f"OpenTelemetry instrumentation complete for {service_name}")


def trace_function(span_name: Optional[str] = None, attributes: Optional[dict] = None):
    """Decorator to trace a function with OpenTelemetry.

    Args:
        span_name: Custom span name (defaults to function name)
        attributes: Additional attributes to add to span

    Returns:
        Decorated function
    """

    def decorator(func: Callable) -> Callable:
        tracer = get_tracer(func.__module__)
        name = span_name or f"{func.__module__}.{func.__name__}"

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            with tracer.start_as_current_span(name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                try:
                    result = await func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            with tracer.start_as_current_span(name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                try:
                    result = func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# Context managers for manual span control
class trace_span:
    """Context manager for manual span creation."""

    def __init__(
        self,
        name: str,
        attributes: Optional[dict] = None,
        tracer_name: str = "audiobook_studio",
    ):
        self.tracer = get_tracer(tracer_name)
        self.name = name
        self.attributes = attributes or {}
        self.span = None

    def __enter__(self):
        self.span = self.tracer.start_span(self.name)
        for key, value in self.attributes.items():
            self.span.set_attribute(key, value)
        self.span.__enter__()
        return self.span

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.span.record_exception(exc_val)
            self.span.set_status(Status(StatusCode.ERROR, str(exc_val)))
        else:
            self.span.set_status(Status(StatusCode.OK))
        self.span.__exit__(exc_type, exc_val, exc_tb)
