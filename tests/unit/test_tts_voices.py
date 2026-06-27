"""Tests for tts_voices module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.audiobook_studio.api.tts_voices import (
    AZURE_VOICES,
    EDGE_TTS_VOICES,
    GCP_VOICES,
    KOKORO_VOICES,
    TTSVoicesResponse,
    TTSEngine,
    TTSVoice,
    VOXCPM2_VOICES,
    get_recommended_voices,
    list_tts_voices,
    preview_voice,
    router,
)


class TTSVoiceTestHelpers:
    """Helper methods for TTSVoice tests."""

    @staticmethod
    def create_voice(**kwargs):
        """Create a TTSVoice with default values."""
        defaults = {
            "id": "test_voice",
            "name": "Test Voice",
            "gender": "female",
            "language": "en-US",
            "description": "A test voice",
            "sample_url": "https://example.com/sample.mp3",
        }
        defaults.update(kwargs)
        return TTSVoice(**defaults)


class TTSEngineTestHelpers:
    """Helper methods for TTSEngine tests."""

    @staticmethod
    def create_engine(voices=None, **kwargs):
        """Create a TTSEngine with default values."""
        if voices is None:
            voices = []
        defaults = {
            "id": "test_engine",
            "name": "Test Engine",
            "available": True,
            "voices": voices,
            "priority": 1,
            "supports_prosody": True,
            "supports_ssml": False,
        }
        defaults.update(kwargs)
        return TTSEngine(**defaults)


class TTSVoicesResponseTestHelpers:
    """Helper methods for TTSVoicesResponse tests."""

    @staticmethod
    def create_response(engines=None, **kwargs):
        """Create a TTSVoicesResponse with default values."""
        if engines is None:
            engines = {}
        defaults = {
            "engines": engines,
            "total_voices": 0,
            "default_engine": "kokoro",
            "default_voice": "kokoro_narrator",
        }
        defaults.update(kwargs)
        return TTSVoicesResponse(**defaults)


class TestTTSVoice:
    """Tests for TTSVoice model."""

    def test_voice_creation(self):
        """Test creating a TTSVoice with all fields."""
        voice = TTSVoiceTestHelpers.create_voice()
        assert voice.id == "test_voice"
        assert voice.name == "Test Voice"
        assert voice.gender == "female"
        assert voice.language == "en-US"
        assert voice.description == "A test voice"
        assert voice.sample_url == "https://example.com/sample.mp3"

    def test_voice_optional_fields(self):
        """Test creating a TTSVoice with optional fields as None."""
        voice = TTSVoice(
            id="test_voice",
            name="Test Voice",
            gender="female",
            language="en-US",
            description=None,
            sample_url=None,
        )
        assert voice.description is None
        assert voice.sample_url is None

    def test_voice_validation(self):
        """Test TTSVoice validation."""
        # This should work
        voice = TTSVoiceTestHelpers.create_voice()
        assert voice.id == "test_voice"

        # Test that we can create with different values
        voice2 = TTSVoice(
            id="another",
            name="Another Voice",
            gender="male",
            language="zh-CN",
        )
        assert voice2.gender == "male"
        assert voice2.language == "zh-CN"


class TestTTSEngine:
    """Tests for TTSEngine model."""

    def test_engine_creation(self):
        """Test creating a TTSEngine with all fields."""
        voice = TTSVoiceTestHelpers.create_voice(id="voice1")
        engine = TTSEngineTestHelpers.create_engine(voices=[voice])
        assert engine.id == "test_engine"
        assert engine.name == "Test Engine"
        assert engine.available is True
        assert len(engine.voices) == 1
        assert engine.voices[0].id == "voice1"
        assert engine.priority == 1
        assert engine.supports_prosody is True
        assert engine.supports_ssml is False

    def test_engine_defaults(self):
        """Test TTSEngine default values."""
        engine = TTSEngine(
            id="test_engine",
            name="Test Engine",
            available=True,
            voices=[],
        )
        assert engine.priority == 0
        assert engine.supports_prosody is True
        assert engine.supports_ssml is False

    def test_engine_with_voices(self):
        """Test TTSEngine with voices list."""
        voices = [
            TTSVoiceTestHelpers.create_voice(id="voice1"),
            TTSVoiceTestHelpers.create_voice(id="voice2", name="Voice 2"),
        ]
        engine = TTSEngineTestHelpers.create_engine(voices=voices)
        assert len(engine.voices) == 2
        assert engine.voices[0].id == "voice1"
        assert engine.voices[1].id == "voice2"


class TestTTSVoicesResponse:
    """Tests for TTSVoicesResponse model."""

    def test_response_creation(self):
        """Test creating a TTSVoicesResponse."""
        engine = TTSEngineTestHelpers.create_engine()
        response = TTSVoicesResponseTestHelpers.create_response(
            engines={"test": engine},
            total_voices=5,
            default_engine="test",
            default_voice="test_voice",
        )
        assert response.engines == {"test": engine}
        assert response.total_voices == 5
        assert response.default_engine == "test"
        assert response.default_voice == "test_voice"

    def test_response_defaults(self):
        """Test TTSVoicesResponse default values."""
        response = TTSVoicesResponseTestHelpers.create_response()
        assert response.engines == {}
        assert response.total_voices == 0
        assert response.default_engine == "kokoro"
        assert response.default_voice == "kokoro_narrator"


class TestVoiceData:
    """Tests for voice data constants."""

    def test_kokoro_voices(self):
        """Test KOKORO_VOICES constant."""
        assert isinstance(KOKORO_VOICES, list)
        assert len(KOKORO_VOICES) > 0
        for voice in KOKORO_VOICES:
            assert isinstance(voice, TTSVoice)
            assert voice.id
            assert voice.name
            assert voice.gender
            assert voice.language

    def test_edge_tts_voices(self):
        """Test EDGE_TTS_VOICES constant."""
        assert isinstance(EDGE_TTS_VOICES, list)
        assert len(EDGE_TTS_VOICES) > 0
        for voice in EDGE_TTS_VOICES:
            assert isinstance(voice, TTSVoice)
            assert voice.id
            assert voice.name
            assert voice.gender
            assert voice.language

    def test_azure_voices(self):
        """Test AZURE_VOICES constant."""
        assert isinstance(AZURE_VOICES, list)
        # Might be empty in some configurations
        for voice in AZURE_VOICES:
            assert isinstance(voice, TTSVoice)
            assert voice.id
            assert voice.name
            assert voice.gender
            assert voice.language

    def test_gcp_voices(self):
        """Test GCP_VOICES constant."""
        assert isinstance(GCP_VOICES, list)
        # Might be empty in some configurations
        for voice in GCP_VOICES:
            assert isinstance(voice, TTSVoice)
            assert voice.id
            assert voice.name
            assert voice.gender
            assert voice.language

    def test_voxcpm2_voices(self):
        """Test VOXCPM2_VOICES constant."""
        assert isinstance(VOXCPM2_VOICES, list)
        assert len(VOXCPM2_VOICES) > 0
        for voice in VOXCPM2_VOICES:
            assert isinstance(voice, TTSVoice)
            assert voice.id
            assert voice.name
            assert voice.gender
            assert voice.language


class TestListTTSVoices:
    """Tests for list_tts_voices function."""

    @pytest.mark.asyncio
    async def test_list_voices_default(self):
        """Test listing voices with default parameters."""
        result = await list_tts_voices()
        assert isinstance(result, TTSVoicesResponse)
        assert result.total_voices >= 0
        assert result.default_engine == "kokoro"
        assert result.default_voice == "kokoro_narrator"
        # Should have all engines
        assert "kokoro" in result.engines
        assert "edge_tts" in result.engines
        assert "azure" in result.engines
        assert "gcp" in result.engines
        assert "voxcpm2" in result.engines

    @pytest.mark.asyncio
    async def test_list_voices_with_language_filter(self):
        """Test listing voices with language filter."""
        result = await list_tts_voices(language="zh-CN")
        assert isinstance(result, TTSVoicesResponse)
        # All voices should be zh-CN
        for engine in result.engines.values():
            for voice in engine.voices:
                assert voice.language == "zh-CN"

    @pytest.mark.asyncio
    async def test_list_voices_with_gender_filter(self):
        """Test listing voices with gender filter."""
        result = await list_tts_voices(gender="female")
        assert isinstance(result, TTSVoicesResponse)
        # All voices should be female
        for engine in result.engines.values():
            for voice in engine.voices:
                assert voice.gender == "female"

    @pytest.mark.asyncio
    async def test_list_voices_with_both_filters(self):
        """Test listing voices with both language and gender filters."""
        result = await list_tts_voices(language="zh-CN", gender="female")
        assert isinstance(result, TTSVoicesResponse)
        # All voices should be zh-CN and female
        for engine in result.engines.values():
            for voice in engine.voices:
                assert voice.language == "zh-CN"
                assert voice.gender == "female"

    @pytest.mark.asyncio
    async def test_list_voices_include_unavailable(self):
        """Test listing voices with include_unavailable=True."""
        result = await list_tts_voices(include_unavailable=True)
        assert isinstance(result, TTSVoicesResponse)
        # All engines should be included regardless of availability
        assert "kokoro" in result.engines
        assert "edge_tts" in result.engines
        assert "azure" in result.engines
        assert "gcp" in result.engines
        assert "voxcpm2" in result.engines

    @pytest.mark.asyncio
    async def test_list_voices_no_matches(self):
        """Test listing voices with filters that match nothing."""
        result = await list_tts_voices(language="xx-XX", gender="unknown")
        assert isinstance(result, TTSVoicesResponse)
        # Should have engines but possibly no voices
        assert isinstance(result.engines, dict)
        total_voices = sum(len(engine.voices) for engine in result.engines.values())
        assert total_voices == 0


class TestGetRecommendedVoices:
    """Tests for get_recommended_voices function."""

    @pytest.mark.asyncio
    async def test_get_recommended_voices_narration(self):
        """Getting recommended voices for narration."""
        result = await get_recommended_voices(context="narration")
        assert isinstance(result, dict)
        assert "context" in result
        assert "recommended" in result
        assert "count" in result
        assert result["context"] == "narration"
        assert isinstance(result["recommended"], list)
        assert result["count"] == len(result["recommended"])
        # All recommended voices should be neutral or contain "晓" (for Chinese)
        for voice in result["recommended"]:
            assert voice.gender == "neutral" or "晓" in voice.name

    @pytest.mark.asyncio
    async def test_get_recommended_voices_dialogue(self):
        """Getting recommended voices for dialogue."""
        result = await get_recommended_voices(context="dialogue")
        assert isinstance(result, dict)
        assert result["context"] == "dialogue"
        assert isinstance(result["recommended"], list)
        # All recommended voices should be male or female (not neutral)
        for voice in result["recommended"]:
            assert voice.gender in ("male", "female")

    @pytest.mark.asyncio
    async def test_get_recommended_voices_female_character(self):
        """Getting recommended voices for female character."""
        result = await get_recommended_voices(context="female_character")
        assert isinstance(result, dict)
        assert result["context"] == "female_character"
        assert isinstance(result["recommended"], list)
        # All recommended voices should be female
        for voice in result["recommended"]:
            assert voice.gender == "female"

    @pytest.mark.asyncio
    async def test_get_recommended_voices_male_character(self):
        """Getting recommended voices for male character."""
        result = await get_recommended_voices(context="male_character")
        assert isinstance(result, dict)
        assert result["context"] == "male_character"
        assert isinstance(result["recommended"], list)
        # All recommended voices should be male
        for voice in result["recommended"]:
            assert voice.gender == "male"

    @pytest.mark.asyncio
    async def test_get_recommended_voices_default_context(self):
        """Getting recommended voices with default context."""
        result = await get_recommended_voices()
        assert isinstance(result, dict)
        assert result["context"] == "general"
        assert isinstance(result["recommended"], list)
        assert result["count"] == len(result["recommended"])

    @pytest.mark.asyncio
    async def test_get_recommended_voices_with_language(self):
        """Getting recommended voices with language filter."""
        result = await get_recommended_voices(context="narration", language="zh-CN")
        assert isinstance(result, dict)
        assert result["context"] == "narration"
        assert isinstance(result["recommended"], list)
        # All voices should be zh-CN
        for voice in result["recommended"]:
            assert voice.language == "zh-CN"

    @pytest.mark.asyncio
    async def test_get_recommended_voices_empty_result(self):
        """Getting recommended voices when no matches."""
        # Use unlikely combination
        result = await get_recommended_voices(context="unknown", language="xx-XX")
        assert isinstance(result, dict)
        assert result["context"] == "unknown"
        assert isinstance(result["recommended"], list)
        # Might be empty or have fallback items
        assert result["count"] == len(result["recommended"])


class TestPreviewVoice:
    """Tests for preview_voice function."""

    @pytest.mark.asyncio
    async def test_preview_voice(self):
        """Testing voice preview."""
        voice_id = "test_voice"
        text = "Hello world"
        result = await preview_voice(voice_id, text)
        assert isinstance(result, dict)
        assert result["voice_id"] == voice_id
        assert result["text"] == text
        assert "preview_url" in result
        assert "note" in result
        assert result["preview_url"] == f"/api/tts/preview/{voice_id}.mp3"
        assert "placeholder" in result["note"].lower()

    @pytest.mark.asyncio
    async def test_preview_voice_default_text(self):
        """Testing voice preview with default text."""
        voice_id = "test_voice"
        result = await preview_voice(voice_id)
        assert result["voice_id"] == voice_id
        assert result["text"] == "这是一个语音试听样本。"

    @pytest.mark.asyncio
    async def test_preview_voice_empty_text(self):
        """Testing voice preview with empty text."""
        voice_id = "test_voice"
        result = await preview_voice(voice_id, "")
        assert result["voice_id"] == voice_id
        assert result["text"] == ""
        assert "preview_url" in result


class TestRouter:
    """Tests for the router object."""

    def test_router_exists(self):
        """Test that router exists and is an APIRouter."""
        assert router is not None
        # Check that it has routes
        assert hasattr(router, "routes")
        assert len(router.routes) > 0

    def test_router_routes(self):
        """Test that router has expected routes."""
        routes = router.routes
        path_methods = {}
        for route in routes:
            if hasattr(route, "path") and hasattr(route, "methods"):
                path_methods[route.path] = route.methods

        # Check for expected endpoints
        assert "/voices" in path_methods
        assert "GET" in path_methods["/voices"]
        assert "/voices/recommended" in path_methods
        assert "GET" in path_methods["/voices/recommended"]
        assert "/voices/preview/{voice_id}" in path_methods
        assert "GET" in path_methods["/voices/preview/{voice_id}"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])