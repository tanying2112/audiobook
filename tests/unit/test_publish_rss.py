"""Tests for RSS Feed Generation module."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.publish.rss import RssFeedGenerator


class TestRssFeedGenerator:
    """Tests for RssFeedGenerator class."""

    @pytest.fixture
    def generator(self):
        return RssFeedGenerator(base_url="http://localhost:8000")

    @pytest.fixture
    def mock_book(self):
        book = MagicMock()
        book.id = 1
        book.title = "测试有声书"
        book.author = "测试作者"
        book.created_at = datetime(2024, 1, 15, 10, 30, 0)
        return book

    @pytest.fixture
    def mock_chapters(self):
        chapters = []
        for i in range(1, 4):
            chapter = MagicMock()
            chapter.id = i
            chapter.title = f"第{i}章 测试标题"
            chapter.summary = f"第{i}章的摘要内容"
            chapter.content = f"第{i}章的正文内容..."
            chapters.append(chapter)
        return chapters

    @pytest.fixture
    def mock_audio_segments_by_chapter(self):
        segments = {}
        for i in range(1, 4):
            seg1 = MagicMock()
            seg1.duration_ms = 1800000  # 30 minutes
            seg2 = MagicMock()
            seg2.duration_ms = 1800000  # 30 minutes
            segments[i] = [seg1, seg2]
        return segments

    def test_generator_initialization(self, generator):
        assert generator.base_url == "http://localhost:8000"

    def test_generator_initialization_strips_trailing_slash(self):
        generator = RssFeedGenerator(base_url="http://localhost:8000/")
        assert generator.base_url == "http://localhost:8000"

    def test_generate_rss_feed_basic(
        self, generator, mock_book, mock_chapters, mock_audio_segments_by_chapter
    ):
        rss_content = generator.generate_rss_feed(
            book=mock_book,
            chapters=mock_chapters,
            audio_segments_by_chapter=mock_audio_segments_by_chapter,
        )

        assert '<?xml version="1.0" encoding="UTF-8"?>' in rss_content
        assert '<rss version="2.0"' in rss_content
        assert "xmlns:itunes" in rss_content
        assert "xmlns:content" in rss_content
        assert "测试有声书 - 有声书" in rss_content
        assert "测试作者" in rss_content

    def test_generate_rss_feed_channel_elements(
        self, generator, mock_book, mock_chapters, mock_audio_segments_by_chapter
    ):
        rss_content = generator.generate_rss_feed(
            book=mock_book,
            chapters=mock_chapters,
            audio_segments_by_chapter=mock_audio_segments_by_chapter,
        )

        # Check channel elements
        assert "<title>测试有声书 - 有声书</title>" in rss_content
        assert "<link>http://localhost:8000</link>" in rss_content
        assert "由Audiobook Studio自动生成的有声书" in rss_content
        assert "<language>zh-CN</language>" in rss_content
        assert "<author>测试作者</author>" in rss_content
        assert "© 2026 测试作者" in rss_content

    def test_generate_rss_feed_itunes_tags(
        self, generator, mock_book, mock_chapters, mock_audio_segments_by_chapter
    ):
        rss_content = generator.generate_rss_feed(
            book=mock_book,
            chapters=mock_chapters,
            audio_segments_by_chapter=mock_audio_segments_by_chapter,
        )

        # Check iTunes specific tags
        assert "<itunes:author>测试作者</itunes:author>" in rss_content
        assert "<itunes:summary>" in rss_content
        assert "<itunes:owner>" in rss_content
        assert "<itunes:name>Audiobook Studio</itunes:name>" in rss_content
        assert "<itunes:email>noreply@audiobook.studio</itunes:email>" in rss_content
        assert "<itunes:explicit>no</itunes:explicit>" in rss_content
        assert '<itunes:category text="Arts">' in rss_content
        assert '<itunes:category text="Books" />' in rss_content

    def test_generate_rss_feed_with_cover_image(
        self, generator, mock_book, mock_chapters, mock_audio_segments_by_chapter
    ):
        cover_url = "http://localhost:8000/covers/book1.jpg"
        rss_content = generator.generate_rss_feed(
            book=mock_book,
            chapters=mock_chapters,
            audio_segments_by_chapter=mock_audio_segments_by_chapter,
            cover_image_url=cover_url,
        )

        assert "<image>" in rss_content
        assert f"<url>{cover_url}</url>" in rss_content
        assert "<title>测试有声书 封面</title>" in rss_content
        assert "<link>http://localhost:8000</link>" in rss_content

    def test_generate_rss_feed_items(
        self, generator, mock_book, mock_chapters, mock_audio_segments_by_chapter
    ):
        rss_content = generator.generate_rss_feed(
            book=mock_book,
            chapters=mock_chapters,
            audio_segments_by_chapter=mock_audio_segments_by_chapter,
        )

        # Check 3 items (chapters) are generated
        assert rss_content.count("<item>") == 3
        assert rss_content.count("</item>") == 3

        # Check first chapter item
        assert "<title>第1章 第1章 测试标题</title>" in rss_content
        assert "第1章的摘要内容" in rss_content
        assert "<content:encoded>" in rss_content
        assert "&lt;![CDATA[第1章的正文内容...]]&gt;" in rss_content
        assert '<guid isPermaLink="false">1-chapter-1</guid>' in rss_content

    def test_generate_rss_feed_enclosure(
        self, generator, mock_book, mock_chapters, mock_audio_segments_by_chapter
    ):
        rss_content = generator.generate_rss_feed(
            book=mock_book,
            chapters=mock_chapters,
            audio_segments_by_chapter=mock_audio_segments_by_chapter,
        )

        # Check enclosure for chapter 1 — audio/mp4 is the correct MIME for M4B
        assert 'type="audio/mp4"' in rss_content
        assert 'url="http://localhost:8000/audio/book_1_chapter_1.m4b"' in rss_content

        # Check duration format (1 hour = 3600 seconds = 01:00:00)
        assert "<itunes:duration>01:00:00</itunes:duration>" in rss_content

    def test_generate_rss_feed_episode_numbers(
        self, generator, mock_book, mock_chapters, mock_audio_segments_by_chapter
    ):
        rss_content = generator.generate_rss_feed(
            book=mock_book,
            chapters=mock_chapters,
            audio_segments_by_chapter=mock_audio_segments_by_chapter,
        )

        assert "<itunes:episode>1</itunes:episode>" in rss_content
        assert "<itunes:episode>2</itunes:episode>" in rss_content
        assert "<itunes:episode>3</itunes:episode>" in rss_content
        assert "<itunes:episodeType>full</itunes:episodeType>" in rss_content

    def test_generate_rss_feed_skips_empty_chapters(
        self, generator, mock_book, mock_chapters
    ):
        # Chapter 2 has no audio segments
        mock_audio_segments_by_chapter = {
            1: [MagicMock(duration_ms=1800000)],
            2: [],  # Empty
            3: [MagicMock(duration_ms=1800000)],
        }

        rss_content = generator.generate_rss_feed(
            book=mock_book,
            chapters=mock_chapters,
            audio_segments_by_chapter=mock_audio_segments_by_chapter,
        )

        # Only 2 items should be generated
        assert rss_content.count("<item>") == 2
        assert "<title>第1章 第1章 测试标题</title>" in rss_content
        assert "<title>第3章 第3章 测试标题</title>" in rss_content
        assert "第2章" not in rss_content  # Skipped chapter

    def test_generate_rss_feed_pub_date_format(
        self, generator, mock_book, mock_chapters, mock_audio_segments_by_chapter
    ):
        rss_content = generator.generate_rss_feed(
            book=mock_book,
            chapters=mock_chapters,
            audio_segments_by_chapter=mock_audio_segments_by_chapter,
        )

        # Check pubDate format: "Mon, 15 Jan 2024 10:30:00 GMT"
        assert "<pubDate>Mon, 15 Jan 2024 10:30:00 GMT</pubDate>" in rss_content

    def test_save_rss_feed(self, generator, tmp_path):
        rss_content = '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Test</title></channel></rss>'
        file_path = tmp_path / "test_feed.xml"

        result = generator.save_rss_feed(rss_content, str(file_path))

        assert result is True
        assert file_path.exists()
        assert file_path.read_text(encoding="utf-8") == rss_content

    def test_save_rss_feed_failure(self, generator):
        # Try to save to a non-writable location (should fail gracefully)
        rss_content = '<rss version="2.0"><channel><title>Test</title></channel></rss>'

        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            result = generator.save_rss_feed(rss_content, "/invalid/path/feed.xml")
            assert result is False

    def test_duration_calculation(self, generator, mock_book):
        # Test duration calculation with varying segment durations
        chapter1 = MagicMock()
        chapter1.id = 1
        chapter1.title = "Chapter 1"
        chapter1.summary = "Summary 1"
        chapter1.content = "Content 1"

        # 3 segments: 30min + 20min + 10min = 60min = 1 hour
        seg1 = MagicMock()
        seg1.duration_ms = 1800000  # 30 min
        seg2 = MagicMock()
        seg2.duration_ms = 1200000  # 20 min
        seg3 = MagicMock()
        seg3.duration_ms = 600000  # 10 min

        mock_audio_segments = {1: [seg1, seg2, seg3]}

        rss_content = generator.generate_rss_feed(
            book=mock_book,
            chapters=[chapter1],
            audio_segments_by_chapter=mock_audio_segments,
        )

        # 60 minutes = 01:00:00
        assert "<itunes:duration>01:00:00</itunes:duration>" in rss_content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
