"""Tests for prompts package initialization."""


def test_prompts_imports():
    """Test that prompts package exports are available."""
    from src.audiobook_studio.prompts import (
        PromptVersion,
        PromptTemplate,
        PromptStage,
        PromptStatus,
        PromptExperiment,
        ExperimentVariant,
        ExperimentType,
        PromptRegistryState,
        PromptVersionMetrics,
        PromptRegistry,
        get_prompt_registry,
    )

    assert PromptVersion is not None
    assert PromptTemplate is not None
    assert PromptStage is not None
    assert PromptStatus is not None
    assert PromptExperiment is not None
    assert ExperimentVariant is not None
    assert ExperimentType is not None
    assert PromptRegistryState is not None
    assert PromptVersionMetrics is not None
    assert PromptRegistry is not None
    assert get_prompt_registry is not None


def test_get_prompt_registry():
    """Test getting global prompt registry instance."""
    from src.audiobook_studio.prompts import get_prompt_registry, PromptRegistry

    registry = get_prompt_registry()
    assert isinstance(registry, PromptRegistry)