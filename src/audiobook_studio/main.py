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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.ab_test_interceptor import ABTestMiddleware
from .api.audio_segments import router as audio_segments_router
from .api.auto_run import router as auto_run_router
from .api.books import router as books_router
from .api.characters import router as characters_router
from .api.config import router as config_router
from .api.export import router as export_router
from .api.feedback import router as feedback_router
from .api.golden import router as golden_router
from .api.harness import router as harness_router
from .api.llm import router as llm_router
from .api.mock_router import router as mock_router
from .api.paragraphs import router as paragraphs_router
from .api.pipeline import router as pipeline_router
from .api.projects import router as projects_router
from .api.publish import router as publish_router
from .api.qualities import router as qualities_router
from .api.routings import router as routings_router
from .api.templates import router as templates_router
from .api.tts_edits import router as tts_edits_router
from .api.tts_voices import router as tts_voices_router
from .api.upload import router as upload_router
from .api.websocket import router as websocket_router
from .auth.router import router as auth_router
from .config import get_settings
from .database import init_db
from .middleware.timestamp import ISOTimestampMiddleware
from .observability import instrument_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables (MVP convenience; production uses Alembic)
    init_db()
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

# CORS middleware
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add ISO Timestamp Middleware (P1-8)
# Disabled: BaseHTTPMiddleware incompatible with Python 3.14 + Starlette 0.36
# app.add_middleware(ISOTimestampMiddleware)

# Add A/B Test Middleware
# Disabled: BaseHTTPMiddleware incompatible with Python 3.14 + Starlette 0.36
# app.add_middleware(ABTestMiddleware)

# Instrument with OpenTelemetry
# Disabled: ObservabilityMiddleware uses BaseHTTPMiddleware incompatible with Python 3.14
# instrument_app(
#     app,
#     service_name="audiobook-studio",
#     service_version="0.1.0",
#     otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
#     enable_console_exporter=os.getenv("OTEL_CONSOLE_EXPORTER", "false").lower()
#     == "true",
#     prometheus_port=int(os.getenv("PROMETHEUS_PORT", "9090")),
#     exclude_paths=["/health", "/metrics", "/docs", "/openapi.json", "/redoc"],
# )

# Include routers
app.include_router(auth_router, prefix="/api")  # Auth endpoints at /api/auth/*
app.include_router(projects_router, prefix="/api")
app.include_router(books_router, prefix="/api")
app.include_router(characters_router, prefix="/api")
app.include_router(config_router, prefix="/api")
app.include_router(paragraphs_router, prefix="/api")
app.include_router(tts_edits_router, prefix="/api")
app.include_router(routings_router, prefix="/api")
app.include_router(qualities_router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(feedback_router, prefix="/api")
app.include_router(audio_segments_router, prefix="/api")
app.include_router(llm_router, prefix="/api")
app.include_router(websocket_router, prefix="/api")
app.include_router(templates_router, prefix="/api")
app.include_router(harness_router, prefix="/api")
app.include_router(golden_router, prefix="/api")
app.include_router(auto_run_router, prefix="/api")
if settings.DEBUG or settings.ENVIRONMENT == "development":
    app.include_router(mock_router, prefix="/api")
app.include_router(tts_voices_router, prefix="/api")
app.include_router(publish_router, prefix="/api")
app.include_router(upload_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")


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

    uvicorn.run(app, host="0.0.0.0", port=8000)
