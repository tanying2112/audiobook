"""Top‑level package for Audiobook Studio.

The package provides the FastAPI application entry point, the core pipeline
modules and utilities.  Importing this package does not have side effects – it
only exposes sub‑modules for convenient access.
"""

# Import submodules to make them available when importing the package
# Note: config, database, and observability are NOT imported here to avoid
# circular dependencies. Import them directly from their modules instead.
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
