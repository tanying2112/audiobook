"""Comprehensive tests for publish/audiobookshelf_integration.py — coverage boost."""

import asyncio
import base64
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from src.audiobook_studio.publish.audiobookshelf_integration import (
    AudiobookshelfConfig,
    AudiobookshelfIntegrator,
    AudiobookMetadata,
    AudiobookFile,
)


def _cfg(**kw):
    c = AudiobookshelfConfig(
        api_url="http://localhost:8080", api_key="k", library_id="lib1", **kw,
    )
    return c


def _meta(**kw):
    defaults = dict(
        title="T", author="A", narrator="N", description="D",
        language="zh-CN", publication_year=2020, publisher="P",
        genres=["g"], tags=["t"], series="S", series_index=1.0,
    )
    defaults.update(kw)
    return AudiobookMetadata(**defaults)


def _ud(**kw):
    d = {
        "title": "T", "author": "A", "narrator": "N", "description": "D",
        "language": "zh-CN", "year": 2020, "publisher": "P",
        "genres": ["g"], "tags": ["t"], "series": "S", "seriesIndex": 1.0,
    }
    d.update(kw)
    return d


def _audio_file(td, fmt="m4b", size=None):
    fp = Path(td) / f"book.{fmt}"
    data = b"audio" * 100
    fp.write_bytes(data)
    sz = size if size is not None else len(data)
    return AudiobookFile(
        file_path=fp, size_bytes=sz, duration_seconds=60,
        format=fmt, bitrate_kbps=64, checksum_md5="x",
    )


def _resp(code=200, json_data=None, text="ok"):
    r = AsyncMock()
    r.status_code = code
    r.text = text
    if json_data is not None:
        r.json = MagicMock(return_value=json_data)
    return r


def _integrator():
    with patch("httpx.AsyncClient"):
        return AudiobookshelfIntegrator(_cfg())


# ---- prepare_audiobook (async) ----
class TestPrepareAudiobook:
    @pytest.mark.asyncio
    async def test_invalid_title(self):
        integ = _integrator()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, _ = await integ.prepare_audiobook(_meta(title="  "), _audio_file(td))
            assert not ok
            assert "标题" in msg

    @pytest.mark.asyncio
    async def test_invalid_author(self):
        integ = _integrator()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, _ = await integ.prepare_audiobook(_meta(author="  "), _audio_file(td))
            assert not ok

    @pytest.mark.asyncio
    async def test_invalid_narrator(self):
        integ = _integrator()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, _ = await integ.prepare_audiobook(_meta(narrator="  "), _audio_file(td))
            assert not ok

    @pytest.mark.asyncio
    async def test_invalid_year_low(self):
        integ = _integrator()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, _ = await integ.prepare_audiobook(_meta(publication_year=500), _audio_file(td))
            assert not ok
            assert "年份" in msg

    @pytest.mark.asyncio
    async def test_invalid_year_high(self):
        integ = _integrator()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, _ = await integ.prepare_audiobook(_meta(publication_year=3000), _audio_file(td))
            assert not ok

    @pytest.mark.asyncio
    async def test_unsupported_format_auto_convert(self):
        integ = _integrator()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, _ = await integ.prepare_audiobook(_meta(), _audio_file(td, fmt="ogg"))
            assert not ok
            assert "不支持的格式" in msg

    @pytest.mark.asyncio
    async def test_unsupported_format_no_auto_convert(self):
        c = _cfg(auto_convert=False)
        with patch("httpx.AsyncClient"):
            integ = AudiobookshelfIntegrator(c)
        with tempfile.TemporaryDirectory() as td:
            ok, msg, _ = await integ.prepare_audiobook(_meta(), _audio_file(td, fmt="ogg"))
            assert not ok
            assert "不支持的格式" in msg

    @pytest.mark.asyncio
    async def test_file_not_exists(self):
        integ = _integrator()
        af = AudiobookFile(
            file_path=Path("/no/such/file.m4b"), size_bytes=0,
            duration_seconds=60, format="m4b", bitrate_kbps=64, checksum_md5="x",
        )
        ok, msg, _ = await integ.prepare_audiobook(_meta(), af)
        assert not ok

    @pytest.mark.asyncio
    async def test_file_is_directory(self):
        integ = _integrator()
        with tempfile.TemporaryDirectory() as td:
            dp = Path(td) / "not_a_file.m4b"
            dp.mkdir()
            af = AudiobookFile(
                file_path=dp, size_bytes=0, duration_seconds=60,
                format="m4b", bitrate_kbps=64, checksum_md5="x",
            )
            ok, msg, _ = await integ.prepare_audiobook(_meta(), af)
            assert not ok

    @pytest.mark.asyncio
    async def test_size_mismatch(self):
        integ = _integrator()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, _ = await integ.prepare_audiobook(_meta(), _audio_file(td, size=999999))
            assert not ok

    @pytest.mark.asyncio
    async def test_ext_mismatch(self):
        integ = _integrator()
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "book.m4b"
            fp.write_bytes(b"audio")
            af = AudiobookFile(
                file_path=fp, size_bytes=len(b"audio"), duration_seconds=60,
                format="mp3", bitrate_kbps=64, checksum_md5="x",
            )
            ok, msg, _ = await integ.prepare_audiobook(_meta(), af)
            assert not ok

    @pytest.mark.asyncio
    async def test_success(self):
        integ = _integrator()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, data = await integ.prepare_audiobook(_meta(), _audio_file(td))
            assert ok
            assert data["title"] == "T"

    @pytest.mark.asyncio
    async def test_cover_with_image(self):
        integ = _integrator()
        with tempfile.TemporaryDirectory() as td:
            cover = Path(td) / "cover.jpg"
            cover.write_bytes(b"\xff\xd8\xff\xe0img")
            ok, msg, data = await integ.prepare_audiobook(_meta(cover_image_path=cover), _audio_file(td))
            assert ok
            assert data["coverImage"] is not None

    @pytest.mark.asyncio
    async def test_no_chapters_default(self):
        integ = _integrator()
        with tempfile.TemporaryDirectory() as td:
            af = _audio_file(td)
            af.chapters = []
            ok, msg, data = await integ.prepare_audiobook(_meta(), af)
            assert ok
            assert len(data["chapters"]) == 1

    @pytest.mark.asyncio
    async def test_year_none(self):
        integ = _integrator()
        with tempfile.TemporaryDirectory() as td:
            ok, msg, data = await integ.prepare_audiobook(_meta(publication_year=None), _audio_file(td))
            assert ok


# ---- _real_api_call library errors ----
class TestRealAPILibraryErrors:
    @pytest.mark.asyncio
    async def test_no_library_id(self):
        integ = _integrator()
        integ.config = MagicMock()
        integ.config.library_id = ""
        r = await integ._real_api_call(_ud(), MagicMock())
        assert r["success"] is False
        assert "库 ID 未配置" in r["message"]

    @pytest.mark.asyncio
    async def test_library_404(self):
        integ = _integrator()
        integ.client.get = AsyncMock(return_value=_resp(404))
        with tempfile.TemporaryDirectory() as td:
            r = await integ._real_api_call(_ud(), _audio_file(td))
            assert r["success"] is False
            assert "不存在" in r["message"]

    @pytest.mark.asyncio
    async def test_library_500(self):
        integ = _integrator()
        integ.client.get = AsyncMock(return_value=_resp(500, text="err"))
        with tempfile.TemporaryDirectory() as td:
            r = await integ._real_api_call(_ud(), _audio_file(td))
            assert r["success"] is False
            assert "无法访问库" in r["message"]

    @pytest.mark.asyncio
    async def test_no_folders(self):
        integ = _integrator()
        integ.client.get = AsyncMock(return_value=_resp(200, {"folders": []}))
        with tempfile.TemporaryDirectory() as td:
            r = await integ._real_api_call(_ud(), _audio_file(td))
            assert r["success"] is False
            assert "没有配置任何文件夹" in r["message"]

    @pytest.mark.asyncio
    async def test_library_exception(self):
        integ = _integrator()
        integ.client.get = AsyncMock(side_effect=ConnectionError("refused"))
        with tempfile.TemporaryDirectory() as td:
            r = await integ._real_api_call(_ud(), _audio_file(td))
            assert r["success"] is False

    @pytest.mark.asyncio
    async def test_no_audio_file(self):
        integ = _integrator()
        integ.client.get = AsyncMock(return_value=_resp(200, {"folders": [{"id": "f1"}]}))
        af = AudiobookFile(
            file_path=Path("/nonexistent.m4b"), size_bytes=0,
            duration_seconds=60, format="m4b", bitrate_kbps=64, checksum_md5="x",
        )
        r = await integ._real_api_call(_ud(), af)
        assert r["success"] is False


# ---- _real_api_call upload & metadata ----
class TestRealAPIUpload:
    @pytest.mark.asyncio
    async def test_upload_success_no_search(self):
        integ = _integrator()
        integ.client.get = AsyncMock(return_value=_resp(200, {"folders": [{"id": "f1"}]}))
        integ.client.post = AsyncMock(return_value=_resp(201))
        with tempfile.TemporaryDirectory() as td:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is True
                assert r["uploaded_files"] == 1

    @pytest.mark.asyncio
    async def test_upload_http_error(self):
        integ = _integrator()
        integ.client.get = AsyncMock(return_value=_resp(200, {"folders": [{"id": "f1"}]}))
        integ.client.post = AsyncMock(return_value=_resp(500, text="err"))
        with tempfile.TemporaryDirectory() as td:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is False
                assert "所有文件上传失败" in r["message"]

    @pytest.mark.asyncio
    async def test_upload_exception(self):
        integ = _integrator()
        integ.client.get = AsyncMock(return_value=_resp(200, {"folders": [{"id": "f1"}]}))
        integ.client.post = AsyncMock(side_effect=ConnectionError("fail"))
        with tempfile.TemporaryDirectory() as td:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is False

    @pytest.mark.asyncio
    async def test_scan_exception_non_fatal(self):
        integ = _integrator()
        integ.client.get = AsyncMock(return_value=_resp(200, {"folders": [{"id": "f1"}]}))
        call_count = [0]
        async def mock_post(url, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return _resp(201)
            raise ConnectionError("scan fail")
        integ.client.post = mock_post
        with tempfile.TemporaryDirectory() as td:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is True

    @pytest.mark.asyncio
    async def test_scan_http_error_non_fatal(self):
        integ = _integrator()
        integ.client.get = AsyncMock(return_value=_resp(200, {"folders": [{"id": "f1"}]}))
        call_count = [0]
        async def mock_post(url, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return _resp(201)
            return _resp(500, text="scan err")
        integ.client.post = mock_post
        with tempfile.TemporaryDirectory() as td:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is True

    @pytest.mark.asyncio
    async def test_search_matches_item(self):
        integ = _integrator()
        search_results = [{"id": "i1", "media": {"metadata": {"title": "T"}}}]
        async def mock_get(url, **kw):
            if "search" in url:
                return _resp(200, search_results)
            return _resp(200, {"folders": [{"id": "f1"}]})
        integ.client.get = mock_get
        integ.client.post = AsyncMock(return_value=_resp(201))
        integ.client.patch = AsyncMock(return_value=_resp(204))
        with tempfile.TemporaryDirectory() as td:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is True
                assert r["item_id"] == "i1"
                integ.client.patch.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_polls_until_match(self):
        integ = _integrator()
        empty = []
        match = [{"id": "i2", "media": {"metadata": {"title": "T"}}}]
        call_idx = [0]
        async def mock_get(url, **kw):
            if "search" in url:
                call_idx[0] += 1
                if call_idx[0] == 1:
                    return _resp(200, empty)
                return _resp(200, match)
            return _resp(200, {"folders": [{"id": "f1"}]})
        integ.client.get = mock_get
        integ.client.post = AsyncMock(return_value=_resp(201))
        with tempfile.TemporaryDirectory() as td:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_ud(), _audio_file(td))
                assert r["item_id"] == "i2"

    @pytest.mark.asyncio
    async def test_search_exception_non_fatal(self):
        integ = _integrator()
        async def mock_get(url, **kw):
            if "search" in url:
                raise ConnectionError("fail")
            return _resp(200, {"folders": [{"id": "f1"}]})
        integ.client.get = mock_get
        integ.client.post = AsyncMock(return_value=_resp(201))
        with tempfile.TemporaryDirectory() as td:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is True

    @pytest.mark.asyncio
    async def test_metadata_patch_exception(self):
        integ = _integrator()
        search_results = [{"id": "i1", "media": {"metadata": {"title": "T"}}}]
        async def mock_get(url, **kw):
            if "search" in url:
                return _resp(200, search_results)
            return _resp(200, {"folders": [{"id": "f1"}]})
        integ.client.get = mock_get
        integ.client.post = AsyncMock(return_value=_resp(201))
        integ.client.patch = AsyncMock(side_effect=ConnectionError("fail"))
        with tempfile.TemporaryDirectory() as td:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is True

    @pytest.mark.asyncio
    async def test_metadata_optional_fields(self):
        integ = _integrator()
        search_results = [{"id": "i1", "media": {"metadata": {"title": "T"}}}]
        async def mock_get(url, **kw):
            if "search" in url:
                return _resp(200, search_results)
            return _resp(200, {"folders": [{"id": "f1"}]})
        integ.client.get = mock_get
        integ.client.post = AsyncMock(return_value=_resp(201))
        integ.client.patch = AsyncMock(return_value=_resp(204))
        ud = _ud(
            description="desc", year=2020, publisher="Pub",
            genres=["scifi"], language="zh", series="Ser",
            seriesIndex=2, tags=["tag1"],
            chapters=[{"title": "Ch1", "start": 0, "end": 100}],
        )
        with tempfile.TemporaryDirectory() as td:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(ud, _audio_file(td))
                assert r["success"] is True
                call_kwargs = integ.client.patch.call_args
                payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
                meta = payload.get("metadata", {})
                assert meta.get("description") == "desc"
                assert meta.get("publishedYear") == 2020
                assert meta.get("language") == "zh-CN"
                assert meta.get("series") == "Ser"
                assert meta.get("seriesSequence") == 2
                assert meta.get("tags") == ["tag1"]
                assert meta.get("genre") == ["scifi"]

    @pytest.mark.asyncio
    async def test_cover_upload(self):
        integ = _integrator()
        search_results = [{"id": "i1", "media": {"metadata": {"title": "T"}}}]
        async def mock_get(url, **kw):
            if "search" in url:
                return _resp(200, search_results)
            return _resp(200, {"folders": [{"id": "f1"}]})
        integ.client.get = mock_get
        integ.client.post = AsyncMock(return_value=_resp(201))
        integ.client.patch = AsyncMock(return_value=_resp(204))
        cover_b64 = base64.b64encode(b"imgdata").decode()
        ud = _ud(coverImage=cover_b64)
        with tempfile.TemporaryDirectory() as td:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(ud, _audio_file(td))
                assert r["success"] is True
                assert integ.client.post.call_count >= 2

    @pytest.mark.asyncio
    async def test_cover_upload_exception(self):
        integ = _integrator()
        search_results = [{"id": "i1", "media": {"metadata": {"title": "T"}}}]
        async def mock_get(url, **kw):
            if "search" in url:
                return _resp(200, search_results)
            return _resp(200, {"folders": [{"id": "f1"}]})
        integ.client.get = mock_get
        call_count = [0]
        async def mock_post(url, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return _resp(201)
            raise ConnectionError("cover fail")
        integ.client.post = mock_post
        integ.client.patch = AsyncMock(return_value=_resp(204))
        cover_b64 = base64.b64encode(b"img").decode()
        ud = _ud(coverImage=cover_b64)
        with tempfile.TemporaryDirectory() as td:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(ud, _audio_file(td))
                assert r["success"] is True

    @pytest.mark.asyncio
    async def test_local_base_path_copy(self):
        integ = _integrator()
        integ.config.base_path = tempfile.mkdtemp()
        integ.client.get = AsyncMock(return_value=_resp(200, {"folders": [{"id": "f1"}]}))
        with tempfile.TemporaryDirectory() as td:
            af = _audio_file(td)
            r = await integ._real_api_call(_ud(), af)
            assert r["success"] is True
            dest = Path(integ.config.base_path) / "A" / "T" / "book.m4b"
            assert dest.exists()

    @pytest.mark.asyncio
    async def test_local_base_path_copy_error(self):
        integ = _integrator()
        integ.config.base_path = "/nonexistent/deeply/nested/path"
        integ.client.get = AsyncMock(return_value=_resp(200, {"folders": [{"id": "f1"}]}))
        with tempfile.TemporaryDirectory() as td:
            r = await integ._real_api_call(_ud(), _audio_file(td))
            assert r["success"] is False

    @pytest.mark.asyncio
    async def test_search_no_title_match(self):
        integ = _integrator()
        search_results = [{"id": "i1", "media": {"metadata": {"title": "Different"}}}]
        async def mock_get(url, **kw):
            if "search" in url:
                return _resp(200, search_results)
            return _resp(200, {"folders": [{"id": "f1"}]})
        integ.client.get = mock_get
        integ.client.post = AsyncMock(return_value=_resp(201))
        with tempfile.TemporaryDirectory() as td:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is True
                assert r["item_id"] is None

    @pytest.mark.asyncio
    async def test_metadata_patch_non_200(self):
        integ = _integrator()
        search_results = [{"id": "i1", "media": {"metadata": {"title": "T"}}}]
        async def mock_get(url, **kw):
            if "search" in url:
                return _resp(200, search_results)
            return _resp(200, {"folders": [{"id": "f1"}]})
        integ.client.get = mock_get
        integ.client.post = AsyncMock(return_value=_resp(201))
        integ.client.patch = AsyncMock(return_value=_resp(500))
        with tempfile.TemporaryDirectory() as td:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_ud(), _audio_file(td))
                assert r["success"] is True

    @pytest.mark.asyncio
    async def test_cover_upload_non_200(self):
        integ = _integrator()
        search_results = [{"id": "i1", "media": {"metadata": {"title": "T"}}}]
        async def mock_get(url, **kw):
            if "search" in url:
                return _resp(200, search_results)
            return _resp(200, {"folders": [{"id": "f1"}]})
        integ.client.get = mock_get
        call_count = [0]
        async def mock_post(url, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return _resp(201)
            return _resp(500)
        integ.client.post = mock_post
        integ.client.patch = AsyncMock(return_value=_resp(204))
        cover_b64 = base64.b64encode(b"img").decode()
        ud = _ud(coverImage=cover_b64)
        with tempfile.TemporaryDirectory() as td:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(ud, _audio_file(td))
                assert r["success"] is True

    @pytest.mark.asyncio
    async def test_metadata_no_optional_fields(self):
        integ = _integrator()
        search_results = [{"id": "i1", "media": {"metadata": {"title": "T"}}}]
        async def mock_get(url, **kw):
            if "search" in url:
                return _resp(200, search_results)
            return _resp(200, {"folders": [{"id": "f1"}]})
        integ.client.get = mock_get
        integ.client.post = AsyncMock(return_value=_resp(201))
        integ.client.patch = AsyncMock(return_value=_resp(204))
        ud = {"title": "T", "author": "A"}
        with tempfile.TemporaryDirectory() as td:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(ud, _audio_file(td))
                assert r["success"] is True


# ---- publish_to_audiobookshelf ----
class TestPublishToAudiobookshelf:
    @pytest.mark.asyncio
    async def test_publish_success(self):
        integ = _integrator()
        search_results = [{"id": "i1", "media": {"metadata": {"title": "T"}}}]
        async def mock_get(url, **kw):
            if "search" in url:
                return _resp(200, search_results)
            return _resp(200, {"folders": [{"id": "f1"}]})
        integ.client.get = mock_get
        integ.client.post = AsyncMock(return_value=_resp(201))
        integ.client.patch = AsyncMock(return_value=_resp(204))
        with tempfile.TemporaryDirectory() as td:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                success, msg, resp = await integ.publish_to_audiobookshelf(_meta(), _audio_file(td))
                assert success is True

    @pytest.mark.asyncio
    async def test_publish_prepare_failure(self):
        integ = _integrator()
        with tempfile.TemporaryDirectory() as td:
            success, msg, resp = await integ.publish_to_audiobookshelf(_meta(title="  "), _audio_file(td))
            assert success is False
            assert resp is None

    @pytest.mark.asyncio
    async def test_publish_network_error(self):
        integ = _integrator()
        integ.client.get = AsyncMock(side_effect=ConnectionError("fail"))
        with tempfile.TemporaryDirectory() as td:
            success, msg, resp = await integ.publish_to_audiobookshelf(_meta(), _audio_file(td))
            assert success is False


# ---- _get_mime_type ----
class TestGetMimeType:
    def test_m4b(self):
        integ = _integrator()
        assert integ._get_mime_type(Path("a.m4b")) == "audio/mp4"

    def test_mp3(self):
        integ = _integrator()
        assert integ._get_mime_type(Path("a.mp3")) == "audio/mpeg"

    def test_unknown(self):
        integ = _integrator()
        assert integ._get_mime_type(Path("a.xyz")) == "application/octet-stream"


# ---- get_library_status ----
class TestGetLibraryStatus:
    @pytest.mark.asyncio
    async def test_online(self):
        integ = _integrator()
        integ.client.get = AsyncMock(return_value=_resp(200, {"mediaCount": 5, "duration": 7200}))
        s = await integ.get_library_status()
        assert s["total_books"] == 5
        assert s["status"] == "online"

    @pytest.mark.asyncio
    async def test_offline(self):
        integ = _integrator()
        integ.client.get = AsyncMock(side_effect=ConnectionError("fail"))
        s = await integ.get_library_status()
        assert s["status"] == "offline"

    @pytest.mark.asyncio
    async def test_non_200(self):
        integ = _integrator()
        integ.client.get = AsyncMock(return_value=_resp(500))
        s = await integ.get_library_status()
        assert s["status"] == "offline"


# ---- main() ----
class TestMain:
    def test_main_runs(self):
        from src.audiobook_studio.publish.audiobookshelf_integration import main
        with patch("builtins.print"):
            main()
