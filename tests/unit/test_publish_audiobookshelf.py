"""Tests for Audiobookshelf publish module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.publish.audiobookshelf import (
    AudiobookFile,
    AudiobookMetadata,
    AudiobookshelfConfig,
    AudiobookshelfPublisher,
)


class TestAudiobookMetadata:
    """Tests for AudiobookMetadata dataclass."""

    def test_required_fields(self):
        metadata = AudiobookMetadata(
            title="Test Book",
            author="Test Author",
            narrator="Test Narrator",
            description="Test description",
        )
        assert metadata.title == "Test Book"
        assert metadata.author == "Test Author"
        assert metadata.narrator == "Test Narrator"
        assert metadata.description == "Test description"

    def test_optional_fields_defaults(self):
        metadata = AudiobookMetadata(
            title="Test Book",
            author="Test Author",
            narrator="Test Narrator",
            description="Test description",
        )
        assert metadata.language == "zh-CN"
        assert metadata.publication_year is None
        assert metadata.publisher == ""
        assert metadata.genres == []
        assert metadata.tags == []
        assert metadata.series is None
        assert metadata.series_index is None
        assert metadata.cover_image_path is None
        assert metadata.duration_seconds == 0.0
        assert metadata.bitrate_kbps == 64
        assert metadata.format == "m4b"

    def test_custom_optional_fields(self):
        metadata = AudiobookMetadata(
            title="Test Book",
            author="Test Author",
            narrator="Test Narrator",
            description="Test description",
            language="en-US",
            publication_year=2024,
            publisher="Test Publisher",
            genres=["Sci-Fi", "Fantasy"],
            tags=["test", "audiobook"],
            series="Test Series",
            series_index=1.5,
            cover_image_path=Path("/path/to/cover.jpg"),
            duration_seconds=3600.0,
            bitrate_kbps=128,
            format="mp3",
        )
        assert metadata.language == "en-US"
        assert metadata.publication_year == 2024
        assert metadata.publisher == "Test Publisher"
        assert metadata.genres == ["Sci-Fi", "Fantasy"]
        assert metadata.tags == ["test", "audiobook"]
        assert metadata.series == "Test Series"
        assert metadata.series_index == 1.5
        assert metadata.duration_seconds == 3600.0
        assert metadata.bitrate_kbps == 128
        assert metadata.format == "mp3"


class TestAudiobookFile:
    """Tests for AudiobookFile dataclass."""

    def test_audiobook_file_creation(self):
        audio_file = AudiobookFile(
            file_path=Path("/path/to/book.m4b"),
            size_bytes=1024000,
            duration_seconds=3600.0,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="abcdef123456",
        )
        assert audio_file.file_path == Path("/path/to/book.m4b")
        assert audio_file.size_bytes == 1024000
        assert audio_file.duration_seconds == 3600.0
        assert audio_file.format == "m4b"
        assert audio_file.bitrate_kbps == 64
        assert audio_file.checksum_md5 == "abcdef123456"
        assert audio_file.chapters == []

    def test_audiobook_file_with_chapters(self):
        chapters = [
            {"title": "Chapter 1", "start": 0, "end": 1800},
            {"title": "Chapter 2", "start": 1800, "end": 3600},
        ]
        audio_file = AudiobookFile(
            file_path=Path("/path/to/book.m4b"),
            size_bytes=1024000,
            duration_seconds=3600.0,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="abcdef123456",
            chapters=chapters,
        )
        assert len(audio_file.chapters) == 2
        assert audio_file.chapters[0]["title"] == "Chapter 1"


class TestAudiobookshelfConfig:
    """Tests for AudiobookshelfConfig dataclass."""

    def test_config_creation(self):
        config = AudiobookshelfConfig(
            api_url="http://localhost:8080/api",
            api_key="test_key",
            library_id="test_library",
        )
        assert config.api_url == "http://localhost:8080/api"
        assert config.api_key == "test_key"
        assert config.library_id == "test_library"
        assert config.supported_formats == ["m4b", "mp3"]
        assert config.auto_convert is True
        assert config.preferred_format == "m4b"

    def test_custom_config(self):
        config = AudiobookshelfConfig(
            api_url="https://abs.example.com/api",
            api_key="custom_key",
            library_id="custom_lib",
            supported_formats=["mp3", "wav", "flac"],
            auto_convert=False,
            preferred_format="mp3",
        )
        assert config.supported_formats == ["mp3", "wav", "flac"]
        assert config.auto_convert is False
        assert config.preferred_format == "mp3"


class TestAudiobookshelfPublisher:
    """Tests for AudiobookshelfPublisher class."""

    @pytest.fixture
    def config(self):
        return AudiobookshelfConfig(
            api_url="http://localhost:8080/api",
            api_key="test_key",
            library_id="test_library",
        )

    @pytest.fixture
    def publisher(self, config):
        return AudiobookshelfPublisher(config)

    @pytest.fixture
    def metadata(self):
        return AudiobookMetadata(
            title="Test Book",
            author="Test Author",
            narrator="Test Narrator",
            description="A test audiobook",
            publication_year=2024,
        )

    @pytest.fixture
    def audio_file(self):
        with tempfile.NamedTemporaryFile(suffix=".m4b", delete=False) as f:
            f.write(b"dummy audio data")
            f.flush()
            path = Path(f.name)

        audio_file = AudiobookFile(
            file_path=path,
            size_bytes=path.stat().st_size,
            duration_seconds=3600.0,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="abcdef1234567890abcdef1234567890",
        )
        yield audio_file
        # Cleanup
        if path.exists():
            path.unlink()

    def test_publisher_initialization(self, publisher):
        assert publisher.config.api_url == "http://localhost:8080/api"
        assert publisher.supported_formats == {"m4b", "mp3"}

    def test_validate_metadata_valid(self, publisher, metadata):
        valid, message = publisher._validate_metadata(metadata)
        assert valid is True
        assert "通过" in message

    def test_validate_metadata_missing_title(self, publisher):
        metadata = AudiobookMetadata(
            title="",
            author="Author",
            narrator="Narrator",
            description="Desc",
        )
        valid, message = publisher._validate_metadata(metadata)
        assert valid is False
        assert "标题不能为空" in message

    def test_validate_metadata_missing_author(self, publisher):
        metadata = AudiobookMetadata(
            title="Title",
            author="",
            narrator="Narrator",
            description="Desc",
        )
        valid, message = publisher._validate_metadata(metadata)
        assert valid is False
        assert "作者不能为空" in message

    def test_validate_metadata_missing_narrator(self, publisher):
        metadata = AudiobookMetadata(
            title="Title",
            author="Author",
            narrator="",
            description="Desc",
        )
        valid, message = publisher._validate_metadata(metadata)
        assert valid is False
        assert "朗读者不能为空" in message

    def test_validate_metadata_invalid_year(self, publisher):
        metadata = AudiobookMetadata(
            title="Title",
            author="Author",
            narrator="Narrator",
            description="Desc",
            publication_year=999,
        )
        valid, message = publisher._validate_metadata(metadata)
        assert valid is False
        assert "出版年份不合理" in message

        metadata.publication_year = 2101
        valid, message = publisher._validate_metadata(metadata)
        assert valid is False

    def test_validate_audio_file_valid(self, publisher, audio_file):
        valid, message = publisher._validate_audio_file(audio_file)
        assert valid is True
        assert "通过" in message

    def test_validate_audio_file_not_exists(self, publisher):
        audio_file = AudiobookFile(
            file_path=Path("/nonexistent/book.m4b"),
            size_bytes=1000,
            duration_seconds=3600.0,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="abcdef1234567890abcdef1234567890",
        )
        valid, message = publisher._validate_audio_file(audio_file)
        assert valid is False
        assert "不存在" in message

    def test_validate_audio_file_size_mismatch(self, publisher, audio_file):
        # Create a larger file than declared
        with tempfile.NamedTemporaryFile(suffix=".m4b", delete=False) as f:
            f.write(b"x" * 10000)
            f.flush()
            large_path = Path(f.name)

        audio_file_large = AudiobookFile(
            file_path=large_path,
            size_bytes=1000,  # Declared smaller than actual
            duration_seconds=3600.0,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="abcdef1234567890abcdef1234567890",
        )
        valid, message = publisher._validate_audio_file(audio_file_large)
        assert valid is False
        assert "文件大小不匹配" in message

        large_path.unlink()

    def test_validate_audio_file_format_mismatch(self, publisher, audio_file):
        audio_file.format = "mp3"  # File is .m4b but format says mp3
        valid, message = publisher._validate_audio_file(audio_file)
        assert valid is False
        assert "不匹配" in message

    def test_prepare_upload_data(self, publisher, metadata, audio_file):
        with patch("src.audiobook_studio.publish.audiobookshelf.base64") as mock_base64:
            mock_base64.b64encode.return_value.decode.return_value = "base64data"
            upload_data = publisher._prepare_upload_data(metadata, audio_file)

        assert upload_data["title"] == "Test Book"
        assert upload_data["author"] == "Test Author"
        assert upload_data["narrator"] == "Test Narrator"
        assert upload_data["description"] == "A test audiobook"
        assert upload_data["duration"] == 3600
        assert upload_data["bitrate"] == 64000  # kbps to bps
        assert upload_data["format"] == "m4b"
        assert upload_data["fileName"] == audio_file.file_path.name

    def test_prepare_upload_data_generates_default_chapter(self, publisher, metadata, audio_file):
        # Audio file without chapters but with duration
        audio_file.chapters = []
        audio_file.duration_seconds = 7200

        with patch("src.audiobook_studio.publish.audiobookshelf.base64") as mock_base64:
            mock_base64.b64encode.return_value.decode.return_value = "base64data"
            upload_data = publisher._prepare_upload_data(metadata, audio_file)

        assert len(upload_data["chapters"]) == 1
        assert upload_data["chapters"][0]["title"] == "Test Book"
        assert upload_data["chapters"][0]["start"] == 0
        assert upload_data["chapters"][0]["end"] == 7200

    def test_prepare_upload_data_uses_existing_chapters(self, publisher, metadata, audio_file):
        chapters = [
            {"title": "Chapter 1", "start": 0, "end": 1800},
            {"title": "Chapter 2", "start": 1800, "end": 3600},
        ]
        audio_file.chapters = chapters

        with patch("src.audiobook_studio.publish.audiobookshelf.base64") as mock_base64:
            mock_base64.b64encode.return_value.decode.return_value = "base64data"
            upload_data = publisher._prepare_upload_data(metadata, audio_file)

        assert upload_data["chapters"] == chapters

    def test_get_library_status(self, publisher):
        status = publisher.get_library_status()
        assert status["library_id"] == "test_library"
        assert "total_books" in status
        assert "total_duration_hours" in status
        assert "status" in status
        assert status["status"] == "online"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])