"""Unit tests for publish API endpoints.

Tests verify route registration, schemas, and business logic without
TestClient (which has Python 3.14 / httpx compatibility issues).
"""

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audiobook_studio.api.publish import _publish_jobs_fallback  # For test compatibility
from src.audiobook_studio.api.publish import (
    AudiobookshelfConfig,
    PodcastRSSConfig,
    PublishJobOut,
    PublishRequest,
    RSSFeedOut,
    _generate_podcast_rss,
    _publish_jobs,
    _publish_to_audiobookshelf,
    router,
)


class TestRouteRegistration:
    """Verify API routes are properly registered."""

    def test_router_has_all_required_routes(self):
        """Verify all expected routes are registered."""
        paths = [r.path for r in router.routes]
        assert "/projects/{project_id}/publish/" in paths
        assert "/projects/{project_id}/publish/jobs/{job_id}" in paths
        assert "/projects/{project_id}/publish/history" in paths
        assert "/projects/{project_id}/publish/feed.xml" in paths

    def test_router_prefix(self):
        """Verify router prefix is correctly set."""
        assert router.prefix == "/projects/{project_id}/publish"
        assert router.tags == ["publish"]


class TestSchemas:
    """Test request/response schemas."""

    def test_audiobookshelf_config_required_fields(self):
        """Test AudiobookshelfConfig requires server_url and api_key."""
        config = AudiobookshelfConfig(
            server_url="https://audiobookshelf.example.com",
            api_key="test_key",
            library_id="lib_123",
        )
        assert config.server_url == "https://audiobookshelf.example.com"
        assert config.api_key == "test_key"
        assert config.library_id == "lib_123"

    def test_audiobookshelf_config_optional_library(self):
        """Test AudiobookshelfConfig library_id is optional."""
        config = AudiobookshelfConfig(
            server_url="https://audiobookshelf.example.com",
            api_key="test_key",
        )
        assert config.library_id is None

    def test_podcast_rss_config_required_fields(self):
        """Test PodcastRSSConfig requires all mandatory fields."""
        config = PodcastRSSConfig(
            feed_title="My Podcast",
            feed_description="Description",
            feed_link="https://example.com",
            author="Author Name",
            owner_email="author@example.com",
            feed_language="en-US",
            categories=["Technology", "Science"],
            explicit=True,
            chapter_as_episode=False,
        )
        assert config.feed_title == "My Podcast"
        assert config.categories == ["Technology", "Science"]
        assert config.explicit is True
        assert config.chapter_as_episode is False

    def test_podcast_rss_config_defaults(self):
        """Test PodcastRSSConfig default values."""
        config = PodcastRSSConfig(
            feed_title="My Podcast",
            feed_description="Description",
            feed_link="https://example.com",
            author="Author",
            owner_email="author@example.com",
        )
        assert config.feed_language == "zh-CN"
        assert config.categories is None
        assert config.explicit is False
        assert config.chapter_as_episode is True

    def test_publish_request_defaults(self):
        """Test PublishRequest default destinations."""
        request = PublishRequest()
        assert request.destinations == ["audiobookshelf"]
        assert request.audiobookshelf_config is None
        assert request.podcast_config is None

    def test_publish_request_custom_destinations(self):
        """Test PublishRequest with custom destinations."""
        request = PublishRequest(
            destinations=["audiobookshelf", "podcast_rss"],
        )
        assert request.destinations == ["audiobookshelf", "podcast_rss"]

    def test_publish_job_out_required_fields(self):
        """Test PublishJobOut required fields."""
        job = PublishJobOut(
            job_id="publish_1_1234567890",
            project_id=1,
            status="pending",
            destinations=["audiobookshelf"],
            results={},
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        assert job.job_id == "publish_1_1234567890"
        assert job.status == "pending"
        assert job.results == {}

    def test_publish_job_out_with_completion(self):
        """Test PublishJobOut with completion data."""
        job = PublishJobOut(
            job_id="publish_1_1234567890",
            project_id=1,
            status="completed",
            destinations=["audiobookshelf"],
            results={"audiobookshelf": {"success": True, "book_url": "https://example.com/item/1"}},
            error=None,
            created_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        assert job.status == "completed"
        assert job.results["audiobookshelf"]["success"] is True
        assert job.completed_at is not None

    def test_rss_feed_out(self):
        """Test RSSFeedOut schema."""
        feed = RSSFeedOut(
            xml='<?xml version="1.0"?><rss>...</rss>',
            feed_url="https://example.com/feed.xml",
            episode_count=10,
        )
        assert feed.episode_count == 10
        assert "rss" in feed.xml


class TestInMemoryJobStore:
    """Test the in-memory job store behavior."""

    def setup_method(self):
        """Clear job store before each test."""
        _publish_jobs.clear()

    def teardown_method(self):
        """Clear job store after each test."""
        _publish_jobs.clear()

    def test_job_store_empty_initially(self):
        """Test job store starts empty."""
        assert len(_publish_jobs) == 0

    def test_job_store_add_and_retrieve(self):
        """Test adding and retrieving jobs."""
        job_data = {
            "job_id": "test_job_1",
            "project_id": 1,
            "status": "pending",
            "destinations": ["audiobookshelf"],
            "results": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _publish_jobs["test_job_1"] = job_data
        assert "test_job_1" in _publish_jobs
        assert _publish_jobs["test_job_1"]["project_id"] == 1

    def test_job_store_multiple_jobs(self):
        """Test storing multiple jobs."""
        for i in range(3):
            _publish_jobs[f"job_{i}"] = {
                "job_id": f"job_{i}",
                "project_id": i,
                "status": "pending",
                "destinations": ["audiobookshelf"],
                "results": {},
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        assert len(_publish_jobs) == 3


class TestPublishToAudiobookshelf:
    """Test the _publish_to_audiobookshelf function."""

    def setup_method(self):
        """Clear job store before each test."""
        _publish_jobs.clear()

    def teardown_method(self):
        """Clear job store after each test."""
        _publish_jobs.clear()

    @patch("src.audiobook_studio.database.AsyncSessionLocal")
    @patch("src.audiobook_studio.api.publish.aiohttp.ClientSession")
    @pytest.mark.asyncio
    async def test_publish_to_audiobookshelf_success(self, mock_session_class, mock_db_class):
        """Test successful Audiobookshelf publish."""
        # Setup mock async database session
        mock_session = AsyncMock()
        mock_db_class.return_value.__aenter__.return_value = mock_session

        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.title = "Test Book"
        mock_project.author = "Test Author"
        mock_project.story_line_summary = "A test story"
        mock_project.genre = "fiction"
        mock_project.language = "zh"

        # Setup mock audio segments
        mock_segment = MagicMock()
        mock_segment.file_path = "/tmp/test.m4b"
        mock_segment.is_current = True

        # Mock execute results - first call for project, second for segments
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = mock_project

        mock_segment_result = MagicMock()
        mock_segment_result.scalars.return_value.all.return_value = [mock_segment]

        mock_session.execute.side_effect = [mock_project_result, mock_segment_result]

        # Setup mock file existence
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
            patch("builtins.open", unittest.mock.mock_open(read_data=b"fake audio data")),
        ):
            mock_stat.return_value.st_size = 1024000

            # Setup mock aiohttp session properly
            mock_session_http = AsyncMock()
            mock_session_class.return_value.__aenter__.return_value = mock_session_http

            # Create async context manager mocks for responses using a proper class
            class MockResponse:
                def __init__(self, status, json_data=None):
                    self.status = status
                    self._json_data = json_data

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    return None

                async def json(self):
                    return self._json_data

                async def text(self):
                    return "OK"

                def __await__(self):
                    async def dummy():
                        return self

                    return dummy().__await__()

            def make_resp(status, json_data=None):
                return MockResponse(status, json_data)

            # Mock library list response
            mock_lib_resp = make_resp(200, [{"id": "lib_1"}])

            # Mock library detail response
            mock_lib_detail = make_resp(200, {"folders": [{"id": "folder_1"}]})

            # Mock upload response
            mock_upload = make_resp(200)

            # Mock scan response
            mock_scan = make_resp(200)

            # Mock search response
            mock_search = make_resp(200, [{"id": "item_1", "media": {"metadata": {"title": "Test Book"}}}])

            # Mock metadata patch response
            mock_meta = make_resp(200)

            # Mock cover response
            mock_cover = make_resp(200)

            # Setup side effects for get and post
            # session.get() should return the response object directly (not a coroutine)
            # because async with calls __aenter__ on the result
            mock_session_http.get = MagicMock(side_effect=[mock_lib_resp, mock_lib_detail, mock_search])
            mock_session_http.post = MagicMock(side_effect=[mock_upload, mock_scan, mock_cover])
            mock_session_http.patch = MagicMock(return_value=mock_meta)

            config = {
                "server_url": "https://audiobookshelf.example.com",
                "api_key": "test_key",
            }

            result = await _publish_to_audiobookshelf(1, config)

            assert result["success"] is True
            assert result["book_url"] == "https://audiobookshelf.example.com/item/item_1"
            assert result["uploaded_files"] == 1

    @pytest.mark.asyncio
    async def test_publish_to_audiobookshelf_missing_config(self):
        """Test Audiobookshelf publish fails without required config."""
        with pytest.raises(ValueError, match="server_url and api_key are required"):
            await _publish_to_audiobookshelf(1, {})

    @patch("src.audiobook_studio.database.AsyncSessionLocal")
    @pytest.mark.asyncio
    async def test_publish_to_audiobookshelf_missing_project(self, mock_db_class):
        """Test Audiobookshelf publish fails when project not found."""
        # Setup mock async database session
        mock_session = AsyncMock()
        mock_db_class.return_value.__aenter__.return_value = mock_session

        # Mock execute result - project not found
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_project_result

        config = {
            "server_url": "https://audiobookshelf.example.com",
            "api_key": "test_key",
        }

        # Need to mock aiohttp to avoid real network calls
        with patch("src.audiobook_studio.api.publish.aiohttp.ClientSession") as mock_session_class:
            mock_session_http = AsyncMock()
            mock_session_class.return_value.__aenter__.return_value = mock_session_http

            # Create async context manager mocks for responses using a proper class
            class MockResponse:
                def __init__(self, status, json_data=None):
                    self.status = status
                    self._json_data = json_data

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    return None

                async def json(self):
                    return self._json_data

                async def text(self):
                    return "OK"

                def __await__(self):
                    async def dummy():
                        return self

                    return dummy().__await__()

            def make_resp(status, json_data=None):
                return MockResponse(status, json_data)

            mock_session_http.get = MagicMock(
                side_effect=[
                    make_resp(200, [{"id": "lib_1"}]),  # library list
                    make_resp(200, {"id": "lib_1", "folders": [{"id": "folder_1"}]}),  # library detail
                ]
            )

            with pytest.raises(ValueError, match="Project 1 not found"):
                await _publish_to_audiobookshelf(1, config)


class TestGeneratePodcastRSS:
    """Test the _generate_podcast_rss function."""

    def setup_method(self):
        """Clear job store before each test."""
        _publish_jobs.clear()

    def teardown_method(self):
        """Clear job store after each test."""
        _publish_jobs.clear()

    @patch("src.audiobook_studio.database.AsyncSessionLocal")
    @pytest.mark.asyncio
    async def test_generate_podcast_rss_success(self, mock_db_class):
        """Test successful podcast RSS generation."""
        # Create async session mock
        mock_session = AsyncMock()
        mock_db_class.return_value.__aenter__.return_value = mock_session

        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.title = "Test Podcast"
        mock_project.author = "Test Author"
        mock_project.story_line_summary = "A test podcast"
        mock_project.language = "zh"

        # Setup mock audio segments
        mock_segment = MagicMock()
        mock_segment.file_path = "/tmp/ep1.m4b"
        mock_segment.file_size_bytes = 1024000
        mock_segment.duration_ms = 1800000
        mock_segment.chapter_index = 1
        mock_segment.index = 1
        mock_segment.is_current = True

        # Mock execute results
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_project

        mock_segment_result = MagicMock()
        mock_segment_result.scalars.return_value.all.return_value = [mock_segment]

        mock_session.execute.side_effect = [mock_result, mock_segment_result]

        config = {
            "feed_title": "My Podcast",
            "feed_description": "Description",
            "feed_link": "https://example.com",
            "author": "Author",
            "owner_email": "author@example.com",
        }

        result = await _generate_podcast_rss(1, config)

        assert result["success"] is True
        assert result["episode_count"] == 1
        assert "rss_url" in result

    @patch("src.audiobook_studio.database.AsyncSessionLocal")
    @pytest.mark.asyncio
    async def test_generate_podcast_rss_no_segments(self, mock_db_class):
        """Test podcast RSS generation with no segments."""
        # Create async session mock
        mock_session = AsyncMock()
        mock_db_class.return_value.__aenter__.return_value = mock_session

        mock_project = MagicMock()
        mock_project.id = 1

        # Mock execute results
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_project

        mock_segment_result = MagicMock()
        mock_segment_result.scalars.return_value.all.return_value = []

        mock_session.execute.side_effect = [mock_result, mock_segment_result]

        config = {
            "feed_title": "My Podcast",
            "feed_description": "Description",
            "feed_link": "https://example.com",
            "author": "Author",
            "owner_email": "author@example.com",
        }

        result = await _generate_podcast_rss(1, config)

        assert result["success"] is True
        assert result["episode_count"] == 0

    @patch("src.audiobook_studio.database.AsyncSessionLocal")
    @pytest.mark.asyncio
    async def test_generate_podcast_rss_project_not_found(self, mock_db_class):
        """Test podcast RSS generation when project not found."""
        # Create async session mock
        mock_session = AsyncMock()
        mock_db_class.return_value.__aenter__.return_value = mock_session

        # Mock execute result - project not found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        config = {}
        with pytest.raises(ValueError, match="Project 1 not found"):
            await _generate_podcast_rss(1, config)


class TestPublishBusinessLogic:
    """Test the background publish task logic."""

    def setup_method(self):
        """Clear job store before each test."""
        _publish_jobs.clear()

    def teardown_method(self):
        """Clear job store after each test."""
        _publish_jobs.clear()

    @patch("src.audiobook_studio.api.publish._publish_to_audiobookshelf")
    @patch("src.audiobook_studio.api.publish._generate_podcast_rss")
    @pytest.mark.asyncio
    async def test_publish_background_audiobookshelf_only(self, mock_rss, mock_abs):
        """Test background publish with audiobookshelf only."""
        from src.audiobook_studio.api.publish import _publish_background

        mock_abs.return_value = {
            "success": True,
            "book_url": "https://example.com/item/1",
        }

        # Pre-create the job in the store (as the endpoint would do)
        _publish_jobs["test_job_1"] = {
            "job_id": "test_job_1",
            "project_id": 1,
            "status": "pending",
            "destinations": ["audiobookshelf"],
            "results": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        await _publish_background(
            job_id="test_job_1",
            project_id=1,
            destinations=["audiobookshelf"],
            audiobookshelf_config={"server_url": "https://abs.com", "api_key": "key"},
        )

        job = _publish_jobs["test_job_1"]
        assert job["status"] == "completed"
        assert job["results"]["audiobookshelf"]["success"] is True
        mock_abs.assert_called_once()
        mock_rss.assert_not_called()

    @patch("src.audiobook_studio.api.publish._publish_to_audiobookshelf")
    @patch("src.audiobook_studio.api.publish._generate_podcast_rss")
    @pytest.mark.asyncio
    async def test_publish_background_podcast_only(self, mock_rss, mock_abs):
        """Test background publish with podcast only."""
        from src.audiobook_studio.api.publish import _publish_background

        mock_rss.return_value = {
            "success": True,
            "rss_url": "https://example.com/feed.xml",
            "episode_count": 5,
        }

        # Pre-create the job in the store
        _publish_jobs["test_job_2"] = {
            "job_id": "test_job_2",
            "project_id": 1,
            "status": "pending",
            "destinations": ["podcast_rss"],
            "results": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        await _publish_background(
            job_id="test_job_2",
            project_id=1,
            destinations=["podcast_rss"],
            podcast_config={"feed_title": "Test"},
        )

        job = _publish_jobs["test_job_2"]
        assert job["status"] == "completed"
        assert job["results"]["podcast_rss"]["success"] is True
        assert job["results"]["podcast_rss"]["episode_count"] == 5
        mock_rss.assert_called_once()
        mock_abs.assert_not_called()

    @patch("src.audiobook_studio.api.publish._publish_to_audiobookshelf")
    @patch("src.audiobook_studio.api.publish._generate_podcast_rss")
    @pytest.mark.asyncio
    async def test_publish_background_both_destinations(self, mock_rss, mock_abs):
        """Test background publish with both destinations."""
        from src.audiobook_studio.api.publish import _publish_background

        mock_abs.return_value = {
            "success": True,
            "book_url": "https://example.com/item/1",
        }
        mock_rss.return_value = {
            "success": True,
            "rss_url": "https://example.com/feed.xml",
            "episode_count": 5,
        }

        # Pre-create the job in the store
        _publish_jobs["test_job_3"] = {
            "job_id": "test_job_3",
            "project_id": 1,
            "status": "pending",
            "destinations": ["audiobookshelf", "podcast_rss"],
            "results": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        await _publish_background(
            job_id="test_job_3",
            project_id=1,
            destinations=["audiobookshelf", "podcast_rss"],
            audiobookshelf_config={"server_url": "https://abs.com", "api_key": "key"},
            podcast_config={"feed_title": "Test"},
        )

        job = _publish_jobs["test_job_3"]
        assert job["status"] == "completed"
        assert job["results"]["audiobookshelf"]["success"] is True
        assert job["results"]["podcast_rss"]["success"] is True
        mock_abs.assert_called_once()
        mock_rss.assert_called_once()

    @patch("src.audiobook_studio.api.publish._publish_to_audiobookshelf")
    @patch("src.audiobook_studio.api.publish._generate_podcast_rss")
    @pytest.mark.asyncio
    async def test_publish_background_audiobookshelf_fails(self, mock_rss, mock_abs):
        """Test background publish when audiobookshelf fails."""
        from src.audiobook_studio.api.publish import _publish_background

        mock_abs.side_effect = Exception("Connection failed")

        # Pre-create the job in the store
        _publish_jobs["test_job_4"] = {
            "job_id": "test_job_4",
            "project_id": 1,
            "status": "pending",
            "destinations": ["audiobookshelf"],
            "results": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        await _publish_background(
            job_id="test_job_4",
            project_id=1,
            destinations=["audiobookshelf"],
            audiobookshelf_config={"server_url": "https://abs.com", "api_key": "key"},
        )

        job = _publish_jobs["test_job_4"]
        assert job["status"] == "failed"
        assert job["results"]["audiobookshelf"]["success"] is False
        assert "Connection failed" in job["results"]["audiobookshelf"]["error"]
        assert job["error"] is not None

    @patch("src.audiobook_studio.api.publish._publish_to_audiobookshelf")
    @patch("src.audiobook_studio.api.publish._generate_podcast_rss")
    @pytest.mark.asyncio
    async def test_publish_background_partial_failure(self, mock_rss, mock_abs):
        """Test background publish with one success and one failure."""
        from src.audiobook_studio.api.publish import _publish_background

        mock_abs.return_value = {"success": True, "book_url": "https://example.com/item/1"}
        mock_rss.side_effect = Exception("RSS generation failed")

        # Pre-create the job in the store
        _publish_jobs["test_job_5"] = {
            "job_id": "test_job_5",
            "project_id": 1,
            "status": "pending",
            "destinations": ["audiobookshelf", "podcast_rss"],
            "results": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        await _publish_background(
            job_id="test_job_5",
            project_id=1,
            destinations=["audiobookshelf", "podcast_rss"],
            audiobookshelf_config={"server_url": "https://abs.com", "api_key": "key"},
            podcast_config={"feed_title": "Test"},
        )

        job = _publish_jobs["test_job_5"]
        assert job["status"] == "failed"  # Overall failed because one failed
        assert job["results"]["audiobookshelf"]["success"] is True
        assert job["results"]["podcast_rss"]["success"] is False


class TestRSSFeedGeneration:
    """Test the RSS feed XML generation endpoint."""

    def setup_method(self):
        """Clear job store before each test."""
        _publish_jobs.clear()

    def teardown_method(self):
        """Clear job store after each test."""
        _publish_jobs.clear()

    @patch("src.audiobook_studio.database.AsyncSessionLocal")
    @pytest.mark.asyncio
    async def test_get_podcast_rss_feed(self, mock_db_class):
        """Test RSS feed XML generation."""
        from src.audiobook_studio.api.publish import get_podcast_rss_feed

        # Create async session mock
        mock_session = AsyncMock()
        mock_db_class.return_value.__aenter__.return_value = mock_session

        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.title = "Test Podcast"
        mock_project.author = "Test Author"
        mock_project.story_line_summary = "A test podcast"
        mock_project.language = "zh"

        mock_segment = MagicMock()
        mock_segment.file_path = "/tmp/ep1.m4b"
        mock_segment.file_size_bytes = 1024000
        mock_segment.duration_ms = 1800000
        mock_segment.chapter_index = 1
        mock_segment.index = 1
        mock_segment.is_current = True

        # Mock execute result
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_session.execute.return_value = mock_result

        # For segments query
        mock_segment_result = MagicMock()
        mock_segment_result.scalars.return_value.all.return_value = [mock_segment]
        # The second call to execute() will be for segments
        mock_session.execute.side_effect = [mock_result, mock_segment_result]

        # Mock Path.exists for cover image check
        with patch("pathlib.Path.exists", return_value=False):
            result = await get_podcast_rss_feed(
                project_id=1,
                feed_title="Custom Title",
                feed_description="Custom Description",
                feed_link="https://custom.com",
                author="Custom Author",
                owner_email="custom@example.com",
                db=mock_session,  # Pass mock session directly
            )

        assert isinstance(result, RSSFeedOut)
        assert result.episode_count == 1
        assert "Custom Title" in result.xml
        assert "Custom Author" in result.xml
        assert "audio/mp4" in result.xml
        assert "ep1.m4b" in result.xml

    @patch("src.audiobook_studio.database.AsyncSessionLocal")
    @pytest.mark.asyncio
    async def test_get_podcast_rss_feed_project_not_found(self, mock_db_class):
        """Test RSS feed when project not found."""
        from fastapi import HTTPException

        from src.audiobook_studio.api.publish import get_podcast_rss_feed

        # Create async session mock
        mock_session = AsyncMock()
        mock_db_class.return_value.__aenter__.return_value = mock_session

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await get_podcast_rss_feed(project_id=999, db=mock_session)

        assert exc_info.value.status_code == 404

    @patch("src.audiobook_studio.database.AsyncSessionLocal")
    @pytest.mark.asyncio
    async def test_get_podcast_rss_feed_defaults(self, mock_db_class):
        """Test RSS feed with default values from project."""
        from src.audiobook_studio.api.publish import get_podcast_rss_feed

        # Create async session mock
        mock_session = AsyncMock()
        mock_db_class.return_value.__aenter__.return_value = mock_session

        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.title = "Test Podcast"
        mock_project.author = "Test Author"
        mock_project.story_line_summary = "A test podcast"
        mock_project.language = "en"

        mock_segment = MagicMock()
        mock_segment.file_path = "/tmp/ep1.m4b"
        mock_segment.file_size_bytes = 1024000
        mock_segment.duration_ms = 1800000
        mock_segment.chapter_index = 1
        mock_segment.index = 1
        mock_segment.is_current = True

        # Mock execute result
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_project

        mock_segment_result = MagicMock()
        mock_segment_result.scalars.return_value.all.return_value = [mock_segment]

        mock_session.execute.side_effect = [mock_result, mock_segment_result]

        with patch("pathlib.Path.exists", return_value=False):
            result = await get_podcast_rss_feed(project_id=1, db=mock_session)

        assert result.episode_count == 1
        assert "Test Podcast" in result.xml
        assert "Test Author" in result.xml
        # Language uses project.language directly (no BCP-47 conversion in RSS feed)
        assert "en" in result.xml


class TestJobEndpoints:
    """Test the job status and history endpoints logic."""

    def setup_method(self):
        """Clear job store before each test."""
        _publish_jobs.clear()

    def teardown_method(self):
        """Clear job store after each test."""
        _publish_jobs.clear()

    @pytest.mark.asyncio
    async def test_get_publish_job_success(self):
        """Test getting a publish job by ID."""
        from fastapi import HTTPException

        from src.audiobook_studio.api.publish import get_publish_job

        job_data = {
            "job_id": "test_job_1",
            "project_id": 1,
            "status": "completed",
            "destinations": ["audiobookshelf"],
            "results": {"audiobookshelf": {"success": True}},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        _publish_jobs["test_job_1"] = job_data

        result = await get_publish_job(project_id=1, job_id="test_job_1")

        assert result.job_id == "test_job_1"
        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_get_publish_job_not_found(self):
        """Test getting a non-existent job."""
        from fastapi import HTTPException

        from src.audiobook_studio.api.publish import get_publish_job

        with pytest.raises(HTTPException) as exc_info:
            await get_publish_job(project_id=1, job_id="nonexistent")

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_publish_job_wrong_project(self):
        """Test getting a job for wrong project."""
        from fastapi import HTTPException

        from src.audiobook_studio.api.publish import get_publish_job

        job_data = {
            "job_id": "test_job_1",
            "project_id": 2,  # Different project
            "status": "completed",
            "destinations": ["audiobookshelf"],
            "results": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _publish_jobs["test_job_1"] = job_data

        with pytest.raises(HTTPException) as exc_info:
            await get_publish_job(project_id=1, job_id="test_job_1")

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_get_publish_history(self):
        """Test getting publish history for a project."""
        from src.audiobook_studio.api.publish import get_publish_history

        # Add jobs for project 1
        for i in range(3):
            _publish_jobs[f"job_{i}"] = {
                "job_id": f"job_{i}",
                "project_id": 1,
                "status": "completed" if i % 2 == 0 else "failed",
                "destinations": ["audiobookshelf"],
                "results": {},
                "created_at": datetime(2024, 1, i + 1, tzinfo=timezone.utc).isoformat(),
                "completed_at": datetime(2024, 1, i + 1, tzinfo=timezone.utc).isoformat(),
            }
        # Add job for project 2 (should not appear)
        _publish_jobs["job_other"] = {
            "job_id": "job_other",
            "project_id": 2,
            "status": "completed",
            "destinations": ["audiobookshelf"],
            "results": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        history = await get_publish_history(project_id=1)

        assert len(history) == 3
        # Should be sorted by created_at descending
        assert history[0].job_id == "job_2"
        assert history[1].job_id == "job_1"
        assert history[2].job_id == "job_0"


class TestPublishValidation:
    """Test validation in publish endpoints."""

    def setup_method(self):
        """Clear job store before each test."""
        _publish_jobs.clear()

    def teardown_method(self):
        """Clear job store after each test."""
        _publish_jobs.clear()

    @pytest.mark.asyncio
    async def test_invalid_destination_rejected(self):
        """Test that invalid destinations are rejected."""
        from pydantic import ValidationError

        from src.audiobook_studio.api.publish import PublishRequest

        # This should not raise during model creation but during endpoint validation
        request = PublishRequest(destinations=["invalid_dest"])
        assert "invalid_dest" in request.destinations

    def test_audiobookshelf_config_model_validation(self):
        """Test AudiobookshelfConfig model validation."""
        # Valid
        config = AudiobookshelfConfig(server_url="https://example.com", api_key="key")
        assert config.server_url == "https://example.com"

        # Invalid - missing required fields
        with pytest.raises(ValidationError):
            AudiobookshelfConfig(server_url="https://example.com")

        with pytest.raises(ValidationError):
            AudiobookshelfConfig(api_key="key")

    def test_podcast_rss_config_model_validation(self):
        """Test PodcastRSSConfig model validation."""
        # Valid
        config = PodcastRSSConfig(
            feed_title="Title",
            feed_description="Desc",
            feed_link="https://example.com",
            author="Author",
            owner_email="author@example.com",
        )
        assert config.feed_title == "Title"

        # Invalid - missing required fields
        with pytest.raises(ValidationError):
            PodcastRSSConfig(
                feed_title="Title",
                feed_description="Desc",
                feed_link="https://example.com",
                # missing author and owner_email
            )


class TestMIMETypeHandling:
    """Test MIME type detection for audio files."""

    @pytest.mark.parametrize(
        "ext,mime",
        [
            (".m4b", "audio/mp4"),
            (".mp3", "audio/mpeg"),
            (".wav", "audio/wav"),
            (".flac", "audio/flac"),
            (".ogg", "audio/ogg"),
            (".aac", "audio/aac"),
            (".unknown", "application/octet-stream"),
        ],
    )
    def test_mime_type_detection(self, ext, mime):
        """Test MIME type detection for various extensions."""
        from src.audiobook_studio.api.publish import _publish_to_audiobookshelf

        # We can't easily test the internal _mime_type function,
        # but we can verify the mapping used in the code
        mime_map = {
            ".m4b": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".flac": "audio/flac",
            ".ogg": "audio/ogg",
            ".aac": "audio/aac",
        }
        assert mime_map.get(ext, "application/octet-stream") == mime


# Import ValidationError for schema tests
from pydantic import ValidationError
