"""Comprehensive tests for publish/audiobookshelf.py sync publisher."""

import base64
import hashlib
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


def _cfg(**kw):
    c = AudiobookshelfConfig(
        api_url="http://localhost:8080",
        api_key="k",
        library_id="lib1",
        **kw,
    )
    return c


def _meta(**kw):
    defaults = dict(
        title="T",
        author="A",
        narrator="N",
        description="D",
        language="zh-CN",
        publication_year=2020,
        publisher="P",
        genres=["g"],
        tags=["t"],
        series="S",
        series_index=1.0,
    )
    defaults.update(kw)
    return AudiobookMetadata(**defaults)


def _ud(**kw):
    """Build a plain dict upload_data as _real_api_call expects."""
    d = {
        "title": "T",
        "author": "A",
        "narrator": "N",
        "description": "D",
        "language": "zh-CN",
        "year": 2020,
        "publisher": "P",
        "genres": ["g"],
        "tags": ["t"],
        "series": "S",
        "seriesIndex": 1.0,
    }
    d.update(kw)
    return d


def _audio_file(td, fmt="m4b", size=None):
    fp = Path(td) / f"book.{fmt}"
    data = b"audio" * 100
    fp.write_bytes(data)
    sz = size if size is not None else len(data)
    return AudiobookFile(
        file_path=fp,
        size_bytes=sz,
        duration_seconds=60,
        format=fmt,
        bitrate_kbps=64,
        checksum_md5="x",
    )


def _resp(code=200, json_data=None, text="ok"):
    r = MagicMock()
    r.status_code = code
    r.text = text
    if json_data is not None:
        r.json.return_value = json_data
    return r


def _publisher_real():
    """Create a publisher in real (non-mock) mode with a MagicMock client."""
    with patch.dict("os.environ", {"MOCK_LLM": "false"}):
        with patch("src.audiobook_studio.publish.audiobookshelf.httpx.Client"):
            p = AudiobookshelfPublisher(_cfg())
            p.client = MagicMock()
            return p


class TestPublisherInit:
    def test_mock_mode(self):
        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            p = AudiobookshelfPublisher(_cfg())
            assert p.mock_mode is True
            assert p.client is None

    def test_real_mode(self):
        with patch.dict("os.environ", {"MOCK_LLM": "false"}):
            with patch("src.audiobook_studio.publish.audiobookshelf.httpx.Client"):
                p = AudiobookshelfPublisher(_cfg())
                assert p.mock_mode is False
                assert p.client is not None

    def test_close_no_client(self):
        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            p = AudiobookshelfPublisher(_cfg())
            p.close()

    def test_close_with_client(self):
        with patch.dict("os.environ", {"MOCK_LLM": "false"}):
            with patch("src.audiobook_studio.publish.audiobookshelf.httpx.Client"):
                p = AudiobookshelfPublisher(_cfg())
                p.client = MagicMock()
                p.close()
                p.client.close.assert_called()


class TestPublishMock:
    def test_publish_mock_success(self):
        p = _publisher_real()
        search_results = [{"id": "i1", "media": {"metadata": {"title": "T"}}}]

        def mock_get(url, **kw):
            if "search" in url:
                return _resp(200, search_results)
            return _resp(200, {"folders": [{"id": "f1"}]})

        p.client.get.side_effect = mock_get
        p.client.post.return_value = _resp(201)
        p.client.patch.return_value = _resp(204)
        with tempfile.TemporaryDirectory() as td:
            af = _audio_file(td)
            with patch("time.sleep"):
                success, msg, resp = p.publish_audiobook(_meta(), af)
                assert success is True
                assert resp is not None
                assert resp.get("item_id") == "i1"

    def test_publish_prepare_failure(self):
        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            p = AudiobookshelfPublisher(_cfg())
            m = _meta(title="  ")
            with tempfile.TemporaryDirectory() as td:
                af = _audio_file(td)
                success, msg, resp = p.publish_audiobook(m, af)
                assert success is False
                assert resp is None


class TestRealAPILibraryErrors:
    def test_no_library_id(self):
        p = _publisher_real()
        p.config = MagicMock()
        p.config.library_id = ""
        r = p._real_api_call(_ud(), MagicMock())
        assert r["success"] is False
        assert "库 ID 未配置" in r["message"]

    def test_library_404(self):
        p = _publisher_real()
        p.client.get.return_value = _resp(404)
        with tempfile.TemporaryDirectory() as td:
            r = p._real_api_call(_ud(), _audio_file(td))
            assert r["success"] is False
            assert "不存在" in r["message"]

    def test_library_500(self):
        p = _publisher_real()
        p.client.get.return_value = _resp(500, text="err")
        with tempfile.TemporaryDirectory() as td:
            r = p._real_api_call(_ud(), _audio_file(td))
            assert r["success"] is False
            assert "无法访问库" in r["message"]

    def test_library_no_folders(self):
        p = _publisher_real()
        p.client.get.return_value = _resp(200, {"folders": []})
        with tempfile.TemporaryDirectory() as td:
            r = p._real_api_call(_ud(), _audio_file(td))
            assert r["success"] is False
            assert "没有配置任何文件夹" in r["message"]

    def test_library_exception(self):
        p = _publisher_real()
        p.client.get.side_effect = ConnectionError("refused")
        with tempfile.TemporaryDirectory() as td:
            r = p._real_api_call(_ud(), _audio_file(td))
            assert r["success"] is False
            assert "获取库信息失败" in r["message"]

    def test_no_audio_file(self):
        p = _publisher_real()
        p.client.get.return_value = _resp(200, {"folders": [{"id": "f1"}]})
        af = AudiobookFile(
            file_path=Path("/nonexistent.m4b"),
            size_bytes=0,
            duration_seconds=60,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="x",
        )
        r = p._real_api_call(_ud(), af)
        assert r["success"] is False
        assert "未找到音频文件" in r["message"]


class TestRealAPIUpload:
    def test_upload_success_no_search_match(self):
        p = _publisher_real()
        p.client.get.return_value = _resp(200, {"folders": [{"id": "f1"}]})
        p.client.post.return_value = _resp(201)
        with tempfile.TemporaryDirectory() as td:
            with patch("time.sleep"):
                r = p._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is True
                assert r["uploaded_files"] == 1

    def test_upload_http_error(self):
        p = _publisher_real()
        p.client.get.return_value = _resp(200, {"folders": [{"id": "f1"}]})
        p.client.post.return_value = _resp(500, text="err")
        with tempfile.TemporaryDirectory() as td:
            with patch("time.sleep"):
                r = p._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is False
                assert "所有文件上传失败" in r["message"]

    def test_upload_exception(self):
        p = _publisher_real()
        p.client.get.return_value = _resp(200, {"folders": [{"id": "f1"}]})
        p.client.post.side_effect = ConnectionError("fail")
        with tempfile.TemporaryDirectory() as td:
            with patch("time.sleep"):
                r = p._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is False

    def test_scan_exception_non_fatal(self):
        p = _publisher_real()
        call_count = [0]

        def mock_post(url, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return _resp(201)
            raise ConnectionError("scan fail")

        p.client.get.return_value = _resp(200, {"folders": [{"id": "f1"}]})
        p.client.post.side_effect = mock_post
        with tempfile.TemporaryDirectory() as td:
            with patch("time.sleep"):
                r = p._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is True

    def test_scan_http_error_non_fatal(self):
        p = _publisher_real()
        call_count = [0]

        def mock_post(url, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return _resp(201)
            return _resp(500, text="scan err")

        p.client.get.return_value = _resp(200, {"folders": [{"id": "f1"}]})
        p.client.post.side_effect = mock_post
        with tempfile.TemporaryDirectory() as td:
            with patch("time.sleep"):
                r = p._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is True

    def test_search_matches_item(self):
        p = _publisher_real()
        search_results = [{"id": "i1", "media": {"metadata": {"title": "T"}}}]

        def mock_get(url, **kw):
            if "search" in url:
                return _resp(200, search_results)
            return _resp(200, {"folders": [{"id": "f1"}]})

        p.client.get.side_effect = mock_get
        p.client.post.return_value = _resp(201)
        p.client.patch.return_value = _resp(204)
        with tempfile.TemporaryDirectory() as td:
            with patch("time.sleep"):
                r = p._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is True
                assert r["item_id"] == "i1"
                p.client.patch.assert_called_once()

    def test_search_polls_until_match(self):
        p = _publisher_real()
        empty = []
        match = [{"id": "i2", "media": {"metadata": {"title": "T"}}}]
        call_idx = [0]

        def mock_get(url, **kw):
            if "search" in url:
                call_idx[0] += 1
                if call_idx[0] == 1:
                    return _resp(200, empty)
                return _resp(200, match)
            return _resp(200, {"folders": [{"id": "f1"}]})

        p.client.get.side_effect = mock_get
        p.client.post.return_value = _resp(201)
        with tempfile.TemporaryDirectory() as td:
            with patch("time.sleep"):
                r = p._real_api_call(_ud(), _audio_file(td))
                assert r["item_id"] == "i2"

    def test_search_exception_non_fatal(self):
        p = _publisher_real()

        def mock_get(url, **kw):
            if "search" in url:
                raise ConnectionError("fail")
            return _resp(200, {"folders": [{"id": "f1"}]})

        p.client.get.side_effect = mock_get
        p.client.post.return_value = _resp(201)
        with tempfile.TemporaryDirectory() as td:
            with patch("time.sleep"):
                r = p._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is True

    def test_metadata_patch_exception(self):
        p = _publisher_real()
        search_results = [{"id": "i1", "media": {"metadata": {"title": "T"}}}]

        def mock_get(url, **kw):
            if "search" in url:
                return _resp(200, search_results)
            return _resp(200, {"folders": [{"id": "f1"}]})

        p.client.get.side_effect = mock_get
        p.client.post.return_value = _resp(201)
        p.client.patch.side_effect = ConnectionError("fail")
        with tempfile.TemporaryDirectory() as td:
            with patch("time.sleep"):
                r = p._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is True

    def test_metadata_optional_fields(self):
        p = _publisher_real()
        search_results = [{"id": "i1", "media": {"metadata": {"title": "T"}}}]

        def mock_get(url, **kw):
            if "search" in url:
                return _resp(200, search_results)
            return _resp(200, {"folders": [{"id": "f1"}]})

        p.client.get.side_effect = mock_get
        p.client.post.return_value = _resp(201)
        p.client.patch.return_value = _resp(204)
        ud = _ud(
            description="desc",
            year=2020,
            publisher="Pub",
            genres=["scifi"],
            language="zh",
            series="Ser",
            seriesIndex=2,
            tags=["tag1"],
            chapters=[{"title": "Ch1", "start": 0, "end": 100}],
        )
        with tempfile.TemporaryDirectory() as td:
            with patch("time.sleep"):
                r = p._real_api_call(ud, _audio_file(td))
                assert r["success"] is True
                call_kwargs = p.client.patch.call_args
                payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
                meta = payload.get("metadata", {})
                assert meta.get("description") == "desc"
                assert meta.get("publishedYear") == 2020
                assert meta.get("language") == "zh-CN"
                assert meta.get("series") == "Ser"
                assert meta.get("seriesSequence") == 2
                assert meta.get("tags") == ["tag1"]
                assert meta.get("genre") == ["scifi"]

    def test_cover_upload(self):
        p = _publisher_real()
        search_results = [{"id": "i1", "media": {"metadata": {"title": "T"}}}]

        def mock_get(url, **kw):
            if "search" in url:
                return _resp(200, search_results)
            return _resp(200, {"folders": [{"id": "f1"}]})

        p.client.get.side_effect = mock_get
        p.client.post.return_value = _resp(201)
        p.client.patch.return_value = _resp(204)
        cover_b64 = base64.b64encode(b"imgdata").decode()
        ud = _ud(coverImage=cover_b64)
        with tempfile.TemporaryDirectory() as td:
            with patch("time.sleep"):
                r = p._real_api_call(ud, _audio_file(td))
                assert r["success"] is True
                assert p.client.post.call_count >= 2

    def test_cover_upload_exception(self):
        p = _publisher_real()
        search_results = [{"id": "i1", "media": {"metadata": {"title": "T"}}}]

        def mock_get(url, **kw):
            if "search" in url:
                return _resp(200, search_results)
            return _resp(200, {"folders": [{"id": "f1"}]})

        p.client.get.side_effect = mock_get
        call_count = [0]

        def mock_post(url, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return _resp(201)
            raise ConnectionError("cover fail")

        p.client.post.side_effect = mock_post
        p.client.patch.return_value = _resp(204)
        cover_b64 = base64.b64encode(b"img").decode()
        ud = _ud(coverImage=cover_b64)
        with tempfile.TemporaryDirectory() as td:
            with patch("time.sleep"):
                r = p._real_api_call(ud, _audio_file(td))
                assert r["success"] is True

    def test_local_base_path_copy(self):
        p = _publisher_real()
        p.config.base_path = tempfile.mkdtemp()
        p.client.get.return_value = _resp(200, {"folders": [{"id": "f1"}]})
        with tempfile.TemporaryDirectory() as td:
            af = _audio_file(td)
            r = p._real_api_call(_ud(), af)
            assert r["success"] is True
            dest = Path(p.config.base_path) / "A" / "T" / "book.m4b"
            assert dest.exists()

    def test_local_base_path_copy_error(self):
        p = _publisher_real()
        p.config.base_path = "/nonexistent/deeply/nested/path"
        p.client.get.return_value = _resp(200, {"folders": [{"id": "f1"}]})
        with tempfile.TemporaryDirectory() as td:
            r = p._real_api_call(_ud(), _audio_file(td))
            assert r["success"] is False


class TestPrepareAudiobook:
    def _publisher(self):
        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            return AudiobookshelfPublisher(_cfg())

    def test_invalid_metadata_title(self):
        p = self._publisher()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, _ = p._prepare_audiobook(_meta(title="  "), _audio_file(td))
            assert not ok
            assert "标题" in msg

    def test_invalid_metadata_author(self):
        p = self._publisher()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, _ = p._prepare_audiobook(_meta(author="  "), _audio_file(td))
            assert not ok
            assert "作者" in msg

    def test_invalid_metadata_narrator(self):
        p = self._publisher()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, _ = p._prepare_audiobook(_meta(narrator="  "), _audio_file(td))
            assert not ok
            assert "朗读者" in msg

    def test_invalid_year_too_low(self):
        p = self._publisher()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, _ = p._prepare_audiobook(_meta(publication_year=500), _audio_file(td))
            assert not ok
            assert "年份" in msg

    def test_invalid_year_too_high(self):
        p = self._publisher()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, _ = p._prepare_audiobook(_meta(publication_year=3000), _audio_file(td))
            assert not ok

    def test_unsupported_format_auto_convert(self):
        p = self._publisher()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, _ = p._prepare_audiobook(_meta(), _audio_file(td, fmt="ogg"))
            assert not ok
            assert "不支持的格式" in msg

    def test_unsupported_format_no_auto_convert(self):
        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            p = AudiobookshelfPublisher(_cfg(auto_convert=False))
            with tempfile.TemporaryDirectory() as td:
                ok, msg, _ = p._prepare_audiobook(_meta(), _audio_file(td, fmt="ogg"))
                assert not ok
                assert "不支持的格式" in msg

    def test_audio_file_size_mismatch(self):
        p = self._publisher()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, _ = p._prepare_audiobook(_meta(), _audio_file(td, size=999999))
            assert not ok
            assert "大小不匹配" in msg

    def test_audio_file_ext_mismatch(self):
        p = self._publisher()
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "book.m4b"
            fp.write_bytes(b"audio")
            af = AudiobookFile(
                file_path=fp,
                size_bytes=len(b"audio"),
                duration_seconds=60,
                format="mp3",
                bitrate_kbps=64,
                checksum_md5="x",
            )
            ok, msg, _ = p._prepare_audiobook(_meta(), af)
            assert not ok
            assert "扩展名" in msg

    def test_audio_file_not_exists(self):
        p = self._publisher()
        af = AudiobookFile(
            file_path=Path("/no/such/file.m4b"),
            size_bytes=0,
            duration_seconds=60,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="x",
        )
        ok, msg, _ = p._prepare_audiobook(_meta(), af)
        assert not ok
        assert "不存在" in msg

    def test_audio_file_is_directory(self):
        p = self._publisher()
        with tempfile.TemporaryDirectory() as td:
            dp = Path(td) / "not_a_file.m4b"
            dp.mkdir()
            af = AudiobookFile(
                file_path=dp,
                size_bytes=0,
                duration_seconds=60,
                format="m4b",
                bitrate_kbps=64,
                checksum_md5="x",
            )
            ok, msg, _ = p._prepare_audiobook(_meta(), af)
            assert not ok
            assert "不是文件" in msg

    def test_success(self):
        p = self._publisher()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, data = p._prepare_audiobook(_meta(), _audio_file(td))
            assert ok
            assert data["title"] == "T"

    def test_cover_with_image(self):
        p = self._publisher()
        with tempfile.TemporaryDirectory() as td:
            cover = Path(td) / "cover.jpg"
            cover.write_bytes(b"\xff\xd8\xff\xe0img")
            ok, msg, data = p._prepare_audiobook(_meta(cover_image_path=cover), _audio_file(td))
            assert ok
            assert data["coverImage"] is not None

    def test_no_chapters_default(self):
        p = self._publisher()
        with tempfile.TemporaryDirectory() as td:
            af = _audio_file(td)
            af.chapters = []
            ok, msg, data = p._prepare_audiobook(_meta(), af)
            assert ok
            assert len(data["chapters"]) == 1

    def test_year_none(self):
        p = self._publisher()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, data = p._prepare_audiobook(_meta(publication_year=None), _audio_file(td))
            assert ok
            assert data["year"] is None


class TestGetMimeTypeSync:
    def _publisher(self):
        with patch.dict("os.environ", {"MOCK_LLM": "false"}):
            with patch("src.audiobook_studio.publish.audiobookshelf.httpx.Client"):
                return AudiobookshelfPublisher(_cfg())

    def test_m4b(self):
        assert self._publisher()._get_mime_type(Path("a.m4b")) == "audio/mp4"

    def test_mp3(self):
        assert self._publisher()._get_mime_type(Path("a.mp3")) == "audio/mpeg"

    def test_unknown(self):
        assert self._publisher()._get_mime_type(Path("a.xyz")) == "application/octet-stream"


class TestGetLibraryStatus:
    def test_online(self):
        p = _publisher_real()
        p.client.get.return_value = _resp(200, {"mediaCount": 5, "duration": 7200})
        s = p.get_library_status()
        assert s["total_books"] == 5
        assert s["status"] == "online"

    def test_offline(self):
        p = _publisher_real()
        p.client.get.side_effect = ConnectionError("fail")
        s = p.get_library_status()
        assert s["status"] == "offline"

    def test_non_200(self):
        p = _publisher_real()
        p.client.get.return_value = _resp(500)
        s = p.get_library_status()
        assert s["status"] == "offline"


class TestMain:
    def test_main_runs(self):
        from src.audiobook_studio.publish.audiobookshelf import main

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            with patch("builtins.print"):
                main()
