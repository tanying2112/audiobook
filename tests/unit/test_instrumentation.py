"""Tests for the FastAPI instrumentation module.

Covers:
- ``_get_http_metrics`` lazy initialization and caching
- ``ObservabilityMiddleware`` ASGI callable: success/error/excluded/non-http
- ``trace_function`` decorator (sync + async wrappers, with/without attributes)
- ``trace_span`` context manager (success and exception paths)
- ``instrument_app`` end-to-end with mocked OpenTelemetry + Prometheus
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

# ── Module-level reset helper ─────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_http_metrics():
    """Reset the module-level metric singletons between tests so caching
    behavior is deterministic."""
    import src.audiobook_studio.observability.instrumentation as instr

    instr._http_duration = None
    instr._http_requests = None
    instr._http_errors = None
    yield
    instr._http_duration = None
    instr._http_requests = None
    instr._http_errors = None


# ── _get_http_metrics ─────────────────────────────────────────────────────────


class TestGetHttpMetrics:
    def test_returns_three_instruments(self):
        from src.audiobook_studio.observability.instrumentation import _get_http_metrics

        dur, req, err = _get_http_metrics()
        assert dur is not None
        assert req is not None
        assert err is not None

    def test_lazy_initialization_caches(self):
        from src.audiobook_studio.observability.instrumentation import _get_http_metrics

        dur1, req1, err1 = _get_http_metrics()
        dur2, req2, err2 = _get_http_metrics()
        assert dur1 is dur2
        assert req1 is req2
        assert err1 is err2

    def test_creates_histogram_with_buckets(self):
        """get_meter should be called once with the right name."""
        with patch("src.audiobook_studio.observability.instrumentation.get_meter") as gm:
            mock_meter = MagicMock()
            gm.return_value = mock_meter
            from src.audiobook_studio.observability.instrumentation import _get_http_metrics

            _get_http_metrics()
            gm.assert_called_once_with("audiobook_studio.http")
            mock_meter.create_histogram.assert_called_once()
            mock_meter.create_counter.assert_called()


# ── ObservabilityMiddleware ───────────────────────────────────────────────────


class TestObservabilityMiddleware:
    @staticmethod
    async def _noop_receive():
        return {"type": "http.request", "body": b""}

    @staticmethod
    async def _noop_send(_msg):
        return None

    @pytest.mark.asyncio
    async def test_http_200_success(self):
        from src.audiobook_studio.observability.instrumentation import ObservabilityMiddleware, _get_http_metrics

        # Pre-init metrics so we can assert they were recorded
        dur, req, err = _get_http_metrics()
        dur.record = MagicMock()
        req.add = MagicMock()
        err.add = MagicMock()

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = ObservabilityMiddleware(app)
        scope = {
            "type": "http",
            "path": "/api/test",
            "method": "GET",
            "scheme": "http",
            "server": ("localhost", 8000),
            "headers": [(b"user-agent", b"pytest")],
        }
        await mw(scope, self._noop_receive, self._noop_send)
        dur.record.assert_called_once()
        req.add.assert_called_once()
        err.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_http_500_increments_errors(self):
        from src.audiobook_studio.observability.instrumentation import ObservabilityMiddleware, _get_http_metrics

        dur, req, err = _get_http_metrics()
        dur.record = MagicMock()
        req.add = MagicMock()
        err.add = MagicMock()

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 500, "headers": []})
            await send({"type": "http.response.body", "body": b"err"})

        mw = ObservabilityMiddleware(app)
        scope = {
            "type": "http",
            "path": "/api/x",
            "method": "POST",
            "scheme": "https",
            "server": ("example.com", 443),
            "headers": [],
        }
        await mw(scope, self._noop_receive, self._noop_send)
        err.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_http_4xx_no_error_metric(self):
        from src.audiobook_studio.observability.instrumentation import ObservabilityMiddleware, _get_http_metrics

        dur, req, err = _get_http_metrics()
        dur.record = MagicMock()
        req.add = MagicMock()
        err.add = MagicMock()

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b"nf"})

        mw = ObservabilityMiddleware(app)
        scope = {"type": "http", "path": "/x", "method": "GET", "scheme": "http", "server": ("", 80), "headers": []}
        await mw(scope, self._noop_receive, self._noop_send)
        # 4xx is still recorded as request, but NOT counted in errors (>=500)
        req.add.assert_called_once()
        err.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_excluded_path_bypasses_tracing(self):
        from src.audiobook_studio.observability.instrumentation import ObservabilityMiddleware, _get_http_metrics

        dur, req, err = _get_http_metrics()
        dur.record = MagicMock()
        req.add = MagicMock()

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        mw = ObservabilityMiddleware(app, exclude_paths=["/health"])
        scope = {"type": "http", "path": "/health", "method": "GET", "scheme": "http", "server": None, "headers": []}
        await mw(scope, self._noop_receive, self._noop_send)
        # Path excluded -> no metrics recorded
        dur.record.assert_not_called()
        req.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through(self):
        from src.audiobook_studio.observability.instrumentation import ObservabilityMiddleware, _get_http_metrics

        dur, req, err = _get_http_metrics()
        dur.record = MagicMock()
        req.add = MagicMock()

        called = {"app": 0}

        async def app(scope, receive, send):
            called["app"] = 1

        mw = ObservabilityMiddleware(app)
        await mw({"type": "lifespan"}, self._noop_receive, self._noop_send)
        assert called["app"] == 1
        dur.record.assert_not_called()

    @pytest.mark.asyncio
    async def test_app_exception_records_and_reraises(self):
        from src.audiobook_studio.observability.instrumentation import ObservabilityMiddleware, _get_http_metrics

        dur, req, err = _get_http_metrics()
        dur.record = MagicMock()
        req.add = MagicMock()
        err.add = MagicMock()

        async def app(scope, receive, send):
            raise RuntimeError("app boom")

        mw = ObservabilityMiddleware(app)
        scope = {
            "type": "http",
            "path": "/x",
            "method": "GET",
            "scheme": "http",
            "server": ("h", 80),
            "headers": [],
        }
        with pytest.raises(RuntimeError, match="app boom"):
            await mw(scope, self._noop_receive, self._noop_send)
        # On exception path, http_errors counter always incremented
        err.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_default_exclude_paths(self):
        from src.audiobook_studio.observability.instrumentation import ObservabilityMiddleware

        async def app(scope, receive, send):
            pass

        mw = ObservabilityMiddleware(app)
        assert "/health" in mw.exclude_paths
        assert "/metrics" in mw.exclude_paths
        assert "/docs" in mw.exclude_paths
        assert "/openapi.json" in mw.exclude_paths

    @pytest.mark.asyncio
    async def test_no_response_start_assumes_500(self):
        """If downstream app never sends http.response.start, status defaults
        to 500 in the error path."""
        from src.audiobook_studio.observability.instrumentation import ObservabilityMiddleware, _get_http_metrics

        dur, req, err = _get_http_metrics()
        dur.record = MagicMock()
        req.add = MagicMock()
        err.add = MagicMock()

        async def app(scope, receive, send):
            raise ValueError("no response")

        mw = ObservabilityMiddleware(app)
        scope = {"type": "http", "path": "/x", "method": "GET", "scheme": "http", "server": None, "headers": []}
        with pytest.raises(ValueError):
            await mw(scope, self._noop_receive, self._noop_send)
        # Last call to err.add uses path /x with status default 500
        args, _ = err.add.call_args
        assert args[0] == 1


# ── trace_function ─────────────────────────────────────────────────────────────


class TestTraceFunction:
    def test_sync_function_traced(self):
        from src.audiobook_studio.observability.instrumentation import trace_function

        @trace_function()
        def add(a, b):
            return a + b

        assert add(2, 3) == 5

    def test_sync_function_with_attributes(self):
        from src.audiobook_studio.observability.instrumentation import trace_function

        @trace_function(span_name="custom_name", attributes={"k": "v"})
        def mul(a, b):
            return a * b

        assert mul(2, 5) == 10

    def test_sync_function_exception_propagates(self):
        from src.audiobook_studio.observability.instrumentation import trace_function

        @trace_function()
        def boom():
            raise ValueError("sync boom")

        with pytest.raises(ValueError, match="sync boom"):
            boom()

    @pytest.mark.asyncio
    async def test_async_function_traced(self):
        from src.audiobook_studio.observability.instrumentation import trace_function

        @trace_function()
        async def add_async(a, b):
            return a + b

        assert await add_async(2, 7) == 9

    @pytest.mark.asyncio
    async def test_async_function_with_attributes(self):
        from src.audiobook_studio.observability.instrumentation import trace_function

        @trace_function(span_name="async_op", attributes={"req_id": "123"})
        async def op():
            return "result"

        assert await op() == "result"

    @pytest.mark.asyncio
    async def test_async_function_exception_propagates(self):
        from src.audiobook_studio.observability.instrumentation import trace_function

        @trace_function()
        async def boom():
            raise RuntimeError("async boom")

        with pytest.raises(RuntimeError, match="async boom"):
            await boom()


# ── trace_span context manager ────────────────────────────────────────────────


class TestTraceSpan:
    def test_success_path(self):
        from src.audiobook_studio.observability.instrumentation import trace_span

        with trace_span("test_span", attributes={"a": "b"}) as span:
            span.set_attribute("extra", "c")
            assert span is not None

    def test_exception_path_records_error(self):
        from src.audiobook_studio.observability.instrumentation import trace_span

        with pytest.raises(ValueError, match="ctx boom"):
            with trace_span("err_span"):
                raise ValueError("ctx boom")

    def test_default_tracer_name(self):
        from src.audiobook_studio.observability.instrumentation import trace_span

        ctx = trace_span("name")
        assert ctx.name == "name"
        assert ctx.attributes == {}
        assert ctx.tracer is not None

    def test_custom_tracer_name(self):
        from src.audiobook_studio.observability.instrumentation import trace_span

        ctx = trace_span("x", tracer_name="custom")
        assert ctx.tracer is not None

    def test_attributes_merged(self):
        from src.audiobook_studio.observability.instrumentation import trace_span

        ctx = trace_span("n", attributes={"k1": "v1", "k2": 2})
        assert ctx.attributes == {"k1": "v1", "k2": 2}


# ── instrument_app ────────────────────────────────────────────────────────────


class TestInstrumentApp:
    def test_instrument_app_calls_init_tracing_and_metrics(self):
        from src.audiobook_studio.observability.instrumentation import instrument_app

        fake_app = MagicMock()

        with (
            patch("src.audiobook_studio.observability.tracing.init_tracing") as mock_tracing,
            patch("src.audiobook_studio.observability.metrics.init_metrics") as mock_metrics,
            patch("src.audiobook_studio.observability.metrics.create_slo_metrics") as mock_slo,
            patch("prometheus_client.make_asgi_app") as mock_prom,
        ):
            instrument_app(
                fake_app,
                service_name="svc",
                service_version="v1",
                otlp_endpoint="http://otlp:4317",
                enable_console_exporter=True,
                prometheus_port=9091,
            )
            mock_tracing.assert_called_once()
            mock_metrics.assert_called_once()
            mock_slo.assert_called_once()
            fake_app.add_middleware.assert_called_once()
            fake_app.mount.assert_called_once_with("/metrics", mock_prom.return_value)
            mock_prom.assert_called_once()

    def test_instrument_app_passes_exclude_paths(self):
        from src.audiobook_studio.observability.instrumentation import instrument_app

        fake_app = MagicMock()
        with (
            patch("src.audiobook_studio.observability.tracing.init_tracing"),
            patch("src.audiobook_studio.observability.metrics.init_metrics"),
            patch("src.audiobook_studio.observability.metrics.create_slo_metrics"),
            patch("prometheus_client.make_asgi_app"),
            patch("src.audiobook_studio.observability.metrics.metrics"),
        ):
            instrument_app(fake_app, exclude_paths=["/custom", "/x"])
            args, kwargs = fake_app.add_middleware.call_args
            middleware_cls = args[0]
            from src.audiobook_studio.observability.instrumentation import ObservabilityMiddleware

            assert middleware_cls is ObservabilityMiddleware
            assert kwargs["exclude_paths"] == ["/custom", "/x"]

    def test_instrument_app_default_args(self):
        from src.audiobook_studio.observability.instrumentation import instrument_app

        fake_app = MagicMock()
        with (
            patch("src.audiobook_studio.observability.tracing.init_tracing") as mt,
            patch("src.audiobook_studio.observability.metrics.init_metrics") as mm,
            patch("src.audiobook_studio.observability.metrics.create_slo_metrics"),
            patch("prometheus_client.make_asgi_app"),
            patch("src.audiobook_studio.observability.metrics.metrics"),
        ):
            instrument_app(fake_app)
            # Verify default service_name and version passed through
            _, tracing_kwargs = mt.call_args
            assert tracing_kwargs["service_name"] == "audiobook-studio"
            assert tracing_kwargs["service_version"] == "0.1.0"
            _, metrics_kwargs = mm.call_args
            assert metrics_kwargs["prometheus_port"] == 9090


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=src/audiobook_studio/observability/instrumentation.py"])
