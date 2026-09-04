"""
Tests for TTS Asset Manager (TEST-001: coverage improvement).

Tests for src/audiobook_studio/tts/asset_manager.py
Target: 70%+ coverage
"""

import os
import tempfile

import requests

# Set TEST_MODE before any imports
os.environ["TEST_MODE"] = "true"

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Now import the module under test
from src.audiobook_studio.tts import asset_manager


class TestAssetManagerConstants:
    """Tests for module-level constants."""

    def test_kokoro_assets_structure(self):
        """Test KOKORO_ASSETS has expected structure."""
        assert "kokoro-v0_19.onnx" in asset_manager.KOKORO_ASSETS
        assert "voices.bin" in asset_manager.KOKORO_ASSETS

        onnx_spec = asset_manager.KOKORO_ASSETS["kokoro-v0_19.onnx"]
        assert "url" in onnx_spec
        assert "size_mb" in onnx_spec
        assert "sha256" in onnx_spec
        assert "description" in onnx_spec
        assert onnx_spec["size_mb"] == 308

        voices_spec = asset_manager.KOKORO_ASSETS["voices.bin"]
        assert voices_spec["size_mb"] == 56

    def test_kokoro_fallback_assets_structure(self):
        """Test KOKORO_FALLBACK_ASSETS has expected structure."""
        assert "kokoro-v0_19.onnx" in asset_manager.KOKORO_FALLBACK_ASSETS
        assert "voices.bin" in asset_manager.KOKORO_FALLBACK_ASSETS

        onnx_spec = asset_manager.KOKORO_FALLBACK_ASSETS["kokoro-v0_19.onnx"]
        assert "github.com" in onnx_spec["url"]

    def test_cache_dir_expands_user(self):
        """Test CACHE_DIR expands ~ to home directory."""
        assert "~" not in str(asset_manager.CACHE_DIR)

    def test_chunk_size_constant(self):
        """Test CHUNK_SIZE constant."""
        assert asset_manager.CHUNK_SIZE == 8192

    def test_max_retries_constant(self):
        """Test MAX_RETRIES constant."""
        assert asset_manager.MAX_RETRIES == 3

    def test_retry_delay_constant(self):
        """Test RETRY_DELAY constant."""
        assert asset_manager.RETRY_DELAY == 2


class TestCalculateSHA256:
    """Tests for calculate_sha256 function."""

    def test_calculate_sha256_empty_file(self):
        """Test SHA256 of empty file."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = Path(f.name)
        try:
            result = asset_manager.calculate_sha256(temp_path)
            expected = hashlib.sha256(b"").hexdigest()
            assert result == expected
        finally:
            temp_path.unlink()

    def test_calculate_sha256_with_content(self):
        """Test SHA256 of file with content."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"Hello world")
            temp_path = Path(f.name)
        try:
            result = asset_manager.calculate_sha256(temp_path)
            expected = hashlib.sha256(b"Hello world").hexdigest()
            assert result == expected
        finally:
            temp_path.unlink()

    def test_calculate_sha256_large_file(self):
        """Test SHA256 reads in chunks."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            # Write more than CHUNK_SIZE (8192 bytes)
            f.write(b"x" * 20000)
            temp_path = Path(f.name)
        try:
            result = asset_manager.calculate_sha256(temp_path)
            expected = hashlib.sha256(b"x" * 20000).hexdigest()
            assert result == expected
        finally:
            temp_path.unlink()


class TestDownloadFile:
    """Tests for download_file function."""

    def test_download_file_success(self):
        """Test successful file download."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"

            with patch("src.audiobook_studio.tts.asset_manager.requests.get") as mock_get:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.headers = {"content-length": "11"}
                mock_response.iter_content.return_value = [b"Hello ", b"world"]
                mock_response.raise_for_status.return_value = None
                mock_get.return_value = mock_response

                success, error = asset_manager.download_file(
                    "http://example.com/file.txt",
                    filepath,
                    expected_size_mb=0.000011,  # ~11 bytes
                )

            assert success is True
            assert error == ""
            assert filepath.exists()
            assert filepath.read_bytes() == b"Hello world"

    def test_download_file_416_range_not_satisfiable(self):
        """Test download_file handles 416 status (file already complete)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"
            temp_path = filepath.with_suffix(filepath.suffix + ".part")
            temp_path.write_bytes(b"already complete")

            with patch("src.audiobook_studio.tts.asset_manager.requests.get") as mock_get:
                mock_response = MagicMock()
                mock_response.status_code = 416
                mock_get.return_value = mock_response

                success, error = asset_manager.download_file(
                    "http://example.com/file.txt",
                    filepath,
                )

            assert success is True
            assert error == "Already complete"
            assert filepath.exists()
            assert filepath.read_bytes() == b"already complete"

    def test_download_file_resume(self):
        """Test download_file resumes partial download."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"
            temp_path = filepath.with_suffix(filepath.suffix + ".part")
            temp_path.write_bytes(b"partial")

            with patch("src.audiobook_studio.tts.asset_manager.requests.get") as mock_get:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.headers = {"content-length": "6"}
                mock_response.iter_content.return_value = [b" content"]
                mock_response.raise_for_status.return_value = None
                mock_get.return_value = mock_response

                success, error = asset_manager.download_file(
                    "http://example.com/file.txt",
                    filepath,
                )

            assert success is True
            assert filepath.read_bytes() == b"partial content"
            # Verify Range header was sent
            call_args = mock_get.call_args
            assert "Range" in call_args[1]["headers"]
            assert call_args[1]["headers"]["Range"] == "bytes=7-"

    def test_download_file_http_error(self):
        """Test download_file handles HTTP errors (HTTPError retries as RequestException)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"

            with (
                patch("src.audiobook_studio.tts.asset_manager.requests.get") as mock_get,
                patch("time.sleep") as mock_sleep,
            ):

                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Not Found")
                mock_get.return_value = mock_response

                success, error = asset_manager.download_file(
                    "http://example.com/file.txt",
                    filepath,
                )

            assert success is False
            assert "Max retries" in error
            assert mock_sleep.call_count == 2  # MAX_RETRIES - 1

    def test_download_file_request_exception(self):
        """Test download_file handles request exceptions (with retry)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"

            with (
                patch("src.audiobook_studio.tts.asset_manager.requests.get") as mock_get,
                patch("time.sleep") as mock_sleep,
            ):

                mock_get.side_effect = requests.exceptions.ConnectionError("Connection failed")

                success, error = asset_manager.download_file(
                    "http://example.com/file.txt",
                    filepath,
                )

            assert success is False
            assert "Max retries" in error
            assert mock_sleep.call_count == 2  # MAX_RETRIES - 1

    def test_download_file_size_mismatch_warning(self):
        """Test download_file logs warning on size mismatch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"

            with (
                patch("src.audiobook_studio.tts.asset_manager.requests.get") as mock_get,
                patch("src.audiobook_studio.tts.asset_manager.logger") as mock_logger,
            ):

                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.headers = {"content-length": "1000000"}  # ~1MB
                mock_response.iter_content.return_value = [b"x" * 100000]
                mock_response.raise_for_status.return_value = None
                mock_get.return_value = mock_response

                success, error = asset_manager.download_file(
                    "http://example.com/file.txt",
                    filepath,
                    expected_size_mb=10,  # Expect 10MB but get 0.1MB
                )

            assert success is True
            mock_logger.warning.assert_called()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "Size mismatch" in warning_msg


class TestVerifyAssetFiles:
    """Tests for verify_asset_files function."""

    def test_verify_asset_files_all_valid(self):
        """Test verify_asset_files when all files valid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            # Create mock asset files with correct content
            file1 = cache_dir / "model.onnx"
            file1.write_bytes(b"x" * 100)

            file2 = cache_dir / "voices.bin"
            file2.write_bytes(b"y" * 50)

            # Calculate expected SHA256
            sha1 = hashlib.sha256(b"x" * 100).hexdigest()
            sha2 = hashlib.sha256(b"y" * 50).hexdigest()

            assets_spec = {
                "model.onnx": {"sha256": sha1, "size_mb": 0.0001},
                "voices.bin": {"sha256": sha2, "size_mb": 0.00005},
            }

            valid, issues = asset_manager.verify_asset_files(cache_dir, assets_spec)

            assert valid is True
            assert issues == []

    def test_verify_asset_files_missing(self):
        """Test verify_asset_files with missing files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            assets_spec = {
                "model.onnx": {"sha256": "abc123", "size_mb": 10},
            }

            valid, issues = asset_manager.verify_asset_files(cache_dir, assets_spec)

            assert valid is False
            assert "Missing: model.onnx" in issues[0]

    def test_verify_asset_files_checksum_mismatch(self):
        """Test verify_asset_files with checksum mismatch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            file1 = cache_dir / "model.onnx"
            file1.write_bytes(b"wrong content")

            assets_spec = {
                "model.onnx": {"sha256": hashlib.sha256(b"correct content").hexdigest(), "size_mb": 10},
            }

            valid, issues = asset_manager.verify_asset_files(cache_dir, assets_spec)

            assert valid is False
            assert "Checksum mismatch" in issues[0]

    def test_verify_asset_files_size_mismatch(self):
        """Test verify_asset_files with size mismatch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            file1 = cache_dir / "model.onnx"
            file1.write_bytes(b"x" * 100)  # Very small file

            assets_spec = {
                "model.onnx": {"sha256": hashlib.sha256(b"x" * 100).hexdigest(), "size_mb": 100},  # Expect 100MB
            }

            valid, issues = asset_manager.verify_asset_files(cache_dir, assets_spec)

            assert valid is False
            assert "Size mismatch" in issues[0]

    def test_verify_asset_files_multiple_issues(self):
        """Test verify_asset_files collects multiple issues."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            file1 = cache_dir / "model.onnx"
            file1.write_bytes(b"wrong")

            assets_spec = {
                "model.onnx": {"sha256": hashlib.sha256(b"correct").hexdigest(), "size_mb": 10},
                "voices.bin": {"sha256": "abc", "size_mb": 5},  # Missing file
            }

            valid, issues = asset_manager.verify_asset_files(cache_dir, assets_spec)

            assert valid is False
            assert len(issues) == 2
            assert any("Checksum mismatch" in i for i in issues)
            assert any("Missing: voices.bin" in i for i in issues)


class TestDownloadAssets:
    """Tests for download_assets function."""

    def test_download_assets_all_exist_no_force(self):
        """Test download_assets skips download when all files exist and valid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            file1 = cache_dir / "model.onnx"
            file1.write_bytes(b"x" * 100)

            sha1 = hashlib.sha256(b"x" * 100).hexdigest()

            assets_spec = {
                "model.onnx": {"url": "http://example.com/model.onnx", "sha256": sha1, "size_mb": 0.0001},
            }

            with patch("src.audiobook_studio.tts.asset_manager.download_file") as mock_download:
                result = asset_manager.download_assets(cache_dir, assets_spec, force=False)

                assert result is True
                mock_download.assert_not_called()

    def test_download_assets_force_redownload(self):
        """Test download_assets forces re-download when force=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            file1 = cache_dir / "model.onnx"
            file1.write_bytes(b"old content")

            sha1 = hashlib.sha256(b"new content").hexdigest()

            assets_spec = {
                "model.onnx": {"url": "http://example.com/model.onnx", "sha256": sha1, "size_mb": 0.0001},
            }

            with (
                patch("src.audiobook_studio.tts.asset_manager.download_file") as mock_download,
                patch("src.audiobook_studio.tts.asset_manager.verify_asset_files") as mock_verify,
            ):

                mock_download.return_value = (True, "")
                mock_verify.return_value = (True, [])

                result = asset_manager.download_assets(cache_dir, assets_spec, force=True)

                assert result is True
                mock_download.assert_called_once()
                mock_verify.assert_called()

    def test_download_assets_download_success(self):
        """Test download_assets downloads successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            assets_spec = {
                "model.onnx": {"url": "http://example.com/model.onnx", "sha256": "abc123", "size_mb": 10},
            }

            with (
                patch("src.audiobook_studio.tts.asset_manager.download_file") as mock_download,
                patch("src.audiobook_studio.tts.asset_manager.verify_asset_files") as mock_verify,
            ):

                mock_download.return_value = (True, "")
                # First call (before download) returns False, second call (after) returns True
                mock_verify.side_effect = [(False, ["Missing"]), (True, [])]

                result = asset_manager.download_assets(cache_dir, assets_spec)

                assert result is True
                mock_download.assert_called_once()
                assert mock_verify.call_count == 2

    def test_download_assets_download_failure(self):
        """Test download_assets handles download failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            assets_spec = {
                "model.onnx": {"url": "http://example.com/model.onnx", "sha256": "abc123", "size_mb": 10},
            }

            with (
                patch("src.audiobook_studio.tts.asset_manager.download_file") as mock_download,
                patch("src.audiobook_studio.tts.asset_manager.verify_asset_files") as mock_verify,
                patch("src.audiobook_studio.tts.asset_manager.logger") as mock_logger,
            ):

                mock_download.return_value = (False, "Connection timeout")
                mock_verify.return_value = (False, ["Missing: model.onnx"])

                result = asset_manager.download_assets(cache_dir, assets_spec)

                assert result is False
                mock_logger.error.assert_called()

    def test_download_assets_skips_existing_when_not_forced(self):
        """Test download_assets skips existing file when not forced."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            file1 = cache_dir / "model.onnx"
            file1.write_bytes(b"existing content")

            sha1 = hashlib.sha256(b"existing content").hexdigest()

            assets_spec = {
                "model.onnx": {"url": "http://example.com/model.onnx", "sha256": sha1, "size_mb": 0.0001},
            }

            with (
                patch("src.audiobook_studio.tts.asset_manager.download_file") as mock_download,
                patch("src.audiobook_studio.tts.asset_manager.verify_asset_files") as mock_verify,
            ):

                mock_verify.return_value = (True, [])

                result = asset_manager.download_assets(cache_dir, assets_spec, force=False)

                assert result is True
                mock_download.assert_not_called()
                mock_verify.assert_called()


class TestEnsureKokoroAssets:
    """Tests for ensure_kokoro_assets function."""

    def test_ensure_kokoro_assets_success_primary(self):
        """Test ensure_kokoro_assets succeeds on primary source."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            with (
                patch("src.audiobook_studio.tts.asset_manager.download_assets") as mock_download,
                patch("src.audiobook_studio.tts.asset_manager.verify_asset_files") as mock_verify,
            ):

                mock_download.return_value = True
                mock_verify.return_value = (True, [])

                result = asset_manager.ensure_kokoro_assets(cache_dir=cache_dir)

                assert result == cache_dir
                mock_download.assert_called_once()
                mock_verify.assert_called()

    def test_ensure_kokoro_assets_fallback(self):
        """Test ensure_kokoro_assets falls back to GitHub on primary failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            with (
                patch("src.audiobook_studio.tts.asset_manager.download_assets") as mock_download,
                patch("src.audiobook_studio.tts.asset_manager.verify_asset_files") as mock_verify,
            ):

                mock_download.side_effect = [False, True]
                mock_verify.return_value = (True, [])

                result = asset_manager.ensure_kokoro_assets(cache_dir=cache_dir)

                assert result == cache_dir
                assert mock_download.call_count == 2
                # Second call should use fallback assets
                second_call_args = mock_download.call_args_list[1]
                assert second_call_args[0][1] == asset_manager.KOKORO_FALLBACK_ASSETS
                mock_verify.assert_called()

    def test_ensure_kokoro_assets_raises_on_failure(self):
        """Test ensure_kokoro_assets raises RuntimeError when both sources fail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            with patch("src.audiobook_studio.tts.asset_manager.download_assets") as mock_download:
                mock_download.return_value = False

                with pytest.raises(RuntimeError, match="Failed to download/verify"):
                    asset_manager.ensure_kokoro_assets(cache_dir=cache_dir)

    def test_ensure_kokoro_assets_use_fallback_param(self):
        """Test ensure_kokoro_assets uses fallback when use_fallback=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            with (
                patch("src.audiobook_studio.tts.asset_manager.download_assets") as mock_download,
                patch("src.audiobook_studio.tts.asset_manager.verify_asset_files") as mock_verify,
            ):

                mock_download.return_value = True
                mock_verify.return_value = (True, [])

                result = asset_manager.ensure_kokoro_assets(cache_dir=cache_dir, use_fallback=True)

                assert result == cache_dir
                mock_download.assert_called_once()
                call_args = mock_download.call_args
                assert call_args[0][1] == asset_manager.KOKORO_FALLBACK_ASSETS
                mock_verify.assert_called()

    def test_ensure_kokoro_assets_default_cache_dir(self):
        """Test ensure_kokoro_assets uses default CACHE_DIR when not specified."""
        with (
            patch("src.audiobook_studio.tts.asset_manager.download_assets") as mock_download,
            patch("src.audiobook_studio.tts.asset_manager.verify_asset_files") as mock_verify,
        ):

            mock_download.return_value = True
            mock_verify.return_value = (True, [])

            result = asset_manager.ensure_kokoro_assets()

            assert result == asset_manager.CACHE_DIR
            mock_download.assert_called_once()
            mock_verify.assert_called()


class TestGetKokoroModelPaths:
    """Tests for get_kokoro_model_paths function."""

    def test_get_kokoro_model_paths_default(self):
        """Test get_kokoro_model_paths returns correct paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            model_path, voices_path = asset_manager.get_kokoro_model_paths(cache_dir)

            assert model_path == cache_dir / "kokoro-v0_19.onnx"
            assert voices_path == cache_dir / "voices.bin"

    def test_get_kokoro_model_paths_default_cache(self):
        """Test get_kokoro_model_paths uses default cache dir."""
        model_path, voices_path = asset_manager.get_kokoro_model_paths()

        assert model_path == asset_manager.CACHE_DIR / "kokoro-v0_19.onnx"
        assert voices_path == asset_manager.CACHE_DIR / "voices.bin"


class TestResolveKokoroPaths:
    """Tests for resolve_kokoro_paths function."""

    def test_resolve_kokoro_paths_explicit(self):
        """Test resolve_kokoro_paths uses explicit paths when provided."""
        with patch("src.audiobook_studio.tts.asset_manager.ensure_kokoro_assets") as mock_ensure:
            mock_ensure.return_value = Path("/fake/cache")

            model, voices = asset_manager.resolve_kokoro_paths(
                model_path="/custom/model.onnx",
                voices_path="/custom/voices.bin",
            )

            assert model == "/custom/model.onnx"
            assert voices == "/custom/voices.bin"
            mock_ensure.assert_called_once()

    def test_resolve_kokoro_paths_default(self):
        """Test resolve_kokoro_paths uses cache when not explicitly provided."""
        with patch("src.audiobook_studio.tts.asset_manager.ensure_kokoro_assets") as mock_ensure:
            mock_ensure.return_value = Path("/fake/cache")

            model, voices = asset_manager.resolve_kokoro_paths()

            assert model == "/fake/cache/kokoro-v0_19.onnx"
            assert voices == "/fake/cache/voices.bin"
            mock_ensure.assert_called_once()

    def test_resolve_kokoro_paths_partial(self):
        """Test resolve_kokoro_paths with only one explicit path."""
        with patch("src.audiobook_studio.tts.asset_manager.ensure_kokoro_assets") as mock_ensure:
            mock_ensure.return_value = Path("/fake/cache")

            model, voices = asset_manager.resolve_kokoro_paths(model_path="/custom/model.onnx")

            assert model == "/custom/model.onnx"
            assert voices == "/fake/cache/voices.bin"
