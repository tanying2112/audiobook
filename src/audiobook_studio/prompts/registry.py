"""Prompt Registry - Core registry implementation with Langfuse integration.

.. deprecated::
    This module is NOT used by the production pipeline. It was the original
    prompt management system based on in-memory state + Langfuse A/B testing.

    **Replacement:** Use ``src/audiobook_studio/feedback/release.VersionStore``
    for file-based prompt version tracking and rollback. Use
    ``src/audiobook_studio/feedback/release.PromotionGate`` for promotion
    criteria. Both are already integrated into the HARNESS console API
    (``api/harness.py``) and the self-iteration loop
    (``feedback/integration.py``).

    This module is retained only for backward compatibility with existing tests
    (``tests/unit/test_prompts_init.py``, ``tests/e2e/test_full_pipeline.py``)
    and as reference for Langfuse experiment tracking patterns.

Provides:
- Prompt template registration and versioning
- A/B experiment management
- Langfuse experiment tracking
- Traffic routing between variants
"""

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from .models import (
    ExperimentType,
    ExperimentVariant,
    PromptExperiment,
    PromptRegistryState,
    PromptStage,
    PromptStatus,
    PromptTemplate,
    PromptVersion,
    PromptVersionMetrics,
)

logger = logging.getLogger(__name__)


class PromptRegistry:
    """Central registry for prompt templates with version control and A/B testing."""

    def __init__(
        self,
        prompts_dir: Optional[Path] = None,
        langfuse_enabled: bool = False,
        langfuse_public_key: Optional[str] = None,
        langfuse_secret_key: Optional[str] = None,
        langfuse_host: Optional[str] = None,
    ):
        """Initialize the prompt registry.

        Args:
            prompts_dir: Directory containing prompt templates (Jinja2 .j2 files)
            langfuse_enabled: Whether to enable Langfuse experiment tracking
            langfuse_public_key: Langfuse public key
            langfuse_secret_key: Langfuse secret key
            langfuse_host: Langfuse host URL
        """
        self.prompts_dir = prompts_dir
        self._state = PromptRegistryState()
        self._langfuse_enabled = langfuse_enabled
        self._langfuse_client = None

        if langfuse_enabled:
            self._init_langfuse(
                public_key=langfuse_public_key,
                secret_key=langfuse_secret_key,
                host=langfuse_host,
            )

    def _init_langfuse(
        self,
        public_key: Optional[str],
        secret_key: Optional[str],
        host: Optional[str],
    ) -> None:
        """Initialize Langfuse client for experiment tracking."""
        try:
            from langfuse import Langfuse

            kwargs = {}
            if public_key:
                kwargs["public_key"] = public_key
            if secret_key:
                kwargs["secret_key"] = secret_key
            if host:
                kwargs["host"] = host
            self._langfuse_client = Langfuse(**kwargs)
            logger.info("Langfuse initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize Langfuse: {e}")
            self._langfuse_enabled = False

    def register_template(
        self,
        prompt_id: str,
        stage: PromptStage,
        version: str,
        template_content: str,
        system_prompt: str = "",
        required_variables: Optional[List[str]] = None,
        optional_variables: Optional[List[str]] = None,
        description: str = "",
        created_by: str = "system",
        response_format: str = "json",
        is_default: bool = False,
        tags: Optional[List[str]] = None,
    ) -> PromptVersion:
        """Register a new prompt template version.

        Args:
            prompt_id: Unique identifier for the prompt (e.g., "analyze_structure")
            stage: Pipeline stage this prompt is used for
            version: Version string (e.g., "v1", "v2.1")
            template_content: Jinja2 template content for user prompt
            system_prompt: System prompt content
            required_variables: List of required template variables
            optional_variables: List of optional template variables
            description: Human-readable description
            created_by: Creator identifier
            response_format: Expected response format (json/text/xml/markdown)
            is_default: Whether this should be the default version
            tags: Optional tags for categorization

        Returns:
            The registered PromptVersion
        """
        template = PromptTemplate(
            template_id=f"{prompt_id}_{version}",
            version=version,
            system_prompt=system_prompt,
            user_prompt_template=template_content,
            required_variables=required_variables or [],
            optional_variables=optional_variables or [],
            response_format=response_format,
            created_by=created_by,
            description=description,
        )

        prompt_version = PromptVersion(
            prompt_id=prompt_id,
            version=version,
            stage=stage,
            template=template,
            status=PromptStatus.ACTIVE,
            is_default=is_default,
            tags=tags or [],
        )

        # Store in registry
        if stage.value not in self._state.versions:
            self._state.versions[stage.value] = {}

        self._state.versions[stage.value][version] = prompt_version

        # Update default if marked
        if is_default:
            self._state.defaults[stage.value] = version

        self._state.last_updated = datetime.now()
        logger.info(f"Registered prompt {prompt_id}/{version} for stage {stage.value}")

        return prompt_version

    def register_from_file(
        self,
        prompt_id: str,
        stage: PromptStage,
        version: str,
        file_path: Path,
        **kwargs,
    ) -> PromptVersion:
        """Register a prompt template from a file.

        Args:
            prompt_id: Unique identifier for the prompt
            stage: Pipeline stage
            version: Version string
            file_path: Path to the .j2 template file
            **kwargs: Additional arguments passed to register_template

        Returns:
            The registered PromptVersion
        """
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        return self.register_template(
            prompt_id=prompt_id,
            stage=stage,
            version=version,
            template_content=content,
            **kwargs,
        )

    def get_version(
        self,
        stage: PromptStage,
        version: Optional[str] = None,
    ) -> Optional[PromptVersion]:
        """Get a specific prompt version.

        Args:
            stage: Pipeline stage
            version: Specific version (if None, returns default)

        Returns:
            PromptVersion or None if not found
        """
        if stage.value not in self._state.versions:
            return None

        if version is None:
            version = self._state.defaults.get(stage.value)
            if version is None:
                return None

        return self._state.versions[stage.value].get(version)

    def get_active_experiment(
        self,
        stage: PromptStage,
    ) -> Optional[PromptExperiment]:
        """Get the active experiment for a stage.

        Args:
            stage: Pipeline stage

        Returns:
            Active PromptExperiment or None
        """
        for exp in self._state.experiments.values():
            if exp.stage == stage and exp.status == "running":
                return exp
        return None

    def select_version_for_request(
        self,
        stage: PromptStage,
        request_id: str,
    ) -> PromptVersion:
        """Select a prompt version for a request (considering experiments).

        Args:
            stage: Pipeline stage
            request_id: Request identifier for consistent hashing

        Returns:
            Selected PromptVersion

        Raises:
            ValueError: If no version is available
        """
        # Check for active experiment
        experiment = self.get_active_experiment(stage)
        if experiment:
            variant = self._get_experiment_variant(experiment, request_id)
            version = self.get_version(stage, variant.prompt_version)
            if version:
                return version

        # Fall back to default
        version = self.get_version(stage)
        if version is None:
            raise ValueError(f"No prompt version available for stage {stage.value}")

        return version

    def _get_experiment_variant(
        self,
        experiment: PromptExperiment,
        request_id: str,
    ) -> ExperimentVariant:
        """Determine which experiment variant to use via consistent hashing.

        Args:
            experiment: Active experiment
            request_id: Request identifier

        Returns:
            Selected ExperimentVariant
        """
        # Hash request_id to get a number 0-100
        # Use SHA256 with usedforsecurity=False for experiment bucketing (non-cryptographic)
        hash_value = int(hashlib.sha256(request_id.encode(), usedforsecurity=False).hexdigest()[:8], 16) % 100

        cumulative = 0
        for variant in experiment.variants:
            cumulative += variant.traffic_percentage
            if hash_value < cumulative:
                return variant

        # Fallback to last variant
        return experiment.variants[-1]

    def create_experiment(
        self,
        experiment_id: str,
        name: str,
        stage: PromptStage,
        variants: List[Dict[str, Any]],
        experiment_type: ExperimentType = ExperimentType.AB_TEST,
        description: str = "",
        **kwargs,
    ) -> PromptExperiment:
        """Create a new A/B test experiment.

        Args:
            experiment_id: Unique experiment identifier
            name: Human-readable name
            stage: Pipeline stage to test
            variants: List of variant configs with {variant_id, prompt_version, traffic_percentage}
            experiment_type: Type of experiment
            description: Experiment description
            **kwargs: Additional config (min_sample_size, max_duration_hours, etc.)

        Returns:
            Created PromptExperiment
        """
        variant_objects = [
            ExperimentVariant(
                variant_id=v["variant_id"],
                prompt_version=v["prompt_version"],
                traffic_percentage=v["traffic_percentage"],
                description=v.get("description", ""),
            )
            for v in variants
        ]

        experiment = PromptExperiment(
            experiment_id=experiment_id,
            name=name,
            description=description,
            experiment_type=experiment_type,
            stage=stage,
            variants=variant_objects,
            **kwargs,
        )

        self._state.experiments[experiment_id] = experiment
        logger.info(f"Created experiment {experiment_id} for stage {stage.value}")

        # Track in Langfuse if enabled
        if self._langfuse_enabled:
            self._track_experiment_start(experiment)

        return experiment

    def _track_experiment_start(self, experiment: PromptExperiment) -> None:
        """Track experiment start in Langfuse."""
        if not self._langfuse_client:
            return

        try:
            self._langfuse_client.create_experiment(
                id=experiment.experiment_id,
                name=experiment.name,
                metadata={
                    "stage": experiment.stage.value,
                    "type": experiment.experiment_type.value,
                    "variants": [v.model_dump() for v in experiment.variants],
                },
            )
        except Exception as e:
            logger.warning(f"Failed to track experiment in Langfuse: {e}")

    def complete_experiment(
        self,
        experiment_id: str,
        winning_variant: Optional[str] = None,
        results: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Mark an experiment as completed.

        Args:
            experiment_id: Experiment identifier
            winning_variant: Winning variant ID (if determined)
            results: Results summary
        """
        if experiment_id not in self._state.experiments:
            raise ValueError(f"Experiment {experiment_id} not found")

        experiment = self._state.experiments[experiment_id]
        experiment.status = "completed"
        experiment.winning_variant = winning_variant
        if results:
            experiment.results_summary = results

        # Update default if winner determined
        if winning_variant:
            self._state.defaults[experiment.stage.value] = winning_variant

        logger.info(f"Completed experiment {experiment_id}, winner: {winning_variant}")

        # Track in Langfuse if enabled
        if self._langfuse_enabled and self._langfuse_client:
            try:
                self._langfuse_client.update_experiment(
                    experiment_id,
                    metadata={
                        "status": "completed",
                        "winning_variant": winning_variant,
                        "results": results,
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to update experiment in Langfuse: {e}")

    def update_metrics(
        self,
        stage: PromptStage,
        version: str,
        metrics: Dict[str, Any],
    ) -> None:
        """Update performance metrics for a prompt version.

        Args:
            stage: Pipeline stage
            version: Prompt version
            metrics: Metrics dict with keys like avg_quality_score, total_uses, etc.
        """
        prompt_version = self.get_version(stage, version)
        if prompt_version is None:
            logger.warning(f"Cannot update metrics: {stage.value}/{version} not found")
            return

        # Update metrics
        for key, value in metrics.items():
            if hasattr(prompt_version.metrics, key):
                setattr(prompt_version.metrics, key, value)

    def render_prompt(
        self,
        stage: PromptStage,
        version: Optional[str] = None,
        request_id: Optional[str] = None,
        **variables,
    ) -> Tuple[str, str]:
        """Render a prompt template with variables.

        Args:
            stage: Pipeline stage
            version: Specific version (None = auto-select via experiment)
            request_id: Request ID for experiment routing
            **variables: Template variables

        Returns:
            Tuple of (system_prompt, rendered_user_prompt)

        Raises:
            ValueError: If version not found or rendering fails
        """
        from jinja2 import Template, TemplateError

        if version is None:
            if request_id is None:
                raise ValueError("request_id required when version is None (for experiment routing)")
            prompt_version = self.select_version_for_request(stage, request_id)
        else:
            prompt_version = self.get_version(stage, version)
            if prompt_version is None:
                raise ValueError(f"Prompt version {stage.value}/{version} not found")

        try:
            user_template = Template(prompt_version.template.user_prompt_template)
            rendered_user = user_template.render(**variables)

            system_template = Template(prompt_version.template.system_prompt)
            rendered_system = system_template.render(**variables)

            return rendered_system, rendered_user

        except TemplateError as e:
            logger.error(f"Failed to render prompt {stage.value}/{prompt_version.version}: {e}")
            raise ValueError(f"Template rendering failed: {e}")

    def load_prompts_from_directory(self) -> int:
        """Load all .j2 templates from the prompts directory.

        Returns:
            Number of templates loaded
        """
        if not self.prompts_dir or not self.prompts_dir.exists():
            logger.warning(f"Prompts directory not found: {self.prompts_dir}")
            return 0

        count = 0
        for stage_dir in self.prompts_dir.iterdir():
            if not stage_dir.is_dir():
                continue

            stage_name = stage_dir.name
            try:
                stage = PromptStage(stage_name.replace("_", "-"))
            except ValueError:
                logger.debug(f"Skipping unknown stage directory: {stage_name}")
                continue

            for template_file in stage_dir.glob("*.j2"):
                # Extract version from filename (e.g., v1.j2, v2.j2)
                version = template_file.stem

                try:
                    self.register_from_file(
                        prompt_id=stage_name,
                        stage=stage,
                        version=version,
                        file_path=template_file,
                        is_default=True,  # Last loaded becomes default
                    )
                    count += 1
                except Exception as e:
                    logger.error(f"Failed to load {template_file}: {e}")

        logger.info(f"Loaded {count} prompt templates from {self.prompts_dir}")
        return count

    def list_versions(self, stage: Optional[PromptStage] = None) -> Dict[str, List[str]]:
        """List all registered prompt versions.

        Args:
            stage: Filter by stage (None = all stages)

        Returns:
            Dict mapping stage -> list of versions
        """
        if stage:
            return {stage.value: list(self._state.versions.get(stage.value, {}).keys())}
        return {stage: list(versions.keys()) for stage, versions in self._state.versions.items()}

    @property
    def state(self) -> PromptRegistryState:
        """Get current registry state."""
        return self._state.model_copy()


# Global registry instance (lazy initialization)
_registry: Optional[PromptRegistry] = None


def get_prompt_registry(**kwargs) -> PromptRegistry:
    """Get or create the global prompt registry.

    Args:
        **kwargs: Arguments passed to PromptRegistry constructor

    Returns:
        PromptRegistry instance
    """
    global _registry
    if _registry is None:
        _registry = PromptRegistry(**kwargs)
    return _registry
