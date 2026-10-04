"""Pydantic schemas for dynamic supplier management."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

# ── Provider Schemas ──────────────────────────────────────────────────────


class ProviderCreate(BaseModel):
    """Schema for creating a new provider."""

    name: str = Field(..., description="Unique provider name")
    display_name: Optional[str] = Field(None, description="Human-readable display name")
    description: Optional[str] = Field(None, description="Provider description")
    provider_type: str = Field(
        ..., description="Type of provider (e.g., openai, anthropic, nvidia_nemotron, fcc_gateway)"
    )
    api_base: Optional[str] = Field(None, description="API base URL")
    api_key: Optional[str] = Field(None, description="API authentication key")
    auth_type: str = Field("bearer", description="Authentication type (bearer, api_key, none)")
    default_model: Optional[str] = Field(None, description="Default model name")
    max_tokens: int = Field(4000, description="Maximum tokens per request")
    temperature: float = Field(0.1, description="Temperature for sampling")
    is_enabled: bool = Field(True, description="Whether the provider is enabled")
    sort_priority: int = Field(100, description="Sort priority (lower = higher priority)")


class ProviderUpdate(BaseModel):
    """Schema for updating a provider."""

    display_name: Optional[str] = Field(None, description="Human-readable display name")
    description: Optional[str] = Field(None, description="Provider description")
    provider_type: Optional[str] = Field(None, description="Type of provider")
    api_base: Optional[str] = Field(None, description="API base URL")
    api_key: Optional[str] = Field(None, description="API authentication key")
    auth_type: Optional[str] = Field(None, description="Authentication type")
    default_model: Optional[str] = Field(None, description="Default model name")
    max_tokens: Optional[int] = Field(None, description="Maximum tokens per request")
    temperature: Optional[float] = Field(None, description="Temperature for sampling")
    is_enabled: Optional[bool] = Field(None, description="Whether the provider is enabled")
    sort_priority: Optional[int] = Field(None, description="Sort priority")


class ProviderOut(BaseModel):
    """Schema for provider API response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    display_name: Optional[str]
    description: Optional[str]
    provider_type: str
    api_base: Optional[str]
    api_key: Optional[str]  # Note: In real implementation, consider masking this
    auth_type: str
    default_model: Optional[str]
    max_tokens: int
    temperature: float
    is_enabled: bool
    sort_priority: int
    created_by: Optional[str]

    # Computed fields
    model_count: int = Field(default=0, description="Number of models under this provider")


# ── Model Schemas ─────────────────────────────────────────────────────────


class ModelCreate(BaseModel):
    """Schema for creating a new model."""

    name: str = Field(..., description="Unique model name")
    provider_id: int = Field(..., description="ID of the parent provider")
    model_id: Optional[str] = Field(None, description="External model ID (e.g., gpt-4o)")
    version: Optional[str] = Field(None, description="Model version")
    context_window: int = Field(128000, description="Context window size")
    instructions: Optional[Dict[str, Any]] = Field(None, description="System instructions")
    parameters: Optional[Dict[str, Any]] = Field(None, description="Additional parameters")
    is_enabled: bool = Field(True, description="Whether the model is enabled")
    sort_priority: int = Field(100, description="Sort priority")


class ModelUpdate(BaseModel):
    """Schema for updating a model."""

    name: Optional[str] = Field(None, description="Model name")
    provider_id: Optional[int] = Field(None, description="Parent provider ID")
    model_id: Optional[str] = Field(None, description="External model ID")
    version: Optional[str] = Field(None, description="Model version")
    context_window: Optional[int] = Field(None, description="Context window size")
    instructions: Optional[Dict[str, Any]] = Field(None, description="System instructions")
    parameters: Optional[Dict[str, Any]] = Field(None, description="Additional parameters")
    is_enabled: Optional[bool] = Field(None, description="Whether the model is enabled")
    sort_priority: Optional[int] = Field(None, description="Sort priority")


class ModelOut(BaseModel):
    """Schema for model API response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider_id: int
    model_id: Optional[str]
    version: Optional[str]
    context_window: int
    instructions: Optional[Dict[str, Any]]
    parameters: Optional[Dict[str, Any]]
    is_enabled: bool
    sort_priority: int

    # Computed/Nested fields
    provider_name: Optional[str] = Field(None, description="Parent provider name")


# ── Response Schemas ──────────────────────────────────────────────────────


class ProviderListResponse(BaseModel):
    """Response for listing providers."""

    providers: List[ProviderOut]
    total: int
    page: int = 1
    page_size: int = 100


class ModelListResponse(BaseModel):
    """Response for listing models."""

    models: List[ModelOut]
    total: int
    provider_name: Optional[str] = Field(None, description="Parent provider name for context")
