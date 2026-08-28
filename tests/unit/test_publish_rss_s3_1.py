"""Tests for S3-1 RSS fixes: GMT pubDate and real enclosure length.

These verify the feed passes podcast validators: ``pubDate``/``lastBuildDate``
must be RFC-822 in GMT (not the local ``%Z`` token), and every ``<enclosure>``
must carry a byte ``length`` and a ``type``.
"""

from datetime import datetime, timezone
from pathlib import Path

from src.audiobook_studio.publish.podcast_rss_generator import (
    PodcastEpisode,
    PodcastFeed,
    PodcastRSSGenerator,
    rfc822_gmt,
)


def _episode(title, enclosure_length=0, audio_file_path=None, mime="audio/mpeg"):
    return PodcastEpisode(
        title=title,
        description="desc",
        audio_file_path=audio_file_path or Path(f"/tmp/{title}.mp3"),
        duration_seconds=100,
        pub_date=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        enclosure_length=enclosure_length,
        enclosure_type=mime,
    )


def _feed():
    return PodcastFeed(
        title="Test Podcast",
        description="desc",
        link="http://example.com",
        language="zh-CN",
    )


def test_rfc822_gmt_format():
    dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert rfc822_gmt(dt) == "Mon, 01 Jan 2024 12:00:00 GMT"
    # naive datetime is treated as UTC and still emits GMT
    assert rfc822_gmt(datetime(2024, 1, 1, 12, 0, 0)) == "Mon, 01 Jan 2024 12:00:00 GMT"
    # non-UTC aware is converted to GMT
    from datetime import timedelta

    tokyo = timezone(timedelta(hours=9))
    assert rfc822_gmt(datetime(2024, 1, 1, 21, 0, 0, tzinfo=tokyo)) == "Mon, 01 Jan 2024 12:00:00 GMT"


def test_pubdate_is_gmt():
    gen = PodcastRSSGenerator(_feed())
    gen.add_episode(_episode("Ep1"))
    xml = gen.generate_rss_xml()
    assert "<pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>" in xml
    # the old local-tz token must not appear
    assert "%Z" not in xml


def test_lastbuilddate_is_gmt():
    gen = PodcastRSSGenerator(_feed())
    gen.add_episode(_episode("Ep1"))
    xml = gen.generate_rss_xml()
    assert "<lastBuildDate>" in xml
    # lastBuildDate is generated at "now" but must still end in GMT
    import re

    m = re.search(r"<lastBuildDate>(.*?)</lastBuildDate>", xml)
    assert m.group(1).endswith("GMT")


def test_enclosure_length_uses_explicit_bytes():
    gen = PodcastRSSGenerator(_feed())
    gen.add_episode(_episode("Ep1", enclosure_length=9999))
    xml = gen.generate_rss_xml()
    assert 'length="9999"' in xml
    assert 'type="audio/mpeg"' in xml


def test_enclosure_length_real_file_bytes():
    import tempfile

    gen = PodcastRSSGenerator(_feed())
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ep.mp3"
        p.write_bytes(b"x" * 1234)
        gen.add_episode(_episode("Ep1", audio_file_path=p))
        xml = gen.generate_rss_xml()
        assert 'length="1234"' in xml


def test_enclosure_length_zero_when_missing():
    gen = PodcastRSSGenerator(_feed())
    gen.add_episode(_episode("Ep1"))
    xml = gen.generate_rss_xml()
    assert 'length="0"' in xml


def test_enclosure_type_reflects_extension():
    gen = PodcastRSSGenerator(_feed())
    gen.add_episode(
        _episode("Ep1", audio_file_path=Path("/tmp/ep.m4b"), mime="audio/mp4")
    )
    xml = gen.generate_rss_xml()
    assert 'type="audio/mp4"' in xml
