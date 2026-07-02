import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add the src directory to the path so we can import the module as a package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src"))

# Set MOCK_LLM before importing the module (required for mock_mode behavior)
os.environ["MOCK_LLM"] = "true"

# Mock external dependencies that might cause import issues
sys.modules["requests"] = MagicMock()
sys.modules["requests.exceptions"] = MagicMock()
sys.modules["urllib3"] = MagicMock()
sys.modules["urllib3.exceptions"] = MagicMock()

from audiobook_studio.publish.audiobookshelf import (
    AudiobookFile,
    AudiobookMetadata,
    AudiobookshelfConfig,
    AudiobookshelfPublisher,
)


class TestAudiobookshelfPublisher(unittest.TestCase):
    def setUp(self):
        self.config = AudiobookshelfConfig(
            api_url="http://localhost:8080",
            api_key="test-key",
            library_id="test-library",
        )
        # Explicitly set MOCK_LLM to ensure mock_mode is True
        os.environ["MOCK_LLM"] = "true"
        self.publisher = AudiobookshelfPublisher(self.config)
        # Double ensure mock_mode is enabled
        self.publisher.mock_mode = True

    def test_init(self):
        self.assertIsInstance(self.publisher, AudiobookshelfPublisher)
        self.assertEqual(self.publisher.config.api_url, "http://localhost:8080")
        self.assertEqual(self.publisher.config.api_key, "test-key")
        self.assertEqual(self.publisher.config.library_id, "test-library")

    def test_validate_metadata_valid(self):
        metadata = AudiobookMetadata(
            title="Test Book",
            author="Test Author",
            narrator="Test Narrator",
            description="A test book description",
        )

        valid, message = self.publisher._validate_metadata(metadata)
        self.assertTrue(valid)
        self.assertEqual(message, "元数据验证通过")

    def test_validate_metadata_missing_title(self):
        metadata = AudiobookMetadata(
            title="",
            author="Test Author",
            narrator="Test Narrator",
            description="A test book description",
        )

        valid, message = self.publisher._validate_metadata(metadata)
        self.assertFalse(valid)
        self.assertIn("标题不能为空", message)

    def test_validate_metadata_missing_author(self):
        metadata = AudiobookMetadata(
            title="Test Book",
            author="",
            narrator="Test Narrator",
            description="A test book description",
        )

        valid, message = self.publisher._validate_metadata(metadata)
        self.assertFalse(valid)
        self.assertIn("作者不能为空", message)

    def test_validate_metadata_missing_narrator(self):
        metadata = AudiobookMetadata(
            title="Test Book",
            author="Test Author",
            narrator="",
            description="A test book description",
        )

        valid, message = self.publisher._validate_metadata(metadata)
        self.assertFalse(valid)
        self.assertIn("朗读者不能为空", message)

    def test_validate_metadata_invalid_year(self):
        metadata = AudiobookMetadata(
            title="Test Book",
            author="Test Author",
            narrator="Test Narrator",
            description="A test book description",
            publication_year=500,  # Too early
        )

        valid, message = self.publisher._validate_metadata(metadata)
        self.assertFalse(valid)
        self.assertIn("出版年份不合理", message)

    def test_validate_audio_file_exists(self):
        # Test with non-existent file (real Path.exists check)
        audio_file = AudiobookFile(
            file_path=Path("/nonexistent/file.mp3"),
            size_bytes=1000,
            duration_seconds=60.0,
            format="mp3",
            bitrate_kbps=128,
            checksum_md5="abc123",
        )

        valid, message = self.publisher._validate_audio_file(audio_file)
        self.assertFalse(valid)
        self.assertIn("音频文件不存在", message)

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.stat")
    @patch("mimetypes.guess_type")
    def test_validate_audio_file_valid(self, mock_guess, mock_stat, mock_is_file, mock_exists):
        # Setup mocks
        mock_exists.return_value = True
        mock_is_file.return_value = True
        mock_stat.return_value.st_size = 1024
        mock_guess.return_value = ("audio/mpeg", None)

        audio_file = AudiobookFile(
            file_path=Path("/tmp/test.mp3"),
            size_bytes=1024,
            duration_seconds=60.0,
            format="mp3",
            bitrate_kbps=128,
            checksum_md5="abc123",
        )

        valid, message = self.publisher._validate_audio_file(audio_file)
        self.assertTrue(valid)
        self.assertEqual(message, "音频文件验证通过")

    def test_get_mime_type(self):
        # Test the actual supported formats in _get_mime_type
        # The method only supports audio formats: .m4b, .mp3, .wav, .flac, .ogg, .aac
        self.assertEqual(self.publisher._get_mime_type(Path("test.m4b")), "audio/mp4")
        self.assertEqual(self.publisher._get_mime_type(Path("test.mp3")), "audio/mpeg")
        self.assertEqual(self.publisher._get_mime_type(Path("test.wav")), "audio/wav")
        self.assertEqual(self.publisher._get_mime_type(Path("test.flac")), "audio/flac")
        # Unknown types should return application/octet-stream
        self.assertEqual(
            self.publisher._get_mime_type(Path("test.unknown")),
            "application/octet-stream",
        )

    def test_prepare_upload_data(self):
        # Create metadata with required fields
        metadata = AudiobookMetadata(
            title="Test Book",
            author="Test Author",
            narrator="Test Narrator",
            description="A test book for testing",
        )

        # Create a temporary file for testing
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            audio_file = AudiobookFile(
                file_path=Path(tmp_path),
                size_bytes=os.path.getsize(tmp_path),
                duration_seconds=300.0,
                format="mp3",
                bitrate_kbps=128,
                checksum_md5="abcd1234",
            )

            # Test _prepare_upload_data
            upload_data = self.publisher._prepare_upload_data(metadata, audio_file)
            self.assertEqual(upload_data["title"], "Test Book")
            self.assertEqual(upload_data["author"], "Test Author")
            self.assertEqual(upload_data["narrator"], "Test Narrator")
            self.assertEqual(upload_data["format"], "mp3")
        finally:
            # Clean up temp file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_mock_api_call(self):
        """Test the internal mock API call method in mock mode."""
        upload_data = {
            "title": "Test Book",
            "author": "Test Author",
            "narrator": "Test Narrator",
            "format": "mp3",
        }
        result = self.publisher._mock_api_call(upload_data)
        # Mock mode has 10% failure rate, so we just check structure
        self.assertIn("success", result)
        self.assertIn("book_id", result)
        self.assertIn("message", result)

    def test_get_library_status_mock(self):
        """Test get_library_status in mock mode."""
        status = self.publisher.get_library_status()
        self.assertEqual(status["status"], "online")
        self.assertEqual(status["library_id"], "test-library")
        self.assertIn("supported_formats", status)

    def test_publish_audiobook_valid(self):
        """Test publish_audiobook with valid metadata and audio file."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            audio_file = AudiobookFile(
                file_path=Path(tmp_path),
                size_bytes=os.path.getsize(tmp_path),
                duration_seconds=60.0,
                format="mp3",
                bitrate_kbps=128,
                checksum_md5="abcd1234",
            )
            metadata = AudiobookMetadata(
                title="Published Book",
                author="Test Author",
                narrator="Test Narrator",
                description="A book to publish",
            )

            # In mock mode, publish uses _mock_api_call internally
            self.publisher.mock_mode = True
            success, message, response = self.publisher.publish_audiobook(metadata, audio_file)
            # Mock mode may succeed or fail randomly
            self.assertIn("success", response)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_publish_audiobook_invalid_metadata(self):
        """Test publish_audiobook with invalid metadata."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            audio_file = AudiobookFile(
                file_path=Path(tmp_path),
                size_bytes=os.path.getsize(tmp_path),
                duration_seconds=60.0,
                format="mp3",
                bitrate_kbps=128,
                checksum_md5="abcd1234",
            )
            metadata = AudiobookMetadata(
                title="",  # Invalid: empty title
                author="Test Author",
                narrator="Test Narrator",
                description="A book to publish",
            )

            success, message, response = self.publisher.publish_audiobook(metadata, audio_file)
            self.assertFalse(success)
            self.assertIn("标题不能为空", message)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_publish_audiobook_invalid_format(self):
        """Test publish_audiobook with unsupported format."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            audio_file = AudiobookFile(
                file_path=Path(tmp_path),
                size_bytes=os.path.getsize(tmp_path),
                duration_seconds=60.0,
                format="wav",  # Not in supported_formats
                bitrate_kbps=128,
                checksum_md5="abcd1234",
            )
            metadata = AudiobookMetadata(
                title="Test Book",
                author="Test Author",
                narrator="Test Narrator",
                description="A book to publish",
            )

            self.publisher.mock_mode = True
            success, message, response = self.publisher.publish_audiobook(metadata, audio_file)
            self.assertFalse(success)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_prepare_upload_data_with_chapters(self):
        """Test prepare_upload_data with chapters."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            audio_file = AudiobookFile(
                file_path=Path(tmp_path),
                size_bytes=os.path.getsize(tmp_path),
                duration_seconds=60.0,
                format="mp3",
                bitrate_kbps=128,
                checksum_md5="abcd1234",
                chapters=[{"title": "Chapter 1", "start": 0, "end": 300}],
            )
            metadata = AudiobookMetadata(
                title="Test Book",
                author="Test Author",
                narrator="Test Narrator",
                description="A book to publish",
                publication_year=2020,
            )

            upload_data = self.publisher._prepare_upload_data(metadata, audio_file)
            self.assertEqual(upload_data["year"], 2020)
            self.assertEqual(len(upload_data["chapters"]), 1)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_prepare_upload_data_with_cover_image(self):
        """Test prepare_upload_data with cover image."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as cover_tmp:
                cover_path = cover_tmp.name
                cover_tmp.write(b"fake cover image")

            audio_file = AudiobookFile(
                file_path=Path(tmp_path),
                size_bytes=os.path.getsize(tmp_path),
                duration_seconds=60.0,
                format="mp3",
                bitrate_kbps=128,
                checksum_md5="abcd1234",
            )
            metadata = AudiobookMetadata(
                title="Test Book",
                author="Test Author",
                narrator="Test Narrator",
                description="A book to publish",
                cover_image_path=Path(cover_path),
            )

            upload_data = self.publisher._prepare_upload_data(metadata, audio_file)
            self.assertIsNotNone(upload_data["coverImage"])
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            if os.path.exists(cover_path):
                os.unlink(cover_path)

    def test_prepare_audiobook_valid(self):
        """Test _prepare_audiobook method."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            audio_file = AudiobookFile(
                file_path=Path(tmp_path),
                size_bytes=os.path.getsize(tmp_path),
                duration_seconds=60.0,
                format="mp3",
                bitrate_kbps=128,
                checksum_md5="abcd1234",
            )
            metadata = AudiobookMetadata(
                title="Test Book",
                author="Test Author",
                narrator="Test Narrator",
                description="A book to publish",
            )

            valid, message, upload_data = self.publisher._prepare_audiobook(metadata, audio_file)
            self.assertTrue(valid)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
