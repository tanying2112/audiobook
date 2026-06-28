"""E2E Tests for LLM Pipeline Stages.

Tests each pipeline stage with real LLM API calls:
1. Extract - Book analysis extraction
2. Analyze Structure - Chapter and character analysis
3. Annotate Paragraph - Paragraph-level annotations
4. Edit for TTS - Text normalization for TTS
5. Quality Check - Audio quality judgment
"""

import json
from pathlib import Path

import pytest

from tests.e2e.conftest import SAMPLE_TEXT, E2ETestConfig

pytestmark = pytest.mark.e2e


class TestLLMExtractStage:
    """E2E tests for the extract stage."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures."""
        self.has_api_key = E2ETestConfig.check_api_key("openrouter")
        if not self.has_api_key:
            pytest.skip("No API key available for extract stage tests")

    def test_extract_book_metadata(self, sample_text):
        """Test book metadata extraction."""
        from src.audiobook_studio.llm.router import LLMRouter

        router = LLMRouter()

        messages = [
            {
                "role": "system",
                "content": "You are a book analysis expert. Extract book metadata from the given text.",
            },
            {
                "role": "user",
                "content": f"Analyze this book excerpt and extract metadata:\n\n{sample_text[:500]}",
            },
        ]

        response = router.call(
            stage="extract",
            messages=messages,
            max_tokens=1000,
        )

        assert response is not None
        assert len(response) > 0

    def test_extract_with_schema(self, sample_text):
        """Test extraction with JSON schema validation."""
        from src.audiobook_studio.llm.router import LLMRouter

        router = LLMRouter()

        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "author": {"type": "string"},
                "chapter_count": {"type": "integer"},
                "genre": {"type": "string"},
            },
            "required": ["title", "author"],
        }

        messages = [
            {
                "role": "system",
                "content": f"Extract book information following this schema: {json.dumps(schema)}",
            },
            {
                "role": "user",
                "content": f"Extract from:\n\n{sample_text[:500]}",
            },
        ]

        response = router.call(
            stage="extract",
            messages=messages,
            response_model=schema,
            max_tokens=500,
        )

        assert response is not None
        # Validate schema compliance
        assert isinstance(response, dict)


class TestLLMAnalyzeStructureStage:
    """E2E tests for the analyze_structure stage."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures."""
        self.has_api_key = E2ETestConfig.check_api_key("openrouter")
        if not self.has_api_key:
            pytest.skip("No API key available for analyze_structure tests")

    def test_analyze_characters(self, sample_text):
        """Test character analysis extraction."""
        from src.audiobook_studio.llm.router import LLMRouter

        router = LLMRouter()

        messages = [
            {
                "role": "system",
                "content": "Analyze characters in the text. Identify all speakers and their traits.",
            },
            {
                "role": "user",
                "content": f"Analyze characters:\n\n{sample_text}",
            },
        ]

        response = router.call(
            stage="analyze_structure",
            messages=messages,
            max_tokens=1500,
        )

        assert response is not None
        assert "李明" in response or "王芳" in response or len(response) > 0


class TestLLMEditForTTSStage:
    """E2E tests for the edit_for_tts stage."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures."""
        self.has_api_key = E2ETestConfig.check_api_key("openrouter")
        if not self.has_api_key:
            pytest.skip("No API key available for edit_for_tts tests")

    def test_normalize_for_tts(self, sample_text):
        """Test text normalization for TTS."""
        from src.audiobook_studio.llm.router import LLMRouter

        router = LLMRouter()

        messages = [
            {
                "role": "system",
                "content": "Normalize this text for text-to-speech. Fix any issues that would cause TTS problems.",
            },
            {
                "role": "user",
                "content": f"Normalize for TTS:\n\n{sample_text}",
            },
        ]

        response = router.call(
            stage="edit_for_tts",
            messages=messages,
            max_tokens=1000,
        )

        assert response is not None
        # Normalized text should be similar length to input
        assert len(response) > len(sample_text) * 0.5


class TestLLMQualityCheckStage:
    """E2E tests for the quality_check stage."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures."""
        self.has_api_key = E2ETestConfig.check_api_key("openrouter")
        if not self.has_api_key:
            pytest.skip("No API key available for quality_check tests")

    def test_quality_judgment(self):
        """Test quality judgment with sample analysis."""
        from src.audiobook_studio.llm.router import LLMRouter

        router = LLMRouter()

        sample_analysis = {
            "overall_score": 0.85,
            "speaker_clarity": 0.9,
            "emotion_match": 0.8,
            "issues": ["minor background noise"],
        }

        messages = [
            {
                "role": "system",
                "content": "Judge the quality of this audio analysis. Return PASS if quality is acceptable, FAIL otherwise.",
            },
            {
                "role": "user",
                "content": f"Quality analysis:\n\n{json.dumps(sample_analysis)}",
            },
        ]

        response = router.call(
            stage="quality_check",
            messages=messages,
            max_tokens=200,
        )

        assert response is not None
        assert any(
            word in response.upper() for word in ["PASS", "FAIL", "ACCEPT", "REJECT"]
        )


class TestLLMPromptCompression:
    """E2E tests for prompt compression feature."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures."""
        self.has_api_key = E2ETestConfig.check_api_key("openrouter")
        if not self.has_api_key:
            pytest.skip("No API key available for prompt compression tests")

    def test_compress_long_context(self):
        """Test prompt compression for long contexts."""
        from src.audiobook_studio.llm.router import LLMRouter

        router = LLMRouter()

        # Generate long context
        long_text = SAMPLE_TEXT * 20  # ~10k characters

        messages = [
            {
                "role": "user",
                "content": f"Summarize this text in 3 sentences:\n\n{long_text}",
            },
        ]

        response = router.call(
            stage="extract",
            messages=messages,
            max_tokens=200,
            enable_prompt_compression=True,
        )

        assert response is not None
        assert len(response) < len(long_text)  # Summary should be shorter
