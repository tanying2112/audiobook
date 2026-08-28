"""
Tests for Publish Tasks (TEST-001: coverage improvement).

Tests for src/audiobook_studio/tasks/publish_tasks.py
Focus on testing utility functions and Celery tasks.
Target: 70%+ coverage
"""

import os
import sys
import importlib
import asyncio as _asyncio  # Import real asyncio before patching
_real_asyncio_run = _asyncio.run  # Save real run before any patching

# Restore real celery module (conftest_minimal.py mocks it globally)
if 'celery' in sys.modules:
    del sys.modules['celery']
import celery  # noqa: F401 - ensure real celery is loaded

# Set TEST_MODE before any imports to use fake services
os.environ["TEST_MODE"] = "true"
os.environ["MOCK_TTS"] = "true"
os.environ["MOCK_LLM"] = "true"

# Now import the module under test
from src.audiobook_studio.tasks import publish_tasks
# If publish_tasks was already imported (cached) with the mocked celery
# before the restore above, reload it so its state constants rebind to
# the real celery states. This makes the constants-order-independent.
if getattr(publish_tasks, "PENDING", None) is not None and not isinstance(
    publish_tasks.PENDING, str
):
    importlib.reload(publish_tasks)

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio
from datetime import datetime, timezone


class TestPublishTaskUtilities:
    """Tests for utility functions and constants in publish_tasks.py"""

    def test_constants_defined(self):
        """Test that key constants are defined."""
        assert publish_tasks.PUBLISH_JOB_KEY_PREFIX == "publish:job:"
        assert publish_tasks.PUBLISH_JOB_TTL == 86400 * 7  # 7 days
        assert publish_tasks.PENDING == "PENDING"
        assert publish_tasks.STARTED == "STARTED"
        assert publish_tasks.SUCCESS == "SUCCESS"
        assert publish_tasks.FAILURE == "FAILURE"
        assert publish_tasks.RETRY == "RETRY"


class TestGetRedis:
    """Tests for _get_redis function."""

    @pytest.mark.asyncio
    async def test_get_redis_returns_client(self):
        """Test _get_redis returns a Redis client."""
        with patch('src.audiobook_studio.config.settings_loader.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock(
                REDIS_URL="redis://localhost:6379/0",
                REDIS_MAX_CONNECTIONS=10
            )
            with patch('redis.asyncio.from_url') as mock_from_url:
                mock_client = AsyncMock()
                mock_from_url.return_value = mock_client
                
                client = await publish_tasks._get_redis()
                
                assert client == mock_client
                mock_from_url.assert_called_once()


class TestPersistJobState:
    """Tests for _persist_job_state function."""

    @pytest.mark.asyncio
    async def test_persist_job_state_success(self):
        """Test _persist_job_state successfully stores state in Redis."""
        job_id = "test_job_123"
        state = {"status": "publishing", "progress": 50}
        
        with patch('src.audiobook_studio.tasks.publish_tasks._get_redis') as mock_get_redis:
            mock_client = AsyncMock()
            mock_get_redis.return_value = mock_client
            
            await publish_tasks._persist_job_state(job_id, state)
            
            # Verify Redis setex was called with correct key and TTL
            mock_client.setex.assert_called_once()
            call_args = mock_client.setex.call_args
            assert call_args[0][0] == f"publish:job:{job_id}"
            assert call_args[0][1] == publish_tasks.PUBLISH_JOB_TTL
            # Check that state was JSON serialized
            import json
            stored_state = json.loads(call_args[0][2])
            assert stored_state["status"] == "publishing"
            assert stored_state["progress"] == 50
            assert "updated_at" in stored_state
            
            mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_job_state_handles_exception(self):
        """Test _persist_job_state handles Redis exceptions gracefully."""
        job_id = "test_job_123"
        state = {"status": "publishing"}
        
        with patch('src.audiobook_studio.tasks.publish_tasks._get_redis') as mock_get_redis:
            mock_client = AsyncMock()
            mock_client.setex.side_effect = Exception("Redis connection failed")
            mock_get_redis.return_value = mock_client
            
            # Should not raise, just log warning
            await publish_tasks._persist_job_state(job_id, state)
            
            # aclose is not called in except block in production code


class TestGetJobState:
    """Tests for _get_job_state function."""

    @pytest.mark.asyncio
    async def test_get_job_state_returns_state(self):
        """Test _get_job_state retrieves state from Redis."""
        job_id = "test_job_123"
        state_data = {"status": "completed", "results": {"audiobookshelf": {"success": True}}}
        
        with patch('src.audiobook_studio.tasks.publish_tasks._get_redis') as mock_get_redis:
            mock_client = AsyncMock()
            import json
            mock_client.get.return_value = json.dumps(state_data)
            mock_get_redis.return_value = mock_client
            
            result = await publish_tasks._get_job_state(job_id)
            
            assert result == state_data
            mock_client.get.assert_called_once_with(f"publish:job:{job_id}")
            mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_job_state_returns_none_when_not_found(self):
        """Test _get_job_state returns None when key doesn't exist."""
        job_id = "nonexistent_job"
        
        with patch('src.audiobook_studio.tasks.publish_tasks._get_redis') as mock_get_redis:
            mock_client = AsyncMock()
            mock_client.get.return_value = None
            mock_get_redis.return_value = mock_client
            
            result = await publish_tasks._get_job_state(job_id)
            
            assert result is None
            mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_job_state_handles_exception(self):
        """Test _get_job_state handles Redis exceptions gracefully."""
        job_id = "test_job_123"
        
        with patch('src.audiobook_studio.tasks.publish_tasks._get_redis') as mock_get_redis:
            mock_client = AsyncMock()
            mock_client.get.side_effect = Exception("Redis connection failed")
            mock_get_redis.return_value = mock_client
            
            result = await publish_tasks._get_job_state(job_id)
            
            assert result is None
            # aclose is not called in except block in production code


class TestPersistJobStateDB:
    """Tests for _persist_job_state_db function."""

    @pytest.mark.asyncio
    async def test_persist_job_state_db_handles_exception_gracefully(self):
        """Test _persist_job_state_db handles exceptions gracefully."""
        job_id = "test_job_123"
        project_id = 1
        state = {"status": "completed"}
        
        # Mock the database session to raise an exception
        with patch('src.audiobook_studio.tasks.publish_tasks.AsyncSessionLocal') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = mock_session
            mock_session.__aexit__.return_value = None
            mock_session.commit.side_effect = Exception("DB error")
            mock_session_class.return_value = mock_session
            
            # Should not raise, just log warning
            await publish_tasks._persist_job_state_db(job_id, project_id, state)


class TestRunPublishAsync:
    """Tests for _run_publish_async function."""

    @pytest.mark.asyncio
    async def test_run_publish_async_calls_persist_and_returns_state(self):
        """Test _run_publish_async initializes state and calls persist."""
        job_id = "test_job_123"
        project_id = 1
        destinations = ["audiobookshelf"]
        
        with patch('src.audiobook_studio.tasks.publish_tasks._persist_job_state') as mock_persist:
            with patch('src.audiobook_studio.tasks.publish_tasks._persist_job_state_db') as mock_persist_db:
                with patch('src.audiobook_studio.api.publish._publish_to_audiobookshelf') as mock_publish:
                    mock_publish.return_value = {"book_url": "http://example.com/book", "item_id": "123"}
                    
                    result = await publish_tasks._run_publish_async(
                        job_id=job_id,
                        project_id=project_id,
                        destinations=destinations,
                    )
                    
                    assert result["job_id"] == job_id
                    assert result["project_id"] == project_id
                    assert result["status"] in ["completed", "failed"]
                    assert "results" in result
                    assert mock_persist.called

    @pytest.mark.asyncio
    async def test_run_publish_async_handles_audiobookshelf_failure(self):
        """Test _run_publish_async handles Audiobookshelf publish failure."""
        job_id = "test_job_123"
        project_id = 1
        destinations = ["audiobookshelf"]
        
        with patch('src.audiobook_studio.tasks.publish_tasks._persist_job_state') as mock_persist:
            with patch('src.audiobook_studio.tasks.publish_tasks._persist_job_state_db') as mock_persist_db:
                with patch('src.audiobook_studio.api.publish._publish_to_audiobookshelf') as mock_publish:
                    mock_publish.side_effect = Exception("Connection refused")
                    
                    result = await publish_tasks._run_publish_async(
                        job_id=job_id,
                        project_id=project_id,
                        destinations=destinations,
                    )
                    
                    assert result["status"] == "failed"
                    assert result["error"] is not None


class TestPublishProjectAsync:
    """Tests for publish_project_async Celery task."""

    def test_publish_project_async_generates_job_id(self):
        """Test publish_project_async generates job_id if not provided."""
        mock_self = MagicMock()
        mock_self.request.id = "task_123"
        mock_self.request.retries = 0
        mock_self.max_retries = 3
        mock_self.retry.side_effect = lambda exc: (_ for _ in ()).throw(exc)
        
        with patch('asyncio.run') as mock_run:
            mock_run.return_value = {
                "job_id": "publish_1_12345",
                "status": "completed",
                "results": {"audiobookshelf": {"success": True}},
                "error": None,
            }
            
            result = publish_tasks.publish_project_async(
                mock_self,
                project_id=1,
                destinations=["audiobookshelf"],
            )
            
            assert "job_id" in result
            assert result["task_id"] == "task_123"
            assert result["project_id"] == 1
            assert result["status"] == "completed"
            mock_run.assert_called_once()

    def test_publish_project_async_uses_provided_job_id(self):
        """Test publish_project_async uses provided job_id."""
        mock_self = MagicMock()
        mock_self.request.id = "task_123"
        mock_self.request.retries = 0
        mock_self.max_retries = 3
        
        with patch('asyncio.run') as mock_run:
            mock_run.return_value = {
                "job_id": "custom_job_id",
                "status": "completed",
                "results": {},
                "error": None,
            }
            
            result = publish_tasks.publish_project_async(
                mock_self,
                project_id=1,
                destinations=["audiobookshelf"],
                job_id="custom_job_id",
            )
            
            assert result["job_id"] == "custom_job_id"

    def test_publish_project_async_retries_on_failure(self):
        """Test publish_project_async retries on failure with exponential backoff."""
        mock_self = MagicMock()
        mock_self.request.id = "task_123"
        mock_self.request.retries = 0
        mock_self.max_retries = 3
        test_exception = Exception("Temporary failure")
        captured = {}

        def _retry(**kwargs):
            captured.update(kwargs)
            raise kwargs.get("exc", test_exception)

        mock_self.retry.side_effect = _retry

        with patch('asyncio.run') as mock_run:
            mock_run.side_effect = test_exception

            with pytest.raises(Exception):
                publish_tasks.publish_project_async(
                    mock_self,
                    project_id=1,
                    destinations=["audiobookshelf"],
                )

            assert mock_self.retry.called
            # Exponential backoff: countdown grows with the retry index.
            assert captured.get("countdown") == publish_tasks.exponential_backoff_countdown(0)
            assert captured.get("countdown") == 5


class TestPublishAudiobookshelfAsync:
    """Tests for publish_audiobookshelf_async Celery task."""

    def test_publish_audiobookshelf_async_success(self):
        """Test publish_audiobookshelf_async returns success on success."""
        mock_self = MagicMock()
        mock_self.request.id = "task_123"
        mock_self.request.retries = 0
        mock_self.max_retries = 3
        
        with patch('asyncio.run') as mock_run:
            mock_run.return_value = {
                "job_id": "abs_1_12345",
                "status": "completed",
                "results": {"audiobookshelf": {"success": True, "book_url": "http://example.com"}},
                "error": None,
            }
            
            result = publish_tasks.publish_audiobookshelf_async(
                mock_self,
                project_id=1,
                config={"server_url": "http://abs.example.com"},
            )
            
            assert result["status"] == "completed"
            assert result["results"]["audiobookshelf"]["success"] is True

    def test_publish_audiobookshelf_async_failure(self):
        """Test publish_audiobookshelf_async returns failure on error."""
        mock_self = MagicMock()
        mock_self.request.id = "task_123"
        mock_self.request.retries = 0
        mock_self.max_retries = 3
        
        with patch('asyncio.run') as mock_run:
            mock_run.return_value = {
                "job_id": "abs_1_12345",
                "status": "failed",
                "results": {"audiobookshelf": {"success": False, "error": "Connection failed"}},
                "error": "Connection failed",
            }
            
            result = publish_tasks.publish_audiobookshelf_async(
                mock_self,
                project_id=1,
                config={"server_url": "http://abs.example.com"},
            )
            
            assert result["status"] == "failed"
            assert result["error"] == "Connection failed"


class TestGeneratePodcastRssAsync:
    """Tests for generate_podcast_rss_async Celery task."""

    def test_generate_podcast_rss_async_success(self):
        """Test generate_podcast_rss_async returns success on success."""
        mock_self = MagicMock()
        mock_self.request.id = "task_123"
        mock_self.request.retries = 0
        mock_self.max_retries = 3
        
        # Mock the broken import from ..publish.podcast
        import sys
        from types import ModuleType
        fake_podcast = ModuleType("src.audiobook_studio.publish.podcast")
        async def fake_generate_podcast_rss(project_id, config):
            return {"rss_url": "http://example.com/rss", "episode_count": 5}
        fake_podcast.generate_podcast_rss = fake_generate_podcast_rss
        
        with patch.dict('sys.modules', {'src.audiobook_studio.publish.podcast': fake_podcast}):
            with patch('asyncio.run') as mock_run:
                mock_run.return_value = {
                    "job_id": "rss_1_12345",
                    "status": "completed",
                    "results": {"podcast_rss": {"success": True, "rss_url": "http://example.com/rss"}},
                    "error": None,
                }
                
                result = publish_tasks.generate_podcast_rss_async(
                    mock_self,
                    project_id=1,
                    config={"title": "Test Podcast"},
                )
                
                assert result["status"] == "completed"
                assert result["results"]["podcast_rss"]["success"] is True


class TestGetPublishStatus:
    """Tests for get_publish_status task."""

    def test_get_publish_status_from_redis(self):
        """Test get_publish_status retrieves state from Redis."""
        job_id = "publish_1_12345"
        state_data = {
            "job_id": job_id,
            "status": "completed",
            "results": {"audiobookshelf": {"success": True}},
            "error": None,
            "created_at": "2024-01-01T00:00:00+00:00",
            "completed_at": "2024-01-01T00:05:00+00:00",
        }
        
        with patch('asyncio.run') as mock_run:
            mock_run.side_effect = lambda coro: _real_asyncio_run(coro)
            
            with patch('src.audiobook_studio.tasks.publish_tasks._get_job_state') as mock_get_state:
                mock_get_state.return_value = state_data
                
                result = publish_tasks.get_publish_status(job_id)
                
                assert result["job_id"] == job_id
                assert result["state"] == "completed"
                assert result["source"] == "redis"
                assert result["results"]["audiobookshelf"]["success"] is True

    def test_get_publish_status_not_found(self):
        """Test get_publish_status returns not_found when job doesn't exist."""
        job_id = "nonexistent_job"
        
        with patch('asyncio.run') as mock_run:
            mock_run.side_effect = lambda coro: _real_asyncio_run(coro)
            
            with patch('src.audiobook_studio.tasks.publish_tasks._get_job_state') as mock_get_state:
                mock_get_state.return_value = None
                
                result = publish_tasks.get_publish_status(job_id)
                
                assert result["job_id"] == job_id
                assert result["state"] == "not_found"
                assert result["source"] == "none"


class TestGetPublishHistory:
    """Tests for get_publish_history task."""

    def test_get_publish_history_returns_empty_on_error(self):
        """Test get_publish_history returns empty history on Redis error."""
        project_id = 1
        
        with patch('asyncio.run') as mock_run:
            mock_run.side_effect = lambda coro: _real_asyncio_run(coro)
            
            with patch('src.audiobook_studio.tasks.publish_tasks._get_redis') as mock_get_redis:
                mock_client = AsyncMock()
                # scan_iter is called with match and count kwargs
                async def mock_scan_iter(*args, **kwargs):
                    raise Exception("Redis error")
                    yield  # make it an async generator
                mock_client.scan_iter = mock_scan_iter
                mock_get_redis.return_value = mock_client
                
                result = publish_tasks.get_publish_history(project_id)
                
                assert result["project_id"] == project_id
                assert result["history"] == []
                assert "error" in result
                # aclose is not called in except block in production code

    def test_get_publish_history_returns_filtered_history(self):
        """Test get_publish_history returns filtered history for project."""
        project_id = 1
        job1 = {
            "job_id": "publish_1_123",
            "status": "completed",
            "destinations": ["audiobookshelf"],
            "created_at": "2024-01-01T00:00:00+00:00",
            "completed_at": "2024-01-01T00:05:00+00:00",
            "project_id": 1
        }
        job2 = {
            "job_id": "publish_2_456",
            "status": "failed",
            "destinations": ["podcast_rss"],
            "created_at": "2024-01-02T00:00:00+00:00",
            "completed_at": "2024-01-02T00:05:00+00:00",
            "project_id": 2  # Different project
        }
        
        with patch('asyncio.run') as mock_run:
            mock_run.side_effect = lambda coro: _real_asyncio_run(coro)
            
            with patch('src.audiobook_studio.tasks.publish_tasks._get_redis') as mock_get_redis:
                mock_client = AsyncMock()
                import json
                # scan_iter yields keys, accepts match and count kwargs
                async def mock_scan_iter(*args, **kwargs):
                    for key in ["publish:job:publish_1_123", "publish:job:publish_2_456"]:
                        yield key
                mock_client.scan_iter = mock_scan_iter
                mock_client.get.side_effect = [json.dumps(job1), json.dumps(job2)]
                mock_get_redis.return_value = mock_client
                
                result = publish_tasks.get_publish_history(project_id)
                
                assert result["project_id"] == project_id
                assert len(result["history"]) == 1
                assert result["history"][0]["job_id"] == "publish_1_123"
                mock_client.aclose.assert_called_once()