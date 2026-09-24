"""Phase B coverage tests for export/mp3.py (ID3v2.4 tagging).

Two tracks:
1. Real environment (mutagen absent): honest-degradation branches, error paths,
   pure dataclasses/helpers, zip packing and batch export plumbing.
2. Mocked mutagen: drive every write branch (basic frames, cover APIC,
   chapters+TOC, USLT/SYLT lyrics incl. CJK language detection).
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import src.audiobook_studio.export.mp3 as mp3mod
from src.audiobook_studio.export.mp3 import (
    ChapterInfo,
    Mp3Metadata,
    add_mp3_to_zip,
    export_mp3_chapters,
    read_id3_tags,
    write_chapters_only,
    write_id3_tags,
)

MOD = "src.audiobook_studio.export.mp3"


def make_mp3_like(tmp_path: Path, name="book.mp3") -> Path:
    """Create a file that passes exists() checks (content irrelevant when mutagen mocked)."""
    f = tmp_path / name
    f.write_bytes(b"ID3" + b"\x00" * 64)
    return f


# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses & degradation branches (no mutagen required)
# ─────────────────────────────────────────────────────────────────────────────


class TestChapterInfo:
    def test_seconds_properties(self):
        ch = ChapterInfo(title="第一章", start_ms=1500, end_ms=92500)
        assert ch.start_seconds == pytest.approx(1.5)
        assert ch.end_seconds == pytest.approx(92.5)


class TestMp3MetadataDefaults:
    def test_defaults(self):
        m = Mp3Metadata()
        assert m.genre == "Audiobook"
        assert m.disc == 1
        assert m.track == 0
        assert m.chapters == []
        assert m.cover_image is None


@pytest.mark.skipif(mp3mod.MUTAGEN_AVAILABLE, reason="mutagen installed: degradation branches unreachable")
class TestDegradationWithoutMutagen:
    def test_write_id3_returns_path_untouched(self, tmp_path):
        f = make_mp3_like(tmp_path)
        assert write_id3_tags(f, Mp3Metadata(title="t")) == f

    def test_write_chapters_only_returns_path(self, tmp_path):
        f = make_mp3_like(tmp_path)
        assert write_chapters_only(f, [ChapterInfo("c", 0, 1000)]) == f

    def test_read_id3_reports_unavailable(self, tmp_path):
        assert read_id3_tags(make_mp3_like(tmp_path)) == {"error": "mutagen not available"}


class TestCommonGuards:
    def test_write_id3_missing_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mp3mod, "MUTAGEN_AVAILABLE", True, raising=False)
        with pytest.raises(FileNotFoundError):
            write_id3_tags(tmp_path / "ghost.mp3", Mp3Metadata())

    def test_read_id3_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mp3mod, "MUTAGEN_AVAILABLE", True, raising=False)
        assert read_id3_tags(tmp_path / "ghost.mp3") == {"error": "File not found"}


# ─────────────────────────────────────────────────────────────────────────────
# Full write path with mocked mutagen frame classes
# ─────────────────────────────────────────────────────────────────────────────


class FakeTags(dict):
    """dict mimicking mutagen ID3 tags: mapping protocol + add()/keys()."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)

    def add(self, frame):
        # MagicMock 帧类名即帧 ID（TIT2/TPE1/...），CHAP/CTOC 在 mutagen 中
        # 实际键带 element_id 后缀，这里只需保证同类型可覆盖即可。
        cls_name = type(frame).__name__
        if cls_name.startswith("MagicMock") or cls_name == "Mock":
            cls_name = f"frame_{id(frame):x}"
        self[cls_name] = frame

    def save(self, path, v2_version=4):
        self.saved_with_version = v2_version


def install_mock_mutagen(monkeypatch, existing_tags=None):
    """Patch module constants so the write path runs end-to-end."""
    tags = FakeTags(existing_tags or {})
    audio = MagicMock()
    audio.tags = tags

    frame_classes = SimpleNamespace(
        **{
            name: MagicMock(name=name)
            for name in [
                "TIT2",
                "TPE1",
                "TALB",
                "TDRC",
                "TCON",
                "TRCK",
                "TPOS",
                "APIC",
                "CHAP",
                "CTOC",
                "USLT",
                "SYLT",
                "COMM",
                "TXXX",
            ]
        }
    )

    mp3_cls = MagicMock(return_value=audio)
    monkeypatch.setattr(mp3mod, "MUTAGEN_AVAILABLE", True, raising=False)
    monkeypatch.setattr(mp3mod, "MP3", mp3_cls, raising=False)
    for name, cls in vars(frame_classes).items():
        # mutagen 缺席时这些名字不在模块命名空间里
        monkeypatch.setattr(mp3mod, name, cls, raising=False)
    monkeypatch.setattr(mp3mod, "ID3", MagicMock(), raising=False)
    return audio, tags, frame_classes


class TestWriteId3FullPath:
    def _meta(self, **kw):
        base = dict(
            title="三体",
            artist="刘慈欣",
            album="地球往事",
            year="2008",
            genre="Sci-Fi",
            track=3,
            disc=2,
        )
        base.update(kw)
        return Mp3Metadata(**base)

    def test_basic_frames_written_and_saved_v24(self, tmp_path, monkeypatch):
        f = make_mp3_like(tmp_path)
        audio, tags, frames = install_mock_mutagen(monkeypatch)
        out = write_id3_tags(f, self._meta())
        assert out == f
        for name in ("TIT2", "TPE1", "TALB", "TDRC", "TCON", "TRCK", "TPOS"):
            getattr(frames, name).assert_called_once()
        assert tags.saved_with_version == 4

    def test_empty_fields_skip_frames(self, tmp_path, monkeypatch):
        f = make_mp3_like(tmp_path)
        audio, tags, frames = install_mock_mutagen(monkeypatch)
        write_id3_tags(f, Mp3Metadata())  # everything default-empty
        frames.TIT2.assert_not_called()
        frames.TRCK.assert_not_called()  # track=0 skipped

    def test_existing_duplicate_frames_cleared_first(self, tmp_path, monkeypatch):
        f = make_mp3_like(tmp_path)
        audio, tags, frames = install_mock_mutagen(monkeypatch, existing_tags={"TIT2": "old", "APIC": "old-cover"})
        write_id3_tags(f, self._meta())
        assert "TIT2" not in tags or tags.get("TIT2") != "old"

    def test_cover_image_jpeg_mime(self, tmp_path, monkeypatch):
        f = make_mp3_like(tmp_path)
        cover = tmp_path / "cover.jpg"
        cover.write_bytes(b"\xff\xd8jpegdata")
        audio, tags, frames = install_mock_mutagen(monkeypatch)
        write_id3_tags(f, self._meta(cover_image=str(cover)))
        kwargs = frames.APIC.call_args.kwargs
        assert kwargs["mime"] == "image/jpeg"
        assert kwargs["data"] == b"\xff\xd8jpegdata"

    def test_cover_image_png_mime(self, tmp_path, monkeypatch):
        f = make_mp3_like(tmp_path)
        cover = tmp_path / "cover.png"
        cover.write_bytes(b"\x89PNG")
        audio, tags, frames = install_mock_mutagen(monkeypatch)
        write_id3_tags(f, self._meta(cover_image=str(cover)))
        assert frames.APIC.call_args.kwargs["mime"] == "image/png"

    def test_cover_missing_file_skips_apic(self, tmp_path, monkeypatch):
        f = make_mp3_like(tmp_path)
        audio, tags, frames = install_mock_mutagen(monkeypatch)
        write_id3_tags(f, self._meta(cover_image=str(tmp_path / "none.jpg")))
        frames.APIC.assert_not_called()

    def test_chapters_written_with_toc(self, tmp_path, monkeypatch):
        f = make_mp3_like(tmp_path)
        audio, tags, frames = install_mock_mutagen(monkeypatch)
        chapters = [
            ChapterInfo("开篇", 0, 60_000),
            ChapterInfo("发展", 60_000, 120_000),
        ]
        tags._frame_names = lambda: [type(v).__name__ for v in tags.values()]
        write_id3_tags(f, self._meta(chapters=chapters))
        assert frames.CHAP.call_count == 2
        chap_kwargs = frames.CHAP.call_args_list[0].kwargs
        assert chap_kwargs["element_id"] == "ch001"
        assert chap_kwargs["start_time"] == 0
        assert chap_kwargs["end_time"] == 60000
        toc_kwargs = frames.CTOC.call_args.kwargs
        assert toc_kwargs["child_element_ids"] == ["ch001", "ch002"]

    def test_uslt_language_detection_cjk_vs_ascii(self, tmp_path, monkeypatch):
        f = make_mp3_like(tmp_path)
        audio, tags, frames = install_mock_mutagen(monkeypatch)
        write_id3_tags(f, self._meta(lyrics="这是一段中文歌词"))
        assert frames.USLT.call_args.kwargs["lang"] == "chi"

        write_id3_tags(f, self._meta(lyrics="plain english lyrics"))
        assert frames.USLT.call_args.kwargs["lang"] == "eng"

    def test_sylt_milliseconds_and_language(self, tmp_path, monkeypatch):
        f = make_mp3_like(tmp_path)
        audio, tags, frames = install_mock_mutagen(monkeypatch)
        synced = [(1.5, "hello"), (3.0, "world")]
        write_id3_tags(f, self._meta(synced_lyrics=synced))
        kwargs = frames.SYLT.call_args.kwargs
        assert kwargs["lang"] == "eng"
        assert kwargs["format"] == 2
        assert [t for t, _ in kwargs["text"]] == [1500, 3000]

    def test_no_tags_added_implicitly(self, tmp_path, monkeypatch):
        f = make_mp3_like(tmp_path)
        audio, tags, frames = install_mock_mutagen(monkeypatch)
        fresh = FakeTags()
        audio.tags = None
        # 模拟 mutagen.add_tags(): 实例化并挂上全新空标签表
        audio.add_tags.side_effect = lambda: setattr(audio, "tags", fresh)
        write_id3_tags(f, self._meta())
        audio.add_tags.assert_called_once()
        assert fresh.saved_with_version == 4


class TestWriteChaptersOnly:
    def test_replaces_old_chap_ctoc_and_writes_toc(self, tmp_path, monkeypatch):
        f = make_mp3_like(tmp_path)
        existing = {"CHAP:ch001": "stale", "CTOC:toc": "stale", "TIT2": "keep me"}
        audio, tags, frames = install_mock_mutagen(monkeypatch, existing_tags=dict(existing))
        # restore real dict behaviour: our FakeTags IS a dict already
        chapters = [ChapterInfo("only", 0, 5000)]
        out = write_chapters_only(f, chapters)
        assert out == f
        assert "CHAP:ch001" not in tags
        assert "CTOC:toc" not in tags
        assert "TIT2" in tags  # non-chapter tag untouched
        frames.CHAP.assert_called_once()
        frames.CTOC.assert_called_once()

    def test_no_chapter_inputs_still_saves(self, tmp_path, monkeypatch):
        f = make_mp3_like(tmp_path)
        audio, tags, frames = install_mock_mutagen(monkeypatch)
        write_chapters_only(f, [])
        frames.CHAP.assert_not_called()
        frames.CTOC.assert_not_called()
        assert tags.saved_with_version == 4


class TestReadId3:
    def test_text_binary_and_str_fallbacks(self, tmp_path, monkeypatch):
        f = make_mp3_like(tmp_path)
        text_frame = type("F", (), {"text": ["标题"]})()
        bin_frame = type("F", (), {"data": b"\x01\x02\x03"})()  # 无 text 属性 → 走 binary 分支
        other_frame = type("F", (), {})()
        tags = {"TIT2": text_frame, "APIC": bin_frame, "WEIRD": other_frame}
        audio = MagicMock()
        audio.tags = tags
        monkeypatch.setattr(mp3mod, "MUTAGEN_AVAILABLE", True, raising=False)
        monkeypatch.setattr(mp3mod, "MP3", MagicMock(return_value=audio), raising=False)

        result = read_id3_tags(f)
        assert result["TIT2"] == ["标题"]
        assert "3 bytes" in result["APIC"]
        assert isinstance(result["WEIRD"], str) or result["WEIRD"] == str(other_frame)

    def test_none_tags_returns_empty(self, tmp_path, monkeypatch):
        f = make_mp3_like(tmp_path)
        audio = MagicMock()
        audio.tags = None
        monkeypatch.setattr(mp3mod, "MUTAGEN_AVAILABLE", True, raising=False)
        monkeypatch.setattr(mp3mod, "MP3", MagicMock(return_value=audio), raising=False)
        assert read_id3_tags(f) == {}


# ─────────────────────────────────────────────────────────────────────────────
# ZIP packing & batch chapter export
# ─────────────────────────────────────────────────────────────────────────────


class TestZipAndBatchExport:
    def test_add_mp3_to_zip_includes_only_existing(self, tmp_path):
        a = make_mp3_like(tmp_path, "a.mp3")
        b = make_mp3_like(tmp_path, "b.mp3")
        ghost = tmp_path / "ghost.mp3"
        zpath = tmp_path / "out" / "pack.zip"
        import zipfile

        add_mp3_to_zip([a, ghost, b], zpath)
        with zipfile.ZipFile(zpath) as zf:
            names = set(zf.namelist())
        assert names == {"a.mp3", "b.mp3"}

    def test_export_mp3_chapters_copies_and_tags_each(self, tmp_path, monkeypatch):
        srcs = [make_mp3_like(tmp_path, f"s{i}.mp3") for i in range(2)]
        chapters = [ChapterInfo("alpha", 0, 100), ChapterInfo("beta", 100, 200)]
        meta = Mp3Metadata(artist="作者", album="专辑", year="2026")

        written = []
        captured = []

        def fake_write(path, metadata):
            written.append(Path(path))
            captured.append(metadata)
            return Path(path)

        monkeypatch.setattr(mp3mod, "write_id3_tags", fake_write)
        outdir = tmp_path / "exported"
        files = export_mp3_chapters(srcs, chapters, outdir, meta)

        assert [f.name for f in files] == [
            "chapter_001_alpha.mp3",
            "chapter_002_beta.mp3",
        ]
        assert all(p.exists() for p in files)  # copied from sources
        assert [m.track for m in captured] == [1, 2]
        assert {m.title for m in captured} == {"alpha", "beta"}
        assert all(m.artist == "作者" for m in captured)

    def test_export_truncates_to_shorter_list(self, tmp_path, monkeypatch):
        srcs = [make_mp3_like(tmp_path, "x.mp3")]
        chapters = [ChapterInfo("one", 0, 1), ChapterInfo("two", 1, 2)]
        monkeypatch.setattr(mp3mod, "write_id3_tags", lambda p, m: Path(p))
        files = export_mp3_chapters(srcs, chapters, tmp_path / "o", Mp3Metadata())
        assert len(files) == 1  # zip() stops at shorter source list
