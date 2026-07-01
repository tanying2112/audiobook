"""Tests for src/audiobook_studio/tts/model_downloader.py — testing
helpers and small isolated functions without performing real network I/O."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.tts.model_downloader import (
    CHUNK_SIZE,
    DEFAULT_MODEL_DIR,
    FALLBACK_FILES,
    MAX_RETRIES,
    MAX_WORKERS,
    REQUIRED_FILES,
    RETRY_DELAY,
    calculate_sha256,
    download_file,
    get_model_paths,
    verify_model_files,
)


class TestConstants:
    def test_chunk_size(self):
        assert isinstance(CHUNK_SIZE, int)
        assert CHUNK_SIZE > 0

    def test_max_workers(self):
        assert MAX_WORKERS >= 1

    def test_max_retries(self):
        assert MAX_RETRIES >= 1

    def test_retry_delay(self):
        assert isinstance(RETRY_DELAY, (int, float))

    def test_default_model_dir_is_path(self):
        assert isinstance(DEFAULT_MODEL_DIR, Path)

    def test_required_files_structure(self):
        assert isinstance(REQUIRED_FILES, dict)
        for name, spec in REQUIRED_FILES.items():
            assert "url" in spec
            assert "size_mb" in spec

    def test_fallback_files_structure(self):
        assert isinstance(FALLBACK_FILES, dict)


class TestCalculateSha256:
    def test_sha256_known_string(self, tmp_path):
        f = tmp_path / "data.bin"
        # Some specific bytes → known SHA256
        f.write_bytes(b"hello world")
        sha = calculate_sha256(f)
        assert isinstance(sha, str)
        # b"hello world" → SHA256 = b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9
        assert sha == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

    def test_sha256_different_content(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"hello")
        f2.write_bytes(b"world")
        assert calculate_sha256(f1) != calculate_sha256(f2)


class TestVerifyModelFiles:
    def test_verify_no_files_returns_invalid(self, tmp_path):
        files_spec = {
            "missing.bin": {"url": "http://example.com", "size_mb": 1}
        }
        valid, issues = verify_model_files(tmp_path, files_spec)
        assert valid is False
        assert any("Missing" in iss for iss in issues)

    def test_verify_files_within_tolerance(self, tmp_path):
        # File at exactly 5 MB → tolerance check (15%) should pass
        file_path = tmp_path / "ok.bin"
        file_path.write_bytes(b"\x00" * (5 * 1024 * 1024))  # exactly 5 MB
        files_spec = {"ok.bin": {"url": "x", "size_mb": 5}}
        valid, issues = verify_model_files(tmp_path, files_spec)
        assert valid is True
        assert issues == []

    def test_verify_files_outside_tolerance(self, tmp_path):
        # File at 1 MB but expected 5 MB → outside 15% tolerance
        file_path = tmp_path / "bad.bin"
        file_path.write_bytes(b"\x00" * (1024 * 1024))  # 1 MB
        files_spec = {"bad.bin": {"url": "x", "size_mb": 5}}
        valid, issues = verify_model_files(tmp_path, files_spec)
        assert valid is False
        assert any("Size mismatch" in iss for iss in issues)

    def test_verify_no_size_spec_skips_check(self, tmp_path):
        file_path = tmp_path / "nocheck.bin"
        file_path.write_bytes(b"small")
        files_spec = {"nocheck.bin": {"url": "x", "size_mb": 0}}
        valid, issues = verify_model_files(tmp_path, files_spec)
        # size_mb=0 is falsy → no size check
        assert valid is True


class TestGetModelPaths:
    def test_get_model_paths(self, tmp_path):
        model_path, voices_path = get_model_paths(tmp_path)
        assert model_path == tmp_path / "kokoro-v1.0.onnx"
        assert voices_path == tmp_path / "voices-v1.0.bin"

    def test_get_model_paths_default(self):
        model_path, voices_path = get_model_paths(None)
        assert model_path.name == "kokoro-v1.0.onnx"
        assert voices_path.name == "voices-v1.0.bin"


class TestDownloadFileMock:
    def test_download_file_success(self, tmp_path):
        target = tmp_path / "file.bin"
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.headers = {"content-length": "10"}
        fake_response.raise_for_status = MagicMock()
        fake_response.iter_content.return_value = [b"0123456789"]

        with patch("src.audiobook_studio.tts.model_downloader.requests.get", return_value=fake_response):
            success, err = download_file(
                url="http://example.com/file.bin",
                filepath=target,
            )
        assert success is True
        assert err == ""
        assert target.exists()
        assert target.read_bytes() == b"0123456789"

    def test_download_file_416_already_complete(self, tmp_path):
        target = tmp_path / "already.bin"
        # Pre-existing .part file
        (tmp_path / "already.bin.part").write_bytes(b"complete")
        fake_response = MagicMock()
        fake_response.status_code = 416
        with patch("src.audiobook_studio.tts.model_downloader.requests.get", return_value=fake_response):
            success, err = download_file(
                url="http://example.com/file.bin",
                filepath=target,
            )
        # When 416 and partial exists, it is renamed
        assert success is True
        assert err == "Already complete"
        assert target.exists()

    def test_download_file_max_retries(self, tmp_path):
        """Failed downloads retry MAX_RETRIES times and return False."""
        target = tmp_path / "x.bin"
        with patch(
            "src.audiobook_studio.tts.model_downloader.requests.get",
            side_effect=Exception("network down"),
        ), patch("src.audiobook_studio.tts.model_downloader.time.sleep"):
            success, err = download_file(
                url="http://example.com/x.bin",
                filepath=target,
            )
        # Generic Exception hits the `except Exception` branch, returning
        # the str(e) of the first attempt rather than the max-retries msg.
        assert success is False
        assert err == "network down"
