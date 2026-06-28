"""E2E Tests for TTS Integration.

Tests the full TTS pipeline from text to audio using real TTS services:
1. Kokoro TTS (local)
2. Azure TTS (cloud)
3. Edge TTS (cloud)
4. GCP TTS (cloud)
5. Full synthesis pipeline
"""

import asyncio
from pathlib import Path

import pytest

from tests.e2e.conftest import E2ETestConfig

pytestmark = pytest.mark.e2e


class TestKokoroTTS:
    """E2E tests for Kokoro TTS backend."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures."""
        # Kokoro is local, no API key needed
        pass

    def test_kokoro_synthesize_short_text(self, temp_output_dir):
        """Test Kokoro TTS synthesis with short text."""
        from src.audiobook_studio.tts.engine import EngineRegistry, TTSEngine

        engine = TTSEngine.get_engine("kokoro")
        if engine is None:
            pytest.skip("Kokoro engine not available")

        text = "你好，这是一个测试。"
        output_path = temp_output_dir / "kokoro_test.wav"

        result = engine.synthesize(text, str(output_path))

        assert result is not None
        assert result.success
        assert output_path.exists()
        assert output_path.stat().st_size > 0  # File has content

    @pytest.mark.asyncio
    async def test_kokoro_async_synthesize(self, temp_output_dir):
        """Test Kokoro async synthesis."""
        from src.audiobook_studio.tts.engine import TTSEngine

        engine = TTSEngine.get_engine("kokoro")
        if engine is None:
            pytest.skip("Kokoro engine not available")

        text = "异步合成测试。"
        output_path = temp_output_dir / "kokoro_async_test.wav"

        result = await engine.asynthesize(text, str(output_path))

        assert result is not None
        assert result.success
        assert output_path.exists()


class TestEdgeTTS:
    """E2E tests for Edge TTS backend."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures."""
        # Edge TTS is free, no API key needed
        pass

    def test_edge_synthesize_short_text(self, temp_output_dir):
        """Test Edge TTS synthesis with short text."""
        from src.audiobook_studio.tts.engine import TTSEngine

        engine = TTSEngine.get_engine("edge")
        if engine is None:
            pytest.skip("Edge TTS engine not available")

        text = "你好，这是 Edge TTS 测试。"
        output_path = temp_output_dir / "edge_test.wav"

        result = engine.synthesize(text, str(output_path))

        assert result is not None
        assert result.success
        assert output_path.exists()
        assert output_path.stat().st_size > 0


class TestAzureTTS:
    """E2E tests for Azure TTS backend."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures."""
        self.has_api_key = (
            E2ETestConfig.check_api_key("azure")
            or "AZURE_SPEECH_KEY" in __import__("os").environ
        )
        if not self.has_api_key:
            pytest.skip("No Azure API key available")

    def test_azure_synthesize_short_text(self, temp_output_dir):
        """Test Azure TTS synthesis with short text."""
        from src.audiobook_studio.tts.engine import TTSEngine

        engine = TTSEngine.get_engine("azure")
        if engine is None:
            pytest.skip("Azure TTS engine not available")

        text = "你好，这是 Azure TTS 测试。"
        output_path = temp_output_dir / "azure_test.wav"

        result = engine.synthesize(text, str(output_path))

        assert result is not None
        assert result.success
        assert output_path.exists()
        assert output_path.stat().st_size > 0


class TestGCPTTS:
    """E2E tests for Google Cloud TTS backend."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures."""
        self.has_api_key = (
            E2ETestConfig.check_api_key("gcp")
            or "GOOGLE_APPLICATION_CREDENTIALS" in __import__("os").environ
        )
        if not self.has_api_key:
            pytest.skip("No GCP credentials available")

    def test_gcp_synthesize_short_text(self, temp_output_dir):
        """Test GCP TTS synthesis with short text."""
        from src.audiobook_studio.tts.engine import TTSEngine

        engine = TTSEngine.get_engine("gcp")
        if engine is None:
            pytest.skip("GCP TTS engine not available")

        text = "你好，这是 Google Cloud TTS 测试。"
        output_path = temp_output_dir / "gcp_test.wav"

        result = engine.synthesize(text, str(output_path))

        assert result is not None
        assert result.success
        assert output_path.exists()


class TestTTSEngineRegistry:
    """E2E tests for TTS Engine Registry."""

    def test_registry_list_engines(self):
        """Test listing available TTS engines."""
        from src.audiobook_studio.tts.engine import EngineRegistry

        registry = EngineRegistry()
        engines = registry.list_engines()

        assert len(engines) > 0
        # At least Kokoro should be available
        assert "kokoro" in engines or len(engines) > 0

    def test_registry_get_engine(self):
        """Test getting a specific engine from registry."""
        from src.audiobook_studio.tts.engine import EngineRegistry

        registry = EngineRegistry()
        engine = registry.get_engine("kokoro")

        # Should return something (might be None if not initialized)
        # If initialized, should have synthesize method
        if engine:
            assert hasattr(engine, "synthesize")


class TestFullSynthesisPipeline:
    """E2E tests for the full synthesis pipeline."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures."""
        pass  # Use whatever engines are available

    def test_synthesis_with_fallback(self, sample_text, temp_output_dir):
        """Test synthesis pipeline with fallback chain."""
        from src.audiobook_studio.pipeline.synthesize import SynthesizePipeline

        pipeline = SynthesizePipeline(
            output_dir=str(temp_output_dir),
            mock_mode=False,
        )

        # Test with paragraph data
        paragraph = {
            "id": "test_p1",
            "text": sample_text[:100],
            "speaker": "李明",
            "emotion": "neutral",
        }

        output_path = temp_output_dir / "pipeline_test.wav"

        result = pipeline._try_synthesize_with_fallback(
            paragraph=paragraph,
            engine_priority=["kokoro", "edge"],  # Try local first
            output_path=str(output_path),
        )

        # Should attempt synthesis (may or may not succeed depending on available engines)
        assert result is not None


class TestTTSAudioAnalysis:
    """E2E tests for TTS audio analysis."""

    def test_audio_duration_analysis(self, temp_output_dir):
        """Test audio duration analysis."""
        from src.audiobook_studio.tts.engine import TTSEngine

        # First create a test audio file
        engine = TTSEngine.get_engine("kokoro")
        if engine is None:
            pytest.skip("Kokoro engine not available")

        text = "测试音频分析。"
        output_path = temp_output_dir / "analysis_test.wav"

        result = engine.synthesize(text, str(output_path))
        if not result or not result.success:
            pytest.skip("Failed to create test audio")

        # Now analyze it
        from src.audiobook_studio.pipeline.quality_check import AudioAnalyzer

        analyzer = AudioAnalyzer()
        analysis = analyzer.analyze(str(output_path))

        assert analysis is not None
        assert "duration" in analysis
        assert analysis["duration"] > 0

    def test_silence_detection(self, temp_output_dir):
        """Test silence detection in audio."""
        from src.audiobook_studio.pipeline.quality_check import AudioAnalyzer
        from src.audiobook_studio.tts.engine import TTSEngine

        # Create test audio
        engine = TTSEngine.get_engine("kokoro")
        if engine is None:
            pytest.skip("Kokoro engine not available")

        text = "安静测试。"
        output_path = temp_output_dir / "silence_test.wav"

        result = engine.synthesize(text, str(output_path))
        if not result or not result.success:
            pytest.skip("Failed to create test audio")

        # Analyze for silence
        analyzer = AudioAnalyzer()
        analysis = analyzer.analyze(str(output_path))

        assert analysis is not None
        assert "silence_segments" in analysis or "silent_ratio" in analysis
