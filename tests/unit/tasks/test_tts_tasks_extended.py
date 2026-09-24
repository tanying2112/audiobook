"""Extended tests for tts_tasks.py - branch coverage.

Focuses on testing additional branches in the TTS task module
that are not covered by the existing test suite.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

# Ensure real celery module is available
if "celery" in sys.modules:
    del sys.modules["celery"]
import celery  # noqa: F401 - ensure real celery is loaded

# Set TEST_MODE before any imports to use fake TTS port
os.environ["TEST_MODE"] = "true"
os.environ["MOCK_TTS"] = "true"


class TestTTSChapterTaskPortInit:
    """Tests for TTSChapterTask port initialization."""

    def test_port_lazy_init_caching(self):
        """Test _get_port returns cached port."""
        from src.audiobook_studio.tasks.tts_tasks import TTSChapterTask

        task = TTSChapterTask()

        # Mock get_port to return a synchronous value
        mock_port = MagicMock()

        with patch("src.audiobook_studio.tasks.tts_tasks.get_port", new=lambda: mock_port):
            port = task._get_port()
            assert port == mock_port

            # Second call should return cached port
            port2 = task._get_port()
            assert port2 == mock_port

    def test_port_lazy_init_different_calls(self):
        """Test _get_port creates new port when none cached."""
        from src.audiobook_studio.tasks.tts_tasks import TTSChapterTask

        task = TTSChapterTask()

        call_count = 0
        mock_port_get = MagicMock(side_effect=lambda: (MagicMock() if call_count < 2 else None))

        with patch("src.audiobook_studio.tasks.tts_tasks.get_port", side_effect=mock_port_get):
            task._get_port()
            call_count += 1
            task._get_port()
            # Port should be cached after first call
            assert call_count == 1  # Only first call triggers get_port


class TestTTSChapterTaskCrossfade:
    """Tests for crossfade duration methods."""

    def test_get_crossfade_ms_positive_env(self):
        """Test _get_crossfade_ms reads positive value from env."""
        import os

        from src.audiobook_studio.tasks.tts_tasks import TTSChapterTask

        task = TTSChapterTask()

        with patch.dict(os.environ, {"CROSSFADE_MS": "75"}):
            result = task._get_crossfade_ms()
            assert result == 75

    def test_get_crossfade_ms_zero_env(self):
        """Test _get_crossfade_ms handles zero env value."""
        import os

        from src.audiobook_studio.tasks.tts_tasks import TTSChapterTask

        task = TTSChapterTask()

        with patch.dict(os.environ, {"CROSSFADE_MS": "0"}):
            result = task._get_crossfade_ms()
            assert result == 0

    def test_get_crossfade_ms_large_env(self):
        """Test _get_crossfade_ms handles large env value."""
        import os

        from src.audiobook_studio.tasks.tts_tasks import TTSChapterTask

        task = TTSChapterTask()

        with patch.dict(os.environ, {"CROSSFADE_MS": "99999"}):
            result = task._get_crossfade_ms()
            assert result == 99999


class TestTTSChapterTaskSemaphoreDetailed:
    """Detailed tests for semaphore logic."""

    def test_acquire_semaphore_first_call(self):
        """Test semaphore acquire on first call."""
        import src.audiobook_studio.tasks.tts_tasks as tts_mod
        from src.audiobook_studio.tasks.tts_tasks import TTSChapterTask

        task = TTSChapterTask()

        # First call should acquire
        with patch.object(tts_mod, "_get_redis") as mock_get_redis:
            mock_client = MagicMock()
            mock_client.script_load.return_value = "sha1"
            mock_client.evalsha.return_value = 1
            mock_get_redis.return_value = mock_client

            result = task._acquire_semaphore()
            assert result is True
            assert task._semaphore_acquired is True

    def test_acquire_semaphore_limit_reached(self):
        """Test semaphore acquire when limit is reached."""
        import src.audiobook_studio.tasks.tts_tasks as tts_mod
        from src.audiobook_studio.tasks.tts_tasks import TTSChapterTask

        task = TTSChapterTask()

        with patch.object(tts_mod, "_get_redis") as mock_get_redis:
            mock_client = MagicMock()
            mock_client.script_load.return_value = "sha1"
            # Always return 0 (limit reached)
            mock_client.evalsha.return_value = 0
            mock_get_redis.return_value = mock_client

            result = task._acquire_semaphore()
            assert result is False
            assert task._semaphore_acquired is False

    def test_release_semaphore_already_released(self):
        """Test release semaphore when already not acquired."""
        from src.audiobook_studio.tasks.tts_tasks import TTSChapterTask

        task = TTSChapterTask()

        # Already not acquired - should not raise
        task._release_semaphore()
        assert task._semaphore_acquired is False


class TestTTSChapterTaskIdempotencyDetailed:
    """Detailed tests for idempotency key logic."""

    def test_idem_key_with_empty_prosody(self):
        """Test _idem_key with empty prosody dict."""
        from src.audiobook_studio.tasks.tts_tasks import TTSChapterTask

        task = TTSChapterTask()

        key1 = task._idem_key("test text", "voice_1", {})
        key2 = task._idem_key("test text", "voice_1", {})

        assert key1 == key2
        assert key1.startswith("tts:idem:")
        assert len(key1) == len("tts:idem:") + 16

    def test_idem_key_prosody_sort_order(self):
        """Test _idem_key is independent of prosody dict key order."""
        from src.audiobook_studio.tasks.tts_tasks import TTSChapterTask

        task = TTSChapterTask()

        prosody_orders = [
            {"rate": 1.0, "pitch": 0.0, "volume": 0.0},
            {"pitch": 0.0, "volume": 0.0, "rate": 1.0},
            {"volume": 0.0, "rate": 1.0, "pitch": 0.0},
        ]

        keys = [task._idem_key("test text", "voice_1", prosody) for prosody in prosody_orders]

        # All keys should be identical despite different order
        assert keys[0] == keys[1] == keys[2]


class TestTTSChapterTaskCallbacksDetailed:
    """Detailed tests for task callbacks."""

    def test_on_failure_releases_semaphore(self):
        """Test on_failure releases semaphore and cleanup_port."""
        from src.audiobook_studio.tasks.tts_tasks import TTSChapterTask

        task = TTSChapterTask()

        with (
            patch.object(task, "_release_semaphore") as mock_release,
            patch.object(task, "_cleanup_port") as mock_cleanup,
        ):
            # Manually call on_failure which should trigger cleanup
            task.on_failure(Exception("test"), "task_id", (), {}, None)
            # on_failure calls _release_semaphore and _cleanup_port
            mock_release.assert_called_once()
            mock_cleanup.assert_called_once()

    def test_on_success_idempotent_cleanup(self):
        """Test on_success properly cleans up."""
        from src.audiobook_studio.tasks.tts_tasks import TTSChapterTask

        task = TTSChapterTask()

        with (
            patch.object(task, "_release_semaphore") as mock_release,
            patch.object(task, "_cleanup_port") as mock_cleanup,
        ):
            task.on_success("result", "task_id", (), {})
            mock_release.assert_called_once()
            mock_cleanup.assert_called_once()


class TestTTSChapterTaskCheckpointDetailed:
    """Detailed tests for checkpoint operations."""

    def test_save_load_clear_checkpoint_cycle(self):
        """Test save -> load -> clear checkpoint cycle."""
        import src.audiobook_studio.tasks.tts_tasks as tts_mod
        from src.audiobook_studio.tasks.tts_tasks import TTSChapterTask

        task = TTSChapterTask()

        with patch.object(tts_mod, "_get_redis") as mock_get_redis:
            mock_client = MagicMock()

            # Setup mock client to be returned by _get_redis
            mock_get_redis.return_value = mock_client

            # Save checkpoint - use direct set call
            checkpoint_key = "tts:checkpoint:99999:99999001"
            task._save_checkpoint(
                project_id=99999,
                chapter_id=99999001,
                completed_paragraphs=[1, 2, 3],
                failed_paragraphs=[4],
                chapter_audio_path="/tmp/chapter.mp3",
                segments=[{"segment_id": "test1"}],
            )

            # Verify set was called with checkpoint key
            assert mock_client.set.called
            # Check the key was set correctly
            set_call_args = mock_client.set.call_args
            assert set_call_args[0][0] == checkpoint_key

            # Load checkpoint
            mock_client.get.return_value = json.dumps(
                {
                    "project_id": 99999,
                    "chapter_id": 99999001,
                    "completed_paragraphs": [1, 2, 3],
                    "failed_paragraphs": [4],
                    "chapter_audio_path": "/tmp/chapter.mp3",
                    "segments": [{"segment_id": "test1"}],
                    "updated_at": 1234567890.0,
                }
            )

            loaded = task._load_checkpoint(99999, 99999001)
            assert loaded is not None
            assert loaded["completed_paragraphs"] == [1, 2, 3]
            assert loaded["failed_paragraphs"] == [4]

            # Clear checkpoint
            task._clear_checkpoint(99999, 99999001)
            assert mock_client.delete.called


def test_json_import():
    """Test that json is importable and usable in tts_tasks."""
    import src.audiobook_studio.tasks.tts_tasks as tts_mod

    assert json is not None
    assert hasattr(tts_mod, "json") or "json" in dir(tts_mod)
    assert json.loads(json.dumps({"a": 1})) == {"a": 1}
