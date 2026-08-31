"""Entry point for the Audiobook Studio FastAPI application.

The application includes routers for all core entities and initializes the
database tables on startup (for the MVP).  In production you would run Alembic
migrations instead of ``init_db``.
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from .api.ab_test_interceptor import ABTestMiddleware
from .api.admin import router as admin_router
from .api.agent_chat import router as agent_chat_router
from .api.audio_segments import router as audio_segments_router
from .api.auto_run import router as auto_run_router
from .api.books import router as books_router
from .api.characters import router as characters_router
from .api.config import router as config_router
from .api.evolution import router as evolution_router
from .api.export import export_tasks_router
from .api.export import router as export_router
from .api.feedback import router as feedback_router
from .api.golden import router as golden_router
from .api.harness import router as harness_router
from .api.languages import router as languages_router
from .api.llm import router as llm_router
from .api.mock_router import router as mock_router
from .api.models_market import router as models_market_router
from .api.monitoring import router as monitoring_router
from .api.paragraphs import router as paragraphs_router
from .api.pipeline import router as pipeline_router
from .api.projects import router as projects_router
from .api.provider_router import router as provider_router
from .api.publish import router as publish_router
from .api.publish_job import router as publish_job_router
from .api.qualities import router as qualities_router
from .api.routings import router as routings_router
from .api.sop_reflection import router as sop_reflection_router
from .api.templates import router as templates_router
from .api.tts_edits import router as tts_edits_router
from .api.tts_voices import router as tts_voices_router
from .api.upload import router as upload_router
from .api.websocket import router as websocket_router
from .auth.dependencies import get_current_active_user
from .auth.router import router as auth_router
from .config import get_settings
from .middleware.timestamp import ISOTimestampMiddleware
from .observability import instrument_app

# Note: MOCK_LLM is NOT set here. Every pipeline consumer reads it lazily at
# __init__ time via os.environ.get("MOCK_LLM", "false"), defaulting to the real
# path when unset. The previous "set false before pipeline modules are imported"
# guard was a no-op (no module reads MOCK_LLM at import time) and created a
# second source of truth that conflicted with the test conftest forcing "true".
# To run mock-first locally, export MOCK_LLM=true in your shell.


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: validate critical security settings FIRST
    from .config import get_settings

    settings = get_settings()
    # P0-2: Explicit JWT secret validation (defense-in-depth; also runs in get_settings())
    settings.validate_jwt_secret()
    # P0-3: Explicit CORS security validation
    settings.validate_cors_security()

    # BP-003: Startup dependency validation — fast-fail on unreachable dependencies
    await settings.validate_runtime_dependencies(timeout=settings.HEALTH_CHECK_TIMEOUT)

    # P1-4 / S3-4: DB schema is now managed EXTERNALLY via Alembic.
    # Migrations run BEFORE the app starts (through `scripts/migrate.sh up` or
    # the `migrate` service in docker-compose, which waits for db to be healthy),
    # so startup NEVER runs migrations. This enables zero-downtime, rollbackable
    # production deployments. See scripts/migrate.sh and docker-compose.yml.

    # Initialize RBAC with default roles and permissions
    from .auth.rbac import init_rbac
    from .database import SessionLocal

    db = SessionLocal()
    try:
        init_rbac(db)
    finally:
        db.close()

    # Load plugins (TTS engines, LLM providers, pipeline stages)
    try:
        from .plugins import get_plugin_manager

        plugin_mgr = get_plugin_manager()
        plugin_mgr.discover()
        plugin_mgr.load_installed()
        results = plugin_mgr.load_all_installed()
        loaded = [name for name, ok in results.items() if ok]
        failed = [name for name, ok in results.items() if not ok]
        if loaded:
            logger.info("Loaded plugins: %s", ", ".join(loaded))
        if failed:
            logger.warning("Failed to load plugins: %s", ", ".join(failed))
    except Exception as e:
        logger.warning("Plugin loading failed (continuing without plugins): %s", e)

    # Shutdown observability
    from .observability.metrics import shutdown_metrics
    from .observability.tracing import shutdown_tracing

    yield
    shutdown_tracing()
    shutdown_metrics()


app = FastAPI(
    title="Audiobook Studio API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Instrument with OpenTelemetry FIRST (so it's outermost for response, innermost for request)
instrument_app(
    app,
    service_name="audiobook-studio",
    service_version="0.1.0",
    otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
    enable_console_exporter=os.getenv("OTEL_CONSOLE_EXPORTER", "false").lower() == "true",
    prometheus_port=int(os.getenv("PROMETHEUS_PORT", "9090")),
    exclude_paths=["/health", "/metrics", "/docs", "/openapi.json", "/redoc"],
)

# Middleware order (added FIRST = innermost for response, LAST = outermost for request):
# Request flow (outermost to innermost):
# 1. TrustedHostMiddleware (security — reject requests with spoofed Host headers)
# 2. CORSMiddleware (cross-origin — must wrap all responses)
# 3. GZipMiddleware (compression — applied after CORS headers are set)
# 4. ISOTimestampMiddleware (response normalization — last before business logic)
# 5. ABTestMiddleware (business routing — depends on normalized responses)
# 6. ObservabilityMiddleware (observability — added by instrument_app, innermost for request)
# Response flow (innermost to outermost):
# 1. ObservabilityMiddleware
# 2. ABTestMiddleware
# 3. ISOTimestampMiddleware
# 4. GZipMiddleware
# 5. CORSMiddleware (adds CORS headers)
# 6. TrustedHostMiddleware
settings = get_settings()
# Middleware order for REQUEST (first added = outermost for request):
# 1. TrustedHostMiddleware (security — reject requests with spoofed Host headers) - FIRST for request
# 2. CORSMiddleware (cross-origin — must handle preflight before other middleware)
# 3. GZipMiddleware (compression)
# 4. ISOTimestampMiddleware (response normalization)
# 5. ABTestMiddleware (business routing)
# 6. ObservabilityMiddleware (added by instrument_app, innermost for request)
# 
# For RESPONSE, order is reversed (last added = outermost for response)
# instrument_app already added ObservabilityMiddleware as innermost for request
# So we add the rest in REVERSE of request order (excluding ObservabilityMiddleware)
app.add_middleware(ABTestMiddleware)
app.add_middleware(ISOTimestampMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.ALLOWED_HOSTS,
)  # outermost for request (added last = first to handle request)

# S3.6: API rate limiting / quota (no-op unless RATE_LIMIT_ENABLED).
from .api.rate_limit_middleware import add_rate_limit_middleware

add_rate_limit_middleware(app)

# Include routers with global auth default-deny (P1-1)
# Public: auth_router (login/register), health endpoints
# Protected by default: all other routers
# upload_router has its own per-endpoint project-level auth
auth_dep = [Depends(get_current_active_user)]

app.include_router(auth_router, prefix="/api")  # Public: login/register
app.include_router(projects_router, prefix="/api", dependencies=auth_dep)
app.include_router(books_router, prefix="/api", dependencies=auth_dep)
app.include_router(characters_router, prefix="/api", dependencies=auth_dep)
app.include_router(config_router, prefix="/api", dependencies=auth_dep)
app.include_router(paragraphs_router, prefix="/api", dependencies=auth_dep)
app.include_router(tts_edits_router, prefix="/api", dependencies=auth_dep)
app.include_router(routings_router, prefix="/api", dependencies=auth_dep)
app.include_router(qualities_router, prefix="/api", dependencies=auth_dep)
app.include_router(export_router, prefix="/api", dependencies=auth_dep)
app.include_router(export_tasks_router, prefix="/api", dependencies=auth_dep)
app.include_router(feedback_router, prefix="/api", dependencies=auth_dep)
app.include_router(audio_segments_router, prefix="/api", dependencies=auth_dep)
app.include_router(llm_router, prefix="/api", dependencies=auth_dep)
app.include_router(languages_router, prefix="/api/v1", dependencies=auth_dep)
app.include_router(provider_router, prefix="/api/v1/providers", tags=["provider-management"], dependencies=auth_dep)
app.include_router(evolution_router, prefix="/api", dependencies=auth_dep)
app.include_router(websocket_router, prefix="/api")  # No auth_dep for WebSocket
app.include_router(templates_router, prefix="/api", dependencies=auth_dep)
app.include_router(harness_router, prefix="/api", dependencies=auth_dep)
app.include_router(golden_router, prefix="/api", dependencies=auth_dep)
app.include_router(auto_run_router, prefix="/api", dependencies=auth_dep)
if settings.DEBUG or settings.ENVIRONMENT == "development":
    app.include_router(mock_router, prefix="/api", dependencies=auth_dep)
app.include_router(tts_voices_router, prefix="/api", dependencies=auth_dep)
app.include_router(publish_router, prefix="/api", dependencies=auth_dep)
app.include_router(publish_job_router, prefix="/api", dependencies=auth_dep)
app.include_router(upload_router, prefix="/api")  # Has own per-endpoint project auth
app.include_router(pipeline_router, prefix="/api", dependencies=auth_dep)
app.include_router(models_market_router, prefix="/api/v1", dependencies=auth_dep)
app.include_router(agent_chat_router, prefix="/api", dependencies=auth_dep)
app.include_router(admin_router, prefix="/api", dependencies=auth_dep)
app.include_router(sop_reflection_router, prefix="/api", dependencies=auth_dep)

from fastapi.routing import APIWebSocketRoute

# ── WebSocket Route Fix ──────────────────────────────────────────────────────
# FastAPI's include_router doesn't properly include WebSocket routes with prefix.
# Manually add websocket routes with combined prefix (/api + /ws = /api/ws).
from .api.websocket import router as _websocket_router

for _route in _websocket_router.routes:
    if isinstance(_route, APIWebSocketRoute):
        _new_path = "/api" + _route.path
        _new_route = APIWebSocketRoute(path=_new_path, endpoint=_route.endpoint, name=_route.name)
        app.router.routes.append(_new_route)

# Clean up
del _websocket_router, _route, _new_path, _new_route, APIWebSocketRoute


# ── Health endpoints (BP-003: liveness vs readiness) ────────────────────────


@app.get("/health")
def health_check():
    """Simple liveness check — always returns 200 if process is alive."""
    return {"status": "ok"}


@app.get("/health/live")
def health_live():
    """K8s liveness probe — returns 200 as long as the process is running."""
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready():
    """K8s readiness probe — returns 200 only when all critical dependencies are up.

    Checks: database SELECT 1, Redis ping, Kokoro model file existence, LLM API key format,
    TTS engine health probes (Kokoro warmup, VoxCPM2/Edge connectivity).
    Returns 503 with structured error details if any dependency is not ready.
    """
    import asyncio

    from sqlalchemy import text

    from .config import get_settings
    from .database import SessionLocal

    settings = get_settings()
    timeout = settings.HEALTH_CHECK_TIMEOUT
    checks: dict[str, Any] = {}

    # DB check
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
    finally:
        db.close()

    # Redis check
    try:
        import redis.asyncio as aioredis

        async with asyncio.timeout(timeout):
            r = await aioredis.from_url(settings.REDIS_URL)
            await r.ping()
            await r.aclose()
            checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # Kokoro model check
    from pathlib import Path

    kokoro_path = settings.KOKORO_MODEL_PATH
    if kokoro_path:
        checks["kokoro_model"] = "ok" if Path(kokoro_path).exists() else "model_not_found"
    else:
        checks["kokoro_model"] = "not_configured"

    # TTS engine health probes (S1-6: real engine probes)
    try:
        from .di import get_app_container
        from .tts.engine import EngineRegistry, probe_tts_engines

        container = get_app_container()
        registry = container.get_or_none(EngineRegistry)
        if registry is not None:
            probe = await asyncio.wait_for(probe_tts_engines(timeout, registry=registry), timeout=timeout)
            checks["tts_engines"] = probe["engines"]  # {"kokoro": bool, "voxcpm2": bool, "edge": bool, "piper": bool}
            checks["tts_engine_health"] = probe["details"]
            checks["tts_overall_healthy"] = any(probe["engines"].values())
        else:
            probe = await asyncio.wait_for(probe_tts_engines(timeout), timeout=timeout)
            checks["tts_engines"] = probe["engines"]
            checks["tts_engine_health"] = probe["details"]
            checks["tts_overall_healthy"] = any(probe["engines"].values())
    except asyncio.TimeoutError:
        checks["tts_engines"] = "timeout"
        checks["tts_engine_health"] = {}
        checks["tts_overall_healthy"] = False
    except Exception as e:
        checks["tts_engines"] = f"error: {e}"
        checks["tts_engine_health"] = {}
        checks["tts_overall_healthy"] = False

    # LLM API key format validation
    try:
        settings._validate_llm_api_keys()
        checks["llm_keys"] = "ok"
    except RuntimeError as e:
        checks["llm_keys"] = f"error: {e}"
    except Exception as e:
        checks["llm_keys"] = f"error: {e}"

    def _is_healthy(v: str | dict[str, Any] | bool) -> bool:
        if isinstance(v, dict):
            return all(_is_healthy(vv) for vv in v.values())
        if isinstance(v, bool):
            return v
        return v == "ok" or v == "not_configured"

    from src.audiobook_studio.config.settings_loader import get_settings

    # ... existing code ...
    # Critical dependencies: DB must be healthy
    # Redis is optional (controlled by REDIS_REQUIRED setting)
    settings = get_settings()
    db_ok = _is_healthy(checks.get("database"))

    if settings.REDIS_REQUIRED:
        # Redis is required - must be healthy
        redis_ok = _is_healthy(checks.get("redis"))
        redis_status = "required"
    else:
        # Redis is optional - check but don't fail if unavailable
        redis_healthy = _is_healthy(checks.get("redis"))
        redis_ok = redis_healthy or checks.get("redis") == "not_configured"
        redis_status = "optional"

    llm_ok = _is_healthy(checks.get("llm_keys"))

    all_ok = db_ok and redis_ok and llm_ok
    status_code = 200 if all_ok else 503
    return JSONResponse(
        content={"status": "ready" if all_ok else "not_ready", "checks": checks},
        status_code=status_code,
    )


# ── Prometheus /metrics endpoint ───────────────────────────────────────────


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint for scraping.

    Returns Prometheus-formatted metrics including:
    - HTTP request counts/durations
    - Pipeline stage durations
    - Queue depths
    - TTS synthesis counts
    - LLM token usage
    - Cost tracking (USD/day)
    - DB pool stats
    """
    from fastapi.responses import PlainTextResponse

    from .core.telemetry import get_telemetry

    metrics_text = get_telemetry().export_prometheus()
    return PlainTextResponse(content=metrics_text, media_type="text/plain; version=0.0.4; charset=utf-8")


from .exceptions import AudiobookError, register_error_handlers

# ── Global exception handler (QUAL-003) — implementation lives in exceptions.py
#    so that test apps mounting bare FastAPI() can reuse the identical contract.
register_error_handlers(app)

# Backward-compatible names (handler was extracted to exceptions.py; some
# callers/tests still import these from main).
from .exceptions import error_code_to_status as _error_code_to_status  # noqa: E402


async def global_exception_handler(request, exc: Exception):  # noqa: ANN001
    """Deprecated direct-call shim — the registered handler is in exceptions.py."""
    from starlette.responses import JSONResponse

    if hasattr(exc, "error_code") and hasattr(exc, "to_dict"):
        return JSONResponse(
            content={"error": exc.to_dict()},
            status_code=_error_code_to_status(exc.error_code),
        )
    from starlette.exceptions import HTTPException as StarletteHTTPException

    if isinstance(exc, StarletteHTTPException):
        return JSONResponse(
            content={"error": {"code": "HTTP_ERROR", "message": exc.detail}},
            status_code=exc.status_code,
        )
    return JSONResponse(
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred. Check server logs for details.",
            }
        },
        status_code=500,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # nosec B104 - standard server binding
