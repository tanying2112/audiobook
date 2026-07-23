"""LLM utilities - shared validation and parsing utilities.

This module contains common utilities used by both client and router
to avoid circular imports.
"""

import json
from typing import Any, Dict, Protocol, Type, TypeVar

T = TypeVar("T")


class SupportsModelValidate(Protocol):
    """Protocol for Pydantic models with model_validate method."""

    @classmethod
    def model_validate(cls: type[T], obj: Any) -> T: ...


class LLMParseError(Exception):
    """Raised when LLM response cannot be parsed as valid JSON or fails schema validation."""

    def __init__(self, message: str, raw_response: str = "", stage: str = ""):
        super().__init__(message)
        self.raw_response = raw_response
        self.stage = stage


def validate_and_parse_llm_response(
    raw_response: Any, response_model: type[SupportsModelValidate], stage: str
) -> SupportsModelValidate:
    """
    Pre-validate LLM response before Pydantic model validation.

    Raises LLMParseError if:
    - Response is None or empty
    - Response is not a dict (after JSON parsing)
    - Response is empty dict {}
    - Response is missing required 'segment_id' field for judge stage
    """
    # Handle None or empty response
    if raw_response is None:
        raise LLMParseError("LLM returned None response", raw_response=str(raw_response), stage=stage)

    # Handle empty string
    if isinstance(raw_response, str):
        if not raw_response.strip():
            raise LLMParseError(
                "LLM returned empty string response",
                raw_response=raw_response,
                stage=stage,
            )
        # Try to parse JSON string
        try:
            raw_response = json.loads(raw_response)
        except json.JSONDecodeError as e:
            raise LLMParseError(
                f"LLM returned invalid JSON: {e}",
                raw_response=raw_response,
                stage=stage,
            )

    # Ensure it's a dict
    if not isinstance(raw_response, dict):
        raise LLMParseError(
            f"LLM response is not a JSON object: got {type(raw_response).__name__}",
            raw_response=str(raw_response),
            stage=stage,
        )

    # Check for empty dict
    if not raw_response:
        raise LLMParseError("LLM returned empty JSON object {}", raw_response="{}", stage=stage)

    # Stage-specific validation
    if stage == "judge":
        if "segment_id" not in raw_response or not raw_response["segment_id"]:
            raise LLMParseError(
                "LLM response missing required 'segment_id' field for judge stage",
                raw_response=json.dumps(raw_response, ensure_ascii=False),
                stage=stage,
            )

    # Validate against Pydantic model if it has model_validate method
    if hasattr(response_model, "model_validate"):
        return response_model.model_validate(raw_response)
    return raw_response  # type: ignore[return-value]
