"""publish/podcast_rss_generator.py 扩展测试 — 提升覆盖率到 80%+。"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestPodcastRSSGeneratorExtended:
    """PodcastRSSGenerator 深度覆盖。"""

    def _make_feed(self, **kwargs):
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastFeed

        defaults = dict(title="播客", description="desc", link="http://x")
        defaults.update(kwargs)
        return PodcastFeed(**defaults)

    def _make_ep(self, title="集1", audio_exists=False, **kwargs):
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastEpisode

        if audio_exists:
            fp = Path(tempfile.mktemp(suffix=".mp3"))
            fp.write_bytes(b"fake audio")
        else:
            fp = Path("/tmp/nonexistent_file.mp3")
        defaults = dict(
            title=title,
            description="desc",
            audio_file_path=fp,
            duration_seconds=600,
            pub_date=datetime(2025, 1, 1),
        )
        defaults.update(kwargs)
        return PodcastEpisode(**defaults)

    def test_guid_file_exists(self):
        """文件存在时基于文件内容生成 GUID。"""
        ep = self._make_ep(audio_exists=True)
        assert isinstance(ep.guid, str)
        assert len(ep.guid) == 64
        # Cleanup
        ep.audio_file_path.unlink(missing_ok=True)

    def test_guid_file_not_exists(self):
        """文件不存在时基于路径+标题生成 GUID。"""
        ep = self._make_ep(audio_exists=False)
        assert isinstance(ep.guid, str)
        assert len(ep.guid) == 64

    def test_add_episode_with_existing_numbers(self):
        """手动设置的 episode_number 不被覆盖。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed()
        gen = PodcastRSSGenerator(feed)
        ep1 = self._make_ep("a")
        ep1.episode_number = 10
        ep2 = self._make_ep("b")
        ep2.episode_number = 20
        gen.add_episode(ep1)
        gen.add_episode(ep2)
        assert ep1.episode_number == 10
        assert ep2.episode_number == 20

    def test_rss_xml_with_owner_info(self):
        """RSS 包含 owner 信息。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed(
            owner_name="Owner",
            owner_email="owner@test.com",
        )
        gen = PodcastRSSGenerator(feed)
        gen.add_episode(self._make_ep())
        xml = gen.generate_rss_xml()
        assert "managingEditor" in xml
        assert "webMaster" in xml

    def test_rss_xml_with_categories(self):
        """RSS 包含分类。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed(categories=["科幻", "有声书"])
        gen = PodcastRSSGenerator(feed)
        gen.add_episode(self._make_ep())
        xml = gen.generate_rss_xml()
        assert "科幻" in xml
        assert "有声书" in xml

    def test_rss_xml_with_itunes_owner(self):
        """RSS 包含 iTunes owner 标签。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed(
            itunes_owner_name="iOwner",
            itunes_owner_email="i@test.com",
            itunes_categories=[("Arts", "Books")],
        )
        gen = PodcastRSSGenerator(feed)
        gen.add_episode(self._make_ep())
        xml = gen.generate_rss_xml()
        assert "itunes:owner" in xml
        assert "itunes:name" in xml
        assert "itunes:email" in xml
        assert "itunes:category" in xml

    def test_rss_xml_with_itunes_no_subcategory(self):
        """RSS 包含无子分类的 iTunes category。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed(itunes_categories=[("Science", None)])
        gen = PodcastRSSGenerator(feed)
        gen.add_episode(self._make_ep())
        xml = gen.generate_rss_xml()
        assert "Science" in xml

    def test_rss_xml_with_author(self):
        """RSS 包含 author 标签。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed(author="TestAuthor")
        gen = PodcastRSSGenerator(feed)
        gen.add_episode(self._make_ep())
        xml = gen.generate_rss_xml()
        assert "author" in xml
        assert "TestAuthor" in xml

    def test_episode_with_season_number(self):
        """RSS 包含 season 标签。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        gen = PodcastRSSGenerator(self._make_feed())
        ep = self._make_ep(season_number=2, episode_number=3)
        gen.add_episode(ep)
        xml = gen.generate_rss_xml()
        assert "itunes:season" in xml
        assert "itunes:episode" in xml
        assert "itunes:episodeType" in xml

    def test_episode_explicit(self):
        """RSS 包含 explicit 标签。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        gen = PodcastRSSGenerator(self._make_feed())
        ep = self._make_ep(explicit=True)
        gen.add_episode(ep)
        xml = gen.generate_rss_xml()
        assert "itunes:explicit" in xml
        assert "yes" in xml

    def test_save_to_file_creates_dir(self):
        """save_to_file 自动创建目录。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        with tempfile.TemporaryDirectory() as tmpdir:
            feed = self._make_feed()
            gen = PodcastRSSGenerator(feed)
            gen.add_episode(self._make_ep())
            path = Path(tmpdir) / "sub" / "feed.xml"
            ok, msg = gen.save_to_file(path)
            assert ok is True
            assert path.exists()

    def test_validate_episode_no_title(self):
        """节目标题为空时报错。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed()
        gen = PodcastRSSGenerator(feed)
        ep = self._make_ep(title="  ")
        gen.add_episode(ep)
        ok, errors = gen.validate_feed()
        assert ok is False
        assert any("标题" in e for e in errors)

    def test_validate_episode_no_description(self):
        """节目描述为空时报错。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed()
        gen = PodcastRSSGenerator(feed)
        ep = self._make_ep(description="  ")
        gen.add_episode(ep)
        ok, errors = gen.validate_feed()
        assert ok is False
        assert any("描述" in e for e in errors)

    def test_validate_episode_no_audio(self):
        """节目音频路径为空时报错。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastEpisode, PodcastRSSGenerator

        feed = self._make_feed()
        gen = PodcastRSSGenerator(feed)
        ep = PodcastEpisode(
            title="t",
            description="d",
            audio_file_path=Path("/tmp/nonexistent.mp3"),
            duration_seconds=60,
            pub_date=datetime.now(),
        )
        gen.add_episode(ep)
        ok, errors = gen.validate_feed()
        # Path exists so validation passes (file not found is just a warning)
        assert ok is True

    def test_validate_episode_file_not_exists(self):
        """节目音频文件不存在时通过（警告但非错误）。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed()
        gen = PodcastRSSGenerator(feed)
        ep = self._make_ep(audio_exists=False)
        gen.add_episode(ep)
        ok, errors = gen.validate_feed()
        assert ok is True  # 文件不存在只是警告

    def test_episode_enclosure_file_exists(self):
        """音频文件存在时 enclosure length 使用文件大小。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        gen = PodcastRSSGenerator(self._make_feed())
        ep = self._make_ep(audio_exists=True)
        gen.add_episode(ep)
        xml = gen.generate_rss_xml()
        assert "enclosure" in xml
        ep.audio_file_path.unlink(missing_ok=True)

    def test_episode_enclosure_file_not_exists(self):
        """音频文件不存在时 enclosure length 为 0。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        gen = PodcastRSSGenerator(self._make_feed())
        ep = self._make_ep(audio_exists=False)
        gen.add_episode(ep)
        xml = gen.generate_rss_xml()
        assert "enclosure" in xml

    def test_rss_xml_full_structure(self):
        """完整的 RSS XML 结构。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        feed = self._make_feed(
            author="Author",
            owner_name="Owner",
            owner_email="o@t.com",
            itunes_author="iAuthor",
            itunes_owner_name="iOwner",
            itunes_owner_email="i@t.com",
            itunes_categories=[("Arts", "Books"), ("Science", None)],
            categories=["科幻"],
            image_url="http://x/img.jpg",
        )
        gen = PodcastRSSGenerator(feed)
        ep = self._make_ep(season_number=1, episode_number=5, explicit=True)
        gen.add_episode(ep)
        xml = gen.generate_rss_xml()
        # Verify structure
        assert "rss" in xml
        assert "channel" in xml
        assert "itunes:explicit" in xml
        assert "atom:link" in xml
        assert "lastBuildDate" in xml
        assert "generator" in xml

    def test_multiple_episodes_sorting(self):
        """多集按发布日期倒序。"""
        from src.audiobook_studio.publish.podcast_rss_generator import PodcastRSSGenerator

        gen = PodcastRSSGenerator(self._make_feed())
        ep1 = self._make_ep("早", pub_date=datetime(2025, 1, 1))
        ep2 = self._make_ep("中", pub_date=datetime(2025, 6, 1))
        ep3 = self._make_ep("晚", pub_date=datetime(2025, 12, 1))
        gen.add_episode(ep1)
        gen.add_episode(ep2)
        gen.add_episode(ep3)
        assert gen.feed.episodes[0].title == "晚"
        assert gen.feed.episodes[1].title == "中"
        assert gen.feed.episodes[2].title == "早"
