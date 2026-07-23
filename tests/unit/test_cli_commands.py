"""Tests for the new modular CLI commands.

These tests verify the new cli/ module structure works correctly,
mirroring the original run_pipeline.py test coverage but for the
decomposed CLI commands.
"""

import argparse
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure src/ is importable
_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import audiobook_studio.cli.mock_data as cli_mock
import audiobook_studio.cli.init_db as cli_init
import audiobook_studio.cli.pipeline as cli_pipeline
import audiobook_studio.cli.export as cli_export
import audiobook_studio.cli.book as cli_book


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_args():
    """Create a mock argparse.Namespace for command testing."""
    def _make(**kwargs):
        ns = argparse.Namespace()
        for k, v in kwargs.items():
            setattr(ns, k, v)
        return ns
    return _make


# ── CLI Mock Data Tests ─────────────────────────────────────────────────────

class TestMockDataCommand:
    """Tests for the mock-data subcommand."""

    def test_create_mock_data_calls_original(self, mock_args, monkeypatch):
        """mock_data_command delegates to run_pipeline.create_mock_data."""
        with patch("audiobook_studio.cli.mock_data.create_mock_data") as mock:
            result = cli_mock.mock_data_command(mock_args())
            assert result == 0
            mock.assert_called_once()

    def test_create_mock_data_error_handling(self, mock_args, monkeypatch):
        """Non-zero return on exception."""
        with patch("audiobook_studio.cli.mock_data.create_mock_data", side_effect=RuntimeError("boom")):
            result = cli_mock.mock_data_command(mock_args())
            assert result == 1


# ── CLI Init DB Tests ────────────────────────────────────────────────────────

class TestInitDbCommand:
    """Tests for the init-db subcommand."""

    def test_init_db_success(self, mock_args, monkeypatch):
        """initialize_database called with correct seed flag."""
        with patch("audiobook_studio.cli.init_db.initialize_database") as mock_init:
            mock_init.return_value = None
            args = mock_args(no_seed=False, drop_first=False)
            result = cli_init.init_db_command(args)
            assert result == 0
            # Called with positional arg (True) due to run_in_executor call
            mock_init.assert_called_once_with(True)

    def test_init_db_no_seed(self, mock_args, monkeypatch):
        """no_seed flag skips seed projects."""
        with patch("audiobook_studio.cli.init_db.initialize_database") as mock_init:
            args = mock_args(no_seed=True, drop_first=False)
            result = cli_init.init_db_command(args)
            assert result == 0
            mock_init.assert_not_called()

    def test_init_db_drop_first(self, mock_args, monkeypatch):
        """drop_first drops tables before init."""
        with patch("audiobook_studio.cli.init_db.drop_async_db") as mock_drop, \
             patch("audiobook_studio.cli.init_db.init_async_db") as mock_init, \
             patch("audiobook_studio.cli.init_db.initialize_database") as mock_seed:
            args = mock_args(no_seed=False, drop_first=True)
            result = cli_init.init_db_command(args)
            assert result == 0
            mock_drop.assert_called_once()
            mock_init.assert_called_once()
            mock_seed.assert_called_once_with(True)

    def test_init_db_error(self, mock_args):
        """Error handling returns non-zero."""
        with patch("audiobook_studio.cli.init_db.initialize_database", side_effect=RuntimeError("fail")):
            result = cli_init.init_db_command(mock_args())
            assert result == 1


# ── CLI Pipeline Tests ───────────────────────────────────────────────────────

class TestPipelineCommand:
    """Tests for the pipeline run/resume subcommands."""

    def test_run_pipeline_basic(self, mock_args, monkeypatch):
        """pipeline_run_command delegates to run_book_pipeline for each book."""
        # Mock the run_pipeline_sync to return success
        with patch("audiobook_studio.cli.pipeline.run_pipeline_sync") as mock_run:
            mock_run.return_value = []
            args = mock_args(books=["红楼梦"], stages=["extract"], quick=False,
                             chapter=None, bg_music=None, bg_volume=-20.0,
                             keep_tmp=False, no_resume=False)
            result = cli_pipeline.pipeline_run_command(args)
            assert result == 0
            assert mock_run.called

    def test_run_pipeline_quick_mode(self, mock_args):
        """quick flag restricts stages to extract/analyze/annotate."""
        with patch("audiobook_studio.cli.pipeline.run_pipeline_sync") as mock_run:
            mock_run.return_value = []
            args = mock_args(books=["红楼梦"], quick=True,
                             stages=None, chapter=None, bg_music=None, bg_volume=-20.0,
                             keep_tmp=False, no_resume=False)
            result = cli_pipeline.pipeline_run_command(args)
            assert result == 0
            assert mock_run.called

    def test_resume_pipeline(self, mock_args):
        """pipeline_resume_command calls run_pipeline_sync with checkpoint resume."""
        with patch("audiobook_studio.cli.pipeline.run_pipeline_sync") as mock_run, \
             patch("audiobook_studio.cli.pipeline.SessionLocal") as mock_session, \
             patch("audiobook_studio.cli.pipeline.Project") as mock_project_class, \
             patch("audiobook_studio.cli.pipeline.Chapter") as mock_chapter_class:

            mock_run.return_value = []
            mock_db = MagicMock()
            mock_session.return_value = mock_db

            # Mock project
            mock_project = MagicMock()
            mock_project.id = 42
            mock_db.query.return_value.filter.return_value.first.return_value = mock_project

            # Mock chapters to resume - need to handle two filter calls
            mock_chapter = MagicMock()
            mock_chapter.index = 2
            mock_chapter.id = 5

            # First filter (project_id) returns a query-like object
            mock_query = MagicMock()
            mock_query.filter.return_value.order_by.return_value.all.return_value = [mock_chapter]
            mock_db.query.return_value.filter.return_value = mock_query

            args = mock_args(project_id=42, chapter=2)
            result = cli_pipeline.pipeline_resume_command(args)
            assert result == 0
            assert mock_run.called


# ── CLI Export Tests ────────────────────────────────────────────────────────

class TestExportCommand:
    """Tests for the export subcommand."""

    def test_export_success(self, mock_args):
        """export_command returns 0 on successful export."""
        mock_job = MagicMock()
        mock_job.progress.value = "complete"
        mock_job.output_paths = {"m4b": "/out.m4b"}
        mock_job.error = None

        with patch("audiobook_studio.cli.export.export_project", return_value=mock_job), \
             patch("audiobook_studio.cli.export.SessionLocal") as mock_session, \
             patch("audiobook_studio.cli.export.Project") as mock_project, \
             patch("audiobook_studio.run_pipeline.cleanup_after_export") as mock_cleanup:

            mock_db = MagicMock()
            mock_session.return_value = mock_db
            mock_project = MagicMock()
            mock_project.id = 1
            mock_project.title = "Test Book"
            mock_project.progress = 100  # Numeric progress
            mock_db.query.return_value.filter.return_value.first.return_value = mock_project

            args = mock_args(project_id=1, formats=["m4b_srt"], bg_music=None, bg_volume=-20.0,
                             cover=None, include_cover=True, no_normalize=False, keep_tmp=False,
                             output_dir=None, chapters=None)
            result = cli_export.export_command(args)
            assert result == 0

    def test_export_project_not_found(self, mock_args):
        """Non-zero return if project doesn't exist."""
        with patch("audiobook_studio.cli.export.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value = mock_db
            mock_db.query.return_value.filter.return_value.first.return_value = None

            args = mock_args(project_id=999)
            result = cli_export.export_command(args)
            assert result == 1

    def test_export_failed_job(self, mock_args):
        """Non-zero if export job reports error."""
        mock_job = MagicMock()
        mock_job.progress.value = "failed"
        mock_job.error = "disk full"

        with patch("audiobook_studio.cli.export.export_project", return_value=mock_job), \
             patch("audiobook_studio.cli.export.SessionLocal") as mock_session, \
             patch("audiobook_studio.cli.export.Project") as mock_project:

            mock_db = MagicMock()
            mock_session.return_value = mock_db
            mock_db.query.return_value.filter.return_value.first.return_value = mock_project

            args = mock_args(project_id=1)
            result = cli_export.export_command(args)
            assert result == 1


# ── CLI Book Tests ──────────────────────────────────────────────────────────

class TestBookCommand:
    """Tests for the book list/create/show/delete subcommands."""

    def test_book_list(self, mock_args):
        """book_list_command prints formatted table."""
        mock_proj = MagicMock()
        mock_proj.id = 1
        mock_proj.title = "红楼梦"
        mock_proj.author = "曹雪芹"
        mock_proj.status = "draft"
        mock_proj.progress = 50.0
        mock_proj.total_chapters_estimated = 3
        mock_proj.created_at = "2024-01-01T00:00:00"

        with patch("audiobook_studio.cli.book.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value = mock_db
            mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_proj]

            args = mock_args(status=None)
            result = cli_book.book_list_command(args)
            assert result == 0

    def test_book_create_success(self, mock_args):
        """book_create_command creates new project."""
        mock_proj = MagicMock()
        mock_proj.id = 42

        with patch("audiobook_studio.cli.book.SessionLocal") as mock_session, \
             patch("audiobook_studio.cli.book.Project", return_value=mock_proj) as mock_project_class:

            mock_db = MagicMock()
            mock_session.return_value = mock_db
            mock_db.query.return_value.filter.return_value.first.return_value = None  # no existing

            args = mock_args(book_name="红楼梦", custom_title=None, custom_author=None)
            result = cli_book.book_create_command(args)
            assert result == 0
            mock_db.add.assert_called()
            mock_db.commit.assert_called()

    def test_book_create_duplicate(self, mock_args):
        """book_create_command fails if project already exists."""
        with patch("audiobook_studio.cli.book.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value = mock_db
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(id=1)

            args = mock_args(book_name="红楼梦")
            result = cli_book.book_create_command(args)
            assert result == 1

    def test_book_show(self, mock_args):
        """book_show_command prints project details."""
        mock_proj = MagicMock()
        mock_proj.id = 1
        mock_proj.title = "红楼梦"
        mock_proj.author = "曹雪芹"
        mock_proj.genre = "古典小说"
        mock_proj.difficulty = "C"
        mock_proj.language = "zh"
        mock_proj.era = "清代"
        mock_proj.status = "draft"
        mock_proj.progress = 50.0
        mock_proj.total_chapters_estimated = 3
        mock_proj.current_stage = "extract"
        mock_proj.total_cost_usd = 0.0
        mock_proj.created_at = "2024-01-01T00:00:00"
        mock_proj.updated_at = "2024-01-01T00:00:00"

        with patch("audiobook_studio.cli.book.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value = mock_db
            mock_db.query.return_value.filter.return_value.first.return_value = mock_proj

            args = mock_args(project_id=1)
            result = cli_book.book_show_command(args)
            assert result == 0

    def test_book_show_not_found(self, mock_args):
        """Non-zero if project not found."""
        with patch("audiobook_studio.cli.book.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value = mock_db
            mock_db.query.return_value.filter.return_value.first.return_value = None

            args = mock_args(project_id=999)
            result = cli_book.book_show_command(args)
            assert result == 1


# ── Parser Integration Tests ─────────────────────────────────────────────────

class TestCliParserIntegration:
    """Integration tests for the full CLI parser."""

    def test_main_parser_has_all_commands(self):
        """Main parser includes all 5 top-level commands."""
        from audiobook_studio.cli.main import create_parser
        parser = create_parser()
        # Check subparsers exist
        assert hasattr(parser, "_subparsers")

    def test_pipeline_subcommands(self):
        """pipeline has run and resume subcommands."""
        from audiobook_studio.cli.pipeline import add_pipeline_parser

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_pipeline_parser(subparsers)

        # Should be able to parse 'pipeline run' and 'pipeline resume'
        args = parser.parse_args(["pipeline", "run", "红楼梦"])
        assert args.pipeline_command == "run"
        assert args.books == ["红楼梦"]

        args = parser.parse_args(["pipeline", "resume", "42"])
        assert args.pipeline_command == "resume"
        assert args.project_id == 42

    def test_book_subcommands(self):
        """book has list/create/show/delete subcommands."""
        from audiobook_studio.cli.book import add_book_parser

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_book_parser(subparsers)

        args = parser.parse_args(["book", "list"])
        assert args.book_command == "list"

        args = parser.parse_args(["book", "create", "红楼梦"])
        assert args.book_command == "create"
        assert args.book_name == "红楼梦"

        args = parser.parse_args(["book", "show", "1"])
        assert args.book_command == "show"
        assert args.project_id == 1

        args = parser.parse_args(["book", "delete", "1", "--force"])
        assert args.book_command == "delete"
        assert args.project_id == 1
        assert args.force is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])