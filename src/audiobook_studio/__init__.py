"""Top‑level package for Audiobook Studio.

The package provides the FastAPI application entry point, the core pipeline
modules and utilities.  Importing this package does not have side effects – it
only exposes sub‑modules for convenient access.
"""

# Import submodules to make them available when importing the package
# Note: config, database, and observability are imported lazily to avoid
# pulling in optional dependencies (opentelemetry, etc.) at import time.
from . import (
    api,
    audio_quality,
    exceptions,
    feedback,
    llm,
    models,
    monitoring,
    pipeline,
    publish,
    schemas,
    storage,
    tts,
)

# Export common exception classes for convenient access
from .exceptions import (
    AudiobookError,
    CircuitOpenError,
    DomainError,
    InfrastructureError,
    PipelineError,
    ProviderError,
    QuotaExceededError,
    RateLimitError,
    SchemaComplianceError,
    StageExecutionError,
    TTSError,
    ValidationError,
)


# Lazy import functions for config, database, and observability
def get_config():
    """Lazy import of config module to avoid circular dependencies."""
    from . import config

    return config


def get_database():
    """Lazy import of database module to avoid circular dependencies."""
    from . import database

    return database


def get_observability():
    """Lazy import of observability module to avoid optional dependencies."""
    from . import observability

    return observability
