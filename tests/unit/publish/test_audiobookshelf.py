"""Tests for Audiobookshelf sync publisher module."""

import base64
import hashlib
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Set MOCK_LLM before importing the module (required for mock_mode behavior)
os.environ["MOCK_LLM"] = "true"

# Mock external dependencies that might cause import issues
_MODULE_MOCK_TARGETS = ["requests", "requests.exceptions", "urllib3", "urllib3.exceptions"]
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in _MODULE_MOCK_TARGETS}

for name in _MODULE_MOCK_TARGETS:
    sys.modules[name] = MagicMock()

from src.audiobook_studio.publish.audiobookshelf import (
    AudiobookFile,
    AudiobookMetadata,
    AudiobookshelfConfig,
    AudiobookshelfPublisher,
)


class TestAudiobookMetadata:
    """Tests for AudiobookMetadata dataclass."""

    def test_default_values(self):
        metadata = AudiobookMetadata(
            title="Test",
            author="Author",
            narrator="Narrator",
            description="Desc",
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

    def test_custom_values(self):
        metadata = AudiobookMetadata(
            title="Test",
            author="Author",
            narrator="Narrator",
            description="Desc",
            language="en-US",
            publication_year=2020,
            publisher="Publisher",
            genres=["Sci-Fi"],
            tags=["tag1"],
            series="Series",
            series_index=1.0,
            cover_image_path=Path("/cover.jpg"),
            duration_seconds=3600.0,
            bitrate_kbps=128,
            format="mp3",
        )
        assert metadata.language == "en-US"
        assert metadata.publication_year == 2020
        assert metadata.publisher == "Publisher"
        assert metadata.genres == ["Sci-Fi"]
        assert metadata.tags == ["tag1"]
        assert metadata.series == "Series"
        assert metadata.series_index == 1.0
        assert metadata.cover_image_path == Path("/cover.jpg")
        assert metadata.duration_seconds == 3600.0
        assert metadata.bitrate_kbps == 128
        assert metadata.format == "mp3"


class TestAudiobookFile:
    """Tests for AudiobookFile dataclass."""

    def test_audiobook_file_creation(self):
        file = AudiobookFile(
            file_path=Path("/audio/test.m4b"),
            size_bytes=1000000,
            duration_seconds=3600.0,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="abc123",
            chapters=[{"title": "Ch1", "start": 0, "end": 1800}],
        )
        assert file.file_path == Path("/audio/test.m4b")
        assert file.size_bytes == 1000000
        assert file.duration_seconds == 3600.0
        assert file.format == "m4b"
        assert file.bitrate_kbps == 64
        assert file.checksum_md5 == "abc123"
        assert len(file.chapters) == 1

    def test_audiobook_file_default_chapters(self):
        file = AudiobookFile(
            file_path=Path("/audio/test.m4b"),
            size_bytes=1000000,
            duration_seconds=3600.0,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="abc123",
        )
        assert file.chapters == []


class TestAudiobookshelfConfig:
    """Tests for AudiobookshelfConfig dataclass."""

    def test_default_values(self):
        config = AudiobookshelfConfig(
            api_url="http://localhost:8080",
            api_key="test_key",
            library_id="lib1",
        )
        assert config.supported_formats == ["m4b", "mp3"]
        assert config.auto_convert is True
        assert config.preferred_format == "m4b"

    def test_custom_values(self):
        config = AudiobookshelfConfig(
            api_url="http://localhost:8080",
            api_key="test_key",
            library_id="lib1",
            supported_formats=["mp3", "wav"],
            auto_convert=False,
            preferred_format="mp3",
        )
        assert config.supported_formats == ["mp3", "wav"]
        assert config.auto_convert is False
        assert config.preferred_format == "mp3"


class TestAudiobookshelfPublisher:
    """Tests for AudiobookshelfPublisher class."""

    @pytest.fixture
    def config(self):
        return AudiobookshelfConfig(
            api_url="http://localhost:8080",
            api_key="test_api_key",
            library_id="test_library",
        )

    @pytest.fixture
    def publisher(self, config):
        with patch.dict(os.environ, {"MOCK_LLM": "true"}):
            return AudiobookshelfPublisher(config)

    @pytest.fixture
    def metadata(self):
        return AudiobookMetadata(
            title="Test Book",
            author="Test Author",
            narrator="Test Narrator",
            description="Test Description",
            language="en-US",
            publication_year=2020,
            publisher="Test Publisher",
            genres=["Sci-Fi", "Fantasy"],
            tags=["tag1", "tag2"],
            series="Test Series",
            series_index=1.0,
        )

    @pytest.fixture
    def audio_file(self, tmp_path):
        # Create a temporary audio file
        audio_path = tmp_path / "test.m4b"
        audio_path.write_bytes(b"fake audio content")
        return AudiobookFile(
            file_path=audio_path,
            size_bytes=len(b"fake audio content"),
            duration_seconds=3600.0,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="abc123",
            chapters=[{"title": "Chapter 1", "start": 0, "end": 1800}],
        )

    def test_init_sets_correct_attributes(self, publisher, config):
        assert publisher.config == config
        assert publisher.supported_formats == {"m4b", "mp3"}
        assert publisher.base_url == "http://localhost:8080"
        assert publisher.mock_mode is True
        assert publisher.client is None

    def test_init_real_mode(self, config):
        with patch.dict(os.environ, {"MOCK_LLM": "false"}):
            publisher = AudiobookshelfPublisher(config)
            assert publisher.mock_mode is False
            assert publisher.client is not None
            assert publisher.client.headers["Authorization"] == "Bearer test_api_key"
            publisher.close()

    def test_close(self, publisher):
        # Mock mode has no client to close
        publisher.close()  # Should not raise

    def test_close_real_mode(self, config):
        with patch.dict(os.environ, {"MOCK_LLM": "false"}):
            publisher = AudiobookshelfPublisher(config)
            publisher.close()
            # Verify close was called on the client

    def test_validate_metadata_success(self, publisher, metadata):
        valid, message = publisher._validate_metadata(metadata)
        assert valid is True
        assert message == "元数据验证通过"

    def test_validate_metadata_empty_title(self, publisher):
        metadata = AudiobookMetadata(
            title="",
            author="Author",
            narrator="Narrator",
            description="Desc",
        )
        valid, message = publisher._validate_metadata(metadata)
        assert valid is False
        assert "标题不能为空" in message

    def test_validate_metadata_empty_author(self, publisher):
        metadata = AudiobookMetadata(
            title="Title",
            author="",
            narrator="Narrator",
            description="Desc",
        )
        valid, message = publisher._validate_metadata(metadata)
        assert valid is False
        assert "作者不能为空" in message

    def test_validate_metadata_empty_narrator(self, publisher):
        metadata = AudiobookMetadata(
            title="Title",
            author="Author",
            narrator="",
            description="Desc",
        )
        valid, message = publisher._validate_metadata(metadata)
        assert valid is False
        assert "朗读者不能为空" in message

    def test_validate_metadata_invalid_publication_year_too_low(self, publisher):
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

    def test_validate_metadata_invalid_publication_year_too_high(self, publisher):
        metadata = AudiobookMetadata(
            title="Title",
            author="Author",
            narrator="Narrator",
            description="Desc",
            publication_year=2101,
        )
        valid, message = publisher._validate_metadata(metadata)
        assert valid is False
        assert "出版年份不合理" in message

    def test_validate_metadata_valid_publication_year(self, publisher):
        metadata = AudiobookMetadata(
            title="Title",
            author="Author",
            narrator="Narrator",
            description="Desc",
            publication_year=2020,
        )
        valid, message = publisher._validate_metadata(metadata)
        assert valid is True

    def test_validate_metadata_whitespace_only(self, publisher):
        metadata = AudiobookMetadata(
            title="   ",
            author="Author",
            narrator="Narrator",
            description="Desc",
        )
        valid, message = publisher._validate_metadata(metadata)
        assert valid is False
        assert "标题不能为空" in message

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.stat")
    @patch("mimetypes.guess_type")
    def test_validate_audio_file_success(self, mock_guess, mock_stat, mock_is_file, mock_exists, publisher, audio_file):
        mock_exists.return_value = True
        mock_is_file.return_value = True
        mock_stat.return_value.st_size = audio_file.size_bytes
        mock_guess.return_value = ("audio/mp4", None)

        valid, message = publisher._validate_audio_file(audio_file)
        assert valid is True
        assert message == "音频文件验证通过"

    def test_validate_audio_file_not_exists(self, publisher):
        audio_file = AudiobookFile(
            file_path=Path("/nonexistent/file.m4b"),
            size_bytes=1000,
            duration_seconds=3600.0,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="abc123",
        )
        valid, message = publisher._validate_audio_file(audio_file)
        assert valid is False
        assert "音频文件不存在" in message

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_file")
    def test_validate_audio_file_size_mismatch(self, mock_is_file, mock_exists, publisher, tmp_path):
        mock_exists.return_value = True
        mock_is_file.return_value = True
        audio_path = tmp_path / "test.m4b"
        audio_path.write_bytes(b"different content")
        audio_file = AudiobookFile(
            file_path=audio_path,
            size_bytes=9999,  # Wrong size
            duration_seconds=3600.0,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="abc123",
        )
        valid, message = publisher._validate_audio_file(audio_file)
        assert valid is False
        assert "文件大小不匹配" in message

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.stat")
    def test_validate_audio_file_extension_mismatch(self, mock_stat, mock_is_file, mock_exists, publisher, tmp_path):
        mock_exists.return_value = True
        mock_is_file.return_value = True
        audio_path = tmp_path / "test.mp3"
        audio_path.write_bytes(b"fake audio")
        mock_stat.return_value.st_size = len(b"fake audio")
        audio_file = AudiobookFile(
            file_path=audio_path,
            size_bytes=len(b"fake audio"),  # Correct size to pass size check first
            duration_seconds=3600.0,
            format="m4b",  # Mismatch: file is .mp3 but format is m4b
            bitrate_kbps=64,
            checksum_md5="abc123",
        )
        valid, message = publisher._validate_audio_file(audio_file)
        assert valid is False
        assert "文件扩展名" in message
        assert "不匹配" in message

    @patch("pathlib.Path.exists")
    def test_validate_audio_file_not_a_file(self, mock_exists, publisher, tmp_path):
        mock_exists.return_value = True
        # Path is a directory, not a file
        audio_file = AudiobookFile(
            file_path=tmp_path,
            size_bytes=1000,
            duration_seconds=3600.0,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="abc123",
        )
        # We need to mock is_file to return False
        with patch("pathlib.Path.is_file", return_value=False):
            valid, message = publisher._validate_audio_file(audio_file)
            assert valid is False
            assert "路径不是文件" in message

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.stat")
    @patch("mimetypes.guess_type")
    def test_validate_audio_file_invalid_mime_type(self, mock_guess, mock_stat, mock_is_file, mock_exists, publisher, tmp_path):
        mock_exists.return_value = True
        mock_is_file.return_value = True
        audio_path = tmp_path / "test.m4b"
        audio_path.write_bytes(b"fake audio")
        mock_stat.return_value.st_size = len(b"fake audio")
        mock_guess.return_value = ("video/mp4", None)  # Wrong MIME type
        audio_file = AudiobookFile(
            file_path=audio_path,
            size_bytes=len(b"fake audio"),
            duration_seconds=3600.0,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="abc123",
        )
        valid, message = publisher._validate_audio_file(audio_file)
        assert valid is False
        assert "MIME 类型不匹配" in message

    def test_prepare_upload_data_basic(self, publisher, metadata, audio_file):
        upload_data = publisher._prepare_upload_data(metadata, audio_file)
        assert upload_data["title"] == "Test Book"
        assert upload_data["author"] == "Test Author"
        assert upload_data["narrator"] == "Test Narrator"
        assert upload_data["description"] == "Test Description"
        assert upload_data["language"] == "en-US"
        assert upload_data["year"] == 2020
        assert upload_data["publisher"] == "Test Publisher"
        assert upload_data["genres"] == ["Sci-Fi", "Fantasy"]
        assert upload_data["tags"] == ["tag1", "tag2"]
        assert upload_data["series"] == "Test Series"
        assert upload_data["seriesIndex"] == 1.0
        assert upload_data["fileName"] == audio_file.file_path.name
        assert upload_data["size"] == audio_file.size_bytes
        assert upload_data["duration"] == int(audio_file.duration_seconds)
        assert upload_data["bitrate"] == audio_file.bitrate_kbps * 1000
        assert upload_data["format"] == "m4b"
        assert upload_data["chapters"] == audio_file.chapters
        assert upload_data["coverImage"] is None

    def test_prepare_upload_data_with_cover_image(self, publisher, metadata, audio_file, tmp_path):
        cover_path = tmp_path / "cover.jpg"
        cover_path.write_bytes(b"fake image")
        metadata.cover_image_path = cover_path
        upload_data = publisher._prepare_upload_data(metadata, audio_file)
        assert upload_data["coverImage"] is not None
        # Verify it's valid base64
        decoded = base64.b64decode(upload_data["coverImage"])
        assert decoded == b"fake image"

    def test_prepare_upload_data_cover_image_read_failure(self, publisher, metadata, audio_file, tmp_path):
        cover_path = tmp_path / "cover.jpg"
        cover_path.write_bytes(b"fake image")
        metadata.cover_image_path = cover_path
        # Remove the file after setting to simulate read failure
        cover_path.unlink()
        upload_data = publisher._prepare_upload_data(metadata, audio_file)
        assert upload_data["coverImage"] is None

    def test_prepare_upload_data_default_chapter(self, publisher, metadata, audio_file):
        audio_file.chapters = []
        upload_data = publisher._prepare_upload_data(metadata, audio_file)
        assert len(upload_data["chapters"]) == 1
        assert upload_data["chapters"][0]["title"] == metadata.title
        assert upload_data["chapters"][0]["start"] == 0
        assert upload_data["chapters"][0]["end"] == int(audio_file.duration_seconds)

    def test_prepare_upload_data_without_chapters_when_duration_zero(self, publisher, audio_file):
        audio_file.chapters = []
        audio_file.duration_seconds = 0
        metadata = AudiobookMetadata(
            title="Test Book",
            author="Test Author",
            narrator="Test Narrator",
            description="Test Description",
        )
        upload_data = publisher._prepare_upload_data(metadata, audio_file)
        assert upload_data["chapters"] == []

    def test_prepare_audiobook_success(self, publisher, metadata, audio_file):
        valid, message, upload_data = publisher._prepare_audiobook(metadata, audio_file)
        assert valid is True
        assert message == "有声书准备成功"
        assert upload_data is not None
        assert upload_data["title"] == metadata.title

    def test_prepare_audiobook_invalid_metadata(self, publisher, metadata, audio_file):
        metadata.title = ""
        valid, message, upload_data = publisher._prepare_audiobook(metadata, audio_file)
        assert valid is False
        assert "标题不能为空" in message
        assert upload_data is None

    def test_prepare_audiobook_invalid_audio_file(self, publisher, metadata, audio_file):
        audio_file.size_bytes = 9999  # Mismatch
        valid, message, upload_data = publisher._prepare_audiobook(metadata, audio_file)
        assert valid is False
        assert "文件大小不匹配" in message
        assert upload_data is None

    def test_prepare_audiobook_unsupported_format_no_convert(self, publisher, metadata, audio_file):
        publisher.config.auto_convert = False
        audio_file.format = "wav"
        valid, message, upload_data = publisher._prepare_audiobook(metadata, audio_file)
        assert valid is False
        assert "不支持的格式" in message
        assert "wav" in message
        assert upload_data is None

    def test_prepare_audiobook_unsupported_format_with_convert(self, publisher, metadata, audio_file):
        publisher.config.auto_convert = True
        audio_file.format = "wav"
        valid, message, upload_data = publisher._prepare_audiobook(metadata, audio_file)
        assert valid is False
        assert "自动转换功能待实现" in message
        assert upload_data is None

    def test_mock_api_call_structure(self, publisher):
        upload_data = {
            "title": "Test Book",
            "author": "Test Author",
            "narrator": "Test Narrator",
            "format": "mp3",
        }
        result = publisher._mock_api_call(upload_data)
        # Check structure
        assert "success" in result
        assert "book_id" in result
        assert "message" in result
        # In current implementation, it always succeeds
        assert result["success"] is True
        assert result["message"] == "书籍已成功导入"
        assert "import_id" in result
        assert "book" in result
        assert result["book"]["id"] == result["book_id"]
        assert result["book"]["title"] == "Test Book"

    def test_mock_api_call_deterministic_book_id(self, publisher):
        upload_data = {"title": "Book", "author": "Author"}
        result1 = publisher._mock_api_call(upload_data)
        result2 = publisher._mock_api_call(upload_data)
        # Same input should produce same book_id (deterministic)
        assert result1["book_id"] == result2["book_id"]
        # Verify it's a SHA256 hash truncated to 12 chars
        expected = hashlib.sha256(b"book|author", usedforsecurity=False).hexdigest()[:12]
        assert result1["book_id"] == expected

    def test_get_mime_type(self, publisher):
        assert publisher._get_mime_type(Path("test.m4b")) == "audio/mp4"
        assert publisher._get_mime_type(Path("test.mp3")) == "audio/mpeg"
        assert publisher._get_mime_type(Path("test.wav")) == "audio/wav"
        assert publisher._get_mime_type(Path("test.flac")) == "audio/flac"
        assert publisher._get_mime_type(Path("test.ogg")) == "audio/ogg"
        assert publisher._get_mime_type(Path("test.aac")) == "audio/aac"
        assert publisher._get_mime_type(Path("test.unknown")) == "application/octet-stream"
        assert publisher._get_mime_type(Path("test.M4B")) == "audio/mp4"  # Case insensitive

    def test_publish_audiobook_valid_mock(self, publisher, metadata, audio_file):
        publisher.mock_mode = True
        success, message, response = publisher.publish_audiobook(metadata, audio_file)
        assert response is not None
        assert "success" in response
        assert "book_id" in response

    def test_publish_audiobook_invalid_metadata(self, publisher, metadata, audio_file):
        metadata.title = ""
        success, message, response = publisher.publish_audiobook(metadata, audio_file)
        assert success is False
        assert "标题不能为空" in message
        assert response is None

    def test_publish_audiobook_invalid_format(self, publisher, metadata, audio_file):
        audio_file.format = "wav"
        publisher.config.auto_convert = False
        success, message, response = publisher.publish_audiobook(metadata, audio_file)
        assert success is False
        assert "不支持的格式" in message
        assert response is None

    def test_publish_audiobook_format_convert_not_implemented(self, publisher, metadata, audio_file):
        audio_file.format = "wav"
        publisher.config.auto_convert = True
        success, message, response = publisher.publish_audiobook(metadata, audio_file)
        assert success is False
        assert "自动转换功能待实现" in message
        assert response is None


class TestAudiobookshelfPublisherRealMode:
    """Tests for AudiobookshelfPublisher in real mode (mocked HTTP)."""

    @pytest.fixture
    def config(self):
        return AudiobookshelfConfig(
            api_url="http://localhost:8080",
            api_key="test_api_key",
            library_id="test_library",
        )

    @pytest.fixture
    def publisher(self, config):
        with patch.dict(os.environ, {"MOCK_LLM": "false"}):
            return AudiobookshelfPublisher(config)

    @pytest.fixture
    def metadata(self):
        return AudiobookMetadata(
            title="Test Book",
            author="Test Author",
            narrator="Test Narrator",
            description="Test Description",
            language="en-US",
            publication_year=2020,
            publisher="Test Publisher",
            genres=["Sci-Fi", "Fantasy"],
            tags=["tag1", "tag2"],
            series="Test Series",
            series_index=1.0,
        )

    @pytest.fixture
    def audio_file(self, tmp_path):
        audio_path = tmp_path / "test.m4b"
        audio_path.write_bytes(b"fake audio content")
        return AudiobookFile(
            file_path=audio_path,
            size_bytes=len(b"fake audio content"),
            duration_seconds=3600.0,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="abc123",
            chapters=[{"title": "Chapter 1", "start": 0, "end": 1800}],
        )

    @pytest.fixture
    def mock_client(self):
        with patch("src.audiobook_studio.publish.audiobookshelf.httpx.Client") as mock:
            client_instance = MagicMock()
            mock.return_value = client_instance
            yield client_instance

    def test_real_api_call_library_not_found(self, publisher, metadata, audio_file, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client.get.return_value = mock_response

        upload_data = {"title": "Test", "author": "Author"}
        result = publisher._real_api_call(upload_data, audio_file)
        assert result["success"] is False
        assert "库 test_library 不存在" in result["message"]

    def test_real_api_call_library_access_error(self, publisher, metadata, audio_file, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_client.get.return_value = mock_response

        upload_data = {"title": "Test", "author": "Author"}
        result = publisher._real_api_call(upload_data, audio_file)
        assert result["success"] is False
        assert "无法访问库" in result["message"]
        assert "500" in result["message"]

    def test_real_api_call_library_no_folders(self, publisher, metadata, audio_file, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"folders": []}
        mock_client.get.return_value = mock_response

        upload_data = {"title": "Test", "author": "Author"}
        result = publisher._real_api_call(upload_data, audio_file)
        assert result["success"] is False
        assert "没有配置任何文件夹" in result["message"]

    def test_real_api_call_library_has_folders(self, publisher, metadata, audio_file, mock_client):
        # The real API call does multiple requests, so we need to mock them in order
        mock_lib_response = MagicMock()
        mock_lib_response.status_code = 200
        mock_lib_response.json.return_value = {"folders": [{"id": "folder1"}]}

        mock_upload_response = MagicMock()
        mock_upload_response.status_code = 200
        mock_upload_response.json.return_value = {}

        mock_scan_response = MagicMock()
        mock_scan_response.status_code = 200

        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = []

        mock_patch_response = MagicMock()
        mock_patch_response.status_code = 200

        mock_cover_response = MagicMock()
        mock_cover_response.status_code = 200

        # Setup side effects for multiple calls
        mock_client.get.side_effect = [mock_lib_response, mock_search_response]
        mock_client.post.side_effect = [mock_upload_response, mock_scan_response, mock_cover_response]
        mock_client.patch.return_value = mock_patch_response

        upload_data = {
            "title": "Test Book",
            "author": "Test Author",
            "description": "Desc",
            "year": 2020,
            "publisher": "Pub",
            "genres": ["Sci-Fi"],
            "tags": ["tag1"],
            "language": "en-US",
            "series": "Series",
            "seriesIndex": 1.0,
            "chapters": [{"title": "Ch1", "start": 0, "end": 100}],
        }
        result = publisher._real_api_call(upload_data, audio_file)
        assert result["success"] is True
        assert result["uploaded_files"] == 1

    def test_real_api_call_upload_failure_remote(self, publisher, metadata, audio_file, mock_client):
        mock_lib_response = MagicMock()
        mock_lib_response.status_code = 200
        mock_lib_response.json.return_value = {"folders": [{"id": "folder1"}]}

        mock_upload_response = MagicMock()
        mock_upload_response.status_code = 500
        mock_upload_response.text = "Upload failed"

        mock_client.get.return_value = mock_lib_response
        mock_client.post.return_value = mock_upload_response

        upload_data = {"title": "Test", "author": "Author"}
        result = publisher._real_api_call(upload_data, audio_file)
        assert result["success"] is False
        assert "所有文件上传失败" in result["message"]

    def test_real_api_call_local_upload(self, publisher, metadata, audio_file, mock_client, tmp_path):
        publisher.config.base_path = str(tmp_path)

        mock_lib_response = MagicMock()
        mock_lib_response.status_code = 200
        mock_lib_response.json.return_value = {"folders": [{"id": "folder1"}]}

        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = []

        mock_client.get.side_effect = [mock_lib_response, mock_search_response]

        upload_data = {"title": "Test Book", "author": "Test Author"}
        result = publisher._real_api_call(upload_data, audio_file)
        assert result["success"] is True
        assert result["upload_results"][0]["success"] is True
        expected_path = tmp_path / "Test Author" / "Test Book" / audio_file.file_path.name
        assert expected_path.exists()

    def test_real_api_call_local_upload_dir_creation_failure(self, publisher, metadata, audio_file, mock_client, tmp_path):
        publisher.config.base_path = "/nonexistent/path"  # Cannot create

        mock_lib_response = MagicMock()
        mock_lib_response.status_code = 200
        mock_lib_response.json.return_value = {"folders": [{"id": "folder1"}]}

        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = []

        mock_client.get.side_effect = [mock_lib_response, mock_search_response]

        upload_data = {"title": "Test Book", "author": "Test Author"}
        result = publisher._real_api_call(upload_data, audio_file)
        assert result["success"] is False
        assert result["upload_results"][0]["success"] is False

    def test_real_api_call_with_cover_image(self, publisher, metadata, audio_file, mock_client, tmp_path):
        mock_lib_response = MagicMock()
        mock_lib_response.status_code = 200
        mock_lib_response.json.return_value = {"folders": [{"id": "folder1"}]}

        mock_upload_response = MagicMock()
        mock_upload_response.status_code = 200
        mock_upload_response.json.return_value = {}

        mock_scan_response = MagicMock()
        mock_scan_response.status_code = 200

        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = [{"id": "item1", "media": {"metadata": {"title": "Test Book"}}}]

        mock_patch_response = MagicMock()
        mock_patch_response.status_code = 200

        mock_cover_response = MagicMock()
        mock_cover_response.status_code = 200

        mock_client.get.side_effect = [mock_lib_response, mock_search_response]
        mock_client.post.side_effect = [mock_upload_response, mock_scan_response, mock_cover_response]
        mock_client.patch.return_value = mock_patch_response

        upload_data = {
            "title": "Test Book",
            "author": "Test Author",
            "coverImage": base64.b64encode(b"fake cover").decode(),
        }
        result = publisher._real_api_call(upload_data, audio_file)
        assert result["success"] is True

    def test_real_api_call_search_finds_item(self, publisher, metadata, audio_file, mock_client):
        mock_lib_response = MagicMock()
        mock_lib_response.status_code = 200
        mock_lib_response.json.return_value = {"folders": [{"id": "folder1"}]}

        mock_upload_response = MagicMock()
        mock_upload_response.status_code = 200

        mock_scan_response = MagicMock()
        mock_scan_response.status_code = 200

        # First search returns empty, second search finds the item
        mock_search_response1 = MagicMock()
        mock_search_response1.status_code = 200
        mock_search_response1.json.return_value = []

        mock_search_response2 = MagicMock()
        mock_search_response2.status_code = 200
        mock_search_response2.json.return_value = [
            {"id": "item1", "media": {"metadata": {"title": "Test Book"}}}
        ]

        mock_patch_response = MagicMock()
        mock_patch_response.status_code = 200

        mock_client.get.side_effect = [
            mock_lib_response,
            mock_search_response1,
            mock_search_response2,
        ]
        mock_client.post.side_effect = [mock_upload_response, mock_scan_response]
        mock_client.patch.return_value = mock_patch_response

        upload_data = {"title": "Test Book", "author": "Test Author"}
        result = publisher._real_api_call(upload_data, audio_file)
        assert result["success"] is True
        assert result["item_id"] == "item1"

    def test_real_api_call_search_timeout(self, publisher, metadata, audio_file, mock_client):
        mock_lib_response = MagicMock()
        mock_lib_response.status_code = 200
        mock_lib_response.json.return_value = {"folders": [{"id": "folder1"}]}

        mock_upload_response = MagicMock()
        mock_upload_response.status_code = 200

        mock_scan_response = MagicMock()
        mock_scan_response.status_code = 200

        # All searches return empty (timeout)
        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = []

        mock_client.get.side_effect = [mock_lib_response] + [mock_search_response] * 10
        mock_client.post.side_effect = [mock_upload_response, mock_scan_response]

        upload_data = {"title": "Test Book", "author": "Test Author"}
        result = publisher._real_api_call(upload_data, audio_file)
        assert result["success"] is True
        assert result["item_id"] is None  # Not found within retries
        assert "未能确认项目 ID" in result["message"]

    def test_real_api_call_metadata_update_failure(self, publisher, metadata, audio_file, mock_client):
        mock_lib_response = MagicMock()
        mock_lib_response.status_code = 200
        mock_lib_response.json.return_value = {"folders": [{"id": "folder1"}]}

        mock_upload_response = MagicMock()
        mock_upload_response.status_code = 200

        mock_scan_response = MagicMock()
        mock_scan_response.status_code = 200

        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = [
            {"id": "item1", "media": {"metadata": {"title": "Test Book"}}}
        ]

        mock_patch_response = MagicMock()
        mock_patch_response.status_code = 500
        mock_patch_response.text = "Failed to update"

        mock_client.get.side_effect = [mock_lib_response, mock_search_response]
        mock_client.post.side_effect = [mock_upload_response, mock_scan_response]
        mock_client.patch.return_value = mock_patch_response

        upload_data = {"title": "Test Book", "author": "Test Author"}
        result = publisher._real_api_call(upload_data, audio_file)
        # Still succeeds even if metadata update fails
        assert result["success"] is True
        assert result["item_id"] == "item1"

    def test_real_api_call_library_get_exception(self, publisher, metadata, audio_file, mock_client):
        mock_client.get.side_effect = Exception("Connection refused")

        upload_data = {"title": "Test", "author": "Author"}
        result = publisher._real_api_call(upload_data, audio_file)
        assert result["success"] is False
        assert "获取库信息失败" in result["message"]

    def test_real_api_call_no_audio_files(self, publisher, metadata, audio_file, mock_client):
        audio_file.file_path = Path("/nonexistent/file.m4b")

        mock_lib_response = MagicMock()
        mock_lib_response.status_code = 200
        mock_lib_response.json.return_value = {"folders": [{"id": "folder1"}]}

        mock_client.get.return_value = mock_lib_response

        upload_data = {"title": "Test", "author": "Author"}
        result = publisher._real_api_call(upload_data, audio_file)
        assert result["success"] is False
        assert "未找到音频文件" in result["message"]

    def test_get_library_status_online(self, publisher, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"mediaCount": 10, "duration": 7200000}
        mock_client.get.return_value = mock_response

        result = publisher.get_library_status()
        assert result["library_id"] == "test_library"
        assert result["total_books"] == 10
        assert result["total_duration_hours"] == 2.0  # 7200000 / 3600
        assert result["status"] == "online"
        assert "last_updated" in result
        assert "error" not in result

    def test_get_library_status_offline_on_exception(self, publisher, mock_client):
        mock_client.get.side_effect = Exception("Connection failed")

        result = publisher.get_library_status()
        assert result["library_id"] == "test_library"
        assert result["total_books"] == 0
        assert result["status"] == "offline"
        assert "无法连接到 Audiobookshelf" in result.get("error", "")

    def test_get_library_status_non_200(self, publisher, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client.get.return_value = mock_response

        result = publisher.get_library_status()
        assert result["status"] == "offline"
        assert result["total_books"] == 0


def tearDownModule():
    """Restore third-party sys.modules entries mocked by this suite."""
    for name in _MODULE_MOCK_TARGETS:
        original = _ORIGINAL_MODULES.get(name)
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


if __name__ == "__main__":
    pytest.main([__file__, "-v"])