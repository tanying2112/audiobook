"""Prompt Registry - Pydantic Models for Prompt Version Management.

Provides structured models for:
- Prompt templates with versioning
- A/B experiment configuration
- Langfuse experiment tracking metadata
- Prompt performance metrics
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class PromptStatus(str, Enum):
    """Prompt lifecycle status."""

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class PromptStage(str, Enum):
    """Pipeline stage that the prompt is used for."""

    EXTRACT = "extract"
    ANALYZE_STRUCTURE = "analyze_structure"
    ANNOTATE_PARAGRAPH = "annotate_paragraph"
    EDIT_FOR_TTS = "edit_for_tts"
    TTS_ROUTING = "tts_routing"
    SYNTHESIZE = "synthesize"
    QUALITY_CHECK = "quality_check"
    FEEDBACK_ANALYSIS = "feedback_analysis"


class ExperimentType(str, Enum):
    """Type of prompt experiment."""

    AB_TEST = "ab_test"
    MULTIVARIATE = "multivariate"
    CANARY = "canary"
    GRADUAL_ROLLOUT = "gradual_rollout"


class PromptVersionMetrics(BaseModel):
    """Performance metrics for a prompt version."""

    # Quality metrics
    avg_quality_score: float = Field(default=0.0, ge=0, le=1)
    avg_schema_compliance_rate: float = Field(default=0.0, ge=0, le=1)

    # Cost metrics
    avg_input_tokens: float = Field(default=0.0, ge=0)
    avg_output_tokens: float = Field(default=0.0, ge=0)
    avg_cost_usd: float = Field(default=0.0, ge=0)

    # Latency metrics
    avg_latency_ms: float = Field(default=0.0, ge=0)
    p95_latency_ms: float = Field(default=0.0, ge=0)
    p99_latency_ms: float = Field(default=0.0, ge=0)

    # Error metrics
    error_rate: float = Field(default=0.0, ge=0, le=1)
    retry_rate: float = Field(default=0.0, ge=0, le=1)

    # Usage metrics
    total_uses: int = Field(default=0, ge=0)
    successful_uses: int = Field(default=0, ge=0)


class PromptTemplate(BaseModel):
    """A single prompt template with Jinja2 syntax."""

    template_id: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)  # e.g., "v1", "v2.1"

    # Template content
    system_prompt: str = ""
    user_prompt_template: str = ""

    # Variables expected in the template
    required_variables: List[str] = Field(default_factory=list)
    optional_variables: List[str] = Field(default_factory=list)

    # Format configuration
    response_format: Literal["json", "text", "xml", "markdown"] = "json"
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=1)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    created_by: str = ""
    description: str = ""

    @field_validator("version")
    @classmethod
    def validate_version_format(cls, v: str) -> str:
        if not v.startswith("v"):
            return f"v{v}"
        return v


class PromptVersion(BaseModel):
    """Complete prompt version with template and metadata."""

    # Identity
    prompt_id: str = Field(..., min_length=1)  # e.g., "analyze_structure"
    version: str = Field(..., min_length=1)  # e.g., "v1", "v2"
    stage: PromptStage

    # Template
    template: PromptTemplate

    # Lifecycle
    status: PromptStatus = PromptStatus.DRAFT
    is_default: bool = False  # Whether this is the default version for its stage

    # Langfuse integration
    langfuse_experiment_id: Optional[str] = None
    langfuse_model_id: Optional[str] = None

    # Performance tracking
    metrics: PromptVersionMetrics = Field(default_factory=PromptVersionMetrics)

    # Additional configuration
    fallback_to: Optional[str] = Field(default=None)  # Version to fallback to on failure
    tags: List[str] = Field(default_factory=list)

    # Validation notes
    validation_errors: List[str] = Field(default_factory=list)
    last_validated: Optional[datetime] = None


class ExperimentVariant(BaseModel):
    """A variant in an A/B test experiment."""

    variant_id: str
    prompt_version: str
    traffic_percentage: float = Field(ge=0, le=100)
    description: str = ""


class PromptExperiment(BaseModel):
    """A/B test or multivariate experiment configuration."""

    experiment_id: str
    name: str
    description: str = ""

    # Experiment type
    experiment_type: ExperimentType = ExperimentType.AB_TEST

    # Target stage
    stage: PromptStage

    # Variants
    variants: List[ExperimentVariant]

    # Duration and sampling
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    min_sample_size: int = Field(default=100, ge=1)
    significance_threshold: float = Field(default=0.05, ge=0, le=1)

    # Stopping criteria
    auto_stop_enabled: bool = True
    min_effect_size: float = Field(default=0.01, ge=0)
    max_duration_hours: int = Field(default=168, ge=1)  # 7 days default

    # Results
    status: Literal["running", "completed", "stopped", "failed"] = "running"
    winning_variant: Optional[str] = None
    results_summary: Dict[str, Any] = Field(default_factory=dict)

    # Langfuse tracking
    langfuse_experiment_key: Optional[str] = None

    @field_validator("variants")
    @classmethod
    def validate_traffic_sum(cls, variants: List[ExperimentVariant]) -> List[ExperimentVariant]:
        total = sum(v.traffic_percentage for v in variants)
        if total != 100:
            raise ValueError(f"Traffic percentages must sum to 100, got {total}")
        return variants


class PromptRegistryState(BaseModel):
    """Complete state of the prompt registry."""

    # All registered prompt versions indexed by stage
    versions: Dict[str, Dict[str, PromptVersion]] = Field(default_factory=dict)

    # Active experiments indexed by experiment_id
    experiments: Dict[str, PromptExperiment] = Field(default_factory=dict)

    # Default version for each stage
    defaults: Dict[str, str] = Field(default_factory=dict)  # stage -> version

    # Registry metadata
    last_updated: datetime = Field(default_factory=datetime.now)
    schema_version: str = "1.0"
