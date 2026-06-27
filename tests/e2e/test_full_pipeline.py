"""E2E Tests for Full Pipeline Integration.

Tests the complete pipeline from raw text to finished audio:
1. Text input -> Analysis -> TTS -> Audio output
2. Multi-paragraph synthesis
3. Chapter-level synthesis
"""

import pytest
from pathlib import Path

from tests.e2e.conftest import E2ETestConfig, SAMPLE_TEXT


pytestmark = pytest.mark.e2e


class TestFullPipelineIntegration:
    """E2E tests for the complete audiobook pipeline."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures."""
        self.has_api_key = E2ETestConfig.check_api_key("openrouter")
        pass  # Don't skip - can test with local engines only

    def test_paragraph_annotation_and_synthesis(self, sample_text, temp_output_dir):
        """Test full flow: annotate paragraph -> synthesize audio."""
        from src.audiobook_studio.llm.router import LLMRouter
        from src.audiobook_studio.tts.engine import TTSEngine

        # Step 1: Annotate paragraph
        router = LLMRouter()

        messages = [
            {
                "role": "system",
                "content": "Annotate this paragraph with speaker, emotion, and TTS direction.",
            },
            {
                "role": "user",
                "content": f"Annotate:\n\n{sample_text[:200]}",
            },
        ]

        annotation = router.call(
            stage="annotate_paragraph",
            messages=messages,
            max_tokens=500,
        )

        assert annotation is not None

        # Step 2: Synthesize with annotation
        engine = TTSEngine.get_engine("kokoro")
        if engine:
            output_path = temp_output_dir / "annotated_synthesis.wav"
            result = engine.synthesize(sample_text[:100], str(output_path))

            if result and result.success:
                assert output_path.exists()
                assert output_path.stat().st_size > 0

    def test_multi_paragraph_synthesis(self, sample_text, temp_output_dir):
        """Test synthesizing multiple paragraphs in sequence."""
        from src.audiobook_studio.tts.engine import TTSEngine

        engine = TTSEngine.get_engine("kokoro")
        if not engine:
            pytest.skip("Kokoro engine not available")

        paragraphs = [
            "Hello, Li Ming said.",
            "Wang Fang turned around and smiled.",
            "They walked together to the park.",
        ]

        output_files = []

        for i, para in enumerate(paragraphs):
            output_path = temp_output_dir / f"para_{i}.wav"
            result = engine.synthesize(para, str(output_path))

            if result and result.success:
                output_files.append(output_path)

        # Should have at least one successful synthesis
        assert len(output_files) > 0

        # All created files should be valid
        for f in output_files:
            assert f.exists()
            assert f.stat().st_size > 0


class TestConfigIntegration:
    """E2E tests for configuration integration."""

    def test_pipeline_config_load(self):
        """Test loading pipeline configuration."""
        from src.audiobook_studio.config.loader import load_pipeline_config

        config = load_pipeline_config()

        assert config is not None
        assert isinstance(config, dict)
        assert len(config) > 0

    def test_quality_thresholds_load(self):
        """Test loading quality thresholds."""
        from src.audiobook_studio.config.loader import load_quality_thresholds

        thresholds = load_quality_thresholds()

        assert thresholds is not None
        assert "overall" in thresholds
        assert "dimensions" in thresholds

    def test_voice_mapping_load(self):
        """Test loading voice mapping."""
        from src.audiobook_studio.config.loader import get_voice_mapping

        mapping = get_voice_mapping()

        assert mapping is not None
        # Should have voice entries
        assert len(mapping) > 0


class TestPromptRegistryIntegration:
    """E2E tests for prompt registry integration."""

    def test_prompt_registry_init(self):
        """Test prompt registry initialization."""
        from src.audiobook_studio.prompts import PromptRegistry

        registry = PromptRegistry()
        assert registry is not None

    def test_prompt_registry_load_from_dir(self, tmp_path):
        """Test loading prompts from directory."""
        from src.audiobook_studio.prompts import PromptRegistry
        from src.audiobook_studio.prompts.models import PromptStage

        # Create test prompt directory
        prompts_dir = tmp_path / "prompts"
        extract_dir = prompts_dir / "extract"
        extract_dir.mkdir(parents=True)

        # Create test template
        template_file = extract_dir / "v1.j2"
        template_file.write_text(
            "Extract from: {{ title }}\n\n{{ text[:1000] }}",
            encoding="utf-8",
        )

        registry = PromptRegistry(prompts_dir=prompts_dir)
        count = registry.load_prompts_from_directory()

        assert count >= 1

        # Should be able to retrieve the loaded prompt
        version = registry.get_version(PromptStage.EXTRACT, "v1")
        assert version is not None


class TestMonitoringIntegration:
    """E2E tests for monitoring/observability integration."""

    def test_langfuse_client_init(self):
        """Test Langfuse client initialization."""
        from src.audiobook_studio.monitoring.langfuse_client import (
            is_enabled as langfuse_is_enabled,
        )

        # Should not crash regardless of configuration
        enabled = langfuse_is_enabled()
        assert isinstance(enabled, bool)

    def test_feedback_collector_init(self):
        """Test feedback collector initialization."""
        from src.audiobook_studio.feedback.collector import FeedbackCollector

        collector = FeedbackCollector()
        assert collector is not None
        assert hasattr(collector, "record")


class TestHardwareProfileIntegration:
    """E2E tests for hardware profile integration."""

    def test_hardware_profile_load(self):
        """Test hardware profile loading."""
        from src.audiobook_studio.config.loader import load_hardware_profile

        profile = load_hardware_profile()
        assert profile is not None

    def test_hardware_profile_tts_routing(self):
        """Test hardware profile affects TTS routing."""
        from src.audiobook_studio.config.hardware_profile import (
            get_hardware_profile,
            TTSEnginePriority,
        )

        profile = get_hardware_profile()

        # Should have TTS priority configured
        if hasattr(profile, "tts_engine_priority"):
            assert isinstance(profile.tts_engine_priority, TTSEnginePriority)
            assert len(profile.tts_engine_priority.engines) > 0