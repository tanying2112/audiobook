"""Prompt Registry Package.

.. deprecated::
    This package is NOT used by the production pipeline. Use
    ``src.audiobook_studio.feedback.release`` instead.

Provides versioned prompt template management with:
- Jinja2 template rendering
- A/B experiment support
- Langfuse experiment tracking
- Performance metrics collection
"""

from .models import (
    PromptVersion,
    PromptTemplate,
    PromptStage,
    PromptStatus,
    PromptExperiment,
    ExperimentVariant,
    ExperimentType,
    PromptRegistryState,
    PromptVersionMetrics,
)

from .registry import (
    PromptRegistry,
    get_prompt_registry,
)

__all__ = [
    # Models
    "PromptVersion",
    "PromptTemplate",
    "PromptStage",
    "PromptStatus",
    "PromptExperiment",
    "ExperimentVariant",
    "ExperimentType",
    "PromptRegistryState",
    "PromptVersionMetrics",
    # Registry
    "PromptRegistry",
    "get_prompt_registry",
]