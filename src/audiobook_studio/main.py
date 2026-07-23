"""Entry point for the Audiobook Studio FastAPI application.

The application includes routers for all core entities and initializes the
database tables on startup (for the MVP).  In production you would run Alembic
migrations instead of ``init_db``.
"""

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from .api.ab_test_interceptor import ABTestMiddleware
from .api.agent_chat import router as agent_chat_router
from .api.audio_segments import router as audio_segments_router
from .api.auto_run import router as auto_run_router
from .api.books import router as books_router
from .api.characters import router as characters_router
from .api.config import router as config_router
from .api.export import export_tasks_router
from .api.export import router as export_router
from .api.feedback import router as feedback_router
from .api.golden import router as golden_router
from .api.harness import router as harness_router
from .api.llm import router as llm_router
from .api.mock_router import router as mock_router
from .api.monitoring import router as monitoring_router
from .api.paragraphs import router as paragraphs_router
from .api.pipeline import router as pipeline_router
from .api.projects import router as projects_router
from .api.publish import router as publish_router
from .api.qualities import router as qualities_router
from .api.routings import router as routings_router
from .api.sop_reflection import router as sop_reflection_router
from .api.templates import router as templates_router
from .api.tts_edits import router as tts_edits_router
from .api.tts_voices import router as tts_voices_router
from .api.admin import router as admin_router
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
    await _validate_runtime_dependencies(settings)

    # P1-4: Use Alembic for DB migrations instead of create_all()
    from subprocess import run

    result = run(["alembic", "upgrade", "head"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Alembic migration failed: {result.stderr}")

    # Initialize RBAC with default roles and permissions
    from .auth.rbac import init_rbac
    from .database import SessionLocal

    db = SessionLocal()
    try:
        init_rbac(db)
    finally:
        db.close()

    # Shutdown observability
    from .observability.metrics import shutdown_metrics
    from .observability.tracing import shutdown_tracing

    yield
    shutdown_tracing()
    shutdown_metrics()


async def _validate_runtime_dependencies(settings) -> None:
    """Validate critical runtime dependencies at startup (BP-003).

    Checks DB connectivity, Redis ping, and model path existence.
    Fast-fails with clear error messages on first failure.
    """
    import asyncio
    import logging

    logger = logging.getLogger("audiobook_studio.startup")
    timeout = settings.HEALTH_CHECK_TIMEOUT

    # 1. Database connectivity
    try:
        from .database import SessionLocal
        from sqlalchemy import text

        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            logger.info("Database connectivity: OK")
        finally:
            db.close()
    except Exception as e:
        logger.critical(f"DATABASE_URL connect failed: {e}")
        raise RuntimeError(
            f"DATABASE_URL connect failed: {e}. "
            f"Check DATABASE_URL={settings.DATABASE_URL}"
        ) from e

    # 2. Redis ping (optional — warn only)
    try:
        import redis.asyncio as aioredis
        async with asyncio.timeout(timeout):
            r = aioredis.from_url(settings.REDIS_URL)
            await r.ping()
            await r.aclose()
            logger.info("Redis connectivity: OK")
    except Exception as e:
        logger.warning(f"Redis ping failed (non-fatal): {e}")

    # 3. KOKORO_MODEL_PATH existence (if configured)
    from pathlib import Path

    kokoro_path = settings.KOKORO_MODEL_PATH
    if kokoro_path:
        model_file = Path(kokoro_path)
        if not model_file.exists():
            logger.error(f"KOKORO_MODEL_PATH not found: {kokoro_path}")
            raise RuntimeError(
                f"KOKORO_MODEL_PATH not found: {kokoro_path}. "
                f"Download models or set ENABLE_LOCAL_TTS=false to fallback to Edge-TTS."
            )


app = FastAPI(
    title="Audiobook Studio API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Middleware order: Security → CORS → Compression → Normalization → Business
# 1. TrustedHost (security — reject requests with spoofed Host headers)
# 2. CORSMiddleware (cross-origin — must wrap all responses)
# 3. GZipMiddleware (compression — applied after CORS headers are set)
# 4. ISOTimestampMiddleware (response normalization — last before business logic)
# 5. ABTestMiddleware (business routing — depends on normalized responses)
settings = get_settings()
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.ALLOWED_HOSTS,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(ISOTimestampMiddleware)
app.add_middleware(ABTestMiddleware)

# Instrument with OpenTelemetry
instrument_app(
    app,
    service_name="audiobook-studio",
    service_version="0.1.0",
    otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
    enable_console_exporter=os.getenv("OTEL_CONSOLE_EXPORTER", "false").lower() == "true",
    prometheus_port=int(os.getenv("PROMETHEUS_PORT", "9090")),
    exclude_paths=["/health", "/metrics", "/docs", "/openapi.json", "/redoc"],
)

# Include routers with global auth default-deny (P1-1)
# Public: auth_router (login/register), health endpoints
# Protected by default: all other routers
# upload_router has its own per-endpoint project-level auth
auth_dep = [Depends(get_current_active_user)]

app.include_router(auth_router, prefix="/api")  # Public: login/register
app.include_router(projects_router, dependencies=auth_dep)
app.include_router(books_router, dependencies=auth_dep)
app.include_router(characters_router, dependencies=auth_dep)
app.include_router(config_router, dependencies=auth_dep)
app.include_router(paragraphs_router, dependencies=auth_dep)
app.include_router(tts_edits_router, dependencies=auth_dep)
app.include_router(routings_router, dependencies=auth_dep)
app.include_router(qualities_router, dependencies=auth_dep)
app.include_router(export_router, dependencies=auth_dep)
app.include_router(export_tasks_router, dependencies=auth_dep)
app.include_router(feedback_router, dependencies=auth_dep)
app.include_router(audio_segments_router, dependencies=auth_dep)
app.include_router(llm_router, dependencies=auth_dep)
app.include_router(websocket_router, dependencies=auth_dep)
app.include_router(templates_router, dependencies=auth_dep)
app.include_router(harness_router, dependencies=auth_dep)
app.include_router(golden_router, dependencies=auth_dep)
app.include_router(auto_run_router, dependencies=auth_dep)
if settings.DEBUG or settings.ENVIRONMENT == "development":
    app.include_router(mock_router, dependencies=auth_dep)
app.include_router(tts_voices_router, dependencies=auth_dep)
app.include_router(publish_router, dependencies=auth_dep)
app.include_router(upload_router)  # Has own per-endpoint project auth
app.include_router(pipeline_router, dependencies=auth_dep)
app.include_router(monitoring_router, prefix="/api", dependencies=auth_dep)
app.include_router(agent_chat_router, dependencies=auth_dep)
app.include_router(admin_router, dependencies=auth_dep)
app.include_router(sop_reflection_router, dependencies=auth_dep)


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

    Checks: database SELECT 1, Redis ping, Kokoro model file existence.
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
            r = aioredis.from_url(settings.REDIS_URL)
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

    # TTS engine load status (PERF-001)
    try:
        from .di import get_app_container
        from .tts.engine import EngineRegistry

        container = get_app_container()
        registry = container.get(EngineRegistry)
        if registry is not None:
            checks["tts_engines"] = registry.ready_status
        else:
            checks["tts_engines"] = "no_registry"
    except Exception as e:
        checks["tts_engines"] = f"error: {e}"

    def _is_healthy(v: str | dict | bool) -> bool:
        if isinstance(v, dict):
            return all(_is_healthy(vv) for vv in v.values())
        if isinstance(v, bool):
            return v
        return v == "ok" or v == "not_configured"

    all_ok = _is_healthy(checks.get("database")) and _is_healthy(checks.get("redis"))
    status_code = 200 if all_ok else 503
    return JSONResponse(
        content={"status": "ready" if all_ok else "not_ready", "checks": checks},
        status_code=status_code,
    )


# ── Global exception handler (QUAL-003: structured error responses) ────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all exception handler returning structured JSON error responses.

    AudiobookError subclasses include error_code and context details.
    Unknown exceptions are logged with traceback and returned as INTERNAL_ERROR.
    """
    import logging
    import traceback

    logger = logging.getLogger("audiobook_studio.errors")

    if hasattr(exc, "error_code") and hasattr(exc, "to_dict"):
        # Structured AudiobookError — return with its error_code
        # Custom exceptions have message, error_code, to_dict(), etc.
        custom_exc: Any = exc
        error_dict = custom_exc.to_dict()
        status_code = _error_code_to_status(custom_exc.error_code)
        logger.error(
            f"Structured error: code={custom_exc.error_code} message={custom_exc.message}",
            extra={"error_code": custom_exc.error_code, "context": getattr(custom_exc, "context", {})},
        )
        return JSONResponse(
            content={"error": error_dict},
            status_code=status_code,
        )
    # Starlette/FastAPI HTTPException — pass through
    from starlette.exceptions import HTTPException as StarletteHTTPException

    if isinstance(exc, StarletteHTTPException):
        return JSONResponse(
            content={"error": {"code": "HTTP_ERROR", "message": exc.detail}},
            status_code=exc.status_code,
        )

    # Unknown exception — log full traceback, return generic 500
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    logger.critical(f"Unhandled exception: {exc}\n{tb}")
    return JSONResponse(
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred. Check server logs for details.",
            }
        },
        status_code=500,
    )


def _error_code_to_status(error_code: str) -> int:
    """Map structured error codes to HTTP status codes."""
    if error_code in ("VALIDATION_ERROR", "SCHEMA_COMPLIANCE_ERROR"):
        return 422
    if error_code in ("FILE_NOT_FOUND",):
        return 404
    if error_code in ("QUOTA_EXCEEDED", "RATE_LIMITED"):
        return 429
    if error_code in ("CIRCUIT_OPEN", "PROVIDER_UNAVAILABLE", "PROVIDER_TIMEOUT"):
        return 503
    if error_code in ("CONFIG_ERROR",):
        return 500
    return 500


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # nosec B104 - standard server binding
