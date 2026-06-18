"""Entry point for the Audiobook Studio FastAPI application.

The application includes routers for all core entities and initializes the
database tables on startup (for the MVP).  In production you would run Alembic
migrations instead of ``init_db``.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.books import router as books_router
from .api.characters import router as characters_router
from .api.config import router as config_router
from .api.export import router as export_router
from .api.paragraphs import router as paragraphs_router
from .api.projects import router as projects_router
from .api.qualities import router as qualities_router
from .api.routings import router as routings_router
from .api.tts_edits import router as tts_edits_router
from .database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables (MVP convenience; production uses Alembic)
    init_db()
    yield
    # Shutdown: nothing to clean up yet


app = FastAPI(title="Audiobook Studio API", version="0.1.0", lifespan=lifespan)

# Include routers
app.include_router(projects_router)
app.include_router(books_router)
app.include_router(characters_router)
app.include_router(config_router)
app.include_router(paragraphs_router)
app.include_router(tts_edits_router)
app.include_router(routings_router)
app.include_router(qualities_router)
app.include_router(export_router)


# Health check endpoint for CI verification
@app.get("/health")
def health_check():
    """Simple health endpoint used by CI to verify the container is running.

    Returns a JSON payload with a status field. This endpoint does not require
    any authentication and is safe to expose in a development environment.
    """
    return {"status": "ok"}
