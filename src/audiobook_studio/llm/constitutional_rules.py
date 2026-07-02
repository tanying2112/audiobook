"""Constitutional Rules enforcement for LLM outputs.

This module provides functions to apply constitutional rules (safety, style, format constraints)
to LLM-generated outputs, as described in HARNESS_SPECIFICATIONS.md Execution Layer.
"""

import logging
import re
from typing import Any, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Blocked patterns for content safety
_BLOCKED_PATTERNS = [
    r"(?i)\b(hack|exploit|crack)\s*(password|system|server)",
    r"(?i)\b(illegal|unlawful)\s*(drug|weapon|activity)",
    r"(?i)\b(self-?harm|suicide)\s*(method|guide|instruction)",
]

# Compiled regex for performance
_BLOCKED_RE = [re.compile(p) for p in _BLOCKED_PATTERNS]


def apply_constitutional_rules(response: BaseModel, context: Optional[dict] = None) -> BaseModel:
    """Apply constitutional rules to an LLM response.

    Applies safety filters and returns the response. If the response
    contains a 'text' or 'edited_text' field, it is checked against
    blocked patterns.

    Args:
        response: The Pydantic model instance returned by the LLM.
        context: Optional dictionary with contextual information.

    Returns:
        The (potentially modified) response after applying constitutional rules.
    """
    # Apply safety filters
    response = apply_safety_filters(response)
    return response


def apply_safety_filters(response: BaseModel) -> BaseModel:
    """Apply safety filters to remove or flag harmful content.

    Checks text fields for blocked patterns and clears them if found.
    """
    # Check common text fields
    text_fields = ["text", "edited_text", "content", "answer", "rationale"]
    for field in text_fields:
        if hasattr(response, field):
            value = getattr(response, field)
            if isinstance(value, str) and value:
                for pattern in _BLOCKED_RE:
                    if pattern.search(value):
                        logger.warning(
                            "Constitutional rule violation: blocked pattern in '%s'",
                            field,
                        )
                        # Replace matched content with [FILTERED]
                        cleaned = pattern.sub("[FILTERED]", value)
                        try:
                            setattr(response, field, cleaned)
                        except Exception:
                            # Some models may be frozen
                            pass
                        break
    return response


def apply_style_guidelines(response: BaseModel, style_guide: Optional[dict] = None) -> BaseModel:
    """Apply style guidelines (tone, formality, etc.) to the response."""
    # Future: implement style enforcement based on style_guide
    return response


def apply_domain_constraints(response: BaseModel, domain: Optional[str] = None) -> BaseModel:
    """Apply domain-specific constraints (e.g., medical, legal, financial)."""
    # Future: implement domain-specific rules
    return response
