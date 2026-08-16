"""Tests for Audiobookshelf integration module."""

import base64
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.audiobook_studio.publish.audiobookshelf_integration import (
    AudiobookFile,
    AudiobookMetadata,
    AudiobookshelfConfig,
    AudiobookshelfIntegrator,
)


class TestAudiobookMetadata:
    """Tests for AudiobookMetadata dataclass."""

    def test_default_values(self):
        metadata = AudiobookMetadata(title="Test", author="Author", narrator="Narrator", description="Desc")
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


class TestAudiobookshelfConfig:
    """Tests for AudiobookshelfConfig dataclass."""

    def test_default_values(self):
        config = AudiobookshelfConfig(
            api_url="http://localhost:8080", api_key="test_key", library_id="lib1"
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


class TestAudiobookshelfIntegrator:
    """Tests for AudiobookshelfIntegrator class."""

    @pytest.fixture
    def config(self):
        return AudiobookshelfConfig(
            api_url="http://localhost:8080", api_key="test_api_key", library_id="test_library"
        )

    @pytest.fixture
    def integrator(self, config):
        return AudiobookshelfIntegrator(config)

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

    def test_init_sets_correct_attributes(self, integrator, config):
        assert integrator.config == config
        assert integrator.supported_formats == {"m4b", "mp3"}
        assert integrator.base_url == "http://localhost:8080"
        assert integrator.client is not None
        assert "Authorization" in integrator.client.headers
        assert integrator.client.headers["Authorization"] == "Bearer test_api_key"

    @pytest.mark.asyncio
    async def test_close_calls_client_aclose(self, integrator):
        integrator.client.aclose = AsyncMock()
        await integrator.close()
        integrator.client.aclose.assert_called_once()

    def test_validate_metadata_success(self, integrator, metadata):
        valid, message = integrator._validate_metadata(metadata)
        assert valid is True
        assert message == "元数据验证通过"

    def test_validate_metadata_empty_title(self, integrator):
        metadata = AudiobookMetadata(title="", author="Author", narrator="Narrator", description="Desc")
        valid, message = integrator._validate_metadata(metadata)
        assert valid is False
        assert "标题不能为空" in message

    def test_validate_metadata_empty_author(self, integrator):
        metadata = AudiobookMetadata(title="Title", author="", narrator="Narrator", description="Desc")
        valid, message = integrator._validate_metadata(metadata)
        assert valid is False
        assert "作者不能为空" in message

    def test_validate_metadata_empty_narrator(self, integrator):
        metadata = AudiobookMetadata(title="Title", author="Author", narrator="", description="Desc")
        valid, message = integrator._validate_metadata(metadata)
        assert valid is False
        assert "朗读者不能为空" in message

    def test_validate_metadata_invalid_publication_year_too_low(self, integrator):
        metadata = AudiobookMetadata(
            title="Title", author="Author", narrator="Narrator", description="Desc", publication_year=999
        )
        valid, message = integrator._validate_metadata(metadata)
        assert valid is False
        assert "出版年份不合理" in message

    def test_validate_metadata_invalid_publication_year_too_high(self, integrator):
        metadata = AudiobookMetadata(
            title="Title", author="Author", narrator="Narrator", description="Desc", publication_year=2101
        )
        valid, message = integrator._validate_metadata(metadata)
        assert valid is False
        assert "出版年份不合理" in message

    def test_validate_metadata_valid_publication_year(self, integrator):
        metadata = AudiobookMetadata(
            title="Title", author="Author", narrator="Narrator", description="Desc", publication_year=2020
        )
        valid, message = integrator._validate_metadata(metadata)
        assert valid is True

    def test_validate_audio_file_success(self, integrator, audio_file):
        valid, message = integrator._validate_audio_file(audio_file)
        assert valid is True
        assert message == "音频文件验证通过"

    def test_validate_audio_file_not_exists(self, integrator):
        audio_file = AudiobookFile(
            file_path=Path("/nonexistent/file.m4b"),
            size_bytes=1000,
            duration_seconds=3600.0,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="abc123",
        )
        valid, message = integrator._validate_audio_file(audio_file)
        assert valid is False
        assert "音频文件不存在" in message

    def test_validate_audio_file_size_mismatch(self, integrator, tmp_path):
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
        valid, message = integrator._validate_audio_file(audio_file)
        assert valid is False
        assert "文件大小不匹配" in message

    def test_validate_audio_file_extension_mismatch(self, integrator, tmp_path):
        audio_path = tmp_path / "test.mp3"
        audio_path.write_bytes(b"fake audio")
        audio_file = AudiobookFile(
            file_path=audio_path,
            size_bytes=len(b"fake audio"),
            duration_seconds=3600.0,
            format="m4b",  # Mismatch: file is .mp3 but format is m4b
            bitrate_kbps=64,
            checksum_md5="abc123",
        )
        valid, message = integrator._validate_audio_file(audio_file)
        assert valid is False
        assert "文件扩展名" in message
        assert "不匹配" in message

    def test_validate_audio_file_not_a_file(self, integrator, tmp_path):
        audio_file = AudiobookFile(
            file_path=tmp_path,
            size_bytes=1000,
            duration_seconds=3600.0,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="abc123",
        )
        valid, message = integrator._validate_audio_file(audio_file)
        assert valid is False
        assert "路径不是文件" in message

    def test_prepare_upload_data_basic(self, integrator, metadata, audio_file):
        upload_data = integrator._prepare_upload_data(metadata, audio_file)
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

    def test_prepare_upload_data_with_cover_image(self, integrator, metadata, audio_file, tmp_path):
        cover_path = tmp_path / "cover.jpg"
        cover_path.write_bytes(b"fake image")
        metadata.cover_image_path = cover_path
        upload_data = integrator._prepare_upload_data(metadata, audio_file)
        assert upload_data["coverImage"] is not None
        # Verify it's valid base64
        decoded = base64.b64decode(upload_data["coverImage"])
        assert decoded == b"fake image"

    def test_prepare_upload_data_default_chapter(self, integrator, metadata, audio_file):
        audio_file.chapters = []
        upload_data = integrator._prepare_upload_data(metadata, audio_file)
        assert len(upload_data["chapters"]) == 1
        assert upload_data["chapters"][0]["title"] == metadata.title
        assert upload_data["chapters"][0]["start"] == 0
        assert upload_data["chapters"][0]["end"] == int(audio_file.duration_seconds)

    @pytest.mark.asyncio
    async def test_prepare_audiobook_success(self, integrator, metadata, audio_file):
        valid, message, upload_data = await integrator.prepare_audiobook(metadata, audio_file)
        assert valid is True
        assert message == "有声书准备成功"
        assert upload_data is not None
        assert upload_data["title"] == metadata.title

    @pytest.mark.asyncio
    async def test_prepare_audiobook_invalid_metadata(self, integrator, metadata, audio_file):
        metadata.title = ""
        valid, message, upload_data = await integrator.prepare_audiobook(metadata, audio_file)
        assert valid is False
        assert "标题不能为空" in message
        assert upload_data is None

    @pytest.mark.asyncio
    async def test_prepare_audiobook_invalid_audio_file(self, integrator, metadata, audio_file):
        audio_file.size_bytes = 9999  # Mismatch
        valid, message, upload_data = await integrator.prepare_audiobook(metadata, audio_file)
        assert valid is False
        assert "文件大小不匹配" in message
        assert upload_data is None

    @pytest.mark.asyncio
    async def test_prepare_audiobook_unsupported_format_no_convert(self, integrator, metadata, audio_file):
        integrator.config.auto_convert = False
        audio_file.format = "wav"
        audio_file.file_path = Path(str(audio_file.file_path).replace(".m4b", ".wav"))
        valid, message, upload_data = await integrator.prepare_audiobook(metadata, audio_file)
        assert valid is False
        assert "不支持的格式" in message
        assert "wav" in message

    @pytest.mark.asyncio
    async def test_prepare_audiobook_unsupported_format_with_convert(self, integrator, metadata, audio_file):
        integrator.config.auto_convert = True
        audio_file.format = "wav"
        audio_file.file_path = Path(str(audio_file.file_path).replace(".m4b", ".wav"))
        valid, message, upload_data = await integrator.prepare_audiobook(metadata, audio_file)
        assert valid is False
        assert "自动转换功能待实现" in message

    @pytest.mark.asyncio
    async def test_publish_to_audiobookshelf_prepare_fails(self, integrator, metadata, audio_file):
        metadata.title = ""
        result = await integrator.publish_to_audiobookshelf(metadata, audio_file)
        assert result[0] is False
        assert "标题不能为空" in result[1]
        assert result[2] is None

    @pytest.mark.asyncio
    async def test_real_api_call_library_not_found(self, integrator, metadata, audio_file):
        upload_data = {"title": "Test", "author": "Author"}
        mock_response = MagicMock()
        mock_response.status_code = 404
        integrator.client.get = AsyncMock(return_value=mock_response)
        result = await integrator._real_api_call(upload_data, audio_file)
        assert result["success"] is False
        assert "库 test_library 不存在" in result["message"]

    @pytest.mark.asyncio
    async def test_real_api_call_library_access_error(self, integrator, metadata, audio_file):
        upload_data = {"title": "Test", "author": "Author"}
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        integrator.client.get = AsyncMock(return_value=mock_response)
        result = await integrator._real_api_call(upload_data, audio_file)
        assert result["success"] is False
        assert "无法访问库" in result["message"]

    @pytest.mark.asyncio
    async def test_real_api_call_library_no_folders(self, integrator, metadata, audio_file):
        upload_data = {"title": "Test", "author": "Author"}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"folders": []}
        integrator.client.get = AsyncMock(return_value=mock_response)
        result = await integrator._real_api_call(upload_data, audio_file)
        assert result["success"] is False
        assert "没有配置任何文件夹" in result["message"]

    @pytest.mark.asyncio
    async def test_real_api_call_upload_success_remote(self, integrator, metadata, audio_file):
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

        integrator.client.get = AsyncMock(side_effect=[mock_lib_response, mock_search_response])
        integrator.client.post = AsyncMock(side_effect=[mock_upload_response, mock_scan_response, mock_cover_response])
        integrator.client.patch = AsyncMock(return_value=mock_patch_response)

        result = await integrator._real_api_call(upload_data, audio_file)
        assert result["success"] is True
        assert result["uploaded_files"] == 1

    @pytest.mark.asyncio
    async def test_real_api_call_upload_failure_remote(self, integrator, metadata, audio_file):
        upload_data = {"title": "Test", "author": "Author"}
        mock_lib_response = MagicMock()
        mock_lib_response.status_code = 200
        mock_lib_response.json.return_value = {"folders": [{"id": "folder1"}]}

        mock_upload_response = MagicMock()
        mock_upload_response.status_code = 500
        mock_upload_response.text = "Upload failed"

        integrator.client.get = AsyncMock(return_value=mock_lib_response)
        integrator.client.post = AsyncMock(return_value=mock_upload_response)

        result = await integrator._real_api_call(upload_data, audio_file)
        assert result["success"] is False
        assert "所有文件上传失败" in result["message"]

    @pytest.mark.asyncio
    async def test_real_api_call_local_upload(self, integrator, metadata, audio_file, tmp_path):
        upload_data = {"title": "Test Book", "author": "Test Author"}
        integrator.config.base_path = str(tmp_path)

        mock_lib_response = MagicMock()
        mock_lib_response.status_code = 200
        mock_lib_response.json.return_value = {"folders": [{"id": "folder1"}]}

        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = []

        integrator.client.get = AsyncMock(side_effect=[mock_lib_response, mock_search_response])

        result = await integrator._real_api_call(upload_data, audio_file)
        assert result["success"] is True
        assert result["upload_results"][0]["success"] is True
        assert (tmp_path / "Test Author" / "Test Book" / audio_file.file_path.name).exists()

    def test_get_mime_type(self, integrator):
        assert integrator._get_mime_type(Path("test.m4b")) == "audio/mp4"
        assert integrator._get_mime_type(Path("test.mp3")) == "audio/mpeg"
        assert integrator._get_mime_type(Path("test.wav")) == "audio/wav"
        assert integrator._get_mime_type(Path("test.flac")) == "audio/flac"
        assert integrator._get_mime_type(Path("test.ogg")) == "audio/ogg"
        assert integrator._get_mime_type(Path("test.aac")) == "audio/aac"
        assert integrator._get_mime_type(Path("test.unknown")) == "application/octet-stream"

    @pytest.mark.asyncio
    async def test_get_library_status_online(self, integrator):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"mediaCount": 10, "duration": 7200000}
        integrator.client.get = AsyncMock(return_value=mock_response)

        result = await integrator.get_library_status()
        assert result["library_id"] == "test_library"
        assert result["total_books"] == 10
        assert result["total_duration_hours"] == 2.0  # 7200000 / 3600
        assert result["status"] == "online"
        assert "last_updated" in result

    @pytest.mark.asyncio
    async def test_get_library_status_offline(self, integrator):
        integrator.client.get = AsyncMock(side_effect=httpx.RequestError("Connection failed"))

        result = await integrator.get_library_status()
        assert result["library_id"] == "test_library"
        assert result["total_books"] == 0
        assert result["status"] == "offline"
        assert "无法连接到 Audiobookshelf" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_get_library_status_non_200(self, integrator):
        mock_response = MagicMock()
        mock_response.status_code = 404
        integrator.client.get = AsyncMock(return_value=mock_response)

        result = await integrator.get_library_status()
        assert result["status"] == "offline"

    @pytest.mark.asyncio
    async def test_publish_to_audiobookshelf_network_error(self, integrator, metadata, audio_file):
        integrator.client.get = AsyncMock(side_effect=httpx.NetworkError("Network error"))

        result = await integrator.publish_to_audiobookshelf(metadata, audio_file)
        assert result[0] is False
        assert "发布过程中出现网络错误" in result[1]
        assert result[2] is None


class TestAudiobookshelfAPIClientStub:
    """Tests for the compatibility stub class."""

    def test_stub_initialization(self):
        client = AudiobookshelfAPIClient("url", "key", "lib")
        assert client is not None

    def test_stub_check_connection(self):
        client = AudiobookshelfAPIClient("url", "key", "lib")
        assert client.check_connection() is True

    def test_stub_upload_audiobook(self):
        client = AudiobookshelfAPIClient("url", "key", "lib")
        assert client.upload_audiobook() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])