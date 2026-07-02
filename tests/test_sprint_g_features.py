"""Tests for Sprint G features — placeholder implementation.

These tests only exercise mock_mode / import paths for stub implementations.
They are frozen until Sprint G is upgraded to real, usable code.
"""

import os

os.environ["MOCK_LLM"] = "true"

import sys

import pytest

pytestmark = pytest.mark.skip(
    reason="Sprint G Placeholder — translate/publish/self-iteration are stub " "implementations, not real usable code"
)

sys.path.insert(0, "src")


def test_translate_pipeline_import():
    """Test that translate pipeline can be imported."""
    from audiobook_studio.pipeline.translate import TranslateAndDubPipeline

    assert TranslateAndDubPipeline is not None


def test_semantic_coherence_import():
    """Test that semantic coherence checker can be imported."""
    from audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker

    assert SemanticCoherenceChecker is not None


def test_voice_cloning_import():
    """Test that voice cloning engine can be imported."""
    from audiobook_studio.tts.clone import VoiceCloningEngine

    assert VoiceCloningEngine is not None


def test_audiobookshelf_publisher_import():
    """Test that audiobookshelf publisher can be imported."""
    from audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

    assert AudiobookshelfPublisher is not None


def test_collab_api_import():
    """Test that collaboration API can be imported."""
    from audiobook_studio.api.collab import router

    assert router is not None


def test_rss_feed_import():
    """Test that RSS feed generator can be imported."""
    from audiobook_studio.publish.rss import RssFeedGenerator

    assert RssFeedGenerator is not None


def test_self_iteration_loop_import():
    """Test that self iteration loop can be imported."""
    from audiobook_studio.feedback.integration import SelfIterationLoop

    assert SelfIterationLoop is not None


def test_translate_pipeline_instantiation():
    """Test that translate pipeline can be instantiated."""
    from audiobook_studio.pipeline.translate import TranslateAndDubPipeline

    pipeline = TranslateAndDubPipeline(mock_mode=True)
    assert pipeline is not None
    assert pipeline.mock_mode is True


def test_semantic_coherence_instantiation():
    """Test that semantic coherence checker can be instantiated."""
    from audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker

    checker = SemanticCoherenceChecker()
    assert checker is not None


def test_voice_cloning_instantiation():
    """Test that voice cloning engine can be instantiated."""
    from audiobook_studio.tts.clone import VoiceCloningEngine

    engine = VoiceCloningEngine()
    assert engine is not None


def test_audiobookshelf_publisher_instantiation():
    """Test that audiobookshelf publisher can be instantiated."""
    from audiobook_studio.publish.audiobookshelf import AudiobookshelfConfig, AudiobookshelfPublisher

    config = AudiobookshelfConfig(
        api_url="http://localhost:8080/api",
        api_key="test_key",
        library_id="test_library",
    )
    publisher = AudiobookshelfPublisher(config)
    assert publisher is not None


def test_rss_feed_instantiation():
    """Test that RSS feed generator can be instantiated."""
    from audiobook_studio.publish.rss import RssFeedGenerator

    generator = RssFeedGenerator(base_url="http://localhost:8000")
    assert generator is not None
    assert generator.base_url == "http://localhost:8000"


def test_self_iteration_loop_instantiation():
    """Test that self iteration loop can be instantiated."""
    from unittest.mock import MagicMock

    from sqlalchemy.orm import Session

    from audiobook_studio.feedback.integration import SelfIterationLoop

    mock_session_factory = MagicMock(return_value=MagicMock(spec=Session))
    loop = SelfIterationLoop(db_session_factory=mock_session_factory, project_id=1)
    assert loop is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
