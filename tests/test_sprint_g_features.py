"""Tests for Sprint G features."""

import sys
import pytest

sys.path.insert(0, "src")


def test_translate_pipeline_import():
    """Test that translate pipeline can be imported."""
    from audiobook_studio.pipeline.translate import TranslateAndDubPipeline
    assert TranslateAndDubPipeline is not None


def test_semantic_coherence_import():
    """Test that semantic coherence checker can be imported."""
    from scripts.semantic_coherence import SemanticCoherenceChecker
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
    from scripts.self_iteration_loop import SelfIterationLoop
    assert SelfIterationLoop is not None


def test_translate_pipeline_instantiation():
    """Test that translate pipeline can be instantiated."""
    from audiobook_studio.pipeline.translate import TranslateAndDubPipeline
    pipeline = TranslateAndDubPipeline(mock_mode=True)
    assert pipeline is not None
    assert pipeline.mock_mode is True


def test_semantic_coherence_instantiation():
    """Test that semantic coherence checker can be instantiated."""
    from scripts.semantic_coherence import SemanticCoherenceChecker
    checker = SemanticCoherenceChecker()
    assert checker is not None


def test_voice_cloning_instantiation():
    """Test that voice cloning engine can be instantiated."""
    from audiobook_studio.tts.clone import VoiceCloningEngine
    engine = VoiceCloningEngine()
    assert engine is not None


def test_audiobookshelf_publisher_instantiation():
    """Test that audiobookshelf publisher can be instantiated."""
    from audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher
    from audiobook_studio.publish.audiobookshelf import AudiobookshelfConfig

    config = AudiobookshelfConfig(
        api_url="http://localhost:8080/api",
        api_key="test_key",
        library_id="test_library"
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
    from scripts.self_iteration_loop import SelfIterationLoop
    loop = SelfIterationLoop(auto_merge=False, auto_deploy=False)
    assert loop is not None
    assert loop.auto_merge is False
    assert loop.auto_deploy is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])