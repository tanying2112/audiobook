"""Entry point for the Audiobook Studio FastAPI application.

The application includes routers for all core entities and initializes the
database tables on startup (for the MVP).  In production you would run Alembic
migrations instead of ``init_db``.
"""

import os

# Disable mock mode for all pipelines before any pipeline modules are imported
# unless overridden by environment variable
if "MOCK_LLM" not in os.environ:
    os.environ["MOCK_LLM"] = "false"

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
from .api.upload import router as upload_router
from .api.websocket import router as websocket_router
from .auth.dependencies import get_current_active_user
from .auth.router import router as auth_router
from .config import get_settings
from .middleware.timestamp import ISOTimestampMiddleware
from .observability import instrument_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: validate critical security settings FIRST
    from .config import get_settings

    settings = get_settings()
    # P0-2: Explicit JWT secret validation (defense-in-depth; also runs in get_settings())
    settings.validate_jwt_secret()
    # P0-3: Explicit CORS security validation
    settings.validate_cors_security()

    # P1-4: Use Alembic for DB migrations instead of create_all()
    # This ensures migrations are applied and Alembic version table is tracked
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


app = FastAPI(
    title="Audiobook Studio API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS middleware - P0-3: Use explicit allow_methods from settings instead of "*"
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)

# Add ISO Timestamp Middleware (P1-8)
app.add_middleware(ISOTimestampMiddleware)

# Add A/B Test Middleware
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
app.include_router(sop_reflection_router, dependencies=auth_dep)


# Health check endpoint for CI verification
@app.get("/health")
def health_check():
    """Simple health endpoint used by CI to verify the container is running.

    Returns a JSON payload with a status field. This endpoint does not require
    any authentication and is safe to expose in a development environment.
    """
    return {"status": "ok"}


# Detailed health check
@app.get("/health/detailed")
def detailed_health_check():
    """Detailed health check with component status."""
    from .auth.jwt_handler import jwt_handler
    from .database import SessionLocal

    db = SessionLocal()
    db_status = "ok"
    try:
        from sqlalchemy import text

        db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {e}"
    finally:
        db.close()

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "database": db_status,
        "version": "0.1.0",
    }


@app.get("/health/db")
def health_db():
    """Database health check for CI."""
    from sqlalchemy import text

    from .database import SessionLocal

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": str(e)}
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # nosec B104 - standard server binding
