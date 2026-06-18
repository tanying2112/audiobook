"""Top‑level package for Audiobook Studio.

The package provides the FastAPI application entry point, the core pipeline
modules and utilities.  Importing this package does not have side effects – it
only exposes sub‑modules for convenient access.
"""

# Import submodules to make them available when importing the package
from . import (
    api,
    config,
    database,
    feedback,
    llm,
    models,
    monitoring,
    observability,
    pipeline,
    publish,
    schemas,
    storage,
    tts,
)
