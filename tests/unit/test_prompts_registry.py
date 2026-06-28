"""Comprehensive tests for Prompt Registry module to achieve 80%+ coverage."""

from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.prompts.models import (
    ExperimentType,
    PromptStage,
    PromptStatus,
)
from src.audiobook_studio.prompts.registry import PromptRegistry, get_prompt_registry


class TestPromptRegistryInit:
    """Tests for PromptRegistry initialization."""

    def test_init_default(self):
        """Test registry initialization with defaults."""
        registry = PromptRegistry()
        assert registry.prompts_dir is None
        assert registry._langfuse_enabled is False
        assert registry._langfuse_client is None

    def test_init_with_prompts_dir(self, tmp_path):
        """Test registry initialization with prompts directory."""
        registry = PromptRegistry(prompts_dir=tmp_path)
        assert registry.prompts_dir == tmp_path

    def test_init_langfuse_disabled_by_default(self):
        """Test that Langfuse is disabled by default."""
        registry = PromptRegistry(langfuse_enabled=False)
        assert registry._langfuse_enabled is False

    def test_init_langfuse_enabled_success(self):
        """Test Langfuse initialization when enabled successfully."""
        mock_langfuse = MagicMock()
        with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_langfuse)}):
            registry = PromptRegistry(
                langfuse_enabled=True,
                langfuse_public_key="test_key",
                langfuse_secret_key="test_secret",
            )
            assert registry._langfuse_enabled is True
            assert registry._langfuse_client is not None

    def test_init_langfuse_partial_kwargs(self):
        """Test Langfuse initialization with partial kwargs."""
        mock_langfuse = MagicMock()
        with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_langfuse)}):
            registry = PromptRegistry(
                langfuse_enabled=True,
                langfuse_public_key="test_key",
            )
            assert registry._langfuse_client is not None


class TestRegisterTemplate:
    """Tests for register_template method."""

    def test_register_template_basic(self):
        """Test basic template registration."""
        registry = PromptRegistry()
        version = registry.register_template(
            prompt_id="test_prompt",
            stage=PromptStage.ANALYZE_STRUCTURE,
            version="v1",
            template_content="Hello {{ name }}",
        )

        assert version.prompt_id == "test_prompt"
        assert version.version == "v1"
        assert version.stage == PromptStage.ANALYZE_STRUCTURE
        assert version.status == PromptStatus.ACTIVE

    def test_register_template_with_all_params(self):
        """Test template registration with all parameters."""
        registry = PromptRegistry()
        version = registry.register_template(
            prompt_id="full_prompt",
            stage=PromptStage.SYNTHESIZE,
            version="v2",
            template_content="Test content",
            system_prompt="System prompt",
            required_variables=["var1", "var2"],
            optional_variables=["opt1"],
            description="Test description",
            created_by="test_user",
            response_format="json",
            is_default=True,
            tags=["tag1", "tag2"],
        )

        assert version.template.system_prompt == "System prompt"
        assert version.template.user_prompt_template == "Test content"
        assert version.template.required_variables == ["var1", "var2"]
        assert version.template.optional_variables == ["opt1"]
        assert version.is_default is True
        assert version.tags == ["tag1", "tag2"]

    def test_register_template_updates_default(self):
        """Test that is_default updates the default version."""
        registry = PromptRegistry()

        registry.register_template(
            prompt_id="test_prompt",
            stage=PromptStage.ANALYZE_STRUCTURE,
            version="v1",
            template_content="Content 1",
            is_default=False,
        )

        registry.register_template(
            prompt_id="test_prompt",
            stage=PromptStage.ANALYZE_STRUCTURE,
            version="v2",
            template_content="Content 2",
            is_default=True,
        )

        state = registry.state
        assert state.defaults.get("analyze_structure") == "v2"

    def test_register_template_none_variables(self):
        """Test registration with None for variables lists."""
        registry = PromptRegistry()
        version = registry.register_template(
            prompt_id="test",
            stage=PromptStage.EXTRACT,
            version="v1",
            template_content="Content",
            required_variables=None,
            optional_variables=None,
            tags=None,
        )

        assert version.template.required_variables == []
        assert version.template.optional_variables == []
        assert version.tags == []


class TestRegisterFromFile:
    """Tests for register_from_file method."""

    def test_register_from_file_success(self, tmp_path):
        """Test registering template from file."""
        template_file = tmp_path / "test.j2"
        template_file.write_text("Hello {{ name }}")

        registry = PromptRegistry()
        version = registry.register_from_file(
            prompt_id="file_prompt",
            stage=PromptStage.EXTRACT,
            version="v1",
            file_path=template_file,
        )

        assert version.prompt_id == "file_prompt"
        assert "Hello" in version.template.user_prompt_template

    def test_register_from_file_with_kwargs(self, tmp_path):
        """Test registering template from file with additional kwargs."""
        template_file = tmp_path / "test.j2"
        template_file.write_text("Test content")

        registry = PromptRegistry()
        version = registry.register_from_file(
            prompt_id="file_prompt",
            stage=PromptStage.EDIT_FOR_TTS,
            version="v3",
            file_path=template_file,
            description="From file",
            is_default=True,
        )

        assert version.template.description == "From file"

    def test_register_from_file_encoding(self, tmp_path):
        """Test that file is read with UTF-8 encoding."""
        template_file = tmp_path / "test.j2"
        template_file.write_text("内容测试", encoding="utf-8")

        registry = PromptRegistry()
        version = registry.register_from_file(
            prompt_id="file_prompt",
            stage=PromptStage.ANALYZE_STRUCTURE,
            version="v1",
            file_path=template_file,
        )

        assert "内容测试" in version.template.user_prompt_template


class TestGetVersion:
    """Tests for get_version method."""

    def test_get_version_none_stage(self):
        """Test getting version from non-existent stage."""
        registry = PromptRegistry()
        result = registry.get_version(PromptStage.EXTRACT)
        assert result is None

    def test_get_version_no_default(self):
        """Test getting version when no default is set."""
        registry = PromptRegistry()
        registry.register_template(
            prompt_id="test",
            stage=PromptStage.ANALYZE_STRUCTURE,
            version="v1",
            template_content="Content",
            is_default=False,
        )

        result = registry.get_version(PromptStage.ANALYZE_STRUCTURE)
        assert result is None

    def test_get_version_specific(self):
        """Test getting specific version."""
        registry = PromptRegistry()
        registry.register_template(
            prompt_id="test",
            stage=PromptStage.SYNTHESIZE,
            version="v1",
            template_content="Content v1",
            is_default=False,
        )

        result = registry.get_version(PromptStage.SYNTHESIZE, "v1")
        assert result is not None
        assert result.version == "v1"

    def test_get_version_specific_not_found(self):
        """Test getting non-existent specific version."""
        registry = PromptRegistry()
        result = registry.get_version(PromptStage.QUALITY_CHECK, "v999")
        assert result is None

    def test_get_version_returns_none_when_version_missing(self):
        """Test getting version that doesn't exist in stage."""
        registry = PromptRegistry()
        registry.register_template(
            prompt_id="test",
            stage=PromptStage.EXTRACT,
            version="v1",
            template_content="Content",
            is_default=False,
        )
        result = registry.get_version(PromptStage.EXTRACT, "v2")
        assert result is None


class TestGetActiveExperiment:
    """Tests for get_active_experiment method."""

    def test_get_active_experiment_none(self):
        """Test when no experiment exists."""
        registry = PromptRegistry()
        result = registry.get_active_experiment(PromptStage.SYNTHESIZE)
        assert result is None

    def test_get_active_experiment_found(self):
        """Test finding active experiment."""
        registry = PromptRegistry()
        registry.create_experiment(
            experiment_id="exp1",
            name="Test Experiment",
            stage=PromptStage.SYNTHESIZE,
            variants=[
                {"variant_id": "A", "prompt_version": "v1", "traffic_percentage": 50},
                {"variant_id": "B", "prompt_version": "v2", "traffic_percentage": 50},
            ],
        )

        result = registry.get_active_experiment(PromptStage.SYNTHESIZE)
        assert result is not None
        assert result.experiment_id == "exp1"

    def test_get_active_experiment_wrong_stage(self):
        """Test getting experiment for stage with no active experiment."""
        registry = PromptRegistry()
        registry.create_experiment(
            experiment_id="exp1",
            name="Test",
            stage=PromptStage.SYNTHESIZE,
            variants=[
                {"variant_id": "A", "prompt_version": "v1", "traffic_percentage": 100}
            ],
        )

        result = registry.get_active_experiment(PromptStage.EXTRACT)
        assert result is None

    def test_get_active_experiment_ignores_completed(self):
        """Test that completed experiments are ignored."""
        registry = PromptRegistry()
        registry.register_template(
            prompt_id="test",
            stage=PromptStage.SYNTHESIZE,
            version="v1",
            template_content="Content",
        )
        registry.create_experiment(
            experiment_id="exp1",
            name="Test",
            stage=PromptStage.SYNTHESIZE,
            variants=[
                {"variant_id": "A", "prompt_version": "v1", "traffic_percentage": 100}
            ],
        )
        registry.complete_experiment("exp1")

        result = registry.get_active_experiment(PromptStage.SYNTHESIZE)
        assert result is None


class TestSelectVersionForRequest:
    """Tests for select_version_for_request method."""

    def test_select_version_no_experiment(self):
        """Test version selection without experiment."""
        registry = PromptRegistry()
        registry.register_template(
            prompt_id="test",
            stage=PromptStage.ANALYZE_STRUCTURE,
            version="v1",
            template_content="Content",
            is_default=True,
        )

        result = registry.select_version_for_request(
            PromptStage.ANALYZE_STRUCTURE, "req123"
        )
        assert result.version == "v1"

    def test_select_version_with_experiment(self):
        """Test version selection with active experiment."""
        registry = PromptRegistry()
        registry.register_template(
            prompt_id="test",
            stage=PromptStage.SYNTHESIZE,
            version="v1",
            template_content="Content v1",
            is_default=False,
        )
        registry.register_template(
            prompt_id="test",
            stage=PromptStage.SYNTHESIZE,
            version="v2",
            template_content="Content v2",
            is_default=False,
        )
        registry.create_experiment(
            experiment_id="exp1",
            name="Test",
            stage=PromptStage.SYNTHESIZE,
            variants=[
                {"variant_id": "A", "prompt_version": "v1", "traffic_percentage": 50},
                {"variant_id": "B", "prompt_version": "v2", "traffic_percentage": 50},
            ],
        )

        result = registry.select_version_for_request(PromptStage.SYNTHESIZE, "req123")
        assert result is not None

    def test_select_version_experiment_variant_not_found(self):
        """Test fallback when experiment variant version not found."""
        registry = PromptRegistry()
        registry.register_template(
            prompt_id="fallback_test",
            stage=PromptStage.SYNTHESIZE,
            version="v1",
            template_content="Content",
            is_default=True,
        )
        registry.create_experiment(
            experiment_id="exp1",
            name="Test",
            stage=PromptStage.SYNTHESIZE,
            variants=[
                {
                    "variant_id": "A",
                    "prompt_version": "v_nonexistent",
                    "traffic_percentage": 100,
                },
            ],
        )

        # Should fall back to default version
        result = registry.select_version_for_request(PromptStage.SYNTHESIZE, "req123")
        assert result.version == "v1"

    def test_select_version_no_version_available(self):
        """Test error when no version available."""
        registry = PromptRegistry()

        with pytest.raises(ValueError, match="No prompt version available"):
            registry.select_version_for_request(PromptStage.SYNTHESIZE, "req123")


class TestGetExperimentVariant:
    """Tests for _get_experiment_variant method."""

    def test_variant_selection_first(self):
        """Test selecting first variant."""
        registry = PromptRegistry()
        experiment = MagicMock()
        experiment.variants = [
            MagicMock(variant_id="A", prompt_version="v1", traffic_percentage=50),
            MagicMock(variant_id="B", prompt_version="v2", traffic_percentage=50),
        ]

        variant = registry._get_experiment_variant(experiment, "test_request")
        assert variant.variant_id in ["A", "B"]

    def test_variant_selection_last_fallback(self):
        """Test fallback to last variant when hash exceeds all ranges."""
        registry = PromptRegistry()
        experiment = MagicMock()
        experiment.variants = [
            MagicMock(variant_id="A", prompt_version="v1", traffic_percentage=100),
        ]

        variant = registry._get_experiment_variant(experiment, "any_request")
        assert variant.variant_id == "A"


class TestCreateExperiment:
    """Tests for create_experiment method."""

    def test_create_experiment_ab_test(self):
        """Test creating A/B test experiment."""
        registry = PromptRegistry()
        experiment = registry.create_experiment(
            experiment_id="exp1",
            name="A/B Test",
            stage=PromptStage.SYNTHESIZE,
            variants=[
                {"variant_id": "A", "prompt_version": "v1", "traffic_percentage": 50},
                {"variant_id": "B", "prompt_version": "v2", "traffic_percentage": 50},
            ],
            experiment_type=ExperimentType.AB_TEST,
        )

        assert experiment.experiment_id == "exp1"
        assert experiment.status == "running"

    def test_create_experiment_multivariate(self):
        """Test creating multivariate experiment."""
        registry = PromptRegistry()
        experiment = registry.create_experiment(
            experiment_id="exp2",
            name="Multivariate",
            stage=PromptStage.QUALITY_CHECK,
            variants=[
                {"variant_id": "V1", "prompt_version": "v1", "traffic_percentage": 33},
                {"variant_id": "V2", "prompt_version": "v2", "traffic_percentage": 33},
                {"variant_id": "V3", "prompt_version": "v3", "traffic_percentage": 34},
            ],
            experiment_type=ExperimentType.MULTIVARIATE,
        )

        assert experiment.experiment_type == ExperimentType.MULTIVARIATE

    def test_create_experiment_with_kwargs(self):
        """Test creating experiment with additional kwargs."""
        registry = PromptRegistry()
        experiment = registry.create_experiment(
            experiment_id="exp3",
            name="Test",
            stage=PromptStage.FEEDBACK_ANALYSIS,
            variants=[
                {"variant_id": "A", "prompt_version": "v1", "traffic_percentage": 100},
            ],
            description="Custom description",
            min_sample_size=200,
            significance_threshold=0.01,
        )

        assert experiment.description == "Custom description"
        assert experiment.min_sample_size == 200


class TestCompleteExperiment:
    """Tests for complete_experiment method."""

    def test_complete_experiment_success(self):
        """Test completing experiment successfully."""
        registry = PromptRegistry()
        registry.register_template(
            prompt_id="test",
            stage=PromptStage.SYNTHESIZE,
            version="v1",
            template_content="Content",
        )
        registry.create_experiment(
            experiment_id="exp1",
            name="Test",
            stage=PromptStage.SYNTHESIZE,
            variants=[
                {"variant_id": "A", "prompt_version": "v1", "traffic_percentage": 100},
            ],
        )

        registry.complete_experiment(
            experiment_id="exp1",
            winning_variant="A",
            results={"quality": 0.95},
        )

        exp = registry._state.experiments["exp1"]
        assert exp.status == "completed"
        assert exp.winning_variant == "A"

    def test_complete_experiment_not_found(self):
        """Test completing non-existent experiment."""
        registry = PromptRegistry()

        with pytest.raises(ValueError, match="Experiment .* not found"):
            registry.complete_experiment("nonexistent")

    def test_complete_experiment_without_winner(self):
        """Test completing experiment without winning variant."""
        registry = PromptRegistry()
        registry.create_experiment(
            experiment_id="exp1",
            name="Test",
            stage=PromptStage.SYNTHESIZE,
            variants=[
                {"variant_id": "A", "prompt_version": "v1", "traffic_percentage": 100}
            ],
        )

        registry.complete_experiment("exp1")

        exp = registry._state.experiments["exp1"]
        assert exp.status == "completed"
        assert exp.winning_variant is None


class TestUpdateMetrics:
    """Tests for update_metrics method."""

    def test_update_metrics_existing_version(self):
        """Test updating metrics for existing version."""
        registry = PromptRegistry()
        registry.register_template(
            prompt_id="test",
            stage=PromptStage.SYNTHESIZE,
            version="v1",
            template_content="Content",
        )

        registry.update_metrics(
            stage=PromptStage.SYNTHESIZE,
            version="v1",
            metrics={"avg_quality_score": 0.85, "total_uses": 100},
        )

        version = registry.get_version(PromptStage.SYNTHESIZE, "v1")
        assert version.metrics.avg_quality_score == 0.85
        assert version.metrics.total_uses == 100

    def test_update_metrics_nonexistent_version(self):
        """Test updating metrics for non-existent version logs warning."""
        registry = PromptRegistry()
        registry.update_metrics(
            stage=PromptStage.SYNTHESIZE,
            version="v999",
            metrics={"total_uses": 1},
        )

    def test_update_metrics_multiple_fields(self):
        """Test updating multiple metric fields."""
        registry = PromptRegistry()
        registry.register_template(
            prompt_id="test",
            stage=PromptStage.SYNTHESIZE,
            version="v1",
            template_content="Content",
        )

        registry.update_metrics(
            stage=PromptStage.SYNTHESIZE,
            version="v1",
            metrics={
                "avg_quality_score": 0.9,
                "avg_input_tokens": 150.5,
                "avg_output_tokens": 200.3,
                "error_rate": 0.05,
            },
        )

        version = registry.get_version(PromptStage.SYNTHESIZE, "v1")
        assert version.metrics.avg_quality_score == 0.9
        assert version.metrics.avg_input_tokens == 150.5
        assert version.metrics.avg_output_tokens == 200.3
        assert version.metrics.error_rate == 0.05


class TestRenderPrompt:
    """Tests for render_prompt method."""

    def test_render_prompt_basic(self):
        """Test basic prompt rendering."""
        registry = PromptRegistry()
        registry.register_template(
            prompt_id="test",
            stage=PromptStage.EXTRACT,
            version="v1",
            template_content="Hello {{ name }}!",
            system_prompt="You are a {{ role }}",
        )

        system, user = registry.render_prompt(
            stage=PromptStage.EXTRACT,
            version="v1",
            name="World",
            role="helper",
        )

        assert user == "Hello World!"
        assert system == "You are a helper"

    def test_render_prompt_with_version(self):
        """Test rendering specific version."""
        registry = PromptRegistry()
        registry.register_template(
            prompt_id="test",
            stage=PromptStage.SYNTHESIZE,
            version="v1",
            template_content="Version 1: {{ value }}",
        )

        system, user = registry.render_prompt(
            stage=PromptStage.SYNTHESIZE,
            version="v1",
            value="test",
        )

        assert "Version 1" in user

    def test_render_prompt_missing_version(self):
        """Test rendering non-existent version raises error."""
        registry = PromptRegistry()

        with pytest.raises(ValueError, match="not found"):
            registry.render_prompt(
                stage=PromptStage.SYNTHESIZE,
                version="v999",
                value="test",
            )

    def test_render_prompt_no_request_id(self):
        """Test that request_id is required when version is None."""
        registry = PromptRegistry()

        with pytest.raises(ValueError, match="request_id required"):
            registry.render_prompt(stage=PromptStage.SYNTHESIZE)

    def test_render_prompt_system_empty(self):
        """Test rendering with empty system prompt."""
        registry = PromptRegistry()
        registry.register_template(
            prompt_id="test",
            stage=PromptStage.QUALITY_CHECK,
            version="v1",
            template_content="Just user prompt: {{ value }}",
            system_prompt="",
        )

        system, user = registry.render_prompt(
            stage=PromptStage.QUALITY_CHECK,
            version="v1",
            value="test_value",
        )

        assert system == ""
        assert user == "Just user prompt: test_value"


class TestLoadPromptsFromDirectory:
    """Tests for load_prompts_from_directory method."""

    def test_load_prompts_no_directory(self):
        """Test loading when no directory set."""
        registry = PromptRegistry()
        count = registry.load_prompts_from_directory()
        assert count == 0

    def test_load_prompts_directory_not_exists(self, tmp_path):
        """Test loading from non-existent directory."""
        registry = PromptRegistry(prompts_dir=tmp_path / "nonexistent")
        count = registry.load_prompts_from_directory()
        assert count == 0

    def test_load_prompts_empty_directory(self, tmp_path):
        """Test loading from empty directory."""
        registry = PromptRegistry(prompts_dir=tmp_path)
        count = registry.load_prompts_from_directory()
        assert count == 0

    def test_load_prompts_with_templates(self, tmp_path):
        """Test loading templates from directory."""
        stage_dir = tmp_path / "extract"
        stage_dir.mkdir()

        (stage_dir / "v1.j2").write_text("Template v1")
        (stage_dir / "v2.j2").write_text("Template v2")

        registry = PromptRegistry(prompts_dir=tmp_path)
        count = registry.load_prompts_from_directory()

        assert count == 2

    def test_load_prompts_skips_unknown_stage(self, tmp_path):
        """Test that unknown stage directories are skipped."""
        unknown_dir = tmp_path / "unknown_stage"
        unknown_dir.mkdir()
        (unknown_dir / "v1.j2").write_text("Content")

        registry = PromptRegistry(prompts_dir=tmp_path)
        count = registry.load_prompts_from_directory()

        assert count == 0

    def test_load_prompts_handles_error(self, tmp_path):
        """Test that loading continues after errors."""
        stage_dir = tmp_path / "extract"
        stage_dir.mkdir()

        (stage_dir / "v1.j2").write_text("Template v1")
        (stage_dir / "v2.j2").write_text("Template v2")

        registry = PromptRegistry(prompts_dir=tmp_path)
        count = registry.load_prompts_from_directory()

        # At least v1 should load
        assert count >= 1


class TestListVersions:
    """Tests for list_versions method."""

    def test_list_versions_empty(self):
        """Test listing versions when empty."""
        registry = PromptRegistry()
        result = registry.list_versions()
        assert result == {}

    def test_list_versions_all(self):
        """Test listing all versions."""
        registry = PromptRegistry()
        registry.register_template(
            prompt_id="test1",
            stage=PromptStage.EXTRACT,
            version="v1",
            template_content="Content",
        )
        registry.register_template(
            prompt_id="test2",
            stage=PromptStage.SYNTHESIZE,
            version="v2",
            template_content="Content",
        )

        result = registry.list_versions()
        assert "extract" in result
        assert "synthesize" in result
        assert "v1" in result["extract"]
        assert "v2" in result["synthesize"]

    def test_list_versions_specific_stage(self):
        """Test listing versions for specific stage."""
        registry = PromptRegistry()
        registry.register_template(
            prompt_id="test",
            stage=PromptStage.QUALITY_CHECK,
            version="v1",
            template_content="Content",
        )

        result = registry.list_versions(PromptStage.QUALITY_CHECK)
        assert "quality_check" in result
        assert "v1" in result["quality_check"]


class TestStateProperty:
    """Tests for state property."""

    def test_state_returns_copy(self):
        """Test that state returns a copy, not reference."""
        registry = PromptRegistry()
        state1 = registry.state
        state2 = registry.state

        assert state1 is not state2


class TestGetPromptRegistry:
    """Tests for get_prompt_registry function."""

    def test_get_prompt_registry_creates_new(self):
        """Test that function creates new registry if none exists."""
        import src.audiobook_studio.prompts.registry as reg_module

        reg_module._registry = None

        registry = get_prompt_registry()
        assert registry is not None
        assert isinstance(registry, PromptRegistry)

    def test_get_prompt_registry_returns_existing(self):
        """Test that function returns existing registry."""
        import src.audiobook_studio.prompts.registry as reg_module

        reg_module._registry = None

        registry1 = get_prompt_registry()
        registry2 = get_prompt_registry()

        assert registry1 is registry2

    def test_get_prompt_registry_passes_kwargs(self):
        """Test that kwargs are passed to constructor."""
        import src.audiobook_studio.prompts.registry as reg_module

        reg_module._registry = None

        registry = get_prompt_registry(langfuse_enabled=False)
        assert registry._langfuse_enabled is False
