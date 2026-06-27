"""Targeted tests for rss.py covering remaining uncovered paths.

Covers:
- pub_date is not a datetime instance (line 160 else branch)
- chapter without content attribute
- parametrized: MP3 vs M4B enclosure types
- parametrized: missing optional metadata fields
- RFC 822 time format validation
- xmlns:itunes namespace assertion
"""

import re
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.audiobook_studio.publish.rss import RssFeedGenerator


@pytest.fixture
def generator():
    return RssFeedGenerator(base_url="http://localhost:8000")


def _make_book(**overrides):
    book = MagicMock()
    book.id = 1
    book.title = "测试有声书"
    book.author = "测试作者"
    book.created_at = datetime(2024, 6, 15, 10, 30, 0)
    for k, v in overrides.items():
        setattr(book, k, v)
    return book


def _make_chapter(**overrides):
    ch = MagicMock()
    ch.id = 1
    ch.title = "第一章"
    ch.summary = "摘要内容"
    ch.content = "正文内容"
    for k, v in overrides.items():
        setattr(ch, k, v)
    return ch


def _make_segment(duration_ms=60000):
    seg = MagicMock()
    seg.duration_ms = duration_ms
    return seg


class TestPubDateFormatNonDatetime:
    """Test pub_date when created_at is NOT a datetime (line 160 else branch)."""

    def test_pub_date_string_created_at(self, generator):
        """When created_at is a string (not datetime), falls through to else branch."""
        book = _make_book(created_at="2024-01-15T10:30:00")  # string, not datetime
        chapter = _make_chapter()
        segments = {1: [_make_segment()]}

        rss = generator.generate_rss_feed(book, [chapter], segments)

        # Should still have a valid pubDate in RFC 822 format
        assert "<pubDate>" in rss
        # Extract pubDate value
        match = re.search(r"<pubDate>(.*?)</pubDate>", rss)
        assert match is not None
        pub_date_str = match.group(1)
        # Verify RFC 822 format: "Day, DD Mon YYYY HH:MM:SS GMT"
        assert re.match(r"[A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} GMT", pub_date_str)

    def test_pub_date_none_created_at(self, generator):
        """When created_at is None, getattr returns datetime.now()."""
        book = _make_book(created_at=None)
        chapter = _make_chapter()
        segments = {1: [_make_segment()]}

        # getattr(book, "created_at", datetime.now()) returns None (attribute exists but is None)
        # isinstance(None, datetime) is False -> else branch
        rss = generator.generate_rss_feed(book, [chapter], segments)
        assert "<pubDate>" in rss

    def test_pub_date_int_created_at(self, generator):
        """When created_at is an int (timestamp), falls to else branch."""
        book = _make_book(created_at=1705312200)
        chapter = _make_chapter()
        segments = {1: [_make_segment()]}

        rss = generator.generate_rss_feed(book, [chapter], segments)
        assert "<pubDate>" in rss
        match = re.search(r"<pubDate>(.*?)</pubDate>", rss)
        assert match is not None
        # RFC 822 format
        assert re.match(r"[A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} GMT", match.group(1))


class TestChapterWithoutContent:
    """Test chapter that has no content attribute or has empty content."""

    def test_chapter_no_content_attr(self, generator):
        """Chapter without 'content' attribute should not add content:encoded."""
        book = _make_book()

        # Use a simple namespace object without 'content' attribute
        class MinimalChapter:
            def __init__(self):
                self.id = 1
                self.title = "第一章"
                self.summary = "摘要"
                # Deliberately no .content attribute
        chapter = MinimalChapter()
        segments = {1: [_make_segment()]}

        rss = generator.generate_rss_feed(book, [chapter], segments)
        assert "<item>" in rss
        assert "<content:encoded>" not in rss

    def test_chapter_empty_content(self, generator):
        """Chapter with empty content string should not add content:encoded."""
        book = _make_book()
        chapter = _make_chapter(content="")
        segments = {1: [_make_segment()]}

        rss = generator.generate_rss_feed(book, [chapter], segments)
        # Empty string is falsy, so `hasattr(chapter, "content") and chapter.content` -> False
        assert "<content:encoded>" not in rss

    def test_chapter_none_content(self, generator):
        """Chapter with None content should not add content:encoded."""
        book = _make_book()
        chapter = _make_chapter(content=None)
        segments = {1: [_make_segment()]}

        rss = generator.generate_rss_feed(book, [chapter], segments)
        assert "<content:encoded>" not in rss


class TestNoCoverImage:
    """Test RSS generation without cover image."""

    def test_no_cover_image(self, generator):
        """No cover_image_url means no <image> element."""
        book = _make_book()
        chapter = _make_chapter()
        segments = {1: [_make_segment()]}

        rss = generator.generate_rss_feed(book, [chapter], segments, cover_image_url=None)
        assert "<image>" not in rss


class TestRfc822DateFormat:
    """Validate RFC 822 date format in generated RSS."""

    RFC822_PATTERN = re.compile(
        r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), "
        r"\d{2} "
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
        r"\d{4} "
        r"\d{2}:\d{2}:\d{2} GMT$"
    )

    def test_all_chapters_have_valid_rfc822_date(self, generator):
        """All pubDate elements should conform to RFC 822."""
        book = _make_book()
        chapters = [_make_chapter(id=i, title=f"第{i}章") for i in range(1, 4)]
        segments = {i: [_make_segment() for _ in range(1)] for i in range(1, 4)}

        rss = generator.generate_rss_feed(book, chapters, segments)

        dates = re.findall(r"<pubDate>(.*?)</pubDate>", rss)
        assert len(dates) >= 3  # At least 3 chapter items
        for d in dates:
            assert self.RFC822_PATTERN.match(d), f"Invalid RFC 822 date: {d}"


class TestXmlnsItunesNamespace:
    """Verify xmlns:itunes namespace is present."""

    def test_xmlns_itunes_present(self, generator):
        """RSS root should declare xmlns:itunes namespace."""
        book = _make_book()
        chapter = _make_chapter()
        segments = {1: [_make_segment()]}

        rss = generator.generate_rss_feed(book, [chapter], segments)
        assert 'xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"' in rss
        assert 'xmlns:content="http://purl.org/rss/1.0/modules/content/"' in rss
        assert '<rss version="2.0"' in rss


class TestEnclosureM4BType:
    """Verify enclosure type is audio/mp4 for .m4b files."""

    def test_m4b_enclosure_type(self, generator):
        """Audio files use .m4b extension with audio/mp4 MIME type."""
        book = _make_book()
        chapter = _make_chapter()
        segments = {1: [_make_segment()]}

        rss = generator.generate_rss_feed(book, [chapter], segments)
        assert 'type="audio/mp4"' in rss
        assert '.m4b"' in rss

    def test_enclosure_url_format(self, generator):
        """Enclosure URL should follow the expected format."""
        book = _make_book(id=42)
        chapter = _make_chapter(id=7)
        segments = {7: [_make_segment()]}

        rss = generator.generate_rss_feed(book, [chapter], segments)
        assert 'url="http://localhost:8000/audio/book_42_chapter_7.m4b"' in rss


class TestParametrizedInputCombinations:
    """Parametrized tests for various input combinations."""

    @pytest.mark.parametrize(
        "author,author_expected",
        [
            ("张三", "张三"),
            (None, "未知作者"),
            ("", "未知作者"),  # "" or "未知作者" -> "未知作者"
        ],
    )
    def test_author_variations(self, generator, author, author_expected):
        """Test RSS with different author values."""
        book = _make_book(author=author)
        chapter = _make_chapter()
        segments = {1: [_make_segment()]}

        rss = generator.generate_rss_feed(book, [chapter], segments)
        assert f"<author>{author_expected}</author>" in rss

    @pytest.mark.parametrize(
        "summary,summary_present",
        [
            ("有摘要内容", True),
            (None, False),
            ("", False),
        ],
    )
    def test_chapter_summary_variations(self, generator, summary, summary_present):
        """Test chapter description with different summary values."""
        book = _make_book()
        chapter = _make_chapter(summary=summary)
        segments = {1: [_make_segment()]}

        rss = generator.generate_rss_feed(book, [chapter], segments)
        if summary_present:
            assert summary in rss

    @pytest.mark.parametrize(
        "durations,expected_duration",
        [
            ([30000, 30000], "00:01:00"),       # 60s
            ([1800000, 1800000], "01:00:00"),    # 1h
            ([3721000], "01:02:01"),              # 1h 2m 1s
            ([0], "00:00:00"),                    # zero duration
        ],
    )
    def test_duration_calculation(self, generator, durations, expected_duration):
        """Test duration calculation with various segment durations."""
        book = _make_book()
        chapter = _make_chapter()
        segments = {1: [_make_segment(d) for d in durations]}

        rss = generator.generate_rss_feed(book, [chapter], segments)
        assert f"<itunes:duration>{expected_duration}</itunes:duration>" in rss

    @pytest.mark.parametrize(
        "num_segments,expected_count",
        [
            (0, 0),   # no segments -> chapter skipped
            (1, 1),
            (3, 1),   # multiple segments but still one chapter
        ],
    )
    def test_segment_count(self, generator, num_segments, expected_count):
        """Test chapter with various numbers of audio segments."""
        book = _make_book()
        chapter = _make_chapter()
        segments = {1: [_make_segment() for _ in range(num_segments)] if num_segments > 0 else []}

        rss = generator.generate_rss_feed(book, [chapter], segments)
        assert rss.count("<item>") == expected_count

    @pytest.mark.parametrize(
        "title,author",
        [
            ("中文书名", "中文作者"),
            ("English Title", "English Author"),
            ("日本語タイトル", "著者"),
        ],
    )
    def test_multilingual_metadata(self, generator, title, author):
        """Test RSS with different language metadata."""
        book = _make_book(title=title, author=author)
        chapter = _make_chapter()
        segments = {1: [_make_segment()]}

        rss = generator.generate_rss_feed(book, [chapter], segments)
        assert title in rss
        assert author in rss

    @pytest.mark.parametrize(
        "base_url",
        [
            "http://localhost:8000",
            "https://example.com/podcast",
            "http://192.168.1.100:9000",
        ],
    )
    def test_base_url_variations(self, generator, base_url):
        """Test RSS with different base URLs."""
        gen = RssFeedGenerator(base_url=base_url)
        book = _make_book()
        chapter = _make_chapter()
        segments = {1: [_make_segment()]}

        rss = gen.generate_rss_feed(book, [chapter], segments)
        assert base_url in rss
        assert f"<link>{base_url}</link>" in rss


class TestEmptyBookMetadata:
    """Test RSS with empty or minimal book metadata."""

    def test_empty_title(self, generator):
        """Book with empty title."""
        book = _make_book(title="")
        chapter = _make_chapter()
        segments = {1: [_make_segment()]}

        rss = generator.generate_rss_feed(book, [chapter], segments)
        assert "<title> - 有声书</title>" in rss

    def test_missing_chapters(self, generator):
        """Empty chapter list produces channel but no items."""
        book = _make_book()
        rss = generator.generate_rss_feed(book, [], {})
        assert "<item>" not in rss
        assert "<channel>" in rss
        assert "xmlns:itunes" in rss
