"""audiobookshelf_integration.py async 方法测试。"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestAudiobookshelfIntegratorAsync:
    """异步方法覆盖。"""

    def _make_config(self):
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookshelfConfig,
        )

        return AudiobookshelfConfig(
            api_url="http://localhost:8080",
            api_key="key",
            library_id="lib1",
        )

    def _make_metadata(self, **kwargs):
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookMetadata,
        )

        defaults = dict(
            title="书", author="作者", narrator="朗读者", description="简介"
        )
        defaults.update(kwargs)
        return AudiobookMetadata(**defaults)

    def _make_integrator(self):
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookshelfIntegrator,
        )

        cfg = self._make_config()
        with patch("httpx.AsyncClient"):
            return AudiobookshelfIntegrator(cfg)

    def test_init(self):
        """初始化验证。"""
        integrator = self._make_integrator()
        assert integrator.config.library_id == "lib1"

    @pytest.mark.asyncio
    async def test_close(self):
        """close 方法。"""
        integrator = self._make_integrator()
        integrator.client = AsyncMock()
        await integrator.close()
        integrator.client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_prepare_audiobook_ok(self):
        """prepare_audiobook 成功路径。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            from src.audiobook_studio.publish.audiobookshelf_integration import (
                AudiobookFile,
            )

            integrator = self._make_integrator()
            fp = Path(tmpdir) / "book.m4b"
            fp.write_bytes(b"audio")
            af = AudiobookFile(
                file_path=fp,
                size_bytes=5,
                duration_seconds=60,
                format="m4b",
                bitrate_kbps=64,
                checksum_md5="x",
            )
            ok, msg, data = await integrator.prepare_audiobook(
                self._make_metadata(), af
            )
            assert ok is True
            assert data["title"] == "书"

    @pytest.mark.asyncio
    async def test_prepare_audiobook_bad_metadata(self):
        """prepare_audiobook 元数据无效。"""
        integrator = self._make_integrator()
        with tempfile.TemporaryDirectory() as tmpdir:
            from src.audiobook_studio.publish.audiobookshelf_integration import (
                AudiobookFile,
            )

            fp = Path(tmpdir) / "book.m4b"
            fp.write_bytes(b"audio")
            af = AudiobookFile(
                file_path=fp,
                size_bytes=5,
                duration_seconds=60,
                format="m4b",
                bitrate_kbps=64,
                checksum_md5="x",
            )
            ok, msg, data = await integrator.prepare_audiobook(
                self._make_metadata(title="  "), af
            )
            assert ok is False

    @pytest.mark.asyncio
    async def test_prepare_audiobook_bad_audio(self):
        """prepare_audiobook 音频无效。"""
        integrator = self._make_integrator()
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookFile,
        )

        af = AudiobookFile(
            file_path=Path("/no/such"),
            size_bytes=0,
            duration_seconds=60,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="x",
        )
        ok, msg, data = await integrator.prepare_audiobook(self._make_metadata(), af)
        assert ok is False

    @pytest.mark.asyncio
    async def test_prepare_audiobook_bad_format(self):
        """prepare_audiobook 格式不支持。"""
        integrator = self._make_integrator()
        with tempfile.TemporaryDirectory() as tmpdir:
            from src.audiobook_studio.publish.audiobookshelf_integration import (
                AudiobookFile,
            )

            fp = Path(tmpdir) / "book.flac"
            fp.write_bytes(b"audio")
            af = AudiobookFile(
                file_path=fp,
                size_bytes=5,
                duration_seconds=60,
                format="flac",
                bitrate_kbps=64,
                checksum_md5="x",
            )
            ok, msg, data = await integrator.prepare_audiobook(
                self._make_metadata(), af
            )
            assert ok is False

    @pytest.mark.asyncio
    async def test_publish_to_audiobookshelf_invalid(self):
        """publish_to_audiobookshelf 元数据无效。"""
        integrator = self._make_integrator()
        with tempfile.TemporaryDirectory() as tmpdir:
            from src.audiobook_studio.publish.audiobookshelf_integration import (
                AudiobookFile,
            )

            fp = Path(tmpdir) / "book.m4b"
            fp.write_bytes(b"audio")
            af = AudiobookFile(
                file_path=fp,
                size_bytes=5,
                duration_seconds=60,
                format="m4b",
                bitrate_kbps=64,
                checksum_md5="x",
            )
            ok, msg, _resp = await integrator.publish_to_audiobookshelf(
                self._make_metadata(title="  "), af
            )
            assert ok is False

    @pytest.mark.asyncio
    async def test_publish_to_audiobookshelf_success(self):
        """publish_to_audiobookshelf 成功路径。"""
        integrator = self._make_integrator()
        with tempfile.TemporaryDirectory() as tmpdir:
            from src.audiobook_studio.publish.audiobookshelf_integration import (
                AudiobookFile,
            )

            fp = Path(tmpdir) / "book.m4b"
            fp.write_bytes(b"audio")
            af = AudiobookFile(
                file_path=fp,
                size_bytes=5,
                duration_seconds=60,
                format="m4b",
                bitrate_kbps=64,
                checksum_md5="x",
            )
            # Mock the real_api_call
            integrator._real_api_call = AsyncMock(
                return_value={
                    "success": True,
                    "item_id": "item1",
                    "uploaded_files": 1,
                    "total_files": 1,
                }
            )
            ok, msg, _resp = await integrator.publish_to_audiobookshelf(
                self._make_metadata(), af
            )
            assert ok is True

    @pytest.mark.asyncio
    async def test_publish_to_audiobookshelf_failure(self):
        """publish_to_audiobookshelf 失败路径。"""
        integrator = self._make_integrator()
        with tempfile.TemporaryDirectory() as tmpdir:
            from src.audiobook_studio.publish.audiobookshelf_integration import (
                AudiobookFile,
            )

            fp = Path(tmpdir) / "book.m4b"
            fp.write_bytes(b"audio")
            af = AudiobookFile(
                file_path=fp,
                size_bytes=5,
                duration_seconds=60,
                format="m4b",
                bitrate_kbps=64,
                checksum_md5="x",
            )
            integrator._real_api_call = AsyncMock(
                return_value={
                    "success": False,
                    "message": "上传失败",
                    "item_id": None,
                }
            )
            ok, msg, _resp = await integrator.publish_to_audiobookshelf(
                self._make_metadata(), af
            )
            assert ok is False

    @pytest.mark.asyncio
    async def test_real_api_call_no_library(self):
        """_real_api_call 无库 ID。"""
        integrator = self._make_integrator()
        with tempfile.TemporaryDirectory() as tmpdir:
            from src.audiobook_studio.publish.audiobookshelf_integration import (
                AudiobookFile,
            )

            fp = Path(tmpdir) / "book.m4b"
            fp.write_bytes(b"audio")
            af = AudiobookFile(
                file_path=fp,
                size_bytes=5,
                duration_seconds=60,
                format="m4b",
                bitrate_kbps=64,
                checksum_md5="x",
            )
            integrator.config.library_id = ""
            result = await integrator._real_api_call({}, af)
            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_get_library_status(self):
        """get_library_status 成功。"""
        integrator = self._make_integrator()
        resp = AsyncMock()
        resp.status_code = 200
        resp.json = MagicMock(return_value={"mediaCount": 5, "duration": 3600})
        integrator.client = AsyncMock()
        integrator.client.get = AsyncMock(return_value=resp)
        status = await integrator.get_library_status()
        assert status["total_books"] == 5

    @pytest.mark.asyncio
    async def test_get_library_status_error(self):
        """get_library_status 异常。"""
        integrator = self._make_integrator()
        integrator.client = AsyncMock()
        integrator.client.get = AsyncMock(side_effect=ConnectionError("refused"))
        status = await integrator.get_library_status()
        assert status["status"] == "offline"
        assert "error" in status
