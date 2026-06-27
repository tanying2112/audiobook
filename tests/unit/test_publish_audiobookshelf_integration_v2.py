"""Comprehensive tests for publish/audiobookshelf_integration.py."""
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

# Force MOCK_LLM so httpx.AsyncClient in integrator.__init__ doesn't block
os.environ["MOCK_LLM"] = "true"

from src.audiobook_studio.publish.audiobookshelf_integration import (
    AudiobookshelfAPIClient,
    AudiobookshelfConfig,
    AudiobookshelfIntegrator,
    AudiobookFile,
    AudiobookMetadata,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_integrator(config=None):
    """Create an integrator with a fully replaceable AsyncClient."""
    cfg = config or AudiobookshelfConfig(
        api_url="http://localhost:1337",
        api_key="test_key_123",
        library_id="lib_1",
    )
    # Patch httpx.AsyncClient so no real network call in __init__
    with patch("httpx.AsyncClient"):
        integrator = AudiobookshelfIntegrator(cfg)
    return integrator


def _attach_client(integrator):
    """Replace integrator.client with an AsyncMock and return it."""
    client = AsyncMock()
    integrator.client = client
    return client


def _make_metadata(**overrides):
    defaults = dict(
        title="Test Book", author="Author", narrator="Narrator",
        description="Desc", language="zh-CN", publication_year=2024,
        publisher="Pub", genres=["fiction"], tags=["t"],
        series="S", series_index=1.0,
    )
    defaults.update(overrides)
    return AudiobookMetadata(**defaults)


def _make_audio_file(tmp_path, fmt="m4b", size=None, chapters=None):
    f = tmp_path / f"test.{fmt}"
    content = b"x" * (size or 100)
    f.write_bytes(content)
    return AudiobookFile(
        file_path=f, size_bytes=f.stat().st_size, duration_seconds=3600.0,
        format=fmt, bitrate_kbps=64, checksum_md5="abc",
        chapters=chapters if chapters is not None else [{"title": "Ch1", "start": 0, "end": 1800}],
    )


async def _library_ok(client, folder_id="f1"):
    """Wire client.get/post/patch for a happy-path library+folder response."""
    lib_resp = MagicMock(); lib_resp.status_code = 200
    lib_resp.json.return_value = {"folders": [{"id": folder_id}]}
    client.get = AsyncMock(return_value=lib_resp)
    return client


async def _full_publish_mocks(client, item_id="i1", metadata_title="Test Book"):
    """Wire client for a complete publish flow returning item_id."""
    lib_resp = MagicMock(); lib_resp.status_code = 200
    lib_resp.json.return_value = {"folders": [{"id": "f1"}]}

    upload_resp = MagicMock(); upload_resp.status_code = 200

    scan_resp = MagicMock(); scan_resp.status_code = 200

    search_resp = MagicMock(); search_resp.status_code = 200
    search_resp.json.return_value = [
        {"id": item_id, "media": {"metadata": {"title": metadata_title}}}
    ]

    patch_resp = MagicMock(); patch_resp.status_code = 200

    async def _get(url, **kw):
        if "search" in url:
            return search_resp
        return lib_resp

    async def _post(url, **kw):
        if "scan" in url:
            return scan_resp
        return upload_resp

    client.get = _get
    client.post = _post
    client.patch = AsyncMock(return_value=patch_resp)
    return client


# ── Stub / client ────────────────────────────────────────────────────────────

class TestAudiobookshelfAPIClient:
    def test_stub(self):
        c = AudiobookshelfAPIClient("url", key="k")
        assert c.check_connection() is True
        assert c.upload_audiobook() is True


# ── Data classes ─────────────────────────────────────────────────────────────

class TestDataClasses:
    def test_config_defaults(self):
        c = AudiobookshelfConfig(api_url="http://x", api_key="k", library_id="1")
        assert "m4b" in c.supported_formats
        assert c.auto_convert is True

    def test_metadata_defaults(self):
        m = AudiobookMetadata(title="T", author="A", narrator="N", description="D")
        assert m.language == "zh-CN"

    def test_file_defaults(self):
        af = AudiobookFile(file_path=Path("/tmp/x.m4b"), size_bytes=100,
                           duration_seconds=10, format="m4b", bitrate_kbps=64, checksum_md5="h")
        assert af.chapters == []


# ── Init / close ────────────────────────────────────────────────────────────

class TestInitClose:
    def test_init(self):
        i = _make_integrator()
        assert i.base_url == "http://localhost:1337"
        assert "m4b" in i.supported_formats

    def test_close(self):
        i = _make_integrator()
        i.client = AsyncMock()
        _run(i.close())
        i.client.aclose.assert_awaited_once()


# ── Validation ───────────────────────────────────────────────────────────────

class TestValidation:
    def test_metadata_ok(self):
        i = _make_integrator()
        ok, _ = i._validate_metadata(_make_metadata())
        assert ok

    @pytest.mark.parametrize("field,val", [("title", " "), ("author", ""), ("narrator", "  ")])
    def test_metadata_empty(self, field, val):
        i = _make_integrator()
        m = _make_metadata(**{field: val})
        ok, _ = i._validate_metadata(m)
        assert not ok

    @pytest.mark.parametrize("year", [500, 2101])
    def test_metadata_bad_year(self, year):
        i = _make_integrator()
        m = _make_metadata(publication_year=year)
        ok, _ = i._validate_metadata(m)
        assert not ok

    def test_audio_file_missing(self):
        i = _make_integrator()
        af = AudiobookFile(Path("/no/such"), 0, 0, "m4b", 64, "")
        ok, _ = i._validate_audio_file(af)
        assert not ok

    def test_audio_file_size_mismatch(self, tmp_path):
        i = _make_integrator()
        f = tmp_path / "t.m4b"; f.write_bytes(b"d")
        af = AudiobookFile(f, 9999, 1, "m4b", 64, "")
        ok, _ = i._validate_audio_file(af)
        assert not ok

    def test_audio_file_ext_mismatch(self, tmp_path):
        i = _make_integrator()
        f = tmp_path / "t.mp3"; f.write_bytes(b"d")
        af = AudiobookFile(f, f.stat().st_size, 1, "m4b", 64, "")
        ok, _ = i._validate_audio_file(af)
        assert not ok

    def test_audio_file_ok(self, tmp_path):
        i = _make_integrator()
        af = _make_audio_file(tmp_path)
        ok, _ = i._validate_audio_file(af)
        assert ok

    def test_audio_file_is_directory(self, tmp_path):
        i = _make_integrator()
        d = tmp_path / "d.m4b"; d.mkdir()
        af = AudiobookFile(d, 0, 0, "m4b", 64, "")
        ok, _ = i._validate_audio_file(af)
        assert not ok


# ── prepare_audiobook ────────────────────────────────────────────────────────

class TestPrepareAudiobook:
    def test_ok(self, tmp_path):
        i = _make_integrator()
        ok, _, data = _run(i.prepare_audiobook(_make_metadata(), _make_audio_file(tmp_path)))
        assert ok and data["title"] == "Test Book"

    def test_unsupported_format_no_convert(self, tmp_path):
        i = _make_integrator()
        i.config.auto_convert = False
        af = _make_audio_file(tmp_path, fmt="ogg")
        ok, msg, _ = _run(i.prepare_audiobook(_make_metadata(), af))
        assert not ok and "不支持的格式" in msg

    def test_unsupported_format_auto_convert(self, tmp_path):
        i = _make_integrator()
        af = _make_audio_file(tmp_path, fmt="ogg")
        ok, msg, _ = _run(i.prepare_audiobook(_make_metadata(), af))
        assert not ok and "自动转换" in msg

    def test_invalid_metadata(self, tmp_path):
        i = _make_integrator()
        ok, _, _ = _run(i.prepare_audiobook(_make_metadata(title=""), _make_audio_file(tmp_path)))
        assert not ok


# ── _prepare_upload_data ─────────────────────────────────────────────────────

class TestUploadData:
    def test_no_chapters_creates_default(self):
        i = _make_integrator()
        af = AudiobookFile(Path("/x.m4b"), 100, 600, "m4b", 64, "h")
        data = i._prepare_upload_data(_make_metadata(), af)
        assert len(data["chapters"]) == 1 and data["chapters"][0]["end"] == 600

    def test_chapters_preserved(self, tmp_path):
        i = _make_integrator()
        data = i._prepare_upload_data(_make_metadata(), _make_audio_file(tmp_path))
        assert data["chapters"][0]["title"] == "Ch1"

    def test_cover_image(self, tmp_path):
        i = _make_integrator()
        cover = tmp_path / "c.jpg"; cover.write_bytes(b"\xff\xd8" + b"\x00" * 10)
        m = _make_metadata(cover_image_path=cover)
        data = i._prepare_upload_data(m, _make_audio_file(tmp_path))
        assert data["coverImage"] is not None

    def test_no_cover(self, tmp_path):
        i = _make_integrator()
        data = i._prepare_upload_data(_make_metadata(), _make_audio_file(tmp_path))
        assert data["coverImage"] is None


# ── _get_mime_type ───────────────────────────────────────────────────────────

class TestMime:
    @pytest.mark.parametrize("ext,exp", [
        (".m4b", "audio/mp4"), (".mp3", "audio/mpeg"), (".wav", "audio/wav"),
        (".flac", "audio/flac"), (".ogg", "audio/ogg"), (".aac", "audio/aac"),
        (".xyz", "application/octet-stream"),
    ])
    def test(self, ext, exp):
        assert _make_integrator()._get_mime_type(Path(f"f{ext}")) == exp


# ── get_library_status ──────────────────────────────────────────────────────

class TestLibraryStatus:
    def test_online(self):
        i = _make_integrator()
        client = _attach_client(i)
        resp = MagicMock(); resp.status_code = 200
        resp.json.return_value = {"mediaCount": 42, "duration": 36000}
        client.get = AsyncMock(return_value=resp)
        s = _run(i.get_library_status())
        assert s["status"] == "online" and s["total_books"] == 42

    def test_error(self):
        i = _make_integrator()
        client = _attach_client(i)
        client.get = AsyncMock(side_effect=Exception("net"))
        s = _run(i.get_library_status())
        assert s["status"] == "offline"

    def test_non_200(self):
        i = _make_integrator()
        client = _attach_client(i)
        resp = MagicMock(); resp.status_code = 500
        client.get = AsyncMock(return_value=resp)
        s = _run(i.get_library_status())
        assert s["status"] == "offline"


# ── publish_to_audiobookshelf ────────────────────────────────────────────────

class TestPublish:
    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_success(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        _run(_full_publish_mocks(client, "item99"))
        ok, msg, resp = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert ok and resp["item_id"] == "item99"

    def test_prepare_fails(self, tmp_path):
        i = _make_integrator()
        ok, _, _ = _run(i.publish_to_audiobookshelf(_make_metadata(title=""), _make_audio_file(tmp_path)))
        assert not ok

    def test_library_404(self, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        resp = MagicMock(); resp.status_code = 404
        client.get = AsyncMock(return_value=resp)
        client.post = AsyncMock()
        ok, msg, _ = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert not ok and "不存在" in msg

    def test_no_folders(self, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        resp = MagicMock(); resp.status_code = 200; resp.json.return_value = {"folders": []}
        client.get = AsyncMock(return_value=resp)
        client.post = AsyncMock()
        ok, msg, _ = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert not ok and "文件夹" in msg

    def test_library_exception(self, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        client.get = AsyncMock(side_effect=Exception("timeout"))
        client.post = AsyncMock()
        ok, _, _ = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert not ok

    def test_empty_library_id(self, tmp_path):
        i = _make_integrator()
        i.config.library_id = ""
        ok, msg, _ = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert not ok and "未配置" in msg

    def test_non_200_library(self, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        resp = MagicMock(); resp.status_code = 503; resp.text = "Unavailable"
        client.get = AsyncMock(return_value=resp)
        client.post = AsyncMock()
        ok, _, _ = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert not ok

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_all_uploads_fail(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        lib_resp = MagicMock(); lib_resp.status_code = 200
        lib_resp.json.return_value = {"folders": [{"id": "f1"}]}
        upload_resp = MagicMock(); upload_resp.status_code = 500; upload_resp.text = "err"
        client.get = AsyncMock(return_value=lib_resp)
        client.post = AsyncMock(return_value=upload_resp)
        ok, _, resp = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert not ok and "所有文件上传失败" in resp["message"]

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_upload_exception(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        lib_resp = MagicMock(); lib_resp.status_code = 200
        lib_resp.json.return_value = {"folders": [{"id": "f1"}]}
        client.get = AsyncMock(return_value=lib_resp)
        client.post = AsyncMock(side_effect=Exception("io"))
        ok, _, _ = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert not ok

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_no_item_found(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        lib_resp = MagicMock(); lib_resp.status_code = 200
        lib_resp.json.return_value = {"folders": [{"id": "f1"}]}
        upload_resp = MagicMock(); upload_resp.status_code = 200
        search_resp = MagicMock(); search_resp.status_code = 200; search_resp.json.return_value = []

        async def _get(url, **kw):
            return search_resp if "search" in url else lib_resp

        client.get = _get
        client.post = AsyncMock(return_value=upload_resp)
        client.patch = AsyncMock()
        ok, _, resp = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert ok and resp["item_id"] is None and "未能确认项目 ID" in resp["message"]

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_file_not_exist(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        lib_resp = MagicMock(); lib_resp.status_code = 200
        lib_resp.json.return_value = {"folders": [{"id": "f1"}]}
        client.get = AsyncMock(return_value=lib_resp)
        client.post = AsyncMock()
        af = AudiobookFile(Path("/nonexistent"), 100, 10, "m4b", 64, "h")
        ok, msg, _ = _run(i.publish_to_audiobookshelf(_make_metadata(), af))
        assert not ok and ("未找到音频文件" in msg or "音频文件不存在" in msg or "不存在" in msg)

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_patch_fails_non_fatal(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        _run(_full_publish_mocks(client))
        client.patch = AsyncMock(return_value=MagicMock(status_code=500, text="err"))
        ok, _, resp = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert ok and resp["item_id"] is not None

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_patch_exception_non_fatal(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        _run(_full_publish_mocks(client))
        client.patch = AsyncMock(side_effect=Exception("patch err"))
        ok, _, resp = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert ok and resp["item_id"] is not None

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_scan_500_non_fatal(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        lib_resp = MagicMock(); lib_resp.status_code = 200
        lib_resp.json.return_value = {"folders": [{"id": "f1"}]}
        upload_resp = MagicMock(); upload_resp.status_code = 200
        scan_resp = MagicMock(); scan_resp.status_code = 500
        search_resp = MagicMock(); search_resp.status_code = 200
        search_resp.json.return_value = [{"id": "i1", "media": {"metadata": {"title": "Test Book"}}}]
        patch_resp = MagicMock(); patch_resp.status_code = 200

        async def _get(url, **kw):
            return search_resp if "search" in url else lib_resp

        async def _post(url, **kw):
            return scan_resp if "scan" in url else upload_resp

        client.get = _get; client.post = _post
        client.patch = AsyncMock(return_value=patch_resp)
        ok, _, resp = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert ok

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_scan_exception_non_fatal(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        lib_resp = MagicMock(); lib_resp.status_code = 200
        lib_resp.json.return_value = {"folders": [{"id": "f1"}]}
        upload_resp = MagicMock(); upload_resp.status_code = 200
        search_resp = MagicMock(); search_resp.status_code = 200
        search_resp.json.return_value = [{"id": "i1", "media": {"metadata": {"title": "Test Book"}}}]
        patch_resp = MagicMock(); patch_resp.status_code = 200

        async def _get(url, **kw):
            return search_resp if "search" in url else lib_resp

        async def _post(url, **kw):
            if "scan" in url:
                raise Exception("scan err")
            return upload_resp

        client.get = _get; client.post = _post
        client.patch = AsyncMock(return_value=patch_resp)
        ok, _, resp = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert ok

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_search_exception(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        lib_resp = MagicMock(); lib_resp.status_code = 200
        lib_resp.json.return_value = {"folders": [{"id": "f1"}]}
        upload_resp = MagicMock(); upload_resp.status_code = 200

        async def _get(url, **kw):
            if "search" in url:
                raise Exception("search err")
            return lib_resp

        client.get = _get
        client.post = AsyncMock(return_value=upload_resp)
        client.patch = AsyncMock()
        ok, _, resp = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert ok and resp["item_id"] is None

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_search_title_mismatch(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        lib_resp = MagicMock(); lib_resp.status_code = 200
        lib_resp.json.return_value = {"folders": [{"id": "f1"}]}
        upload_resp = MagicMock(); upload_resp.status_code = 200
        search_resp = MagicMock(); search_resp.status_code = 200
        search_resp.json.return_value = [{"id": "i1", "media": {"metadata": {"title": "Other"}}}]
        patch_resp = MagicMock(); patch_resp.status_code = 200

        async def _get(url, **kw):
            return search_resp if "search" in url else lib_resp

        client.get = _get; client.post = AsyncMock(return_value=upload_resp)
        client.patch = AsyncMock(return_value=patch_resp)
        ok, _, resp = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert ok and resp["item_id"] is None

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_search_non_200(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        lib_resp = MagicMock(); lib_resp.status_code = 200
        lib_resp.json.return_value = {"folders": [{"id": "f1"}]}
        upload_resp = MagicMock(); upload_resp.status_code = 200
        search_resp = MagicMock(); search_resp.status_code = 500

        async def _get(url, **kw):
            return search_resp if "search" in url else lib_resp

        client.get = _get; client.post = AsyncMock(return_value=upload_resp)
        client.patch = AsyncMock()
        ok, _, resp = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert ok and resp["item_id"] is None

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_search_missing_media(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        lib_resp = MagicMock(); lib_resp.status_code = 200
        lib_resp.json.return_value = {"folders": [{"id": "f1"}]}
        upload_resp = MagicMock(); upload_resp.status_code = 200
        search_resp = MagicMock(); search_resp.status_code = 200
        search_resp.json.return_value = [{"id": "i1"}]

        async def _get(url, **kw):
            return search_resp if "search" in url else lib_resp

        client.get = _get; client.post = AsyncMock(return_value=upload_resp)
        client.patch = AsyncMock()
        ok, _, resp = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert ok and resp["item_id"] is None

    def test_network_exception(self, tmp_path):
        i = _make_integrator()
        i.prepare_audiobook = AsyncMock(return_value=(True, "ok", {"title": "T"}))
        i._real_api_call = AsyncMock(side_effect=Exception("net"))
        ok, msg, _ = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert not ok and "网络错误" in msg

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_language_short_code(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        _run(_full_publish_mocks(client))
        m = _make_metadata(language="en")
        ok, _, resp = _run(i.publish_to_audiobookshelf(m, _make_audio_file(tmp_path)))
        assert ok
        lang = client.patch.call_args[1]["json"]["metadata"]["language"]
        assert lang == "en-US"

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_language_ja(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        _run(_full_publish_mocks(client))
        m = _make_metadata(language="ja")
        ok, _, _ = _run(i.publish_to_audiobookshelf(m, _make_audio_file(tmp_path)))
        assert ok
        lang = client.patch.call_args[1]["json"]["metadata"]["language"]
        assert lang == "ja-JP"

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_language_ko(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        _run(_full_publish_mocks(client))
        m = _make_metadata(language="ko")
        ok, _, _ = _run(i.publish_to_audiobookshelf(m, _make_audio_file(tmp_path)))
        assert ok
        lang = client.patch.call_args[1]["json"]["metadata"]["language"]
        assert lang == "ko-KR"

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_language_unknown_short(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        _run(_full_publish_mocks(client))
        m = _make_metadata(language="fr")
        ok, _, _ = _run(i.publish_to_audiobookshelf(m, _make_audio_file(tmp_path)))
        assert ok
        lang = client.patch.call_args[1]["json"]["metadata"]["language"]
        assert lang == "fr"

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_all_metadata_fields(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        _run(_full_publish_mocks(client))
        m = _make_metadata(tags=["a", "b"], publisher="P", genres=["g1"], language="zh-CN")
        ok, _, _ = _run(i.publish_to_audiobookshelf(m, _make_audio_file(tmp_path)))
        assert ok
        meta = client.patch.call_args[1]["json"]["metadata"]
        for key in ("tags", "publisher", "genre", "series", "seriesSequence", "chapters", "language", "description"):
            assert key in meta

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_cover_upload_exception(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        _run(_full_publish_mocks(client))
        cover_resp = MagicMock(); cover_resp.status_code = 200
        # Make post fail on 3rd call (cover upload)
        original_post = client.post
        call_count = [0]
        async def _post(url, **kw):
            call_count[0] += 1
            if "cover" in url:
                raise Exception("cover err")
            return await original_post(url, **kw)
        client.post = _post

        m = _make_metadata()
        m.cover_image_path = Path("/tmp/fake.jpg")
        with patch.object(Path, "exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=b"fake")):
            ok, _, resp = _run(i.publish_to_audiobookshelf(m, _make_audio_file(tmp_path)))
        assert ok and resp["item_id"] is not None

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_cover_upload_non_200(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        _run(_full_publish_mocks(client))
        cover_resp = MagicMock(); cover_resp.status_code = 500
        original_post = client.post
        async def _post(url, **kw):
            if "cover" in url:
                return cover_resp
            return await original_post(url, **kw)
        client.post = _post

        m = _make_metadata()
        m.cover_image_path = Path("/tmp/fake.jpg")
        with patch.object(Path, "exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=b"fake")):
            ok, _, resp = _run(i.publish_to_audiobookshelf(m, _make_audio_file(tmp_path)))
        assert ok

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_cover_bad_base64(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        _run(_full_publish_mocks(client))
        m = _make_metadata()
        # Inject invalid base64 into upload_data
        data = i._prepare_upload_data(m, _make_audio_file(tmp_path))
        data["coverImage"] = "NOT_BASE64!!!"
        i.prepare_audiobook = AsyncMock(return_value=(True, "ok", data))
        ok, _, resp = _run(i.publish_to_audiobookshelf(m, _make_audio_file(tmp_path)))
        assert ok

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_metadata_patch_exception_in_cover(self, _, tmp_path):
        """Cover upload after patch exception."""
        i = _make_integrator()
        client = _attach_client(i)
        _run(_full_publish_mocks(client))
        client.patch = AsyncMock(side_effect=Exception("patch err"))

        m = _make_metadata()
        m.cover_image_path = Path("/tmp/fake.jpg")
        with patch.object(Path, "exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=b"fake")):
            ok, _, resp = _run(i.publish_to_audiobookshelf(m, _make_audio_file(tmp_path)))
        assert ok

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_base_path_local_library(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        i.config.base_path = str(tmp_path / "library")
        lib_resp = MagicMock(); lib_resp.status_code = 200
        lib_resp.json.return_value = {"folders": [{"id": "f1"}]}
        client.get = AsyncMock(return_value=lib_resp)
        search_resp = MagicMock(); search_resp.status_code = 200; search_resp.json.return_value = []
        scan_resp = MagicMock(); scan_resp.status_code = 200
        patch_resp = MagicMock(); patch_resp.status_code = 200

        async def _get(url, **kw):
            return search_resp if "search" in url else lib_resp
        client.get = _get
        client.post = AsyncMock(return_value=scan_resp)
        client.patch = AsyncMock(return_value=patch_resp)

        with patch("shutil.copy2"), patch("pathlib.Path.mkdir"):
            ok, _, resp = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert ok and resp["uploaded_files"] == 1

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_base_path_mkdir_fails(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        i.config.base_path = str(tmp_path / "library")
        lib_resp = MagicMock(); lib_resp.status_code = 200
        lib_resp.json.return_value = {"folders": [{"id": "f1"}]}
        client.get = AsyncMock(return_value=lib_resp)
        search_resp = MagicMock(); search_resp.status_code = 200; search_resp.json.return_value = []
        scan_resp = MagicMock(); scan_resp.status_code = 200

        client.post = AsyncMock(return_value=scan_resp)
        client.patch = AsyncMock()

        with patch("pathlib.Path.mkdir", side_effect=Exception("perm")), \
             patch("shutil.copy2"):
            ok, _, resp = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert ok

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_base_path_copy_fails(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        i.config.base_path = str(tmp_path / "library")
        lib_resp = MagicMock(); lib_resp.status_code = 200
        lib_resp.json.return_value = {"folders": [{"id": "f1"}]}
        client.get = AsyncMock(return_value=lib_resp)
        search_resp = MagicMock(); search_resp.status_code = 200; search_resp.json.return_value = []
        scan_resp = MagicMock(); scan_resp.status_code = 200

        client.post = AsyncMock(return_value=scan_resp)
        client.patch = AsyncMock()

        with patch("pathlib.Path.mkdir"), \
             patch("shutil.copy2", side_effect=Exception("copy err")):
            ok, _, resp = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        # Still ok because one file fails but we only have one
        assert not ok  # 0 successful uploads

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_search_multiple_items(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        lib_resp = MagicMock(); lib_resp.status_code = 200
        lib_resp.json.return_value = {"folders": [{"id": "f1"}]}
        upload_resp = MagicMock(); upload_resp.status_code = 200
        search_resp = MagicMock(); search_resp.status_code = 200
        search_resp.json.return_value = [
            {"id": "wrong1", "media": {"metadata": {"title": "Wrong"}}},
            {"id": "correct1", "media": {"metadata": {"title": "Test Book"}}},
        ]
        patch_resp = MagicMock(); patch_resp.status_code = 200

        async def _get(url, **kw):
            return search_resp if "search" in url else lib_resp

        client.get = _get; client.post = AsyncMock(return_value=upload_resp)
        client.patch = AsyncMock(return_value=patch_resp)
        ok, _, resp = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert ok and resp["item_id"] == "correct1"

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_search_empty_media(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        lib_resp = MagicMock(); lib_resp.status_code = 200
        lib_resp.json.return_value = {"folders": [{"id": "f1"}]}
        upload_resp = MagicMock(); upload_resp.status_code = 200
        search_resp = MagicMock(); search_resp.status_code = 200
        search_resp.json.return_value = [{"id": "i1", "media": None}]
        patch_resp = MagicMock(); patch_resp.status_code = 200

        async def _get(url, **kw):
            return search_resp if "search" in url else lib_resp

        client.get = _get; client.post = AsyncMock(return_value=upload_resp)
        client.patch = AsyncMock(return_value=patch_resp)
        ok, _, resp = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert ok and resp["item_id"] is None

    @patch("asyncio.sleep", new_callable=AsyncMock)
    def test_upload_read_file_error(self, _, tmp_path):
        i = _make_integrator()
        client = _attach_client(i)
        lib_resp = MagicMock(); lib_resp.status_code = 200
        lib_resp.json.return_value = {"folders": [{"id": "f1"}]}
        client.get = AsyncMock(return_value=lib_resp)

        original_post = client.post
        async def _post(url, **kw):
            if "scan" not in url and "upload" not in url:
                return await original_post(url, **kw)
            # simulate upload failure for file reading
            raise Exception("read error")
        client.post = _post
        client.patch = AsyncMock()
        ok, _, _ = _run(i.publish_to_audiobookshelf(_make_metadata(), _make_audio_file(tmp_path)))
        assert not ok
