"""publish/audiobookshelf.py 扩展测试 — 覆盖 AudiobookshelfPublisher 核心路径。"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest


class TestAudiobookshelfPublisher:
    """AudiobookshelfPublisher 测试覆盖。"""

    def _make_config(self):
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfConfig

        return AudiobookshelfConfig(
            api_url="http://localhost:8080",
            api_key="test-key",
            library_id="lib-1",
        )

    def _make_metadata(self, **kwargs):
        from src.audiobook_studio.publish.audiobookshelf import AudiobookMetadata

        defaults = dict(
            title="测试书",
            author="作者",
            narrator="朗读者",
            description="简介",
        )
        defaults.update(kwargs)
        return AudiobookMetadata(**defaults)

    def _make_audio_file(self, tmpdir, suffix=".m4b", content=b"audio"):
        from src.audiobook_studio.publish.audiobookshelf import AudiobookFile

        fp = Path(tmpdir) / f"book{suffix}"
        fp.write_bytes(content)
        return AudiobookFile(
            file_path=fp,
            size_bytes=len(content),
            duration_seconds=3600,
            format=suffix.lstrip("."),
            bitrate_kbps=64,
            checksum_md5="abc",
        )

    def test_init_mock_mode(self):
        """mock 模式初始化。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            cfg = self._make_config()
            pub = AudiobookshelfPublisher(cfg)
            assert pub.mock_mode is True
            assert pub.client is None

    def test_init_real_mode(self):
        """真实模式初始化创建 httpx client。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with patch.dict("os.environ", {"MOCK_LLM": "false"}):
            cfg = self._make_config()
            pub = AudiobookshelfPublisher(cfg)
            assert pub.mock_mode is False
            assert pub.client is not None
            pub.close()

    def test_close_without_client(self):
        """无 client 时 close 不报错。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            pub = AudiobookshelfPublisher(self._make_config())
            pub.close()

    def test_validate_metadata_ok(self):
        """元数据验证通过。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            pub = AudiobookshelfPublisher(self._make_config())
            ok, msg = pub._validate_metadata(self._make_metadata())
            assert ok is True

    def test_validate_metadata_empty_title(self):
        """空标题验证失败。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            pub = AudiobookshelfPublisher(self._make_config())
            ok, msg = pub._validate_metadata(self._make_metadata(title="  "))
            assert ok is False
            assert "标题" in msg

    def test_validate_metadata_empty_author(self):
        """空作者验证失败。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            pub = AudiobookshelfPublisher(self._make_config())
            ok, msg = pub._validate_metadata(self._make_metadata(author="  "))
            assert ok is False
            assert "作者" in msg

    def test_validate_metadata_empty_narrator(self):
        """空朗读者验证失败。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            pub = AudiobookshelfPublisher(self._make_config())
            ok, msg = pub._validate_metadata(self._make_metadata(narrator="  "))
            assert ok is False
            assert "朗读者" in msg

    def test_validate_metadata_bad_year(self):
        """不合理年份验证失败。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            pub = AudiobookshelfPublisher(self._make_config())
            ok, msg = pub._validate_metadata(self._make_metadata(publication_year=500))
            assert ok is False
            assert "年份" in msg

    def test_validate_metadata_bad_year_high(self):
        """过高年份验证失败。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            pub = AudiobookshelfPublisher(self._make_config())
            ok, msg = pub._validate_metadata(self._make_metadata(publication_year=3000))
            assert ok is False

    def test_validate_audio_file_not_exists(self):
        """不存在的音频文件验证失败。"""
        from src.audiobook_studio.publish.audiobookshelf import (
            AudiobookFile,
            AudiobookshelfPublisher,
        )

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            pub = AudiobookshelfPublisher(self._make_config())
            f = AudiobookFile(
                file_path=Path("/nonexistent.m4b"),
                size_bytes=100,
                duration_seconds=60,
                format="m4b",
                bitrate_kbps=64,
                checksum_md5="x",
            )
            ok, msg = pub._validate_audio_file(f)
            assert ok is False
            assert "不存在" in msg

    def test_validate_audio_file_is_dir(self):
        """路径是目录时验证失败。"""
        from src.audiobook_studio.publish.audiobookshelf import (
            AudiobookFile,
            AudiobookshelfPublisher,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"MOCK_LLM": "true"}):
                pub = AudiobookshelfPublisher(self._make_config())
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
                ok, msg = pub._validate_audio_file(f)
                assert ok is False
                assert "不是文件" in msg

    def test_validate_audio_file_size_mismatch(self):
        """文件大小不匹配验证失败。"""
        from src.audiobook_studio.publish.audiobookshelf import (
            AudiobookFile,
            AudiobookshelfPublisher,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"MOCK_LLM": "true"}):
                pub = AudiobookshelfPublisher(self._make_config())
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
                ok, msg = pub._validate_audio_file(f)
                assert ok is False
                assert "大小不匹配" in msg

    def test_validate_audio_file_ext_mismatch(self):
        """扩展名不匹配验证失败。"""
        from src.audiobook_studio.publish.audiobookshelf import (
            AudiobookFile,
            AudiobookshelfPublisher,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"MOCK_LLM": "true"}):
                pub = AudiobookshelfPublisher(self._make_config())
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
                ok, msg = pub._validate_audio_file(f)
                assert ok is False
                assert "不匹配" in msg

    def test_validate_audio_file_ok(self):
        """有效音频文件验证通过。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"MOCK_LLM": "true"}):
                pub = AudiobookshelfPublisher(self._make_config())
                af = self._make_audio_file(tmpdir)
                ok, msg = pub._validate_audio_file(af)
                assert ok is True

    def test_prepare_upload_data(self):
        """_prepare_upload_data 生成正确数据。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"MOCK_LLM": "true"}):
                pub = AudiobookshelfPublisher(self._make_config())
                meta = self._make_metadata()
                af = self._make_audio_file(tmpdir)
                data = pub._prepare_upload_data(meta, af)
                assert data["title"] == "测试书"
                assert data["author"] == "作者"
                assert data["fileName"] == "book.m4b"

    def test_prepare_upload_data_with_cover(self):
        """_prepare_upload_data 有封面图片时读取 base64。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"MOCK_LLM": "true"}):
                pub = AudiobookshelfPublisher(self._make_config())
                cover = Path(tmpdir) / "cover.jpg"
                cover.write_bytes(b"\xff\xd8\xff")
                meta = self._make_metadata(cover_image_path=cover)
                af = self._make_audio_file(tmpdir)
                data = pub._prepare_upload_data(meta, af)
                assert data["coverImage"] is not None

    def test_prepare_upload_data_no_chapters(self):
        """无章节信息时自动生成默认章节。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"MOCK_LLM": "true"}):
                pub = AudiobookshelfPublisher(self._make_config())
                meta = self._make_metadata()
                af = self._make_audio_file(tmpdir)
                af.chapters = []
                data = pub._prepare_upload_data(meta, af)
                assert len(data["chapters"]) == 1
                assert data["chapters"][0]["start"] == 0

    def test_prepare_audiobook_invalid_metadata(self):
        """元数据无效时 _prepare_audiobook 返回失败。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"MOCK_LLM": "true"}):
                pub = AudiobookshelfPublisher(self._make_config())
                meta = self._make_metadata(title="  ")
                af = self._make_audio_file(tmpdir)
                ok, msg, data = pub._prepare_audiobook(meta, af)
                assert ok is False

    def test_prepare_audiobook_unsupported_format(self):
        """不支持的格式返回失败。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"MOCK_LLM": "true"}):
                pub = AudiobookshelfPublisher(self._make_config())
                meta = self._make_metadata()
                af = self._make_audio_file(tmpdir, suffix=".flac")
                ok, msg, data = pub._prepare_audiobook(meta, af)
                assert ok is False
                assert "格式" in msg

    def test_publish_audiobook_invalid(self):
        """无效元数据发布返回 False。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"MOCK_LLM": "true"}):
                pub = AudiobookshelfPublisher(self._make_config())
                meta = self._make_metadata(title="  ")
                af = self._make_audio_file(tmpdir)
                ok, msg, resp = pub.publish_audiobook(meta, af)
                assert ok is False
                assert resp is None

    def test_real_api_call_no_library_id(self):
        """无库 ID 时 _real_api_call 返回失败。"""
        from src.audiobook_studio.publish.audiobookshelf import (
            AudiobookshelfConfig,
            AudiobookshelfPublisher,
        )

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            cfg = AudiobookshelfConfig(api_url="http://x", api_key="k", library_id="")
            pub = AudiobookshelfPublisher(cfg)
            result = pub._real_api_call({}, MagicMock())
            assert result["success"] is False
            assert "库 ID" in result["message"]

    def test_get_mime_type(self):
        """_get_mime_type 返回正确 MIME。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            pub = AudiobookshelfPublisher(self._make_config())
            assert pub._get_mime_type(Path("a.m4b")) == "audio/mp4"
            assert pub._get_mime_type(Path("a.mp3")) == "audio/mpeg"
            assert pub._get_mime_type(Path("a.wav")) == "audio/wav"
            assert pub._get_mime_type(Path("a.flac")) == "audio/flac"
            assert "octet-stream" in pub._get_mime_type(Path("a.xyz"))

    def test_mock_api_call(self):
        """_mock_api_call 返回成功结果。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            pub = AudiobookshelfPublisher(self._make_config())
            with patch("random.random", return_value=0.5):
                result = pub._mock_api_call({"title": "T", "author": "A"})
                assert result["success"] is True

    def test_prepare_upload_data_cover_read_fail(self):
        """封面图片读取失败时 coverImage 为 None。"""
        from src.audiobook_studio.publish.audiobookshelf import AudiobookshelfPublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"MOCK_LLM": "true"}):
                pub = AudiobookshelfPublisher(self._make_config())
                cover = Path(tmpdir) / "cover.jpg"
                cover.write_bytes(b"img")
                meta = self._make_metadata(cover_image_path=cover)
                af = self._make_audio_file(tmpdir)
                # Patch open to raise
                with patch("builtins.open", side_effect=PermissionError("denied")):
                    data = pub._prepare_upload_data(meta, af)
                # coverImage should be None due to exception
                assert data["coverImage"] is None

    def test_real_api_call_library_not_found(self):
        """库不存在时 _real_api_call 返回 404 错误。"""
        from src.audiobook_studio.publish.audiobookshelf import (
            AudiobookFile,
            AudiobookMetadata,
            AudiobookshelfConfig,
            AudiobookshelfPublisher,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"MOCK_LLM": "true"}):
                cfg = AudiobookshelfConfig(
                    api_url="http://x", api_key="k", library_id="lib1"
                )
                pub = AudiobookshelfPublisher(cfg)
                # Mock client
                mock_client = MagicMock()
                resp_404 = MagicMock()
                resp_404.status_code = 404
                mock_client.get.return_value = resp_404
                pub.client = mock_client
                result = pub._real_api_call({"title": "T"}, MagicMock())
                assert result["success"] is False
                assert "不存在" in result["message"]

    def test_real_api_call_library_no_folders(self):
        """库无文件夹时返回失败。"""
        from src.audiobook_studio.publish.audiobookshelf import (
            AudiobookshelfConfig,
            AudiobookshelfPublisher,
        )

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            cfg = AudiobookshelfConfig(
                api_url="http://x", api_key="k", library_id="lib1"
            )
            pub = AudiobookshelfPublisher(cfg)
            mock_client = MagicMock()
            resp_ok = MagicMock()
            resp_ok.status_code = 200
            resp_ok.json.return_value = {"folders": []}
            mock_client.get.return_value = resp_ok
            pub.client = mock_client
            result = pub._real_api_call({"title": "T"}, MagicMock())
            assert result["success"] is False
            assert "文件夹" in result["message"]

    def test_real_api_call_library_exception(self):
        """获取库信息异常时返回失败。"""
        from src.audiobook_studio.publish.audiobookshelf import (
            AudiobookshelfConfig,
            AudiobookshelfPublisher,
        )

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            cfg = AudiobookshelfConfig(
                api_url="http://x", api_key="k", library_id="lib1"
            )
            pub = AudiobookshelfPublisher(cfg)
            mock_client = MagicMock()
            mock_client.get.side_effect = ConnectionError("refused")
            pub.client = mock_client
            result = pub._real_api_call({"title": "T"}, MagicMock())
            assert result["success"] is False
            assert "失败" in result["message"]

    def test_real_api_call_library_500(self):
        """库返回 500 时返回失败。"""
        from src.audiobook_studio.publish.audiobookshelf import (
            AudiobookshelfConfig,
            AudiobookshelfPublisher,
        )

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            cfg = AudiobookshelfConfig(
                api_url="http://x", api_key="k", library_id="lib1"
            )
            pub = AudiobookshelfPublisher(cfg)
            mock_client = MagicMock()
            resp_500 = MagicMock()
            resp_500.status_code = 500
            resp_500.text = "Internal Error"
            mock_client.get.return_value = resp_500
            pub.client = mock_client
            result = pub._real_api_call({"title": "T"}, MagicMock())
            assert result["success"] is False
