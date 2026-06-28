"""publish/audiobookshelf_integration.py 扩展测试 — 覆盖 AudiobookshelfIntegrator 核心路径。"""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestAudiobookshelfIntegratorExtended:
    """AudiobookshelfIntegrator 扩展覆盖。"""

    def _make_config(self):
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookshelfConfig,
        )

        return AudiobookshelfConfig(
            api_url="http://localhost:8080",
            api_key="test-key",
            library_id="lib-1",
        )

    def _make_metadata(self, **kwargs):
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookMetadata,
        )

        defaults = dict(
            title="测试书",
            author="作者",
            narrator="朗读者",
            description="简介",
        )
        defaults.update(kwargs)
        return AudiobookMetadata(**defaults)

    def _make_integrator(self):
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookshelfIntegrator,
        )

        return AudiobookshelfIntegrator(self._make_config())

    def test_init(self):
        """AudiobookshelfIntegrator 初始化。"""
        integrator = self._make_integrator()
        assert integrator.config.library_id == "lib-1"

    def test_validate_metadata_ok(self):
        """元数据验证通过。"""
        integrator = self._make_integrator()
        ok, msg = integrator._validate_metadata(self._make_metadata())
        assert ok is True

    def test_validate_metadata_empty_title(self):
        """空标题验证失败。"""
        integrator = self._make_integrator()
        ok, msg = integrator._validate_metadata(self._make_metadata(title="  "))
        assert ok is False
        assert "标题" in msg

    def test_validate_metadata_empty_author(self):
        """空作者验证失败。"""
        integrator = self._make_integrator()
        ok, msg = integrator._validate_metadata(self._make_metadata(author="  "))
        assert ok is False
        assert "作者" in msg

    def test_validate_metadata_empty_narrator(self):
        """空朗读者验证失败。"""
        integrator = self._make_integrator()
        ok, msg = integrator._validate_metadata(self._make_metadata(narrator="  "))
        assert ok is False
        assert "朗读者" in msg

    def test_validate_metadata_bad_year(self):
        """年份不合理验证失败。"""
        integrator = self._make_integrator()
        ok, msg = integrator._validate_metadata(
            self._make_metadata(publication_year=500)
        )
        assert ok is False

    def test_validate_metadata_no_year(self):
        """无年份验证通过。"""
        integrator = self._make_integrator()
        ok, msg = integrator._validate_metadata(
            self._make_metadata(publication_year=None)
        )
        assert ok is True

    def test_validate_audio_file_not_exists(self):
        """不存在的文件验证失败。"""
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookFile,
        )

        integrator = self._make_integrator()
        f = AudiobookFile(
            file_path=Path("/nonexistent.m4b"),
            size_bytes=100,
            duration_seconds=60,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="x",
        )
        ok, msg = integrator._validate_audio_file(f)
        assert ok is False
        assert "不存在" in msg

    def test_validate_audio_file_is_dir(self):
        """路径是目录时验证失败。"""
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookFile,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            integrator = self._make_integrator()
            d = Path(tmpdir) / "isdir"
            d.mkdir()
            f = AudiobookFile(
                file_path=d,
                size_bytes=0,
                duration_seconds=60,
                format="m4b",
                bitrate_kbps=64,
                checksum_md5="x",
            )
            ok, msg = integrator._validate_audio_file(f)
            assert ok is False

    def test_validate_audio_file_size_mismatch(self):
        """大小不匹配验证失败。"""
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookFile,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            integrator = self._make_integrator()
            fp = Path(tmpdir) / "book.m4b"
            fp.write_bytes(b"audio")
            f = AudiobookFile(
                file_path=fp,
                size_bytes=999,
                duration_seconds=60,
                format="m4b",
                bitrate_kbps=64,
                checksum_md5="x",
            )
            ok, msg = integrator._validate_audio_file(f)
            assert ok is False

    def test_validate_audio_file_ext_mismatch(self):
        """扩展名不匹配验证失败。"""
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookFile,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            integrator = self._make_integrator()
            fp = Path(tmpdir) / "book.m4b"
            fp.write_bytes(b"audio")
            f = AudiobookFile(
                file_path=fp,
                size_bytes=5,
                duration_seconds=60,
                format="mp3",
                bitrate_kbps=64,
                checksum_md5="x",
            )
            ok, msg = integrator._validate_audio_file(f)
            assert ok is False

    def test_validate_audio_file_ok(self):
        """有效文件验证通过。"""
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookFile,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            integrator = self._make_integrator()
            fp = Path(tmpdir) / "book.m4b"
            fp.write_bytes(b"audio")
            f = AudiobookFile(
                file_path=fp,
                size_bytes=5,
                duration_seconds=60,
                format="m4b",
                bitrate_kbps=64,
                checksum_md5="x",
            )
            ok, msg = integrator._validate_audio_file(f)
            assert ok is True

    def test_prepare_upload_data(self):
        """_prepare_upload_data 生成正确数据。"""
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookFile,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            integrator = self._make_integrator()
            fp = Path(tmpdir) / "book.m4b"
            fp.write_bytes(b"audio")
            af = AudiobookFile(
                file_path=fp,
                size_bytes=5,
                duration_seconds=3600,
                format="m4b",
                bitrate_kbps=64,
                checksum_md5="x",
            )
            meta = self._make_metadata()
            data = integrator._prepare_upload_data(meta, af)
            assert data["title"] == "测试书"
            assert data["author"] == "作者"
            assert data["fileName"] == "book.m4b"

    def test_prepare_upload_data_with_cover(self):
        """带封面图片的上传数据。"""
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookFile,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            integrator = self._make_integrator()
            fp = Path(tmpdir) / "book.m4b"
            fp.write_bytes(b"audio")
            cover = Path(tmpdir) / "cover.jpg"
            cover.write_bytes(b"\xff\xd8\xff")
            af = AudiobookFile(
                file_path=fp,
                size_bytes=5,
                duration_seconds=3600,
                format="m4b",
                bitrate_kbps=64,
                checksum_md5="x",
            )
            meta = self._make_metadata(cover_image_path=cover)
            data = integrator._prepare_upload_data(meta, af)
            assert data["coverImage"] is not None

    def test_prepare_upload_data_cover_fail(self):
        """封面读取失败时 coverImage 为 None。"""
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookFile,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            integrator = self._make_integrator()
            fp = Path(tmpdir) / "book.m4b"
            fp.write_bytes(b"audio")
            cover = Path(tmpdir) / "cover.jpg"
            cover.write_bytes(b"img")
            af = AudiobookFile(
                file_path=fp,
                size_bytes=5,
                duration_seconds=3600,
                format="m4b",
                bitrate_kbps=64,
                checksum_md5="x",
            )
            meta = self._make_metadata(cover_image_path=cover)
            with patch("builtins.open", side_effect=PermissionError("denied")):
                data = integrator._prepare_upload_data(meta, af)
            assert data["coverImage"] is None

    def test_prepare_upload_data_no_chapters(self):
        """无章节时自动生成默认章节。"""
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookFile,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            integrator = self._make_integrator()
            fp = Path(tmpdir) / "book.m4b"
            fp.write_bytes(b"audio")
            af = AudiobookFile(
                file_path=fp,
                size_bytes=5,
                duration_seconds=3600,
                format="m4b",
                bitrate_kbps=64,
                checksum_md5="x",
                chapters=[],
            )
            meta = self._make_metadata()
            data = integrator._prepare_upload_data(meta, af)
            assert len(data["chapters"]) == 1

    def test_get_mime_type(self):
        """_get_mime_type 返回正确 MIME。"""
        integrator = self._make_integrator()
        assert integrator._get_mime_type(Path("a.m4b")) == "audio/mp4"
        assert integrator._get_mime_type(Path("a.mp3")) == "audio/mpeg"
        assert integrator._get_mime_type(Path("a.wav")) == "audio/wav"
        assert "octet-stream" in integrator._get_mime_type(Path("a.xyz"))

    def test_prepare_audiobook_invalid_metadata(self):
        """无效元数据返回失败。"""
        integrator = self._make_integrator()
        ok, msg = integrator._validate_metadata(self._make_metadata(title="  "))
        assert ok is False

    def test_dataclass_defaults(self):
        """数据类默认值。"""
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookMetadata,
            AudiobookshelfConfig,
        )

        cfg = AudiobookshelfConfig(api_url="http://x", api_key="k", library_id="l")
        assert cfg.auto_convert is True
        assert cfg.preferred_format == "m4b"
        meta = AudiobookMetadata(title="t", author="a", narrator="n", description="d")
        assert meta.language == "zh-CN"
        assert meta.bitrate_kbps == 64
        assert meta.format == "m4b"

    def test_audiobook_file_defaults(self):
        """AudiobookFile 默认值。"""
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookFile,
        )

        f = AudiobookFile(
            file_path=Path("/x.m4b"),
            size_bytes=100,
            duration_seconds=60,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="x",
        )
        assert f.chapters == []
