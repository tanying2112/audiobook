"""Comprehensive tests for publish/podcast_rss_generator.py — coverage boost to 80%+."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from src.audiobook_studio.publish.podcast_rss_generator import PodcastEpisode, PodcastFeed, PodcastRSSGenerator


def _feed(**kw):
    defaults = dict(
        title="Test Feed",
        description="A test feed",
        link="https://example.com/feed",
        language="en",
        author="Author",
        owner_name="Owner",
        owner_email="owner@test.com",
        image_url="https://example.com/image.jpg",
        categories=["Tech", "Books"],
        explicit=False,
        itunes_author="iTunes Author",
        itunes_owner_name="iTunes Owner",
        itunes_owner_email="itunes@test.com",
        itunes_explicit="no",
        itunes_categories=[("Arts", "Books"), ("Tech", None)],
    )
    defaults.update(kw)
    return PodcastFeed(**defaults)


def _episode(td, **kw):
    fp = Path(td) / "ep1.mp3"
    fp.write_bytes(b"\x00audio" * 1000)
    defaults = dict(
        title="Ep 1",
        description="Episode 1",
        audio_file_path=fp,
        duration_seconds=300,
        pub_date=datetime(2024, 1, 1),
        episode_number=1,
        season_number=1,
        explicit=False,
    )
    defaults.update(kw)
    return PodcastEpisode(**defaults)


# ---- PodcastEpisode ----
class TestPodcastEpisode:
    def test_guid_file_exists(self):
        with tempfile.TemporaryDirectory() as td:
            ep = _episode(td)
            assert ep.guid is not None
            assert len(ep.guid) == 64

    def test_guid_file_not_exists(self):
        fp = Path("/nonexistent/ep.mp3")
        ep = PodcastEpisode(
            title="Test",
            description="desc",
            audio_file_path=fp,
            duration_seconds=60,
            pub_date=datetime(2024, 1, 1),
        )
        assert ep.guid is not None
        assert len(ep.guid) == 64

    def test_enclosure_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            ep = _episode(td)
            assert ep.enclosure_type == "audio/mpeg"
            assert ep.episode_type == "full"

    def test_default_optional_fields(self):
        with tempfile.TemporaryDirectory() as td:
            ep = PodcastEpisode(
                title="T",
                description="D",
                audio_file_path=Path(td) / "a.mp3",
                duration_seconds=60,
                pub_date=datetime(2024, 1, 1),
            )
            assert ep.season_number is None
            assert ep.episode_number is None


# ---- PodcastFeed ----
class TestPodcastFeed:
    def test_defaults(self):
        f = _feed()
        assert f.title == "Test Feed"
        assert "Audiobook Studio" in f.copyright
        assert "Audiobook Studio" in f.generator
        assert isinstance(f.last_build_date, datetime)
        assert f.episodes == []


# ---- PodcastRSSGenerator ----
class TestGenerator:
    def test_add_episode(self):
        gen = PodcastRSSGenerator(_feed())
        with tempfile.TemporaryDirectory() as td:
            gen.add_episode(_episode(td))
            assert len(gen.feed.episodes) == 1

    def test_validate_feed_valid(self):
        gen = PodcastRSSGenerator(_feed())
        with tempfile.TemporaryDirectory() as td:
            gen.add_episode(_episode(td))
            valid, errors = gen.validate_feed()
            assert valid is True
            assert len(errors) == 0

    def test_validate_feed_no_title(self):
        f = _feed(title="  ")
        gen = PodcastRSSGenerator(f)
        valid, errors = gen.validate_feed()
        assert valid is False
        assert any("标题" in e for e in errors)

    def test_validate_feed_no_description(self):
        f = _feed(description="  ")
        gen = PodcastRSSGenerator(f)
        valid, errors = gen.validate_feed()
        assert valid is False
        assert any("描述" in e for e in errors)

    def test_validate_feed_no_link(self):
        f = _feed(link="  ")
        gen = PodcastRSSGenerator(f)
        valid, errors = gen.validate_feed()
        assert valid is False
        assert any("链接" in e for e in errors)

    def test_validate_feed_no_episodes(self):
        gen = PodcastRSSGenerator(_feed())
        valid, errors = gen.validate_feed()
        assert valid is False
        assert any("节目" in e for e in errors)

    def test_validate_episode_no_title(self):
        gen = PodcastRSSGenerator(_feed())
        with tempfile.TemporaryDirectory() as td:
            gen.add_episode(_episode(td, title="  "))
            valid, errors = gen.validate_feed()
            assert valid is False
            assert any("标题" in e for e in errors)

    def test_validate_episode_no_description(self):
        gen = PodcastRSSGenerator(_feed())
        with tempfile.TemporaryDirectory() as td:
            gen.add_episode(_episode(td, description="  "))
            valid, errors = gen.validate_feed()
            assert valid is False

    def test_validate_episode_file_not_exists_is_warning(self):
        gen = PodcastRSSGenerator(_feed())
        fp = Path("/nonexistent/ep.mp3")
        ep = PodcastEpisode(
            title="T",
            description="D",
            audio_file_path=fp,
            duration_seconds=60,
            pub_date=datetime(2024, 1, 1),
        )
        gen.add_episode(ep)
        valid, errors = gen.validate_feed()
        assert valid is True

    def test_generate_rss_xml(self):
        gen = PodcastRSSGenerator(_feed())
        with tempfile.TemporaryDirectory() as td:
            gen.add_episode(_episode(td))
            xml = gen.generate_rss_xml()
            assert "<channel>" in xml
            assert "Test Feed" in xml
            assert "Ep 1" in xml

    def test_generate_rss_xml_no_episodes(self):
        gen = PodcastRSSGenerator(_feed())
        xml = gen.generate_rss_xml()
        assert "<channel>" in xml

    def test_save_to_file_success(self):
        gen = PodcastRSSGenerator(_feed())
        with tempfile.TemporaryDirectory() as td:
            gen.add_episode(_episode(td))
            out = Path(td) / "out" / "feed.rss"
            success, msg = gen.save_to_file(out)
            assert success is True
            assert out.exists()
            content = out.read_text(encoding="utf-8")
            assert "Test Feed" in content

    def test_save_to_file_exception(self):
        gen = PodcastRSSGenerator(_feed())
        with tempfile.TemporaryDirectory() as td:
            gen.add_episode(_episode(td))
            out = Path("/dev/null/impossible/feed.rss")
            success, msg = gen.save_to_file(out)
            assert success is False
            assert "失败" in msg

    def test_itunes_categories(self):
        gen = PodcastRSSGenerator(_feed())
        with tempfile.TemporaryDirectory() as td:
            gen.add_episode(_episode(td))
            xml = gen.generate_rss_xml()
            assert "itunes:category" in xml

    def test_no_itunes_author(self):
        f = _feed(itunes_author=None, itunes_owner_name=None, itunes_owner_email=None)
        gen = PodcastRSSGenerator(f)
        with tempfile.TemporaryDirectory() as td:
            gen.add_episode(_episode(td))
            xml = gen.generate_rss_xml()
            assert "<channel>" in xml

    def test_episode_with_season_and_explicit(self):
        gen = PodcastRSSGenerator(_feed())
        with tempfile.TemporaryDirectory() as td:
            ep = _episode(td, season_number=2, episode_number=5, explicit=True)
            gen.add_episode(ep)
            xml = gen.generate_rss_xml()
            assert "itunes:season" in xml
            assert "itunes:episode" in xml
            assert "yes" in xml

    def test_episode_without_season_reassigned(self):
        """episode_number=None gets reassigned by _reassign_episode_numbers."""
        gen = PodcastRSSGenerator(_feed())
        with tempfile.TemporaryDirectory() as td:
            ep = _episode(td, season_number=None, episode_number=None)
            gen.add_episode(ep)
            assert ep.episode_number == 1  # reassigned
            xml = gen.generate_rss_xml()
            assert "itunes:episode" in xml  # reassigned

    def test_no_image(self):
        f = _feed(image_url=None)
        gen = PodcastRSSGenerator(f)
        with tempfile.TemporaryDirectory() as td:
            gen.add_episode(_episode(td))
            xml = gen.generate_rss_xml()
            assert "<channel>" in xml

    def test_no_owner(self):
        f = _feed(owner_name=None, owner_email=None)
        gen = PodcastRSSGenerator(f)
        with tempfile.TemporaryDirectory() as td:
            gen.add_episode(_episode(td))
            xml = gen.generate_rss_xml()
            assert "<channel>" in xml

    def test_no_author(self):
        f = _feed(author=None)
        gen = PodcastRSSGenerator(f)
        with tempfile.TemporaryDirectory() as td:
            gen.add_episode(_episode(td))
            xml = gen.generate_rss_xml()
            assert "<channel>" in xml

    def test_no_categories(self):
        f = _feed(categories=[])
        gen = PodcastRSSGenerator(f)
        with tempfile.TemporaryDirectory() as td:
            gen.add_episode(_episode(td))
            xml = gen.generate_rss_xml()
            assert "<channel>" in xml

    def test_no_itunes_categories(self):
        f = _feed(itunes_categories=None)
        gen = PodcastRSSGenerator(f)
        with tempfile.TemporaryDirectory() as td:
            gen.add_episode(_episode(td))
            xml = gen.generate_rss_xml()
            assert "<channel>" in xml

    def test_enclosure_length_file_exists(self):
        gen = PodcastRSSGenerator(_feed())
        with tempfile.TemporaryDirectory() as td:
            ep = _episode(td, enclosure_length=9999)
            gen.add_episode(ep)
            xml = gen.generate_rss_xml()
            assert 'length="9999"' in xml

    def test_enclosure_length_file_not_exists(self):
        gen = PodcastRSSGenerator(_feed())
        fp = Path("/nonexistent/ep.mp3")
        ep = PodcastEpisode(
            title="T",
            description="D",
            audio_file_path=fp,
            duration_seconds=60,
            pub_date=datetime(2024, 1, 1),
        )
        gen.add_episode(ep)
        xml = gen.generate_rss_xml()
        assert 'length="0"' in xml

    def test_multiple_episodes(self):
        gen = PodcastRSSGenerator(_feed())
        with tempfile.TemporaryDirectory() as td:
            for i in range(3):
                gen.add_episode(_episode(td, title=f"Ep {i+1}", episode_number=i + 1))
            xml = gen.generate_rss_xml()
            assert "Ep 1" in xml
            assert "Ep 2" in xml
            assert "Ep 3" in xml


# ---- main() function ----
class TestMain:
    def test_main_runs(self):
        from src.audiobook_studio.publish.podcast_rss_generator import main

        with patch("builtins.print"):
            main()
