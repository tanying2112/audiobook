"""audiobookshelf_integration.py _real_api_call async path coverage."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_integrator():
    from src.audiobook_studio.publish.audiobookshelf_integration import (
        AudiobookshelfIntegrator,
    )

    cfg = MagicMock()
    cfg.api_url = "http://localhost:8080"
    cfg.api_key = "key"
    cfg.library_id = "lib1"
    cfg.supported_formats = ["m4b", "mp3"]
    cfg.base_path = None  # MagicMock auto-generates truthy attrs; must set explicitly
    with patch("httpx.AsyncClient"):
        return AudiobookshelfIntegrator(cfg)


def _upload_data():
    return {"title": "t", "author": "a", "description": "d"}


def _audio_file(tmpdir):
    from src.audiobook_studio.publish.audiobookshelf_integration import AudiobookFile

    fp = Path(tmpdir) / "book.m4b"
    fp.write_bytes(b"audio")
    return AudiobookFile(
        file_path=fp,
        size_bytes=5,
        duration_seconds=60,
        format="m4b",
        bitrate_kbps=64,
        checksum_md5="x",
    )


def _resp(code=200, json_data=None, text=""):
    r = AsyncMock()
    r.status_code = code
    r.text = text
    if json_data is not None:
        r.json = MagicMock(return_value=json_data)
    return r


class TestIntegrationRealAPI:
    @pytest.mark.asyncio
    async def test_library_404(self):
        integ = _make_integrator()
        with tempfile.TemporaryDirectory() as td:
            af = _audio_file(td)
            integ.client.get = AsyncMock(return_value=_resp(404))
            r = await integ._real_api_call(_upload_data(), af)
            assert r["success"] is False

    @pytest.mark.asyncio
    async def test_library_500(self):
        integ = _make_integrator()
        with tempfile.TemporaryDirectory() as td:
            af = _audio_file(td)
            integ.client.get = AsyncMock(return_value=_resp(500, text="err"))
            r = await integ._real_api_call(_upload_data(), af)
            assert r["success"] is False

    @pytest.mark.asyncio
    async def test_no_folders(self):
        integ = _make_integrator()
        with tempfile.TemporaryDirectory() as td:
            af = _audio_file(td)
            integ.client.get = AsyncMock(return_value=_resp(200, {"folders": []}))
            r = await integ._real_api_call(_upload_data(), af)
            assert r["success"] is False

    @pytest.mark.asyncio
    async def test_library_exception(self):
        integ = _make_integrator()
        with tempfile.TemporaryDirectory() as td:
            af = _audio_file(td)
            integ.client.get = AsyncMock(side_effect=ConnectionError("refused"))
            r = await integ._real_api_call(_upload_data(), af)
            assert r["success"] is False

    @pytest.mark.asyncio
    async def test_no_audio_file(self):
        integ = _make_integrator()
        from src.audiobook_studio.publish.audiobookshelf_integration import (
            AudiobookFile,
        )

        af = AudiobookFile(
            file_path=Path("/nonexistent.m4b"),
            size_bytes=0,
            duration_seconds=60,
            format="m4b",
            bitrate_kbps=64,
            checksum_md5="x",
        )
        integ.client.get = AsyncMock(
            return_value=_resp(200, {"folders": [{"id": "f1"}]})
        )
        r = await integ._real_api_call(_upload_data(), af)
        assert r["success"] is False

    @pytest.mark.asyncio
    async def test_upload_success(self):
        integ = _make_integrator()
        with tempfile.TemporaryDirectory() as td:
            af = _audio_file(td)
            search_r = _resp(200, [])  # empty search results

            async def mock_get(url, **kwargs):
                if "search" in url:
                    return search_r
                return _resp(200, {"folders": [{"id": "f1"}]})

            integ.client.get = mock_get
            integ.client.post = AsyncMock(return_value=_resp(201))
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_upload_data(), af)
            assert r["success"] is True
            assert r["uploaded_files"] == 1

    @pytest.mark.asyncio
    async def test_upload_error(self):
        integ = _make_integrator()
        with tempfile.TemporaryDirectory() as td:
            af = _audio_file(td)
            integ.client.get = AsyncMock(
                return_value=_resp(200, {"folders": [{"id": "f1"}]})
            )
            integ.client.post = AsyncMock(return_value=_resp(500, text="err"))
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_upload_data(), af)
            assert r["success"] is False

    @pytest.mark.asyncio
    async def test_upload_exception(self):
        integ = _make_integrator()
        with tempfile.TemporaryDirectory() as td:
            af = _audio_file(td)
            integ.client.get = AsyncMock(
                return_value=_resp(200, {"folders": [{"id": "f1"}]})
            )
            integ.client.post = AsyncMock(side_effect=ConnectionError("refused"))
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_upload_data(), af)
            assert r["success"] is False

    @pytest.mark.asyncio
    async def test_scan_exception(self):
        integ = _make_integrator()
        with tempfile.TemporaryDirectory() as td:
            af = _audio_file(td)
            integ.client.get = AsyncMock(
                return_value=_resp(200, {"folders": [{"id": "f1"}]})
            )
            integ.client.post = AsyncMock(return_value=_resp(201))
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_upload_data(), af)
            assert r["success"] is True

    @pytest.mark.asyncio
    async def test_metadata_update(self):
        integ = _make_integrator()
        with tempfile.TemporaryDirectory() as td:
            af = _audio_file(td)
            search_r = _resp(200, [{"id": "i1", "media": {"metadata": {"title": "t"}}}])

            async def mock_get(url, **kwargs):
                if "search" in url:
                    return search_r
                return _resp(200, {"folders": [{"id": "f1"}]})

            integ.client.get = mock_get
            integ.client.post = AsyncMock(return_value=_resp(201))
            integ.client.patch = AsyncMock(return_value=_resp(204))
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_upload_data(), af)
            assert r["success"] is True
            assert r["item_id"] == "i1"

    @pytest.mark.asyncio
    async def test_metadata_patch_exception(self):
        integ = _make_integrator()
        with tempfile.TemporaryDirectory() as td:
            af = _audio_file(td)
            search_r = _resp(200, [{"id": "i1", "media": {"metadata": {"title": "t"}}}])

            async def mock_get(url, **kwargs):
                if "search" in url:
                    return search_r
                return _resp(200, {"folders": [{"id": "f1"}]})

            integ.client.get = mock_get
            integ.client.post = AsyncMock(return_value=_resp(201))
            integ.client.patch = AsyncMock(side_effect=ConnectionError("fail"))
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_upload_data(), af)
            assert r["success"] is True

    @pytest.mark.asyncio
    async def test_search_exception(self):
        integ = _make_integrator()
        with tempfile.TemporaryDirectory() as td:
            af = _audio_file(td)

            async def mock_get_exc(url, **kwargs):
                if "search" in url:
                    raise ConnectionError("fail")
                return _resp(200, {"folders": [{"id": "f1"}]})

            integ.client.get = mock_get_exc
            integ.client.post = AsyncMock(return_value=_resp(201))
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(_upload_data(), af)
            assert r["success"] is True

    @pytest.mark.asyncio
    async def test_cover_upload(self):
        import base64

        integ = _make_integrator()
        with tempfile.TemporaryDirectory() as td:
            af = _audio_file(td)
            ud = _upload_data()
            ud["coverImage"] = base64.b64encode(b"img").decode()
            search_r = _resp(200, [{"id": "i1", "media": {"metadata": {"title": "t"}}}])

            async def mock_get(url, **kwargs):
                if "search" in url:
                    return search_r
                return _resp(200, {"folders": [{"id": "f1"}]})

            integ.client.get = mock_get
            integ.client.post = AsyncMock(return_value=_resp(201))
            integ.client.patch = AsyncMock(return_value=_resp(204))
            with patch("asyncio.sleep", new_callable=AsyncMock):
                r = await integ._real_api_call(ud, af)
            assert r["success"] is True

    @pytest.mark.asyncio
    async def test_get_library_status_ok(self):
        integ = _make_integrator()
        integ.client.get = AsyncMock(
            return_value=_resp(200, {"mediaCount": 10, "duration": 7200})
        )
        s = await integ.get_library_status()
        assert s["total_books"] == 10

    @pytest.mark.asyncio
    async def test_get_library_status_exception(self):
        integ = _make_integrator()
        integ.client.get = AsyncMock(side_effect=ConnectionError("fail"))
        s = await integ.get_library_status()
        assert s["status"] == "offline"
