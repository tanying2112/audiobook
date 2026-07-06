"""Tests for the unified pipeline entry script run_pipeline.py.

These tests target pure-logic helpers and database/filesystem/orchestrator-bound
functions. Heavy dependencies (database SessionLocal/init_db, models.Project,
pipeline.orchestrator.run_pipeline) are mocked through sys.modules stubs so the
module loads under pytest's ``src`` layout.
"""

import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Module loading stub ──────────────────────────────────────────────────────
# run_pipeline.py imports `from audiobook_studio.database import ...` (absolute,
# no ``src`` prefix). Under pytest we import via ``src.audiobook_studio`` so we
# pre-stub the absolute modules to make the import resolve.
@pytest.fixture(scope="module", autouse=True)
def _stub_run_pipeline_deps():
    stubs = {}
    for name in (
        "audiobook_studio",
        "audiobook_studio.database",
        "audiobook_studio.models",
        "audiobook_studio.pipeline",
        "audiobook_studio.pipeline.orchestrator",
    ):
        if name not in sys.modules:
            stubs[name] = MagicMock()
            sys.modules[name] = stubs[name]
    # Preserve the real models module since run_pipeline uses Project only via
    # the mocked attribute path; orchestrator_run_pipeline is also mocked.
    yield
    for name in list(stubs.keys()):
        sys.modules.pop(name, None)


@pytest.fixture
def rp():
    """Import run_pipeline module fresh for each test (after stub is installed)."""
    import importlib

    import src.audiobook_studio.run_pipeline as run_pipeline

    importlib.reload(run_pipeline)
    return run_pipeline


# ── Pure-logic helpers ─────────────────────────────────────────────────────────


class TestParseArguments:
    def test_default_args(self, rp, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["run_pipeline"])
        args = rp.parse_arguments()
        assert args.mock_data is False
        assert args.init_db is False
        assert args.books == ["红楼梦", "三国演义"]
        assert args.chapter is None
        assert args.quick is False

    def test_mock_data_flag(self, rp, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["run_pipeline", "--mock-data"])
        args = rp.parse_arguments()
        assert args.mock_data is True
        assert args.init_db is False

    def test_init_db_flag(self, rp, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["run_pipeline", "--init-db"])
        args = rp.parse_arguments()
        assert args.init_db is True
        assert args.mock_data is False

    def test_books_custom(self, rp, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["run_pipeline", "--books", "红楼梦", "三国演义"])
        args = rp.parse_arguments()
        assert args.books == ["红楼梦", "三国演义"]

    def test_books_single(self, rp, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["run_pipeline", "--books", "红楼梦"])
        args = rp.parse_arguments()
        assert args.books == ["红楼梦"]

    def test_chapter_filter(self, rp, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["run_pipeline", "--chapter", "5"])
        args = rp.parse_arguments()
        assert args.chapter == 5

    def test_quick_mode(self, rp, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["run_pipeline", "--quick"])
        args = rp.parse_arguments()
        assert args.quick is True

    def test_all_flags_combined(self, rp, monkeypatch):
        monkeypatch.setattr(
            sys, "argv", ["run_pipeline", "--mock-data", "--init-db", "--quick", "--chapter", "2", "--books", "A", "B"]
        )
        args = rp.parse_arguments()
        assert args.mock_data is True
        assert args.init_db is True
        assert args.quick is True
        assert args.chapter == 2
        assert args.books == ["A", "B"]


class TestGetChapterTemplates:
    def test_honglou_returns_three(self, rp):
        templates = rp._get_chapter_templates("红楼梦")
        assert set(templates.keys()) == {1, 2, 3}
        assert "红楼梦第一回" in templates[1]
        assert "红楼梦第二回" in templates[2]
        assert "红楼梦第三回" in templates[3]

    def test_sanguo_returns_three(self, rp):
        templates = rp._get_chapter_templates("三国演义")
        assert set(templates.keys()) == {1, 2, 3}
        assert "三国演义第一回" in templates[1]
        assert "三国演义第二回" in templates[2]
        assert "三国演义第三回" in templates[3]

    def test_unknown_book_returns_empty(self, rp):
        templates = rp._get_chapter_templates("未知书")
        assert templates == {}

    def test_template_content_is_string(self, rp):
        templates = rp._get_chapter_templates("红楼梦")
        for _num, content in templates.items():
            assert isinstance(content, str)
            assert len(content) > 100  # Non-trivial template text


class TestModuleConstants:
    def test_stages_order(self, rp):
        assert rp.STAGES == [
            "extract",
            "analyze",
            "annotate",
            "edit",
            "audio_postprocess",
            "synthesize",
            "quality",
        ]

    def test_book_config_keys(self, rp):
        assert set(rp.BOOK_CONFIG.keys()) == {"红楼梦", "三国演义"}

    def test_book_config_fields(self, rp):
        for _name, cfg in rp.BOOK_CONFIG.items():
            assert cfg["title"]
            assert cfg["author"]
            assert cfg["language"] == "zh"
            assert cfg["num_mock_chapters"] == 3
            assert cfg["difficulty"] == "C"

    def test_mock_data_dir_exists(self, rp):
        assert rp.MOCK_DATA_DIR.exists()
        assert rp.MOCK_DATA_DIR.parent == rp.DATA_DIR


# ── Database-bound function (initialize_database) ──────────────────────────────


class TestInitializeDatabase:
    def test_full_seed_walk(self, rp):
        """init_db called once, SessionLocal returns a mock that sees existing
        Project records for both books → no new projects inserted."""
        mock_session = MagicMock()
        # First query: Project exists for both books
        mock_session.query.return_value.filter.return_value.first.side_effect = [
            MagicMock(id=1),
            MagicMock(id=2),
        ]
        with patch.object(rp, "init_db") as mock_init_db, patch.object(rp, "SessionLocal", return_value=mock_session):
            rp.initialize_database(seed_projects=True)
            mock_init_db.assert_called_once()
            # No db.add nor db.commit (because both projects exist)
            mock_session.add.assert_not_called()
            assert mock_session.commit.call_count == 0

    def test_seed_creates_missing_project(self, rp):
        mock_session = MagicMock()
        # First book: no existing; second book: existing
        mock_session.query.return_value.filter.return_value.first.side_effect = [
            None,
            MagicMock(id=1),
        ]
        # When project created, db.add then commit then refresh
        with patch.object(rp, "init_db"), patch.object(rp, "SessionLocal", return_value=mock_session):
            rp.initialize_database(seed_projects=True)
            # db.add called once for the missing project
            assert mock_session.add.call_count == 1
            assert mock_session.commit.call_count == 1
            mock_session.refresh.assert_called_once()

    def test_skip_seed(self, rp):
        with patch.object(rp, "init_db") as mock_init_db:
            rp.initialize_database(seed_projects=False)
            mock_init_db.assert_called_once()

    def test_seed_error_rolls_back(self, rp):
        mock_session = MagicMock()
        mock_session.query.side_effect = RuntimeError("boom")
        with patch.object(rp, "init_db"), patch.object(rp, "SessionLocal", return_value=mock_session):
            with pytest.raises(RuntimeError):
                rp.initialize_database(seed_projects=True)
            mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()


# ── Filesystem-bound _get_chapter_files ───────────────────────────────────────


class TestGetChapterFiles:
    def test_no_dir_no_single_file(self, rp, tmp_path):
        with patch.object(rp, "MOCK_DATA_DIR", tmp_path / "nope"), patch.object(rp, "DATA_DIR", tmp_path):
            result = rp._get_chapter_files("ghost_book")
            assert result == []

    def test_single_file_fallback(self, rp, tmp_path):
        single = tmp_path / "孤本.txt"
        single.write_text("content", encoding="utf-8")
        with patch.object(rp, "MOCK_DATA_DIR", tmp_path / "nope"), patch.object(rp, "DATA_DIR", tmp_path):
            result = rp._get_chapter_files("孤本")
            assert result == [(1, single)]

    def test_chapter_files_sorted_by_number(self, rp, tmp_path):
        # Create chapter files in non-sorted naming order
        book_dir = tmp_path / "testbook"
        book_dir.mkdir()
        for n in [10, 1, 2, 20]:
            (book_dir / f"chapter_{n:02d}.txt").write_text(f"chapter {n}", encoding="utf-8")
        # Mock dir.exists() to True
        with patch.object(rp, "MOCK_DATA_DIR", tmp_path):
            result = rp._get_chapter_files("testbook")
        nums = [n for n, _ in result]
        assert nums == [1, 2, 10, 20]

    def test_dir_exists_no_chapter_files(self, rp, tmp_path):
        # Empty dir
        book_dir = tmp_path / "testbook"
        book_dir.mkdir()
        with patch.object(rp, "MOCK_DATA_DIR", tmp_path):
            result = rp._get_chapter_files("testbook")
            assert result == []

    def test_non_chapter_files_ignored(self, rp, tmp_path):
        book_dir = tmp_path / "testbook"
        book_dir.mkdir()
        (book_dir / "chapter_01.txt").write_text("c1", encoding="utf-8")
        (book_dir / "notes.txt").write_text("ignore", encoding="utf-8")
        (book_dir / "chapter_02.txt").write_text("c2", encoding="utf-8")
        with patch.object(rp, "MOCK_DATA_DIR", tmp_path):
            result = rp._get_chapter_files("testbook")
        assert len(result) == 2

    def test_returns_tuples_of_int_and_path(self, rp, tmp_path):
        book_dir = tmp_path / "testbook"
        book_dir.mkdir()
        (book_dir / "chapter_07.txt").write_text("c", encoding="utf-8")
        with patch.object(rp, "MOCK_DATA_DIR", tmp_path):
            result = rp._get_chapter_files("testbook")
        assert len(result) == 1
        num, path = result[0]
        assert num == 7
        assert isinstance(path, Path)


# ── _find_project ──────────────────────────────────────────────────────────────


class TestFindProject:
    def test_known_book_uses_config_title(self, rp):
        mock_db = MagicMock()
        rp._find_project(mock_db, "红楼梦")
        # It should query Project.title == config title (红楼梦)
        mock_db.query.assert_called_once()
        # filter chain ends with .first() called
        mock_db.query.return_value.filter.return_value.first.assert_called_once()

    def test_unknown_book_uses_book_name(self, rp):
        mock_db = MagicMock()
        rp._find_project(mock_db, "未知书名")
        mock_db.query.assert_called_once()

    def test_returns_query_result(self, rp):
        mock_db = MagicMock()
        sentinel = MagicMock(id=42)
        mock_db.query.return_value.filter.return_value.first.return_value = sentinel
        result = rp._find_project(mock_db, "红楼梦")
        assert result is sentinel


# ── create_mock_data ─────────────────────────────────────────────────────────


class TestCreateMockData:
    def test_creates_all_chapters_fresh(self, rp, tmp_path):
        with patch.object(rp, "MOCK_DATA_DIR", tmp_path):
            rp.create_mock_data()
        # Each book dir should have 3 chapters
        for book in ("红楼梦", "三国演义"):
            book_dir = tmp_path / book
            assert book_dir.exists()
            files = list(book_dir.glob("chapter_*.txt"))
            assert len(files) == 3
            for f in files:
                assert f.read_text(encoding="utf-8")

    def test_skips_existing_files(self, rp, tmp_path):
        # Pre-create one chapter to ensure it's skipped
        book_dir = tmp_path / "红楼梦"
        book_dir.mkdir(parents=True)
        existing = book_dir / "chapter_01.txt"
        existing.write_text("OLD", encoding="utf-8")
        with patch.object(rp, "MOCK_DATA_DIR", tmp_path):
            rp.create_mock_data()
        # Existing file should be preserved
        assert existing.read_text(encoding="utf-8") == "OLD"
        # Other two files were created
        assert (book_dir / "chapter_02.txt").exists()
        assert (book_dir / "chapter_03.txt").exists()


# ── run_book_pipeline ─────────────────────────────────────────────────────────


class TestRunBookPipeline:
    def test_unknown_book_no_config_returns_early(self, rp):
        # Book not in BOOK_CONFIG → no project creation path
        with patch.object(rp, "_get_chapter_files", return_value=[]):
            # The function should return early because no project & no config
            mock_db = MagicMock()
            # _find_project returns None for unknown book
            mock_db.query.return_value.filter.return_value.first.return_value = None
            with patch.object(rp, "SessionLocal", return_value=mock_db):
                # Should not raise even though config is missing
                rp.run_book_pipeline("does_not_exist", stages=["extract"])

    def test_no_chapter_files_returns_early(self, rp, tmp_path):
        # book has config but no chapter files
        with patch.object(rp, "_get_chapter_files", return_value=[]):
            mock_db = MagicMock()
            # existing project
            mock_proj = MagicMock(id=1)
            mock_db.query.return_value.filter.return_value.first.return_value = mock_proj
            with patch.object(rp, "SessionLocal", return_value=mock_db):
                rp.run_book_pipeline("红楼梦", stages=["extract"])

    def test_chapter_filter_excludes_all(self, rp, tmp_path):
        # create chapter files
        for n in (1, 2):
            (tmp_path / f"chapter_{n:02d}.txt").write_text(f"c{n}", encoding="utf-8")
        with patch.object(rp, "MOCK_DATA_DIR", tmp_path):
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(id=1)
            with patch.object(rp, "SessionLocal", return_value=mock_db), patch.object(rp, "orchestrator_run_pipeline"):
                rp.run_book_pipeline("红楼梦", stages=["extract"], chapter_filter=[99])
                # Should return after filter empty, orchestrator not called
                rp.orchestrator_run_pipeline.assert_not_called()

    def test_runs_extract_analyze_only(self, rp, tmp_path):
        (tmp_path / "chapter_01.txt").write_text("hello world", encoding="utf-8")
        with patch.object(rp, "MOCK_DATA_DIR", tmp_path):
            mock_db = MagicMock()
            mock_proj = MagicMock(id=42)
            mock_db.query.return_value.filter.return_value.first.return_value = mock_proj
            # Chapter query returns None → function skips paragraph-level pipeline
            mock_db.query.return_value.filter.return_value.filter.return_value.first.return_value = None
            with (
                patch.object(rp, "SessionLocal", return_value=mock_db),
                patch.object(rp, "orchestrator_run_pipeline", return_value=[{"stage": "extract"}]) as mock_orch,
            ):
                rp.run_book_pipeline("红楼梦", stages=["extract", "analyze"])
                # orchestrator called once for chapter-level
                assert mock_orch.call_count == 1
                # project updated to completed
                assert mock_proj.current_stage == "completed"
                mock_db.commit.assert_called()

    def test_empty_chapter_file_skipped(self, rp, tmp_path):
        book_dir = tmp_path / "红楼梦"
        book_dir.mkdir()
        (book_dir / "chapter_01.txt").write_text("   ", encoding="utf-8")
        with patch.object(rp, "MOCK_DATA_DIR", tmp_path), patch.object(rp, "DATA_DIR", tmp_path):
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(id=1)
            with (
                patch.object(rp, "SessionLocal", return_value=mock_db),
                patch.object(rp, "orchestrator_run_pipeline") as mock_orch,
            ):
                rp.run_book_pipeline("红楼梦", stages=["extract"])
                # Empty file means orchestrator not called for this chapter
                mock_orch.assert_not_called()

    def test_orchestrator_exception_continues_next_chapter(self, rp, tmp_path):
        (tmp_path / "chapter_01.txt").write_text("content1", encoding="utf-8")
        (tmp_path / "chapter_02.txt").write_text("content2", encoding="utf-8")
        with patch.object(rp, "MOCK_DATA_DIR", tmp_path):
            mock_db = MagicMock()
            mock_proj = MagicMock(id=1)
            mock_db.query.return_value.filter.return_value.first.return_value = mock_proj
            # Chapter queries return None for both
            mock_db.query.return_value.filter.return_value.filter.return_value.first.return_value = None
            call_count = [0]

            def side_effect(**kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise RuntimeError("first chapter boom")
                return []

            with (
                patch.object(rp, "SessionLocal", return_value=mock_db),
                patch.object(rp, "orchestrator_run_pipeline", side_effect=side_effect),
            ):
                # Should not raise — single chapter error is swallowed
                rp.run_book_pipeline("红楼梦", stages=["extract"])

    def test_creates_project_when_missing(self, rp, tmp_path):
        (tmp_path / "chapter_01.txt").write_text("hello", encoding="utf-8")
        with patch.object(rp, "MOCK_DATA_DIR", tmp_path):
            mock_db = MagicMock()
            # No existing project
            mock_db.query.return_value.filter.return_value.first.return_value = None
            # And chapter query returns None
            mock_db.query.return_value.filter.return_value.filter.return_value.first.return_value = None
            with (
                patch.object(rp, "SessionLocal", return_value=mock_db),
                patch.object(rp, "orchestrator_run_pipeline", return_value=[]),
            ):
                # Project is constructed via the mocked models.Project
                rp.run_book_pipeline("红楼梦", stages=["extract"])
                # db.add called once to create new project
                mock_db.add.assert_called()


# ── main() ────────────────────────────────────────────────────────────────────


class TestMain:
    def test_main_with_no_flags(self, rp, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["run_pipeline"])
        with (
            patch.object(rp, "create_mock_data") as mock_mock,
            patch.object(rp, "initialize_database") as mock_init,
            patch.object(rp, "run_book_pipeline") as mock_run,
        ):
            rp.main()
            mock_mock.assert_not_called()
            mock_init.assert_not_called()
            # Default books both attempted
            assert mock_run.call_count == 2

    def test_main_mock_data_only(self, rp, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["run_pipeline", "--mock-data"])
        with (
            patch.object(rp, "create_mock_data") as mock_mock,
            patch.object(rp, "initialize_database"),
            patch.object(rp, "run_book_pipeline"),
        ):
            rp.main()
            mock_mock.assert_called_once()

    def test_main_init_db_only(self, rp, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["run_pipeline", "--init-db"])
        with (
            patch.object(rp, "create_mock_data"),
            patch.object(rp, "initialize_database") as mock_init,
            patch.object(rp, "run_book_pipeline"),
        ):
            rp.main()
            mock_init.assert_called_once()

    def test_main_quick_mode(self, rp, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["run_pipeline", "--quick", "--books", "红楼梦"])
        with patch.object(rp, "run_book_pipeline") as mock_run:
            rp.main()
            assert mock_run.call_count == 1
            # stages = ["extract", "analyze", "annotate"]
            _, kwargs = mock_run.call_args
            assert kwargs["stages"] == ["extract", "analyze", "annotate"]

    def test_main_full_mode_default_stages(self, rp, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["run_pipeline", "--books", "红楼梦"])
        with patch.object(rp, "run_book_pipeline") as mock_run:
            rp.main()
            _, kwargs = mock_run.call_args
            assert kwargs["stages"] == rp.STAGES

    def test_main_book_error_does_not_propagate(self, rp, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["run_pipeline", "--books", "红楼梦"])
        with patch.object(rp, "run_book_pipeline", side_effect=RuntimeError("boom")):
            # main() catches per-book errors → should NOT raise
            rp.main()

    def test_main_chapter_filter_to_run(self, rp, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["run_pipeline", "--chapter", "3", "--books", "红楼梦"])
        with patch.object(rp, "run_book_pipeline") as mock_run:
            rp.main()
            assert mock_run.call_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=src/audiobook_studio/run_pipeline.py"])
