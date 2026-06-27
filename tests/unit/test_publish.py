"""publish 模块补充测试 — 覆盖 PodcastRSSGenerator, PodcastFeed,
PodcastEpisode, AudiobookshelfIntegrator, AudiobookshelfAPIClient stub,
以及 AudiobookMetadata/AudiobookFile 的边界情况。"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ===========================================================================
# PodcastEpisode
# ===========================================================================


class TestPodcastEpisode:
    def test_basic_creation(self):
        """PodcastEpisode 基本创建。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastEpisode

        ep = PodcastEpisode(
            title="测试集",
            description="测试描述",
            audio_file_path=Path("/tmp/test.mp3"),
            duration_seconds=1800,
            pub_date=datetime(2025, 1, 1),
        )
        assert ep.title == "测试集"
        assert ep.duration_seconds == 1800
        assert ep.guid  # 自动生成 GUID

    def test_guid_generation_file_not_exists(self):
        """文件不存在时基于路径+标题生成 GUID。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastEpisode

        ep = PodcastEpisode(
            title="集1",
            description="d",
            audio_file_path=Path("/nonexistent/file.mp3"),
            duration_seconds=100,
            pub_date=datetime(2025, 6, 1),
        )
        assert isinstance(ep.guid, str)
        assert len(ep.guid) == 64  # SHA-256 hex

    def test_episode_defaults(self):
        """默认字段值。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastEpisode

        ep = PodcastEpisode(
            title="t", description="d",
            audio_file_path=Path("/tmp/x.mp3"),
            duration_seconds=60,
            pub_date=datetime(2025, 1, 1),
        )
        assert ep.episode_type == "full"
        assert ep.season_number is None
        assert ep.episode_number is None
        assert ep.explicit is False


# ===========================================================================
# PodcastFeed
# ===========================================================================


class TestPodcastFeed:
    def test_creation(self):
        """PodcastFeed 创建并含默认字段。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastFeed

        feed = PodcastFeed(
            title="播客",
            description="desc",
            link="https://example.com",
        )
        assert feed.title == "播客"
        assert feed.language == "zh-CN"
        assert feed.episodes == []

    def test_creation_with_options(self):
        """PodcastFeed 自定义选项。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastFeed

        feed = PodcastFeed(
            title="t", description="d", link="http://x",
            language="en-US",
            author="Me",
            itunes_categories=[("Arts", "Books")],
        )
        assert feed.language == "en-US"
        assert feed.itunes_categories == [("Arts", "Books")]


# ===========================================================================
# PodcastRSSGenerator
# ===========================================================================


class TestPodcastRSSGenerator:
    def _make_feed(self, **kwargs):
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastFeed

        defaults = dict(title="播客", description="desc", link="http://x")
        defaults.update(kwargs)
        return PodcastFeed(**defaults)

    def _make_ep(self, title="集1", **kwargs):
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastEpisode

        defaults = dict(
            title=title,
            description="desc",
            audio_file_path=Path("/tmp/test.mp3"),
            duration_seconds=600,
            pub_date=datetime(2025, 1, 1),
        )
        defaults.update(kwargs)
        return PodcastEpisode(**defaults)

    def test_add_episode(self):
        """add_episode 添加并排序。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed()
        gen = PodcastRSSGenerator(feed)
        ep1 = self._make_ep("早", pub_date=datetime(2025, 1, 1))
        ep2 = self._make_ep("晚", pub_date=datetime(2025, 6, 1))
        gen.add_episode(ep1)
        gen.add_episode(ep2)
        assert len(feed.episodes) == 2
        # 最新在前
        assert feed.episodes[0].title == "晚"

    def test_generate_rss_xml(self):
        """generate_rss_xml 输出包含 RSS 结构。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed()
        gen = PodcastRSSGenerator(feed)
        gen.add_episode(self._make_ep())
        xml = gen.generate_rss_xml()
        assert "rss" in xml
        assert "channel" in xml
        assert "集1" in xml

    def test_generate_rss_xml_with_itunes(self):
        """generate_rss_xml 包含 iTunes 标签。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed(itunes_author="Me", itunes_categories=[("Arts", "Books")])
        gen = PodcastRSSGenerator(feed)
        gen.add_episode(self._make_ep())
        xml = gen.generate_rss_xml()
        assert "itunes:author" in xml
        assert "itunes:category" in xml

    def test_generate_rss_xml_with_image(self):
        """generate_rss_xml 包含封面图。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed(image_url="http://x/img.jpg")
        gen = PodcastRSSGenerator(feed)
        gen.add_episode(self._make_ep())
        xml = gen.generate_rss_xml()
        assert "image" in xml
        assert "http://x/img.jpg" in xml

    def test_save_to_file(self):
        """save_to_file 写入文件成功。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        with tempfile.TemporaryDirectory() as tmpdir:
            feed = self._make_feed()
            gen = PodcastRSSGenerator(feed)
            gen.add_episode(self._make_ep())
            path = Path(tmpdir) / "feed.xml"
            ok, msg = gen.save_to_file(path)
            assert ok is True
            assert path.exists()
            assert "xml" in path.read_text(encoding="utf-8")

    def test_save_to_file_error(self):
        """save_to_file 写入失败返回错误。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed()
        gen = PodcastRSSGenerator(feed)
        with patch("builtins.open", side_effect=PermissionError("denied")):
            ok, msg = gen.save_to_file(Path("/no/such/path"))
            assert ok is False

    def test_validate_feed_ok(self):
        """validate_feed 通过。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed()
        gen = PodcastRSSGenerator(feed)
        gen.add_episode(self._make_ep())
        ok, errors = gen.validate_feed()
        assert ok is True
        assert errors == []

    def test_validate_feed_empty_title(self):
        """validate_feed 标题为空时报错。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed(title="  ")
        gen = PodcastRSSGenerator(feed)
        ok, errors = gen.validate_feed()
        assert ok is False
        assert any("标题" in e for e in errors)

    def test_validate_feed_empty_description(self):
        """validate_feed 描述为空时报错。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed(description="  ")
        gen = PodcastRSSGenerator(feed)
        ok, errors = gen.validate_feed()
        assert ok is False
        assert any("描述" in e for e in errors)

    def test_validate_feed_empty_link(self):
        """validate_feed 链接为空时报错。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed(link="  ")
        gen = PodcastRSSGenerator(feed)
        ok, errors = gen.validate_feed()
        assert ok is False

    def test_validate_feed_no_episodes(self):
        """validate_feed 无节目时报错。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed()
        gen = PodcastRSSGenerator(feed)
        ok, errors = gen.validate_feed()
        assert ok is False
        assert any("至少一个节目" in e for e in errors)

    def test_validate_feed_episode_no_title(self):
        """validate_feed 节目标题为空时报错。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed()
        gen = PodcastRSSGenerator(feed)
        ep = self._make_ep(title="  ")
        gen.add_episode(ep)
        ok, errors = gen.validate_feed()
        assert ok is False

    def test_reassign_episode_numbers(self):
        """add_episode 重新分配 episode_number。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed()
        gen = PodcastRSSGenerator(feed)
        ep1 = self._make_ep("a")
        ep2 = self._make_ep("b")
        ep2.episode_number = 99  # 手动设置
        gen.add_episode(ep1)
        gen.add_episode(ep2)
        # ep2 手动设置的不应被覆盖
        assert ep2.episode_number == 99
        # ep1 应被分配编号
        assert ep1.episode_number is not None


# ===========================================================================
# AudiobookshelfAPIClient stub
# ===========================================================================


class TestAudiobookshelfAPIClient:
    def test_stub_methods(self):
        """AudiobookshelfAPIClient stub 的方法返回正确值。"""
        from src.audiobook_studio.publish.audiobookshelf_integration import AudiobookshelfAPIClient

        client = AudiobookshelfAPIClient()
        assert client.check_connection() is True
        assert client.upload_audiobook() is True


# ===========================================================================
# AudiobookshelfIntegrator dataclass
# ===========================================================================


class TestAudiobookIntegratorData:
    def test_metadata_fields(self):
        """AudiobookMetadata 所有字段可访问。"""
        from src.audiobook_studio.publish.audiobookshelf_integration import AudiobookMetadata

        m = AudiobookMetadata(
            title="书", author="作者", narrator="旁白", description="简介",
            language="en", publication_year=2024, publisher="出版社",
            genres=["sci-fi"], tags=["tag1"], series="系列", series_index=1.0,
            cover_image_path=Path("/cover.jpg"),
            duration_seconds=3600, bitrate_kbps=128, format="mp3",
        )
        assert m.title == "书"
        assert m.duration_seconds == 3600

    def test_file_dataclass(self):
        """AudiobookFile 数据类可创建。"""
        from src.audiobook_studio.publish.audiobookshelf_integration import AudiobookFile

        f = AudiobookFile(
            file_path=Path("/book.m4b"),
            size_bytes=1024000,
            duration_seconds=7200,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="abc123",
            chapters=[{"start": 0, "title": "Ch1"}],
        )
        assert f.file_path.name == "book.m4b"
        assert len(f.chapters) == 1

    def test_config_dataclass(self):
        """AudiobookshelfConfig 数据类可创建。"""
        from src.audiobook_studio.publish.audiobookshelf_integration import AudiobookshelfConfig

        c = AudiobookshelfConfig(
            api_url="http://localhost:8080",
            api_key="test-key",
            library_id="lib-1",
        )
        assert c.supported_formats == ["m4b", "mp3"]
        assert c.auto_convert is True
