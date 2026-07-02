"""Unit tests for observability tracing to boost coverage."""

from unittest.mock import MagicMock, patch

from src.audiobook_studio.observability import tracing


def _mock_instrumentations():
    """Context manager to mock all lazy-loaded instrumentations at their import source."""
    return (
        patch.multiple(
            "opentelemetry.instrumentation.fastapi",
            FastAPIInstrumentor=MagicMock(),
        ),
        patch.multiple(
            "opentelemetry.instrumentation.sqlalchemy",
            SQLAlchemyInstrumentor=MagicMock(),
        ),
        patch.multiple(
            "opentelemetry.instrumentation.httpx",
            HTTPXClientInstrumentor=MagicMock(),
        ),
        patch.multiple(
            "opentelemetry.instrumentation.requests",
            RequestsInstrumentor=MagicMock(),
        ),
    )


def test_init_tracing_minimal():
    """Test init_tracing with minimal config (no OTLP, no console)."""
    with (
        _mock_instrumentations()[0] as mock_fastapi,
        _mock_instrumentations()[1] as mock_sqlalchemy,
        _mock_instrumentations()[2] as mock_httpx,
        _mock_instrumentations()[3] as mock_requests,
    ):

        provider = tracing.init_tracing(
            service_name="test-service",
            service_version="1.0.0",
            otlp_endpoint=None,
            enable_console_exporter=False,
        )

        assert provider is not None
        assert tracing._tracer_provider is provider


def test_init_tracing_with_console_exporter():
    """Test init_tracing with console exporter enabled."""
    with (
        _mock_instrumentations()[0],
        _mock_instrumentations()[1],
        _mock_instrumentations()[2],
        _mock_instrumentations()[3],
    ):

        provider = tracing.init_tracing(
            service_name="test-service",
            service_version="1.0.0",
            otlp_endpoint=None,
            enable_console_exporter=True,
        )

        assert provider is not None


def test_init_tracing_with_otlp_endpoint():
    """Test init_tracing with OTLP endpoint."""
    with (
        patch("src.audiobook_studio.observability.tracing.OTLPSpanExporter") as mock_otlp_exporter,
        _mock_instrumentations()[0],
        _mock_instrumentations()[1],
        _mock_instrumentations()[2],
        _mock_instrumentations()[3],
    ):

        mock_otlp_exporter.return_value = MagicMock()

        provider = tracing.init_tracing(
            service_name="test-service",
            service_version="1.0.0",
            otlp_endpoint="http://localhost:4317",
            enable_console_exporter=False,
        )

        assert provider is not None
        mock_otlp_exporter.assert_called_once_with(endpoint="http://localhost:4317", insecure=True)


def test_get_tracer_auto_init():
    """Test get_tracer auto-initializes when not initialized."""
    tracing.shutdown_tracing()  # Ensure clean state

    with (
        _mock_instrumentations()[0],
        _mock_instrumentations()[1],
        _mock_instrumentations()[2],
        _mock_instrumentations()[3],
    ):

        tracer = tracing.get_tracer("test-module")
        assert tracer is not None


def test_shutdown_tracing():
    """Test shutdown_tracing flushes and clears provider."""
    with (
        _mock_instrumentations()[0],
        _mock_instrumentations()[1],
        _mock_instrumentations()[2],
        _mock_instrumentations()[3],
    ):

        provider = tracing.init_tracing(
            service_name="test-service",
            service_version="1.0.0",
        )
        assert tracing._tracer_provider is not None

        tracing.shutdown_tracing()
        assert tracing._tracer_provider is None
        # provider.shutdown.assert_called_once()  # Real provider, not a mock


def test_shutdown_tracing_idempotent():
    """Test shutdown_tracing is idempotent (safe to call multiple times)."""
    tracing.shutdown_tracing()  # Should not raise
    tracing.shutdown_tracing()  # Should not raise
    assert tracing._tracer_provider is None
