"""
Tests for Version Manager (TEST-001: coverage improvement).

Tests for src/audiobook_studio/version_manager.py
Target: 70%+ coverage
"""

import os

# Set TEST_MODE before any imports
os.environ["TEST_MODE"] = "true"

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Now import the module under test
from src.audiobook_studio import version_manager


class TestVersionManagerHelpers:
    """Tests for internal helper functions."""

    def test_get_db_returns_session(self):
        """Test _get_db returns a database session."""
        with patch("src.audiobook_studio.version_manager.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value = mock_db

            db = version_manager._get_db()

            assert db == mock_db
            mock_session.assert_called_once()

    def test_find_run_by_id(self):
        """Test _find_run finds run by ID."""
        mock_db = MagicMock()
        mock_run = MagicMock()
        mock_run.id = 1
        mock_db.query.return_value.filter.return_value.first.return_value = mock_run

        result = version_manager._find_run(mock_db, project_id=1, run_id=1)

        assert result == mock_run
        mock_db.query.assert_called_once()

    def test_find_run_by_tag(self):
        """Test _find_run finds run by tag."""
        mock_db = MagicMock()
        mock_run = MagicMock()
        mock_run.version_tag = "v1.0"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_run

        result = version_manager._find_run(mock_db, project_id=1, tag="v1.0")

        assert result == mock_run

    def test_find_run_latest_completed(self):
        """Test _find_run finds latest completed run when no ID or tag."""
        mock_db = MagicMock()
        mock_run = MagicMock()
        mock_run.status = "completed"
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_run

        result = version_manager._find_run(mock_db, project_id=1)

        assert result == mock_run

    def test_find_run_not_found(self):
        """Test _find_run returns None when not found."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = version_manager._find_run(mock_db, project_id=1, run_id=999)

        assert result is None


class TestCollectStagesConfig:
    """Tests for _collect_stages_config helper."""

    def test_collect_stages_config_basic(self):
        """Test _collect_stages_config returns expected structure."""
        mock_db = MagicMock()
        mock_ch = MagicMock()
        mock_ch.extract_status = "completed"
        mock_ch.analyze_status = "pending"
        mock_ch.annotate_status = "completed"
        mock_ch.edit_status = "completed"
        mock_ch.synthesize_status = "pending"
        mock_ch.quality_status = "pending"

        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_ch]
        mock_db.query.return_value.filter.return_value.count.return_value = 5

        result = version_manager._collect_stages_config(mock_db, project_id=1)

        assert "stages_completed" in result
        assert "extract" in result["stages_completed"]
        assert "annotate" in result["stages_completed"]
        assert "edit" in result["stages_completed"]
        assert result["chapter_count"] == 1


class TestSaveRun:
    """Tests for save_run function."""

    def test_save_run_basic(self):
        """Test basic save_run creates a run."""
        with (
            patch("src.audiobook_studio.version_manager._get_db") as mock_get_db,
            patch("src.audiobook_studio.version_manager._collect_stages_config") as mock_collect,
        ):

            mock_db = MagicMock()
            mock_get_db.return_value = mock_db
            mock_collect.return_value = {
                "stages_completed": ["extract", "analyze"],
                "total_paragraphs": 10,
                "processed_paragraphs": 5,
                "chapter_count": 2,
            }

            mock_run = MagicMock()
            mock_run.id = 1
            mock_run.version_tag = "v1.0"
            mock_db.add.return_value = None
            mock_db.commit.return_value = None
            mock_db.refresh.side_effect = lambda r: setattr(r, "id", 1)

            with patch("src.audiobook_studio.version_manager.ProcessingRun", return_value=mock_run):
                result = version_manager.save_run(project_id=1, tag="v1.0", message="Test run")

            assert result == mock_run
            mock_db.add.assert_called_once()
            mock_db.commit.assert_called_once()
            mock_db.close.assert_called_once()

    def test_save_run_with_parent_id(self):
        """Test save_run links to parent by ID."""
        with (
            patch("src.audiobook_studio.version_manager._get_db") as mock_get_db,
            patch("src.audiobook_studio.version_manager._collect_stages_config") as mock_collect,
        ):

            mock_db = MagicMock()
            mock_get_db.return_value = mock_db
            mock_collect.return_value = {
                "stages_completed": [],
                "total_paragraphs": 0,
                "processed_paragraphs": 0,
                "chapter_count": 0,
            }

            mock_parent = MagicMock()
            mock_parent.id = 5
            mock_db.query.return_value.filter.return_value.first.return_value = mock_parent

            mock_run = MagicMock()
            mock_run.id = 2
            with patch("src.audiobook_studio.version_manager.ProcessingRun", return_value=mock_run):
                result = version_manager.save_run(project_id=1, parent_run_id=5)

            assert result == mock_run
            assert mock_run.parent_run_id == 5

    def test_save_run_with_parent_tag(self):
        """Test save_run links to parent by tag."""
        with (
            patch("src.audiobook_studio.version_manager._get_db") as mock_get_db,
            patch("src.audiobook_studio.version_manager._collect_stages_config") as mock_collect,
        ):

            mock_db = MagicMock()
            mock_get_db.return_value = mock_db
            mock_collect.return_value = {
                "stages_completed": [],
                "total_paragraphs": 0,
                "processed_paragraphs": 0,
                "chapter_count": 0,
            }

            mock_parent = MagicMock()
            mock_parent.id = 3
            mock_db.query.return_value.filter.return_value.first.return_value = mock_parent

            mock_run = MagicMock()
            mock_run.id = 2
            with patch("src.audiobook_studio.version_manager.ProcessingRun", return_value=mock_run):
                result = version_manager.save_run(project_id=1, parent_tag="v0.9")

            assert result == mock_run
            assert mock_run.parent_run_id == 3

    def test_save_run_parent_not_found_warnings(self):
        """Test save_run logs warning when parent not found."""
        with (
            patch("src.audiobook_studio.version_manager._get_db") as mock_get_db,
            patch("src.audiobook_studio.version_manager._collect_stages_config") as mock_collect,
            patch("src.audiobook_studio.version_manager.logger") as mock_logger,
        ):

            mock_db = MagicMock()
            mock_get_db.return_value = mock_db
            mock_collect.return_value = {
                "stages_completed": [],
                "total_paragraphs": 0,
                "processed_paragraphs": 0,
                "chapter_count": 0,
            }

            mock_db.query.return_value.filter.return_value.first.return_value = None

            mock_run = MagicMock()
            mock_run.id = 2
            with patch("src.audiobook_studio.version_manager.ProcessingRun", return_value=mock_run):
                result = version_manager.save_run(project_id=1, parent_run_id=999)

            assert result == mock_run
            mock_logger.warning.assert_called()


class TestListRuns:
    """Tests for list_runs function."""

    def test_list_runs_returns_list(self):
        """Test list_runs returns list of runs."""
        with patch("src.audiobook_studio.version_manager._get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value = mock_db

            mock_runs = [MagicMock(), MagicMock()]
            mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_runs

            result = version_manager.list_runs(project_id=1)

            assert result == mock_runs
            mock_db.close.assert_called_once()

    def test_list_runs_empty(self):
        """Test list_runs returns empty list when no runs."""
        with patch("src.audiobook_studio.version_manager._get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value = mock_db

            mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

            result = version_manager.list_runs(project_id=1)

            assert result == []


class TestGetRun:
    """Tests for get_run function."""

    def test_get_run_by_id(self):
        """Test get_run finds run by ID."""
        with (
            patch("src.audiobook_studio.version_manager._get_db") as mock_get_db,
            patch("src.audiobook_studio.version_manager._find_run") as mock_find,
        ):

            mock_db = MagicMock()
            mock_get_db.return_value = mock_db
            mock_run = MagicMock()
            mock_run.id = 1
            mock_find.return_value = mock_run

            result = version_manager.get_run(project_id=1, run_id=1)

            assert result == mock_run
            mock_find.assert_called_with(mock_db, 1, run_id=1, tag=None)

    def test_get_run_by_tag(self):
        """Test get_run finds run by tag."""
        with (
            patch("src.audiobook_studio.version_manager._get_db") as mock_get_db,
            patch("src.audiobook_studio.version_manager._find_run") as mock_find,
        ):

            mock_db = MagicMock()
            mock_get_db.return_value = mock_db
            mock_run = MagicMock()
            mock_run.version_tag = "v1.0"
            mock_find.return_value = mock_run

            result = version_manager.get_run(project_id=1, tag="v1.0")

            assert result == mock_run
            mock_find.assert_called_with(mock_db, 1, run_id=None, tag="v1.0")

    def test_get_run_latest(self):
        """Test get_run finds latest run when no ID or tag."""
        with (
            patch("src.audiobook_studio.version_manager._get_db") as mock_get_db,
            patch("src.audiobook_studio.version_manager._find_run") as mock_find,
        ):

            mock_db = MagicMock()
            mock_get_db.return_value = mock_db
            mock_run = MagicMock()
            mock_find.return_value = mock_run

            result = version_manager.get_run(project_id=1)

            assert result == mock_run
            mock_find.assert_called_with(mock_db, 1, run_id=None, tag=None)


class TestRollbackToRun:
    """Tests for rollback_to_run function."""

    def test_rollback_target_not_found(self):
        """Test rollback returns None when target not found."""
        with (
            patch("src.audiobook_studio.version_manager._get_db") as mock_get_db,
            patch("src.audiobook_studio.version_manager.logger") as mock_logger,
        ):

            mock_db = MagicMock()
            mock_get_db.return_value = mock_db
            mock_db.query.return_value.filter.return_value.first.return_value = None

            result = version_manager.rollback_to_run(project_id=1, run_id=999)

            assert result is None
            mock_logger.error.assert_called()

    def test_rollback_dry_run(self):
        """Test rollback dry run (apply=False) returns None."""
        with patch("src.audiobook_studio.version_manager._get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value = mock_db

            mock_target = MagicMock()
            mock_target.id = 5
            mock_target.version_tag = "v1.0"
            mock_target.started_at = datetime.now(timezone.utc)
            mock_target.stages_completed = ["extract", "analyze"]

            mock_latest = MagicMock()
            mock_latest.id = 10
            mock_latest.version_tag = "v2.0"
            mock_latest.started_at = datetime.now(timezone.utc)

            # First call for target, second for latest
            mock_db.query.return_value.filter.return_value.first.side_effect = [mock_target, mock_latest]
            # For latest query
            mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_latest

            result = version_manager.rollback_to_run(project_id=1, run_id=5, apply=False)

            # When apply=False, function returns None (logs plan but doesn't create run)
            assert result is None
            mock_db.commit.assert_not_called()

    def test_rollback_apply_creates_new_run(self):
        """Test rollback with apply=True creates a new rollback run."""
        with patch("src.audiobook_studio.version_manager._get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value = mock_db

            mock_target = MagicMock()
            mock_target.id = 5
            mock_target.version_tag = "v1.0"
            mock_target.started_at = datetime.now(timezone.utc)
            mock_target.stages_completed = ["extract", "analyze"]
            mock_target.config_json = '{"key": "value"}'
            mock_target.prompt_versions = {"prompt1": "v1"}

            mock_latest = MagicMock()
            mock_latest.id = 10
            mock_latest.version_tag = "v2.0"
            mock_latest.started_at = datetime.now(timezone.utc)

            mock_db.query.return_value.filter.return_value.first.side_effect = [mock_target, mock_latest]
            mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_latest

            # Create a proper mock for the rollback run with attributes
            mock_rollback_run = MagicMock()
            mock_rollback_run.id = 11
            mock_rollback_run.status = "rollback"
            mock_rollback_run.version_tag = "rollback_to_v1.0"

            with patch(
                "src.audiobook_studio.version_manager.ProcessingRun", return_value=mock_rollback_run
            ) as mock_processing_run:
                result = version_manager.rollback_to_run(project_id=1, run_id=5, apply=True)

            assert result == mock_rollback_run
            mock_processing_run.assert_called_once()
            call_kwargs = mock_processing_run.call_args[1]
            assert call_kwargs["status"] == "rollback"
            assert "rollback_to" in call_kwargs["version_tag"]
            mock_db.add.assert_called_once_with(mock_rollback_run)
            mock_db.commit.assert_called_once()


class TestDiffRuns:
    """Tests for diff_runs function."""

    def test_diff_runs_not_found(self):
        """Test diff_runs returns error when run not found."""
        with patch("src.audiobook_studio.version_manager._get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value = mock_db
            mock_db.query.return_value.filter.return_value.first.return_value = None

            result = version_manager.diff_runs(1, 999)

            assert "error" in result
            assert result["error"] == "Run not found"

    def test_diff_runs_same_status(self):
        """Test diff_runs with no differences except note."""
        with patch("src.audiobook_studio.version_manager._get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value = mock_db

            mock_run_a = MagicMock()
            mock_run_a.id = 1
            mock_run_a.version_tag = "v1.0"
            mock_run_a.status = "completed"
            mock_run_a.golden_score = None
            mock_run_a.stages_completed = ["extract", "analyze"]
            mock_run_a.config_json = '{"key": "value"}'

            mock_run_b = MagicMock()
            mock_run_b.id = 2
            mock_run_b.version_tag = "v2.0"
            mock_run_b.status = "completed"
            mock_run_b.golden_score = None
            mock_run_b.stages_completed = ["extract", "analyze"]
            mock_run_b.config_json = '{"key": "value"}'

            mock_db.query.return_value.filter.return_value.first.side_effect = [mock_run_a, mock_run_b]

            result = version_manager.diff_runs(1, 2)

            assert result["run_a"]["id"] == 1
            assert result["run_b"]["id"] == 2
            assert "note" in result["differences"]
            assert result["differences"]["note"] == "No significant differences"

    def test_diff_runs_status_diff(self):
        """Test diff_runs captures status difference."""
        with patch("src.audiobook_studio.version_manager._get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value = mock_db

            mock_run_a = MagicMock()
            mock_run_a.id = 1
            mock_run_a.version
