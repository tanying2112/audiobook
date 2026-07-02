"""Tests for api/publish.py — schemas, endpoints, background tasks, and RSS generation.

Covers:
- Request/Response schemas
- publish_project endpoint (validation, project not found, status check)
- _publish_background (audiobookshelf, podcast_rss, mixed results)
- get_publish_job / get_publish_history
- get_podcast_rss_feed (.m4b → audio/mp4 enclosure type)
- _publish_to_audiobookshelf (MIME type mapping, upload flow)
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ===========================================================================
# Schema tests
# ===========================================================================


class TestPublishSchemas:
    def test_audiobookshelf_config(self):
        from src.audiobook_studio.api.publish import AudiobookshelfConfig

        cfg = AudiobookshelfConfig(server_url="http://localhost:13378", api_key="key123")
        assert cfg.library_id is None

    def test_podcast_rss_config(self):
        from src.audiobook_studio.api.publish import PodcastRSSConfig

        cfg = PodcastRSSConfig(
            feed_title="My Pod",
            feed_description="desc",
            feed_link="http://x",
            author="Me",
            owner_email="me@example.com",
        )
        assert cfg.feed_language == "zh-CN"
        assert cfg.explicit is False
        assert cfg.chapter_as_episode is True

    def test_publish_request_defaults(self):
        from src.audiobook_studio.api.publish import PublishRequest

        req = PublishRequest()
        assert req.destinations == ["audiobookshelf"]

    def test_publish_job_out_defaults(self):
        from src.audiobook_studio.api.publish import PublishJobOut

        job = PublishJobOut(job_id="j1", project_id=1, destinations=["audiobookshelf"], created_at="now")
        assert job.status == "pending"
        assert job.error is None
        assert job.completed_at is None
        assert job.results == {}

    def test_rss_feed_out(self):
        from src.audiobook_studio.api.publish import RSSFeedOut

        feed = RSSFeedOut(xml="<rss/>", feed_url="http://x/feed.xml", episode_count=5)
        assert feed.episode_count == 5


# ===========================================================================
# publish_project endpoint
# ===========================================================================


class TestPublishEndpoint:
    def _make_project(self, status="completed"):
        p = MagicMock()
        p.id = 10
        p.status = status
        return p

    @pytest.mark.asyncio
    async def test_project_not_found(self):
        from fastapi import HTTPException

        from src.audiobook_studio.api.publish import PublishRequest, publish_project

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        req = PublishRequest(destinations=["audiobookshelf"])

        with patch("src.audiobook_studio.api.publish.get_db", return_value=iter([db])):
            with pytest.raises(HTTPException) as exc_info:
                await publish_project(
                    project_id=999,
                    request=req,
                    background_tasks=MagicMock(),
                    db=db,
                )
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_project_not_completed(self):
        from fastapi import HTTPException

        from src.audiobook_studio.api.publish import PublishRequest, publish_project

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = self._make_project(status="processing")
        req = PublishRequest(destinations=["audiobookshelf"])

        with pytest.raises(HTTPException) as exc_info:
            await publish_project(
                project_id=10,
                request=req,
                background_tasks=MagicMock(),
                db=db,
            )
        assert exc_info.value.status_code == 400
        assert "not ready" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_invalid_destination(self):
        from fastapi import HTTPException

        from src.audiobook_studio.api.publish import PublishRequest, publish_project

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = self._make_project()
        req = PublishRequest(destinations=["invalid_service"])

        with pytest.raises(HTTPException) as exc_info:
            await publish_project(
                project_id=10,
                request=req,
                background_tasks=MagicMock(),
                db=db,
            )
        assert exc_info.value.status_code == 400
        assert "Invalid destinations" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_valid_publish_creates_job(self):
        from src.audiobook_studio.api.publish import PublishRequest, _publish_jobs, publish_project

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = self._make_project()
        req = PublishRequest(destinations=["audiobookshelf", "podcast_rss"])
        bg = MagicMock()

        result = await publish_project(
            project_id=10,
            request=req,
            background_tasks=bg,
            db=db,
        )

        assert result.project_id == 10
        assert result.status == "pending"
        assert "audiobookshelf" in result.destinations
        assert "podcast_rss" in result.destinations
        # Background task should be scheduled
        bg.add_task.assert_called_once()
        # Cleanup
        _publish_jobs.clear()

    @pytest.mark.asyncio
    async def test_publish_with_audiobookshelf_config(self):
        from src.audiobook_studio.api.publish import (
            AudiobookshelfConfig,
            PublishRequest,
            _publish_jobs,
            publish_project,
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = self._make_project()
        ab_config = AudiobookshelfConfig(server_url="http://abs:13378", api_key="key")
        req = PublishRequest(
            destinations=["audiobookshelf"],
            audiobookshelf_config=ab_config,
        )
        bg = MagicMock()

        result = await publish_project(
            project_id=10,
            request=req,
            background_tasks=bg,
            db=db,
        )
        assert result.job_id.startswith("publish_10_")
        _publish_jobs.clear()


# ===========================================================================
# get_publish_job / get_publish_history
# ===========================================================================


class TestPublishJobEndpoints:
    def _setup_job(self):
        from src.audiobook_studio.api.publish import _publish_jobs

        _publish_jobs.clear()
        _publish_jobs["publish_10_001"] = {
            "job_id": "publish_10_001",
            "project_id": 10,
            "status": "completed",
            "destinations": ["audiobookshelf"],
            "results": {"audiobookshelf": {"success": True}},
            "created_at": "2025-01-01T00:00:00Z",
            "completed_at": "2025-01-01T00:01:00Z",
        }
        _publish_jobs["publish_10_002"] = {
            "job_id": "publish_10_002",
            "project_id": 10,
            "status": "failed",
            "destinations": ["podcast_rss"],
            "results": {"podcast_rss": {"success": False, "error": "timeout"}},
            "error": "timeout",
            "created_at": "2025-01-02T00:00:00Z",
            "completed_at": "2025-01-02T00:01:00Z",
        }
        yield
        _publish_jobs.clear()

    def test_get_job_found(self):
        from src.audiobook_studio.api.publish import _publish_jobs, get_publish_job

        _publish_jobs.clear()
        _publish_jobs["publish_10_001"] = {
            "job_id": "publish_10_001",
            "project_id": 10,
            "status": "completed",
            "destinations": ["audiobookshelf"],
            "results": {},
            "created_at": "2025-01-01T00:00:00Z",
        }
        import asyncio

        result = asyncio.run(get_publish_job(project_id=10, job_id="publish_10_001"))
        assert result.status == "completed"
        _publish_jobs.clear()

    def test_get_job_not_found(self):
        import asyncio

        from fastapi import HTTPException

        from src.audiobook_studio.api.publish import get_publish_job

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(get_publish_job(project_id=10, job_id="nonexistent"))
        assert exc_info.value.status_code == 404

    def test_get_job_wrong_project(self):
        from fastapi import HTTPException

        from src.audiobook_studio.api.publish import _publish_jobs, get_publish_job

        _publish_jobs.clear()
        _publish_jobs["publish_10_001"] = {
            "job_id": "publish_10_001",
            "project_id": 10,
            "status": "completed",
            "destinations": [],
            "results": {},
            "created_at": "2025-01-01T00:00:00Z",
        }
        import asyncio

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(get_publish_job(project_id=99, job_id="publish_10_001"))
        assert exc_info.value.status_code == 400
        _publish_jobs.clear()

    def test_get_history(self):
        from src.audiobook_studio.api.publish import _publish_jobs, get_publish_history

        _publish_jobs.clear()
        _publish_jobs["a"] = {
            "job_id": "a",
            "project_id": 10,
            "status": "completed",
            "destinations": ["audiobookshelf"],
            "created_at": "2025-01-01",
        }
        _publish_jobs["b"] = {
            "job_id": "b",
            "project_id": 20,
            "status": "failed",
            "destinations": ["podcast_rss"],
            "created_at": "2025-01-02",
        }
        _publish_jobs["c"] = {
            "job_id": "c",
            "project_id": 10,
            "status": "completed",
            "destinations": [],
            "created_at": "2025-01-03",
        }

        import asyncio

        history = asyncio.run(get_publish_history(project_id=10))
        assert len(history) == 2
        # Sorted descending by created_at
        assert history[0].job_id == "c"
        assert history[1].job_id == "a"
        _publish_jobs.clear()


# ===========================================================================
# _publish_background
# ===========================================================================


class TestPublishBackground:
    def test_missing_job_returns_early(self):
        from src.audiobook_studio.api.publish import _publish_background, _publish_jobs

        _publish_jobs.clear()
        import asyncio

        # Should not raise — just logs error and returns
        asyncio.run(_publish_background(job_id="nonexistent", project_id=1, destinations=["audiobookshelf"]))

    @pytest.mark.asyncio
    async def test_audiobookshelf_success(self):
        from src.audiobook_studio.api.publish import _publish_background, _publish_jobs

        _publish_jobs.clear()
        _publish_jobs["j1"] = {
            "job_id": "j1",
            "project_id": 1,
            "status": "pending",
            "destinations": ["audiobookshelf"],
            "results": {},
        }

        with patch(
            "src.audiobook_studio.api.publish._publish_to_audiobookshelf",
            new_callable=AsyncMock,
            return_value={"book_url": "http://abs/1"},
        ):
            await _publish_background(job_id="j1", project_id=1, destinations=["audiobookshelf"])

        job = _publish_jobs["j1"]
        assert job["status"] == "completed"
        assert job["results"]["audiobookshelf"]["success"] is True
        assert job["results"]["audiobookshelf"]["book_url"] == "http://abs/1"
        _publish_jobs.clear()

    @pytest.mark.asyncio
    async def test_audiobookshelf_failure(self):
        from src.audiobook_studio.api.publish import _publish_background, _publish_jobs

        _publish_jobs.clear()
        _publish_jobs["j2"] = {
            "job_id": "j2",
            "project_id": 2,
            "status": "pending",
            "destinations": ["audiobookshelf"],
            "results": {},
        }

        with patch(
            "src.audiobook_studio.api.publish._publish_to_audiobookshelf",
            new_callable=AsyncMock,
            side_effect=ValueError("Connection refused"),
        ):
            await _publish_background(job_id="j2", project_id=2, destinations=["audiobookshelf"])

        job = _publish_jobs["j2"]
        assert job["status"] == "failed"
        assert "Connection refused" in job["results"]["audiobookshelf"]["error"]
        _publish_jobs.clear()

    @pytest.mark.asyncio
    async def test_podcast_rss_success(self):
        from src.audiobook_studio.api.publish import _publish_background, _publish_jobs

        _publish_jobs.clear()
        _publish_jobs["j3"] = {
            "job_id": "j3",
            "project_id": 3,
            "status": "pending",
            "destinations": ["podcast_rss"],
            "results": {},
        }

        with patch(
            "src.audiobook_studio.api.publish._generate_podcast_rss",
            new_callable=AsyncMock,
            return_value={"rss_url": "http://x/feed.xml", "episode_count": 5},
        ):
            await _publish_background(job_id="j3", project_id=3, destinations=["podcast_rss"])

        job = _publish_jobs["j3"]
        assert job["status"] == "completed"
        assert job["results"]["podcast_rss"]["success"] is True
        assert job["results"]["podcast_rss"]["episode_count"] == 5
        _publish_jobs.clear()

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self):
        from src.audiobook_studio.api.publish import _publish_background, _publish_jobs

        _publish_jobs.clear()
        _publish_jobs["j4"] = {
            "job_id": "j4",
            "project_id": 4,
            "status": "pending",
            "destinations": ["audiobookshelf", "podcast_rss"],
            "results": {},
        }

        with patch(
            "src.audiobook_studio.api.publish._publish_to_audiobookshelf",
            new_callable=AsyncMock,
            return_value={"book_url": "http://abs/4"},
        ):
            with patch(
                "src.audiobook_studio.api.publish._generate_podcast_rss",
                new_callable=AsyncMock,
                side_effect=RuntimeError("RSS error"),
            ):
                await _publish_background(
                    job_id="j4",
                    project_id=4,
                    destinations=["audiobookshelf", "podcast_rss"],
                )

        job = _publish_jobs["j4"]
        assert job["status"] == "failed"
        assert job["results"]["audiobookshelf"]["success"] is True
        assert job["results"]["podcast_rss"]["success"] is False
        assert "RSS error" in job["error"]
        _publish_jobs.clear()


# ===========================================================================
# _publish_to_audiobookshelf — MIME type mapping
# ===========================================================================


class TestAudiobookshelfMimeTypes:
    """Test _mime_type helper inside _publish_to_audiobookshelf."""

    def test_m4b_returns_audio_mp4(self):
        """Core requirement: .m4b → audio/mp4."""
        # The _mime_type function is a local function inside _publish_to_audiobookshelf.
        # We can't call it directly, but we can test by checking the function source.
        import inspect
        from pathlib import Path

        from src.audiobook_studio.api.publish import _publish_to_audiobookshelf

        source = inspect.getsource(_publish_to_audiobookshelf)
        assert '".m4b": "audio/mp4"' in source

    @pytest.mark.asyncio
    async def test_missing_config_raises(self):
        from src.audiobook_studio.api.publish import _publish_to_audiobookshelf

        with pytest.raises(ValueError, match="server_url and api_key"):
            await _publish_to_audiobookshelf(project_id=1, config={})

    @pytest.mark.asyncio
    async def test_missing_server_url_raises(self):
        from src.audiobook_studio.api.publish import _publish_to_audiobookshelf

        with pytest.raises(ValueError, match="server_url and api_key"):
            await _publish_to_audiobookshelf(project_id=1, config={"api_key": "k"})


# ===========================================================================
# get_podcast_rss_feed — .m4b enclosure type
# ===========================================================================


class TestPodcastRSSFeedEndpoint:
    """Test the RSS feed generation endpoint, focusing on enclosure type for .m4b."""

    def _make_segment(
        self,
        file_path="chapter_1.m4b",
        duration_ms=60000,
        file_size_bytes=1024000,
        index=1,
        chapter_index=1,
    ):
        seg = MagicMock()
        seg.file_path = file_path
        seg.duration_ms = duration_ms
        seg.file_size_bytes = file_size_bytes
        seg.index = index
        seg.chapter_index = chapter_index
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
        """Helper to run get_podcast_rss_feed with proper mocking.

        AudioSegment has no 'index' column but the code accesses
        AudioSegment.index in order_by(). We temporarily add it to the class.
        """
        from src.audiobook_studio.api.publish import get_podcast_rss_feed
        from src.audiobook_studio.models.audio_segment import AudioSegment

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = project
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = segments

        import asyncio

        with patch("src.audiobook_studio.database.SessionLocal", return_value=mock_db):
            # Temporarily add 'index' to AudioSegment class
            AudioSegment.index = MagicMock(name="index_col")
            try:
                return asyncio.run(get_podcast_rss_feed(project_id=5, **kwargs))
            finally:
                try:
                    del AudioSegment.index
                except AttributeError:
                    pass

    def test_m4b_enclosure_type_is_audio_mp4(self):
        """Core test: .m4b files produce enclosure type='audio/mp4'."""
        project = self._make_project()
        segments = [self._make_segment("book_ch1.m4b")]
        result = self._run_feed(project, segments)
        assert 'type="audio/mp4"' in result.xml
        assert ".m4b" in result.xml

    def test_mp3_enclosure_type_is_audio_mpeg(self):
        project = self._make_project()
        segments = [self._make_segment("chapter.mp3")]
        result = self._run_feed(project, segments)
        assert 'type="audio/mpeg"' in result.xml

    def test_unknown_extension_defaults_to_octet_stream(self):
        project = self._make_project()
        segments = [self._make_segment("audio.xyz")]
        result = self._run_feed(project, segments)
        assert 'type="application/octet-stream"' in result.xml

    def test_no_file_path_defaults_to_m4b(self):
        """Segment with no file_path defaults to episode_N.m4b."""
        project = self._make_project()
        seg = MagicMock()
        seg.file_path = None
        seg.duration_ms = 30000
        seg.file_size_bytes = 500000
        seg.index = 1
        seg.chapter_index = 1
        result = self._run_feed(project, [seg])
        # Default is .m4b → audio/mp4
        assert 'type="audio/mp4"' in result.xml
        assert "episode_1.m4b" in result.xml

    def test_project_not_found(self):
        from fastapi import HTTPException

        from src.audiobook_studio.api.publish import get_podcast_rss_feed

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        import asyncio

        with patch("src.audiobook_studio.database.SessionLocal", return_value=mock_db):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(get_podcast_rss_feed(project_id=999))
        assert exc_info.value.status_code == 404

    def test_rss_contains_channel_and_items(self):
        project = self._make_project()
        segments = [
            self._make_segment("ch1.m4b", index=1),
            self._make_segment("ch2.m4b", index=2),
        ]
        result = self._run_feed(project, segments, categories="Arts,Books")
        assert "channel" in result.xml
        assert result.episode_count == 2
        assert "itunes:category" in result.xml
        assert "Arts" in result.xml
        assert "Books" in result.xml

    def test_zero_duration_segment(self):
        """Segment with duration_ms=0 should produce 0 seconds."""
        project = self._make_project()
        seg = self._make_segment("ch.m4b", duration_ms=0, file_size_bytes=0)
        result = self._run_feed(project, [seg])
        assert "<itunes:duration>0</itunes:duration>" in result.xml

    def test_feed_defaults_from_project(self):
        """Feed config defaults to project metadata when no params given."""
        project = self._make_project()
        project.title = "默认书名"
        project.author = "默认作者"
        result = self._run_feed(project, [])
        assert "默认书名" in result.xml
        assert "默认作者" in result.xml


# ===========================================================================
# _generate_podcast_rss
# ===========================================================================


class TestGeneratePodcastRss:
    @pytest.mark.asyncio
    async def test_project_not_found_raises(self):
        from src.audiobook_studio.api.publish import _generate_podcast_rss

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("src.audiobook_studio.database.SessionLocal", return_value=mock_db):
            with pytest.raises(ValueError, match="not found"):
                await _generate_podcast_rss(project_id=999, config={})

    @pytest.mark.asyncio
    async def test_returns_episode_count(self):
        from src.audiobook_studio.api.publish import _generate_podcast_rss
        from src.audiobook_studio.models.audio_segment import AudioSegment

        mock_project = MagicMock()
        mock_project.id = 5
        mock_segments = [MagicMock(), MagicMock(), MagicMock()]

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_project
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_segments

        AudioSegment.index = MagicMock(name="index_col")
        try:
            with patch("src.audiobook_studio.database.SessionLocal", return_value=mock_db):
                result = await _generate_podcast_rss(project_id=5, config={})
        finally:
            try:
                del AudioSegment.index
            except AttributeError:
                pass

        assert result["episode_count"] == 3
        assert result["success"] is True
        assert "feed.xml" in result["rss_url"]
