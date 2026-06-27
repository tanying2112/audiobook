"""publish/rss.py 扩展测试 — 覆盖 RssFeedGenerator 全部路径。"""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class TestRssFeedGeneratorExtended:
    """RssFeedGenerator 全路径覆盖。"""

    def test_init_default_url(self):
        """默认 base_url 初始化。"""
        from src.audiobook_studio.publish.rss import RssFeedGenerator
        gen = RssFeedGenerator()
        assert gen.base_url == "http://localhost:8000"

    def test_init_custom_url_trailing_slash(self):
        """自定义 base_url 去除尾部斜杠。"""
        from src.audiobook_studio.publish.rss import RssFeedGenerator
        gen = RssFeedGenerator(base_url="http://example.com/")
        assert gen.base_url == "http://example.com"

    def test_generate_rss_feed_basic(self):
        """基本 RSS Feed 生成。"""
        from src.audiobook_studio.publish.rss import RssFeedGenerator

        book = MagicMock()
        book.title = "测试书"
        book.author = "作者"
        book.id = 1
        book.created_at = datetime(2025, 1, 1)

        chapter = MagicMock()
        chapter.id = 10
        chapter.title = "第一章"
        chapter.summary = "摘要"
        chapter.content = None

        seg = MagicMock()
        seg.duration_ms = 60000  # 60s

        gen = RssFeedGenerator()
        rss = gen.generate_rss_feed(
            book=book,
            chapters=[chapter],
            audio_segments_by_chapter={10: [seg]},
        )
        assert "<?xml" in rss
        assert "测试书" in rss
        assert "有声书" in rss
        assert "第一章" in rss

    def test_generate_rss_feed_with_cover(self):
        """带封面图的 RSS Feed。"""
        from src.audiobook_studio.publish.rss import RssFeedGenerator

        book = MagicMock()
        book.title = "测试书"
        book.author = "作者"
        book.id = 1
        book.created_at = datetime(2025, 1, 1)

        chapter = MagicMock()
        chapter.id = 10
        chapter.title = "第一章"
        chapter.summary = "摘要"
        chapter.content = None

        seg = MagicMock()
        seg.duration_ms = 60000

        gen = RssFeedGenerator()
        rss = gen.generate_rss_feed(
            book=book,
            chapters=[chapter],
            audio_segments_by_chapter={10: [seg]},
            cover_image_url="http://example.com/cover.jpg",
        )
        assert "cover.jpg" in rss
        assert "image" in rss

    def test_generate_rss_feed_with_content(self):
        """带 content 字段的章节。"""
        from src.audiobook_studio.publish.rss import RssFeedGenerator

        book = MagicMock()
        book.title = "测试书"
        book.author = "作者"
        book.id = 1
        book.created_at = datetime(2025, 1, 1)

        chapter = MagicMock()
        chapter.id = 10
        chapter.title = "第一章"
        chapter.summary = "摘要"
        chapter.content = "章节内容正文"
        # Make hasattr work
        chapter.__class__ = type("Chapter", (), {"content": "章节内容正文"})

        seg = MagicMock()
        seg.duration_ms = 120000  # 2min

        gen = RssFeedGenerator()
        rss = gen.generate_rss_feed(
            book=book,
            chapters=[chapter],
            audio_segments_by_chapter={10: [seg]},
        )
        assert "content:encoded" in rss

    def test_generate_rss_feed_skip_empty_chapter(self):
        """无音频片段的章节被跳过。"""
        from src.audiobook_studio.publish.rss import RssFeedGenerator

        book = MagicMock()
        book.title = "测试书"
        book.author = "作者"
        book.id = 1
        book.created_at = datetime(2025, 1, 1)

        chapter = MagicMock()
        chapter.id = 10
        chapter.title = "第一章"
        chapter.summary = "摘要"
        chapter.content = None

        gen = RssFeedGenerator()
        rss = gen.generate_rss_feed(
            book=book,
            chapters=[chapter],
            audio_segments_by_chapter={},  # 空
        )
        # Chapter should be skipped, no "第一章" in item
        assert "第一章" not in rss or "item" not in rss

    def test_generate_rss_feed_no_author(self):
        """无作者时使用默认。"""
        from src.audiobook_studio.publish.rss import RssFeedGenerator

        book = MagicMock()
        book.title = "测试书"
        book.author = None
        book.id = 1
        book.created_at = datetime(2025, 1, 1)

        chapter = MagicMock()
        chapter.id = 10
        chapter.title = "第一章"
        chapter.summary = "摘要"
        chapter.content = None

        seg = MagicMock()
        seg.duration_ms = 3600000  # 1h

        gen = RssFeedGenerator()
        rss = gen.generate_rss_feed(
            book=book,
            chapters=[chapter],
            audio_segments_by_chapter={10: [seg]},
        )
        assert "未知作者" in rss

    def test_generate_rss_feed_duration_calculation(self):
        """时长计算正确。"""
        from src.audiobook_studio.publish.rss import RssFeedGenerator

        book = MagicMock()
        book.title = "测试书"
        book.author = "作者"
        book.id = 1
        book.created_at = datetime(2025, 1, 1)

        chapter = MagicMock()
        chapter.id = 10
        chapter.title = "第一章"
        chapter.summary = "摘要"
        chapter.content = None

        seg = MagicMock()
        seg.duration_ms = 3723000  # 1h 2min 3s

        gen = RssFeedGenerator()
        rss = gen.generate_rss_feed(
            book=book,
            chapters=[chapter],
            audio_segments_by_chapter={10: [seg]},
        )
        assert "01:02:03" in rss

    def test_generate_rss_feed_seg_with_none_duration(self):
        """音频片段 duration_ms 为 None 时不崩溃。"""
        from src.audiobook_studio.publish.rss import RssFeedGenerator

        book = MagicMock()
        book.title = "测试书"
        book.author = "作者"
        book.id = 1
        book.created_at = datetime(2025, 1, 1)

        chapter = MagicMock()
        chapter.id = 10
        chapter.title = "第一章"
        chapter.summary = "摘要"
        chapter.content = None

        seg = MagicMock()
        seg.duration_ms = None

        gen = RssFeedGenerator()
        rss = gen.generate_rss_feed(
            book=book,
            chapters=[chapter],
            audio_segments_by_chapter={10: [seg]},
        )
        assert "<?xml" in rss

    def test_generate_rss_feed_non_datetime_created_at(self):
        """book.created_at 非 datetime 时使用当前时间。"""
        from src.audiobook_studio.publish.rss import RssFeedGenerator

        book = MagicMock()
        book.title = "测试书"
        book.author = "作者"
        book.id = 1
        book.created_at = "2025-01-01"  # 字符串而非 datetime

        chapter = MagicMock()
        chapter.id = 10
        chapter.title = "第一章"
        chapter.summary = "摘要"
        chapter.content = None

        seg = MagicMock()
        seg.duration_ms = 60000

        gen = RssFeedGenerator()
        rss = gen.generate_rss_feed(
            book=book,
            chapters=[chapter],
            audio_segments_by_chapter={10: [seg]},
        )
        assert "<?xml" in rss

    def test_save_rss_feed_success(self):
        """save_rss_feed 成功保存。"""
        from src.audiobook_studio.publish.rss import RssFeedGenerator

        with tempfile.TemporaryDirectory() as tmpdir:
            gen = RssFeedGenerator()
            path = str(Path(tmpdir) / "feed.xml")
            ok = gen.save_rss_feed("<?xml?>", path)
            assert ok is True
            assert Path(path).exists()

    def test_save_rss_feed_failure(self):
        """save_rss_feed 写入失败返回 False。"""
        from src.audiobook_studio.publish.rss import RssFeedGenerator

        gen = RssFeedGenerator()
        ok = gen.save_rss_feed("<?xml?>", "/no/such/path/feed.xml")
        assert ok is False

    def test_generate_rss_feed_multiple_chapters(self):
        """多个章节生成多个 item。"""
        from src.audiobook_studio.publish.rss import RssFeedGenerator

        book = MagicMock()
        book.title = "测试书"
        book.author = "作者"
        book.id = 1
        book.created_at = datetime(2025, 1, 1)

        chapters = []
        segments = {}
        for i in range(3):
            ch = MagicMock()
            ch.id = i
            ch.title = f"第{i}章"
            ch.summary = f"摘要{i}"
            ch.content = None
            chapters.append(ch)
            seg = MagicMock()
            seg.duration_ms = 60000
            segments[i] = [seg]

        gen = RssFeedGenerator()
        rss = gen.generate_rss_feed(
            book=book,
            chapters=chapters,
            audio_segments_by_chapter=segments,
        )
        # Check all three chapters are in the output
        for i in range(3):
            assert f"第{i}章" in rss

    def test_itunes_tags(self):
        """RSS 包含 iTunes 标签。"""
        from src.audiobook_studio.publish.rss import RssFeedGenerator

        book = MagicMock()
        book.title = "测试书"
        book.author = "作者"
        book.id = 1
        book.created_at = datetime(2025, 1, 1)

        chapter = MagicMock()
        chapter.id = 10
        chapter.title = "第一章"
        chapter.summary = "摘要"
        chapter.content = None

        seg = MagicMock()
        seg.duration_ms = 60000

        gen = RssFeedGenerator()
        rss = gen.generate_rss_feed(
            book=book,
            chapters=[chapter],
            audio_segments_by_chapter={10: [seg]},
        )
        assert "itunes:author" in rss
        assert "itunes:summary" in rss
        assert "itunes:explicit" in rss
        assert "itunes:category" in rss
        assert "itunes:duration" in rss
        assert "itunes:episode" in rss
