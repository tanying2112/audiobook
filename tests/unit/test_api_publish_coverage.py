"""Additional coverage tests for publish.py - targeting uncovered code paths."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock, PropertyMock

import pytest
import aiohttp


class MockAsyncContextManager:
    """Helper to create proper async context manager mocks."""
    def __init__(self, return_value=None):
        self.return_value = return_value
        self.called = False
    
    async def __aenter__(self):
        self.called = True
        return self.return_value
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


def create_mock_response(status=200, json_data=None, text_data=""):
    """Create a mock aiohttp response with async context manager support."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    if json_data is not None:
        mock_resp.json = AsyncMock(return_value=json_data)
    else:
        mock_resp.json = AsyncMock(return_value={})
    mock_resp.text = AsyncMock(return_value=text_data)
    return MockAsyncContextManager(mock_resp)


class TestPublishToAudiobookshelf:
    """Tests for _publish_to_audiobookshelf function - covers lines 293-576."""

    def _setup_mocks(self):
        """Setup common mocks for _publish_to_audiobookshelf tests."""
        mock_db = MagicMock()
        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.title = "Test Book"
        mock_project.author = "Test Author"
        mock_project.story_line_summary = "A test book"
        mock_project.genre = "fiction"
        mock_project.language = "zh"
        
        mock_segment = MagicMock()
        mock_segment.file_path = "/tmp/test_chapter.m4b"
        mock_segment.duration_ms = 60000
        mock_segment.file_size_bytes = 1024000
        mock_segment.is_current = True
        mock_segment.index = 1
        
        # Setup query chain properly
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_order_by = MagicMock()
        
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.first.return_value = mock_project
        mock_filter.order_by.return_value = mock_order_by
        mock_order_by.all.return_value = [mock_segment]
        
        return mock_db, mock_project, mock_segment

    def _create_mock_session(self):
        """Create a properly mocked aiohttp ClientSession with async context manager."""
        mock_session = AsyncMock()
        
        # Create mock responses as async context managers
        mock_lib_list_resp = create_mock_response(
            status=200, 
            json_data=[{"id": "lib1", "name": "Test Library"}]
        )
        
        # Mock responses for library details
        mock_lib_detail_resp = create_mock_response(
            status=200,
            json_data={"folders": [{"id": "folder1", "name": "Test Folder"}]}
        )
        
        # Mock search response
        mock_search_resp = create_mock_response(
            status=200,
            json_data=[{"id": "item1", "media": {"metadata": {"title": "Test Book"}}}]
        )
        
        # Mock metadata patch response
        mock_meta_resp = create_mock_response(status=200)
        
        # Mock cover upload response
        mock_cover_resp = create_mock_response(status=200)
        
        # Mock scan response
        mock_scan_resp = create_mock_response(status=200)
        
        # Mock upload response
        mock_upload_resp = create_mock_response(status=200)
        
        def mock_get(url, *args, **kwargs):
            if "libraries" in url and "search" not in url and url.endswith("/libraries"):  # /api/libraries
                return mock_lib_list_resp
            elif "libraries" in url and "search" not in url:  # /api/libraries/{id}
                return mock_lib_detail_resp
            elif "search" in url:
                return mock_search_resp
            return create_mock_response(status=404)
        
        def mock_post(url, *args, **kwargs):
            if "upload" in url:
                return mock_upload_resp
            elif "scan" in url:
                return mock_scan_resp
            elif "cover" in url:
                return mock_cover_resp
            elif "items" in url and "media" in url:
                return mock_meta_resp
            return create_mock_response(status=404)
        
        mock_session.get = mock_get
        mock_session.post = mock_post
        
        # Make the session itself an async context manager
        session_cm = MockAsyncContextManager(mock_session)
        
        return mock_session, session_cm

    @pytest.mark.asyncio
    async def test_publish_to_audiobookshelf_local_copy(self):
        """Test local file copy mode (base_path provided)."""
        from src.audiobook_studio.api.publish import _publish_to_audiobookshelf
        
        mock_db, mock_project, mock_segment = self._setup_mocks()
        mock_session, session_cm = self._create_mock_session()
        
        # Need to patch SessionLocal in the publish module where it's used internally
        with patch("src.audiobook_studio.database.SessionLocal", return_value=mock_db):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.is_file", return_value=True):
                    with patch("pathlib.Path.stat") as mock_stat:
                        mock_stat.return_value.st_size = 1024000
                        with patch("shutil.copy2") as mock_copy:
                            with patch("src.audiobook_studio.storage.project_dir") as mock_project_dir:
                                mock_project_dir.return_value = Path("/tmp/projects/1")
                                with patch("pathlib.Path.exists", return_value=False):  # No cover
                                    with patch("aiohttp.ClientSession", return_value=session_cm):
                                        config = {
                                            "server_url": "http://localhost:13378",
                                            "api_key": "test_key",
                                            "base_path": "/media/books",
                                        }
                                        result = await _publish_to_audiobookshelf(project_id=1, config=config)
                                        
        assert result["success"] is True
        assert result["uploaded_files"] == 1
        assert result["total_files"] == 1
        mock_copy.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_to_audiobookshelf_remote_upload(self):
        """Test remote upload mode (no base_path)."""
        from src.audiobook_studio.api.publish import _publish_to_audiobookshelf
        
        mock_db, mock_project, mock_segment = self._setup_mocks()
        mock_session, session_cm = self._create_mock_session()
        
        # Need to patch SessionLocal in the publish module where it's used internally
        with patch("src.audiobook_studio.database.SessionLocal", return_value=mock_db):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.is_file", return_value=True):
                    with patch("pathlib.Path.stat") as mock_stat:
                        mock_stat.return_value.st_size = 1024000
                        with patch("builtins.open", return_value=MagicMock()):
                            with patch("aiohttp.ClientSession", return_value=session_cm):
                                with patch("src.audiobook_studio.storage.project_dir") as mock_project_dir:
                                    mock_project_dir.return_value = Path("/tmp/projects/1")
                                    with patch("pathlib.Path.exists", return_value=False):  # No cover
                                        config = {
                                            "server_url": "http://localhost:13378",
                                            "api_key": "test_key",
                                            "library_id": "lib1",
                                        }
                                        result = await _publish_to_audiobookshelf(project_id=1, config=config)
                                        
        assert result["success"] is True
        assert result["uploaded_files"] == 1

    @pytest.mark.asyncio
    async def test_publish_to_audiobookshelf_library_not_found(self):
        """Test library not found error."""
        from src.audiobook_studio.api.publish import _publish_to_audiobookshelf
        
        mock_db, mock_project, mock_segment = self._setup_mocks()
        
        # Create mock session that returns 404 for library detail
        mock_session = AsyncMock()
        mock_lib_list_resp = create_mock_response(status=200, json_data=[{"id": "lib1"}])
        mock_lib_detail_resp = create_mock_response(status=404)
        
        def mock_get(url, *args, **kwargs):
            if "libraries" in url and "search" not in url and len(url.split("/")) == 5:
                return mock_lib_list_resp
            elif "libraries" in url:
                return mock_lib_detail_resp
            return create_mock_response(status=404)
        
        mock_session.get = mock_get
        mock_session.post = AsyncMock(return_value=create_mock_response(status=200))
        session_cm = MockAsyncContextManager(mock_session)
        
        with patch("src.audiobook_studio.database.SessionLocal", return_value=mock_db):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.is_file", return_value=True):
                    with patch("pathlib.Path.stat") as mock_stat:
                        mock_stat.return_value.st_size = 1024000
                        with patch("aiohttp.ClientSession", return_value=session_cm):
                            config = {
                                "server_url": "http://localhost:13378",
                                "api_key": "test_key",
                                "library_id": "invalid_lib",
                            }
                            with pytest.raises(ValueError, match="Library invalid_lib not found"):
                                await _publish_to_audiobookshelf(project_id=1, config=config)

    @pytest.mark.asyncio
    async def test_publish_to_audiobookshelf_no_audio_files(self):
        """Test error when no audio files found."""
        from src.audiobook_studio.api.publish import _publish_to_audiobookshelf
        
        mock_db = MagicMock()
        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.title = "Test Book"
        mock_project.author = "Test Author"
        
        mock_db.query.return_value.filter.return_value.first.return_value = mock_project
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        
        mock_session, session_cm = self._create_mock_session()
        
        # Need to patch SessionLocal in the publish module where it's used internally
        with patch("src.audiobook_studio.database.SessionLocal", return_value=mock_db):
            with patch("aiohttp.ClientSession", return_value=session_cm):
                config = {
                    "server_url": "http://localhost:13378",
                    "api_key": "test_key",
                }
                with pytest.raises(ValueError, match="No audio files found"):
                    await _publish_to_audiobookshelf(project_id=1, config=config)

    @pytest.mark.asyncio
    async def test_publish_to_audiobookshelf_all_uploads_failed(self):
        """Test error when all uploads fail."""
        from src.audiobook_studio.api.publish import _publish_to_audiobookshelf
        
        mock_db, mock_project, mock_segment = self._setup_mocks()
        
        # Create mock session with failed upload
        mock_session = AsyncMock()
        mock_lib_list_resp = create_mock_response(status=200, json_data=[{"id": "lib1"}])
        mock_lib_detail_resp = create_mock_response(status=200, json_data={"folders": [{"id": "folder1"}]})
        mock_upload_resp = create_mock_response(status=500, text_data="Server error")
        
        def mock_get(url, *args, **kwargs):
            if "libraries" in url and "search" not in url and url.endswith("/libraries"):
                return mock_lib_list_resp
            elif "libraries" in url:
                return mock_lib_detail_resp
            return create_mock_response(status=404)
        
        def mock_post(url, *args, **kwargs):
            if "upload" in url:
                return mock_upload_resp
            return create_mock_response(status=200)
        
        mock_session.get = mock_get
        mock_session.post = mock_post
        session_cm = MockAsyncContextManager(mock_session)
        
        # Need to patch SessionLocal in the publish module where it's used internally
        with patch("src.audiobook_studio.database.SessionLocal", return_value=mock_db):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.is_file", return_value=True):
                    with patch("pathlib.Path.stat") as mock_stat:
                        mock_stat.return_value.st_size = 1024000
                        with patch("builtins.open", return_value=MagicMock()):
                            with patch("aiohttp.ClientSession", return_value=session_cm):
                                config = {
                                    "server_url": "http://localhost:13378",
                                    "api_key": "test_key",
                                    "library_id": "lib1",
                                }
                                with pytest.raises(ValueError, match="All file uploads failed"):
                                    await _publish_to_audiobookshelf(project_id=1, config=config)

    @pytest.mark.asyncio
    async def test_publish_to_audiobookshelf_with_cover_upload(self):
        """Test cover image upload."""
        from src.audiobook_studio.api.publish import _publish_to_audiobookshelf
        
        mock_db, mock_project, mock_segment = self._setup_mocks()
        mock_session, session_cm = self._create_mock_session()
        
        # Need to patch SessionLocal in the publish module where it's used internally
        with patch("src.audiobook_studio.database.SessionLocal", return_value=mock_db):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.is_file", return_value=True):
                    with patch("pathlib.Path.stat") as mock_stat:
                        mock_stat.return_value.st_size = 1024000
                        with patch("builtins.open", return_value=MagicMock()):
                            with patch("aiohttp.ClientSession", return_value=session_cm):
                                with patch("src.audiobook_studio.storage.project_dir") as mock_project_dir:
                                    mock_project_dir.return_value = Path("/tmp/projects/1")
                                    with patch("pathlib.Path.exists", side_effect=[True, False]):  # cover.jpg exists
                                        config = {
                                            "server_url": "http://localhost:13378",
                                            "api_key": "test_key",
                                            "library_id": "lib1",
                                        }
                                        result = await _publish_to_audiobookshelf(project_id=1, config=config)
                                        
        assert result["success"] is True
        assert result["book_id"] == "item1"


class TestGeneratePodcastRss:
    """Tests for _generate_podcast_rss function - covers lines 578-590."""

    @pytest.mark.asyncio
    async def test_generate_podcast_rss_success(self):
        """Test successful RSS generation."""
        from src.audiobook_studio.api.publish import _generate_podcast_rss
        from src.audiobook_studio.models.audio_segment import AudioSegment
        
        mock_db = MagicMock()
        mock_project = MagicMock()
        mock_project.id = 5
        mock_project.title = "Test Podcast"
        mock_project.author = "Author"
        mock_project.language = "zh"
        mock_project.story_line_summary = "Description"
        
        mock_segment1 = MagicMock()
        mock_segment1.file_path = "/media/5/ep1.m4b"
        mock_segment1.duration_ms = 60000
        mock_segment1.file_size_bytes = 1024000
        mock_segment1.index = 1
        mock_segment1.chapter_index = 1
        mock_segment1.is_current = True
        
        mock_segment2 = MagicMock()
        mock_segment2.file_path = "/media/5/ep2.m4b"
        mock_segment2.duration_ms = 120000
        mock_segment2.file_size_bytes = 2048000
        mock_segment2.index = 2
        mock_segment2.chapter_index = 2
        mock_segment2.is_current = True
        
        mock_db.query.return_value.filter.return_value.first.return_value = mock_project
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_segment1, mock_segment2]
        
        AudioSegment.index = MagicMock(name="index_col")
        
        try:
            with patch("src.audiobook_studio.database.SessionLocal", return_value=mock_db):
                with patch.dict("os.environ", {"APP_PUBLIC_URL": "http://localhost:8000"}):
                    result = await _generate_podcast_rss(project_id=5, config={})
        finally:
            try:
                del AudioSegment.index
            except AttributeError:
                pass
        
        assert result["success"] is True
        assert result["episode_count"] == 2
        assert "feed.xml" in result["rss_url"]

    @pytest.mark.asyncio
    async def test_generate_podcast_rss_project_not_found(self):
        """Test project not found error."""
        from src.audiobook_studio.api.publish import _generate_podcast_rss
        
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        with patch("src.audiobook_studio.database.SessionLocal", return_value=mock_db):
            with pytest.raises(ValueError, match="not found"):
                await _generate_podcast_rss(project_id=999, config={})


class TestGetPodcastRssFeed:
    """Tests for get_podcast_rss_feed endpoint - covers lines 668-682."""

    def _make_segment(self, file_path="chapter_1.m4b", duration_ms=60000, file_size_bytes=1024000, index=1, chapter_index=1):
        seg = MagicMock()
        seg.file_path = file_path
        seg.duration_ms = duration_ms
        seg.file_size_bytes = file_size_bytes
        seg.index = index
        seg.chapter_index = chapter_index
        seg.is_current = True
        return seg

    def _make_project(self):
        proj = MagicMock()
        proj.id = 5
        proj.title = "测试有声书"
        proj.author = "测试作者"
        proj.language = "zh"
        proj.story_line_summary = "简介"
        proj.genre = "fiction"
        return proj

    def _run_feed(self, project, segments, **kwargs):
        """Helper to run get_podcast_rss_feed with proper mocking."""
        from src.audiobook_studio.api.publish import get_podcast_rss_feed
        from src.audiobook_studio.models.audio_segment import AudioSegment

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = project
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = segments

        import asyncio
        with patch("src.audiobook_studio.database.SessionLocal", return_value=mock_db):
            with patch.dict("os.environ", {"APP_PUBLIC_URL": "http://localhost:8000"}):
                AudioSegment.index = MagicMock(name="index_col")
                try:
                    return asyncio.run(get_podcast_rss_feed(project_id=5, **kwargs))
                finally:
                    try:
                        del AudioSegment.index
                    except AttributeError:
                        pass

    def test_feed_with_all_config_params(self):
        """Test feed with all optional query params provided."""
        project = self._make_project()
        segments = [self._make_segment("ch1.m4b")]
        
        result = self._run_feed(
            project, segments,
            feed_title="Custom Title",
            feed_description="Custom Desc",
            feed_link="http://custom.link",
            feed_language="en-US",
            author="Custom Author",
            owner_email="custom@example.com",
            categories="Technology,Science",
            explicit=True,
        )
        
        assert "Custom Title" in result.xml
        assert "Custom Desc" in result.xml
        assert "http://custom.link" in result.xml
        assert "en-US" in result.xml
        assert "Custom Author" in result.xml
        assert "custom@example.com" in result.xml
        assert "Technology" in result.xml
        assert "Science" in result.xml
        assert "True" in result.xml  # explicit

    def test_feed_with_flac_audio(self):
        """Test FLAC audio enclosure type."""
        project = self._make_project()
        segments = [self._make_segment("audio.flac")]
        result = self._run_feed(project, segments)
        assert 'type="audio/flac"' in result.xml

    def test_feed_with_ogg_audio(self):
        """Test OGG audio enclosure type."""
        project = self._make_project()
        segments = [self._make_segment("audio.ogg")]
        result = self._run_feed(project, segments)
        assert 'type="audio/ogg"' in result.xml

    def test_feed_with_aac_audio(self):
        """Test AAC audio enclosure type."""
        project = self._make_project()
        segments = [self._make_segment("audio.aac")]
        result = self._run_feed(project, segments)
        assert 'type="audio/aac"' in result.xml

    def test_feed_with_wav_audio(self):
        """Test WAV audio enclosure type."""
        project = self._make_project()
        segments = [self._make_segment("audio.wav")]
        result = self._run_feed(project, segments)
        assert 'type="audio/wav"' in result.xml

    def test_feed_with_multiple_episodes(self):
        """Test feed with multiple episodes."""
        project = self._make_project()
        segments = [
            self._make_segment("ep1.m4b", index=1, chapter_index=1),
            self._make_segment("ep2.m4b", index=2, chapter_index=1),
            self._make_segment("ep3.m4b", index=3, chapter_index=2),
        ]
        result = self._run_feed(project, segments)
        assert result.episode_count == 3
        assert result.xml.count("<item>") == 3
        assert "Episode 1" in result.xml
        assert "Episode 2" in result.xml
        assert "Episode 3" in result.xml

    def test_feed_rss_structure(self):
        """Test RSS XML structure is valid."""
        project = self._make_project()
        segments = [self._make_segment("ch1.m4b")]
        result = self._run_feed(project, segments)
        
        # Check required RSS elements
        assert '<?xml version="1.0" encoding="UTF-8"?>' in result.xml
        assert '<rss version="2.0"' in result.xml
        assert 'xmlns:itunes=' in result.xml
        assert "<channel>" in result.xml
        assert "</channel>" in result.xml
        assert "</rss>" in result.xml
        
        # Check iTunes elements
        assert "<itunes:author>" in result.xml
        assert "<itunes:owner>" in result.xml
        assert "<itunes:email>" in result.xml
        assert "<itunes:explicit>" in result.xml
        assert "<itunes:duration>" in result.xml
        
        # Check item elements
        assert "<item>" in result.xml
        assert "<title>" in result.xml
        assert "<description>" in result.xml
        assert "<enclosure" in result.xml
        assert "<guid>" in result.xml
        assert "<pubDate>" in result.xml


class TestPublishBackgroundExtended:
    """Extended tests for _publish_background - covers lines 174-187."""

    @pytest.mark.asyncio
    async def test_publish_background_both_success(self):
        """Test both destinations succeed."""
        from src.audiobook_studio.api.publish import _publish_background, _publish_jobs
        
        _publish_jobs.clear()
        _publish_jobs["j_both"] = {
            "job_id": "j_both", "project_id": 1, "status": "pending",
            "destinations": ["audiobookshelf", "podcast_rss"], "results": {},
        }
        
        with patch("src.audiobook_studio.api.publish._publish_to_audiobookshelf",
                    new_callable=AsyncMock, return_value={"book_url": "http://abs/1"}):
            with patch("src.audiobook_studio.api.publish._generate_podcast_rss",
                      new_callable=AsyncMock, return_value={"rss_url": "http://x/feed.xml", "episode_count": 3}):
                await _publish_background(
                    job_id="j_both", project_id=1,
                    destinations=["audiobookshelf", "podcast_rss"],
                )
        
        job = _publish_jobs["j_both"]
        assert job["status"] == "completed"
        assert job["results"]["audiobookshelf"]["success"] is True
        assert job["results"]["podcast_rss"]["success"] is True
        assert job.get("error") is None
        _publish_jobs.clear()

    @pytest.mark.asyncio
    async def test_publish_background_both_failed(self):
        """Test both destinations fail."""
        from src.audiobook_studio.api.publish import _publish_background, _publish_jobs
        
        _publish_jobs.clear()
        _publish_jobs["j_fail"] = {
            "job_id": "j_fail", "project_id": 2, "status": "pending",
            "destinations": ["audiobookshelf", "podcast_rss"], "results": {},
        }
        
        with patch("src.audiobook_studio.api.publish._publish_to_audiobookshelf",
                    new_callable=AsyncMock, side_effect=ValueError("ABS error")):
            with patch("src.audiobook_studio.api.publish._generate_podcast_rss",
                      new_callable=AsyncMock, side_effect=RuntimeError("RSS error")):
                await _publish_background(
                    job_id="j_fail", project_id=2,
                    destinations=["audiobookshelf", "podcast_rss"],
                )
        
        job = _publish_jobs["j_fail"]
        assert job["status"] == "failed"
        assert job["results"]["audiobookshelf"]["success"] is False
        assert job["results"]["podcast_rss"]["success"] is False
        assert "ABS error" in job["error"]
        assert "RSS error" in job["error"]
        _publish_jobs.clear()


class TestPublishEndpointExtended:
    """Extended tests for publish_project endpoint."""

    @pytest.mark.asyncio
    async def test_publish_with_podcast_config(self):
        """Test publish with podcast config."""
        from src.audiobook_studio.api.publish import publish_project, PublishRequest, PodcastRSSConfig, _publish_jobs
        
        db = MagicMock()
        mock_project = MagicMock()
        mock_project.id = 10
        mock_project.status = "completed"
        db.query.return_value.filter.return_value.first.return_value = mock_project
        
        podcast_config = PodcastRSSConfig(
            feed_title="My Podcast",
            feed_description="Description",
            feed_link="http://link",
            author="Author",
            owner_email="author@example.com",
        )
        req = PublishRequest(
            destinations=["podcast_rss"],
            podcast_config=podcast_config,
        )
        bg = MagicMock()
        
        result = await publish_project(
            project_id=10, request=req, background_tasks=bg, db=db,
        )
        
        assert result.project_id == 10
        assert "podcast_rss" in result.destinations
        bg.add_task.assert_called_once()
        _publish_jobs.clear()

    @pytest.mark.asyncio
    async def test_publish_destinations_both(self):
        """Test publish with both destinations."""
        from src.audiobook_studio.api.publish import publish_project, PublishRequest, AudiobookshelfConfig, PodcastRSSConfig, _publish_jobs
        
        db = MagicMock()
        mock_project = MagicMock()
        mock_project.id = 10
        mock_project.status = "completed"
        db.query.return_value.filter.return_value.first.return_value = mock_project
        
        ab_config = AudiobookshelfConfig(server_url="http://abs", api_key="key")
        podcast_config = PodcastRSSConfig(
            feed_title="Pod", feed_description="Desc", feed_link="http://link",
            author="Author", owner_email="author@example.com",
        )
        req = PublishRequest(
            destinations=["audiobookshelf", "podcast_rss"],
            audiobookshelf_config=ab_config,
            podcast_config=podcast_config,
        )
        bg = MagicMock()
        
        result = await publish_project(
            project_id=10, request=req, background_tasks=bg, db=db,
        )
        
        assert result.project_id == 10
        assert result.destinations == ["audiobookshelf", "podcast_rss"]
        bg.add_task.assert_called_once()
        _publish_jobs.clear()


class TestPublishHistoryEdgeCases:
    """Edge case tests for publish history."""

    def test_get_history_empty(self):
        """Test empty history."""
        from src.audiobook_studio.api.publish import get_publish_history, _publish_jobs
        
        _publish_jobs.clear()
        
        import asyncio
        history = asyncio.run(get_publish_history(project_id=999))
        assert history == []
        _publish_jobs.clear()


class TestPublishJobEndpointExtended:
    """Extended tests for get_publish_job."""

    def test_get_job_with_error_field(self):
        """Test job with error field."""
        from src.audiobook_studio.api.publish import get_publish_job, _publish_jobs
        
        _publish_jobs.clear()
        _publish_jobs["job_with_error"] = {
            "job_id": "job_with_error",
            "project_id": 10,
            "status": "failed",
            "destinations": ["audiobookshelf"],
            "results": {"audiobookshelf": {"success": False, "error": "Failed"}},
            "error": "Failed",
            "created_at": "2025-01-01T00:00:00Z",
            "completed_at": "2025-01-01T00:01:00Z",
        }
        
        import asyncio
        result = asyncio.run(get_publish_job(project_id=10, job_id="job_with_error"))
        assert result.status == "failed"
        assert result.error == "Failed"
        assert result.completed_at == "2025-01-01T00:01:00Z"
        _publish_jobs.clear()

    def test_get_job_pending_status(self):
        """Test job with pending status."""
        from src.audiobook_studio.api.publish import get_publish_job, _publish_jobs
        
        _publish_jobs.clear()
        _publish_jobs["job_pending"] = {
            "job_id": "job_pending",
            "project_id": 10,
            "status": "pending",
            "destinations": ["audiobookshelf"],
            "results": {},
            "created_at": "2025-01-01T00:00:00Z",
        }
        
        import asyncio
        result = asyncio.run(get_publish_job(project_id=10, job_id="job_pending"))
        assert result.status == "pending"
        assert result.completed_at is None
        _publish_jobs.clear()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
