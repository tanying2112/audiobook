"""
Tests for TTS Tasks (TEST-001: coverage improvement).

Tests for src/audiobook_studio/tasks/tts_tasks.py
Focus on testing actual available utilities and functions.
Target: 70%+ coverage
"""

import os
import sys

# Restore real celery module (conftest_minimal.py mocks it globally)
if 'celery' in sys.modules:
    del sys.modules['celery']
import celery  # noqa: F401 - ensure real celery is loaded

# Set TEST_MODE before any imports to use fake TTS port
os.environ["TEST_MODE"] = "true"
os.environ["MOCK_TTS"] = "true"

# Now import the module under test
from src.audiobook_studio.tasks import tts_tasks

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


class TestTTSTaskUtilities:
    """Tests for utility functions and constants in tts_tasks.py"""

    def test_acquire_lua_script(self):
        """Test _ACQUIRE_LUA script exists and has correct structure."""
        script = tts_tasks._ACQUIRE_LUA
        assert "redis.call" in script
        assert "GET" in script
        assert "INCR" in script
        assert "ARGV" in script
        assert "KEYS" in script

    def test_release_lua_script(self):
        """Test _RELEASE_LUA script exists."""
        script = tts_tasks._RELEASE_LUA
        assert "redis.call" in script
        assert "DECR" in script or "GET" in script


class TestTTSTaskIdempotency:
    """Tests for idempotency key generation and checking."""

    def test_idem_key_generation(self):
        """Test _idem_key generates consistent keys."""
        task = tts_tasks.TTSChapterTask()
        
        # Same inputs should produce same key
        key1 = task._idem_key("Hello world", "zh_female_1", {"rate": 1.0, "pitch": 0.0})
        key2 = task._idem_key("Hello world", "zh_female_1", {"rate": 1.0, "pitch": 0.0})
        assert key1 == key2
        
        # Different text should produce different key
        key3 = task._idem_key("Different text", "zh_female_1", {"rate": 1.0, "pitch": 0.0})
        assert key1 != key3
        
        # Different voice_id should produce different key
        key4 = task._idem_key("Hello world", "zh_male_1", {"rate": 1.0, "pitch": 0.0})
        assert key1 != key4
        
        # Different prosody should produce different key
        key5 = task._idem_key("Hello world", "zh_female_1", {"rate": 1.5, "pitch": 0.0})
        assert key1 != key5
        
        # Keys should have expected prefix and length
        assert key1.startswith("tts:idem:")
        assert len(key1) == len("tts:idem:") + 16  # 16 char hex digest

    def test_idem_key_prosody_order_independence(self):
        """Test that prosody dict key order doesn't affect idem key."""
        task = tts_tasks.TTSChapterTask()
        
        prosody1 = {"rate": 1.0, "pitch": 0.0, "volume": 0.0}
        prosody2 = {"volume": 0.0, "rate": 1.0, "pitch": 0.0}
        
        key1 = task._idem_key("Test text", "zh_female_1", prosody1)
        key2 = task._idem_key("Test text", "zh_female_1", prosody2)
        assert key1 == key2  # sort_keys=True in json.dumps ensures consistency

    def test_check_and_set_idempotency_no_redis(self):
        """Test _check_and_set_idempotency returns True when Redis unavailable."""
        task = tts_tasks.TTSChapterTask()
        
        with patch.object(tts_tasks, '_get_redis', return_value=None):
            result = task._check_and_set_idempotency("test_key")
            assert result is True  # Should proceed when Redis unavailable


class TestTTSTaskSemaphore:
    """Tests for semaphore acquire/release logic."""

    def test_acquire_semaphore_no_redis(self):
        """Test _acquire_semaphore returns True when Redis unavailable."""
        task = tts_tasks.TTSChapterTask()
        
        with patch.object(tts_tasks, '_get_redis', return_value=None):
            result = task._acquire_semaphore()
            assert result is True  # Should proceed without limit when Redis unavailable

    def test_release_semaphore_not_acquired(self):
        """Test _release_semaphore does nothing when not acquired."""
        task = tts_tasks.TTSChapterTask()
        task._semaphore_acquired = False
        
        # Should not raise any exception
        task._release_semaphore()
        assert task._semaphore_acquired is False


class TestTTSTaskFailedParagraphs:
    """Tests for failed paragraph tracking."""

    def test_record_failed_paragraph_no_redis(self):
        """Test _record_failed_paragraph handles missing Redis gracefully."""
        task = tts_tasks.TTSChapterTask()
        
        with patch.object(tts_tasks, '_get_redis', return_value=None):
            # Should not raise any exception
            task._record_failed_paragraph(1, 2, 3)

    def test_get_failed_paragraphs_no_redis(self):
        """Test _get_failed_paragraphs returns empty set when Redis unavailable."""
        task = tts_tasks.TTSChapterTask()
        
        with patch.object(tts_tasks, '_get_redis', return_value=None):
            result = task._get_failed_paragraphs(1, 2)
            assert result == set()

    def test_clear_failed_paragraphs_no_redis(self):
        """Test _clear_failed_paragraphs handles missing Redis gracefully."""
        task = tts_tasks.TTSChapterTask()
        
        with patch.object(tts_tasks, '_get_redis', return_value=None):
            # Should not raise any exception
            task._clear_failed_paragraphs(1, 2)


class TestTTSTaskCheckpoint:
    """Tests for checkpoint save/load/clear."""

    def test_save_checkpoint_no_redis(self):
        """Test _save_checkpoint handles missing Redis gracefully."""
        task = tts_tasks.TTSChapterTask()
        
        with patch.object(tts_tasks, '_get_redis', return_value=None):
            # Should not raise any exception
            task._save_checkpoint(1, 2, [1, 2], [3], "/path/audio.mp3", [{"segment_id": "test"}])

    def test_load_checkpoint_no_redis(self):
        """Test _load_checkpoint returns None when Redis unavailable."""
        task = tts_tasks.TTSChapterTask()
        
        with patch.object(tts_tasks, '_get_redis', return_value=None):
            result = task._load_checkpoint(1, 2)
            assert result is None

    def test_clear_checkpoint_no_redis(self):
        """Test _clear_checkpoint handles missing Redis gracefully."""
        task = tts_tasks.TTSChapterTask()
        
        with patch.object(tts_tasks, '_get_redis', return_value=None):
            # Should not raise any exception
            task._clear_checkpoint(1, 2)


class TestTTSTaskCallbacks:
    """Tests for Celery task callbacks (on_failure, on_retry, on_success)."""

    def test_on_failure_calls_cleanup(self):
        """Test on_failure calls release_semaphore and cleanup_port."""
        task = tts_tasks.TTSChapterTask()
        
        with patch.object(task, '_release_semaphore') as mock_release, \
             patch.object(task, '_cleanup_port') as mock_cleanup:
            task.on_failure(Exception("test"), "task_id", (), {}, None)
            mock_release.assert_called_once()
            mock_cleanup.assert_called_once()

    def test_on_retry_calls_cleanup(self):
        """Test on_retry calls release_semaphore and cleanup_port."""
        task = tts_tasks.TTSChapterTask()
        
        with patch.object(task, '_release_semaphore') as mock_release, \
             patch.object(task, '_cleanup_port') as mock_cleanup:
            task.on_retry(Exception("test"), "task_id", (), {}, None)
            mock_release.assert_called_once()
            mock_cleanup.assert_called_once()

    def test_on_success_calls_cleanup(self):
        """Test on_success calls release_semaphore and cleanup_port."""
        task = tts_tasks.TTSChapterTask()
        
        with patch.object(task, '_release_semaphore') as mock_release, \
             patch.object(task, '_cleanup_port') as mock_cleanup:
            task.on_success("result", "task_id", (), {})
            mock_release.assert_called_once()
            mock_cleanup.assert_called_once()


class TestBuildPortPayload:
    """Tests for _build_port_payload function."""

    def test_build_port_payload_defaults(self):
        """Test _build_port_payload with minimal prosody."""
        payload = tts_tasks._build_port_payload("Test text", "zh_female_1", {})
        
        assert payload.text == "Test text"
        assert payload.voice_anchor.voice_id == "zh_female_1"
        assert payload.voice_anchor.language == "zh-CN"
        assert payload.prosody.rate == 1.0
        assert payload.prosody.pitch == 0.0
        assert payload.prosody.volume == 0.0
        assert payload.prosody.emotion is None
        assert payload.metadata["source"] == "celery_task"
        assert payload.metadata["prosody_raw"] == {}

    def test_build_port_payload_custom_prosody(self):
        """Test _build_port_payload with custom prosody."""
        prosody = {"rate": 1.5, "pitch": 5.0, "volume": -2.0, "emotion": "happy"}
        payload = tts_tasks._build_port_payload("Test text", "zh_male_1", prosody)
        
        assert payload.text == "Test text"
        assert payload.voice_anchor.voice_id == "zh_male_1"
        assert payload.prosody.rate == 1.5
        assert payload.prosody.pitch == 5.0
        assert payload.prosody.volume == -2.0
        assert payload.prosody.emotion == "happy"
        assert payload.metadata["prosody_raw"] == prosody


class TestGetAudioDuration:
    """Tests for _get_audio_duration function."""

    @patch('subprocess.run')
    def test_get_audio_duration_ffprobe_success(self, mock_run):
        """Test _get_audio_duration with successful ffprobe."""
        from pathlib import Path
        
        mock_run.return_value = MagicMock(returncode=0, stdout="10.5\n")
        
        result = tts_tasks._get_audio_duration(Path("/fake/path/audio.wav"))
        
        assert result == 10500  # 10.5 seconds * 1000
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_get_audio_duration_ffprobe_failure(self, mock_run):
        """Test _get_audio_duration falls back to file size estimation."""
        from pathlib import Path
        
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        
        with patch.object(Path, 'stat') as mock_stat:
            mock_stat.return_value.st_size = 480000  # ~10 seconds at 48KB/s
            result = tts_tasks._get_audio_duration(Path("/fake/path/audio.wav"))
            
            # Fallback: size / 48000 * 1000
            assert result == 10000

    @patch('subprocess.run')
    def test_get_audio_duration_exception(self, mock_run):
        """Test _get_audio_duration handles exceptions."""
        from pathlib import Path
        
        mock_run.side_effect = FileNotFoundError("ffprobe not found")
        
        with patch.object(Path, 'stat') as mock_stat:
            mock_stat.return_value.st_size = 480000
            result = tts_tasks._get_audio_duration(Path("/fake/path/audio.wav"))
            assert result == 10000


class TestTTSChapterTaskCrossfade:
    """Tests for crossfade-related methods."""

    def test_get_crossfade_ms_default(self):
        """Test _get_crossfade_ms returns default."""
        task = tts_tasks.TTSChapterTask()
        
        with patch.dict(os.environ, {}, clear=True):
            result = task._get_crossfade_ms()
            assert result == 50

    def test_get_crossfade_ms_from_env(self):
        """Test _get_crossfade_ms reads from environment."""
        task = tts_tasks.TTSChapterTask()
        
        with patch.dict(os.environ, {"CROSSFADE_MS": "100"}):
            result = task._get_crossfade_ms()
            assert result == 100

    def test_get_crossfade_ms_invalid_env(self):
        """Test _get_crossfade_ms handles invalid env value."""
        task = tts_tasks.TTSChapterTask()
        
        with patch.dict(os.environ, {"CROSSFADE_MS": "invalid"}):
            result = task._get_crossfade_ms()
            assert result == 50  # falls back to default


class TestTTSChapterTaskPort:
    """Tests for port-related methods."""

    def test_get_port_lazy_init(self):
        """Test _get_port creates port lazily."""
        task = tts_tasks.TTSChapterTask()
        
        # Mock get_port to return a synchronous value (since _get_port doesn't await it)
        mock_port = MagicMock()
        
        with patch('src.audiobook_studio.tasks.tts_tasks.get_port', new=lambda: mock_port):
            port = task._get_port()
            assert port == mock_port
            
            # Second call should return cached port
            port2 = task._get_port()
            assert port2 == mock_port


class TestCleanupPort:
    """Tests for _cleanup_port method."""

    def test_cleanup_port_closes_port(self):
        """Test _cleanup_port properly closes port."""
        task = tts_tasks.TTSChapterTask()
        mock_port = AsyncMock()
        task._port = mock_port
        
        # TTSChapterTask._cleanup_port uses asyncio.run
        with patch('asyncio.run') as mock_run:
            task._cleanup_port()
            mock_run.assert_called_once()
        
        assert task._port is None  # Should be cleared


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])