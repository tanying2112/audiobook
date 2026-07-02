"""OpenTelemetry tracing setup."""

import logging
import os
from typing import Optional

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

logger = logging.getLogger(__name__)

# Global tracer provider
_tracer_provider: Optional[TracerProvider] = None


def init_tracing(
    service_name: str = "audiobook-studio",
    service_version: str = "0.1.0",
    otlp_endpoint: Optional[str] = None,
    enable_console_exporter: bool = False,
) -> TracerProvider:
    """Initialize OpenTelemetry tracing.

    Args:
        service_name: Service name for traces
        service_version: Service version
        otlp_endpoint: OTLP collector endpoint (e.g., http://localhost:4317)
        enable_console_exporter: Whether to also export to console (dev only)

    Returns:
        Configured TracerProvider
    """
    global _tracer_provider

    # Create resource with service info
    resource = Resource.create(
        {
            SERVICE_NAME: service_name,
            SERVICE_VERSION: service_version,
            "deployment.environment": os.getenv("DEPLOYMENT_ENV", "development"),
        }
    )

    # Create tracer provider
    _tracer_provider = TracerProvider(resource=resource)

    # Set up exporters
    if otlp_endpoint:
        try:
            otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
            _tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            logger.info(f"OTLP trace exporter configured: {otlp_endpoint}")
        except Exception as e:
            logger.warning(f"Failed to configure OTLP exporter: {e}")

    if enable_console_exporter:
        console_exporter = ConsoleSpanExporter()
        _tracer_provider.add_span_processor(BatchSpanProcessor(console_exporter))
        logger.info("Console trace exporter enabled")

    # Set global tracer provider
    trace.set_tracer_provider(_tracer_provider)

    # Auto-instrument common libraries (imported lazily to avoid test setup issues)
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument()
        logger.info("FastAPI instrumentation enabled")
    except Exception as e:
        logger.warning(f"FastAPI instrumentation failed: {e}")

    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor.instrument(engine=None)
        logger.info("SQLAlchemy instrumentation enabled")
    except Exception as e:
        logger.warning(f"SQLAlchemy instrumentation failed: {e}")

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor.instrument()
        logger.info("HTTPX instrumentation enabled")
    except Exception as e:
        logger.warning(f"HTTPX instrumentation failed: {e}")

    try:
        from opentelemetry.instrumentation.requests import RequestsInstrumentor

        RequestsInstrumentor.instrument()
        logger.info("Requests instrumentation enabled")
    except Exception as e:
        logger.warning(f"Requests instrumentation failed: {e}")

    logger.info(f"OpenTelemetry tracing initialized for {service_name} v{service_version}")
    return _tracer_provider


def get_tracer(name: str = "audiobook_studio") -> trace.Tracer:
    """Get a tracer instance.

    Args:
        name: Tracer name (usually __name__ of calling module)

    Returns:
        Tracer instance
    """
    if _tracer_provider is None:
        init_tracing()
    return trace.get_tracer(name)


def shutdown_tracing() -> None:
    """Shutdown tracer provider and flush spans."""
    global _tracer_provider
    if _tracer_provider:
        _tracer_provider.shutdown()
        _tracer_provider = None
        logger.info("OpenTelemetry tracing shut down")
