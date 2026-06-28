"""Tests for version_manager module — comprehensive coverage.

Covers: save_run, list_runs, get_run, rollback_to_run, diff_runs,
restore_state, _find_run, _collect_stages_config.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers: build lightweight fake ORM objects without a real DB
# ---------------------------------------------------------------------------


def _make_run(
    id=1,
    project_id=1,
    status="completed",
    version_tag=None,
    commit_message=None,
    golden_score=None,
    parent_run_id=None,
    stages_completed=None,
    config_json="{}",
    prompt_versions=None,
    started_at=None,
):
    """Create a mock ProcessingRun with realistic attributes."""
    r = MagicMock()
    r.id = id
    r.project_id = project_id
    r.status = status
    r.version_tag = version_tag
    r.commit_message = commit_message
    r.golden_score = golden_score
    r.parent_run_id = parent_run_id
    r.stages_completed = stages_completed or []
    r.config_json = config_json
    r.prompt_versions = prompt_versions or {}
    r.started_at = started_at or datetime(2025, 1, 1, tzinfo=timezone.utc)
    r.completed_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    return r


def _make_chapter(id=1, project_id=1, index=0, **stage_statuses):
    ch = MagicMock()
    ch.id = id
    ch.project_id = project_id
    ch.index = index
    ch.extract_status = stage_statuses.get("extract_status", "pending")
    ch.analyze_status = stage_statuses.get("analyze_status", "pending")
    ch.annotate_status = stage_statuses.get("annotate_status", "pending")
    ch.edit_status = stage_statuses.get("edit_status", "pending")
    ch.synthesize_status = stage_statuses.get("synthesize_status", "pending")
    ch.quality_status = stage_statuses.get("quality_status", "pending")
    return ch


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

VM = "src.audiobook_studio.version_manager"


# ===========================================================================
# save_run
# ===========================================================================


class TestSaveRun:
    """Tests for save_run."""

    @patch(f"{VM}._collect_stages_config")
    @patch(f"{VM}._get_db")
    def test_save_run_basic(self, mock_get_db, mock_collect):
        """save_run creates a ProcessingRun with correct fields."""
        from src.audiobook_studio.version_manager import ProcessingRun, save_run

        db = MagicMock()
        mock_get_db.return_value = db
        mock_collect.return_value = {
            "stages_completed": ["extract", "analyze"],
            "total_paragraphs": 100,
            "processed_paragraphs": 50,
            "chapter_count": 5,
            "config_json": "{}",
        }

        # Capture the ProcessingRun object passed to db.add
        added_run = None

        def capture_add(obj):
            nonlocal added_run
            added_run = obj
            obj.id = 42  # simulate refresh

        db.add.side_effect = capture_add

        result = save_run(
            project_id=1,
            tag="v1.0",
            message="Initial run",
            score=0.85,
        )

        db.add.assert_called_once()
        db.commit.assert_called_once()
        db.refresh.assert_called_once()
        assert result.id == 42

    @patch(f"{VM}._collect_stages_config")
    @patch(f"{VM}._get_db")
    def test_save_run_with_parent_run_id(self, mock_get_db, mock_collect):
        """save_run links to parent when parent_run_id given."""
        from src.audiobook_studio.version_manager import save_run

        db = MagicMock()
        mock_get_db.return_value = db
        mock_collect.return_value = {
            "stages_completed": [],
            "total_paragraphs": 0,
            "processed_paragraphs": 0,
            "chapter_count": 0,
        }

        parent = _make_run(id=10, project_id=1)
        query = MagicMock()
        query.filter.return_value.first.return_value = parent
        db.query.return_value = query

        added_run = None

        def capture_add(obj):
            nonlocal added_run
            added_run = obj

        db.add.side_effect = capture_add

        save_run(project_id=1, parent_run_id=10)

        assert added_run.parent_run_id == 10

    @patch(f"{VM}._collect_stages_config")
    @patch(f"{VM}._get_db")
    def test_save_run_with_parent_tag(self, mock_get_db, mock_collect):
        """save_run links to parent when parent_tag given."""
        from src.audiobook_studio.version_manager import save_run

        db = MagicMock()
        mock_get_db.return_value = db
        mock_collect.return_value = {
            "stages_completed": [],
            "total_paragraphs": 0,
            "processed_paragraphs": 0,
            "chapter_count": 0,
        }

        parent = _make_run(id=20, project_id=1, version_tag="v0.5")
        query = MagicMock()
        query.filter.return_value.first.return_value = parent
        db.query.return_value = query

        added_run = None

        def capture_add(obj):
            nonlocal added_run
            added_run = obj

        db.add.side_effect = capture_add

        save_run(project_id=1, parent_tag="v0.5")
        assert added_run.parent_run_id == 20

    @patch(f"{VM}._collect_stages_config")
    @patch(f"{VM}._get_db")
    def test_save_run_parent_not_found(self, mock_get_db, mock_collect):
        """save_run still succeeds if parent not found (just warns)."""
        from src.audiobook_studio.version_manager import save_run

        db = MagicMock()
        mock_get_db.return_value = db
        mock_collect.return_value = {
            "stages_completed": [],
            "total_paragraphs": 0,
            "processed_paragraphs": 0,
            "chapter_count": 0,
        }
        query = MagicMock()
        query.filter.return_value.first.return_value = None
        db.query.return_value = query

        added_run = None

        def capture_add(obj):
            nonlocal added_run
            added_run = obj

        db.add.side_effect = capture_add

        save_run(project_id=1, parent_run_id=999)
        assert added_run.parent_run_id is None

    @patch(f"{VM}._collect_stages_config")
    @patch(f"{VM}._get_db")
    def test_save_run_prompt_versions(self, mock_get_db, mock_collect):
        """save_run stores prompt_versions dict."""
        from src.audiobook_studio.version_manager import save_run

        db = MagicMock()
        mock_get_db.return_value = db
        mock_collect.return_value = {
            "stages_completed": [],
            "total_paragraphs": 0,
            "processed_paragraphs": 0,
            "chapter_count": 0,
        }
        added_run = None

        def capture_add(obj):
            nonlocal added_run
            added_run = obj

        db.add.side_effect = capture_add

        pvs = {"annotate": "v2", "edit": "v1"}
        save_run(project_id=1, prompt_versions=pvs)
        assert added_run.prompt_versions == pvs


# ===========================================================================
# list_runs
# ===========================================================================


class TestListRuns:
    @patch(f"{VM}._get_db")
    def test_list_runs(self, mock_get_db):
        from src.audiobook_studio.version_manager import list_runs

        db = MagicMock()
        mock_get_db.return_value = db
        r1 = _make_run(id=2)
        r2 = _make_run(id=1)
        query = MagicMock()
        query.filter.return_value.order_by.return_value.all.return_value = [r1, r2]
        db.query.return_value = query

        result = list_runs(project_id=1)
        assert len(result) == 2
        assert result[0].id == 2

    @patch(f"{VM}._get_db")
    def test_list_runs_empty(self, mock_get_db):
        from src.audiobook_studio.version_manager import list_runs

        db = MagicMock()
        mock_get_db.return_value = db
        query = MagicMock()
        query.filter.return_value.order_by.return_value.all.return_value = []
        db.query.return_value = query

        result = list_runs(project_id=999)
        assert result == []


# ===========================================================================
# get_run
# ===========================================================================


class TestGetRun:
    @patch(f"{VM}._get_db")
    def test_get_run_by_id(self, mock_get_db):
        from src.audiobook_studio.version_manager import get_run

        db = MagicMock()
        mock_get_db.return_value = db
        target = _make_run(id=5)
        query = MagicMock()
        query.filter.return_value.first.return_value = target
        db.query.return_value = query

        result = get_run(project_id=1, run_id=5)
        assert result.id == 5

    @patch(f"{VM}._get_db")
    def test_get_run_by_tag(self, mock_get_db):
        from src.audiobook_studio.version_manager import get_run

        db = MagicMock()
        mock_get_db.return_value = db
        target = _make_run(id=6, version_tag="v2.0")
        query = MagicMock()
        query.filter.return_value.first.return_value = target
        db.query.return_value = query

        result = get_run(project_id=1, tag="v2.0")
        assert result.version_tag == "v2.0"

    @patch(f"{VM}._get_db")
    def test_get_run_not_found(self, mock_get_db):
        from src.audiobook_studio.version_manager import get_run

        db = MagicMock()
        mock_get_db.return_value = db
        query = MagicMock()
        query.filter.return_value.first.return_value = None
        db.query.return_value = query

        result = get_run(project_id=1, run_id=999)
        assert result is None


# ===========================================================================
# rollback_to_run
# ===========================================================================


class TestRollbackToRun:
    @patch(f"{VM}._get_db")
    def test_rollback_not_applied(self, mock_get_db):
        """rollback without apply=True returns None."""
        from src.audiobook_studio.version_manager import rollback_to_run

        db = MagicMock()
        mock_get_db.return_value = db

        target = _make_run(id=5, version_tag="v0.5")
        latest = _make_run(id=10, version_tag="v1.0")

        query = MagicMock()
        query.filter.return_value.first.side_effect = [target, latest]
        db.query.return_value = query

        result = rollback_to_run(project_id=1, run_id=5, apply=False)
        assert result is None

    @patch(f"{VM}._get_db")
    def test_rollback_applied(self, mock_get_db):
        """rollback with apply=True creates a new run."""
        from src.audiobook_studio.version_manager import rollback_to_run

        db = MagicMock()
        mock_get_db.return_value = db

        target = _make_run(
            id=5,
            version_tag="v0.5",
            stages_completed=["extract"],
            config_json='{"k": 1}',
            prompt_versions={"annotate": "v1"},
        )
        latest = _make_run(id=10, version_tag="v1.0")

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            q = MagicMock()
            if call_count == 1:
                q.filter.return_value.first.return_value = target
            else:
                q.filter.return_value.first.return_value = latest
            return q

        db.query.side_effect = side_effect

        rollback_run = rollback_to_run(project_id=1, run_id=5, apply=True)
        assert rollback_run is not None
        db.add.assert_called_once()
        db.commit.assert_called()

    @patch(f"{VM}._get_db")
    def test_rollback_target_not_found(self, mock_get_db):
        """rollback returns None if target not found."""
        from src.audiobook_studio.version_manager import rollback_to_run

        db = MagicMock()
        mock_get_db.return_value = db
        query = MagicMock()
        query.filter.return_value.first.return_value = None
        db.query.return_value = query

        result = rollback_to_run(project_id=1, run_id=999)
        assert result is None

    @patch(f"{VM}._get_db")
    def test_rollback_by_tag(self, mock_get_db):
        """rollback can locate target by version_tag."""
        from src.audiobook_studio.version_manager import rollback_to_run

        db = MagicMock()
        mock_get_db.return_value = db

        target = _make_run(id=7, version_tag="v0.3")
        query = MagicMock()
        query.filter.return_value.first.return_value = target
        db.query.return_value = query

        result = rollback_to_run(project_id=1, tag="v0.3", apply=True)
        assert result is not None


# ===========================================================================
# diff_runs
# ===========================================================================


class TestDiffRuns:
    @patch(f"{VM}._get_db")
    def test_diff_runs_status_diff(self, mock_get_db):
        from src.audiobook_studio.version_manager import diff_runs

        db = MagicMock()
        mock_get_db.return_value = db

        run_a = _make_run(id=1, status="completed", golden_score=0.8)
        run_b = _make_run(id=2, status="rollback", golden_score=0.9)

        query = MagicMock()
        query.filter.return_value.first.side_effect = [run_a, run_b]
        db.query.return_value = query

        result = diff_runs(1, 2)
        assert "status" in result["differences"]
        assert result["differences"]["status"]["from"] == "completed"
        assert result["differences"]["status"]["to"] == "rollback"

    @patch(f"{VM}._get_db")
    def test_diff_runs_score_diff(self, mock_get_db):
        from src.audiobook_studio.version_manager import diff_runs

        db = MagicMock()
        mock_get_db.return_value = db

        run_a = _make_run(id=1, golden_score=0.5)
        run_b = _make_run(id=2, golden_score=0.9)

        query = MagicMock()
        query.filter.return_value.first.side_effect = [run_a, run_b]
        db.query.return_value = query

        result = diff_runs(1, 2)
        assert "golden_score" in result["differences"]
        assert result["differences"]["golden_score"]["from"] == 0.5

    @patch(f"{VM}._get_db")
    def test_diff_runs_stages_added_removed(self, mock_get_db):
        from src.audiobook_studio.version_manager import diff_runs

        db = MagicMock()
        mock_get_db.return_value = db

        run_a = _make_run(id=1, stages_completed=["extract", "analyze"])
        run_b = _make_run(id=2, stages_completed=["analyze", "edit"])

        query = MagicMock()
        query.filter.return_value.first.side_effect = [run_a, run_b]
        db.query.return_value = query

        result = diff_runs(1, 2)
        assert "stages_added" in result["differences"]
        assert "stages_removed" in result["differences"]
        assert "edit" in result["differences"]["stages_added"]
        assert "extract" in result["differences"]["stages_removed"]

    @patch(f"{VM}._get_db")
    def test_diff_runs_config_key_diff(self, mock_get_db):
        from src.audiobook_studio.version_manager import diff_runs

        db = MagicMock()
        mock_get_db.return_value = db

        run_a = _make_run(id=1, config_json=json.dumps({"a": 1}))
        run_b = _make_run(id=2, config_json=json.dumps({"a": 1, "b": 2}))

        query = MagicMock()
        query.filter.return_value.first.side_effect = [run_a, run_b]
        db.query.return_value = query

        result = diff_runs(1, 2)
        assert "config_keys_added" in result["differences"]
        assert "b" in result["differences"]["config_keys_added"]

    @patch(f"{VM}._get_db")
    def test_diff_runs_no_diff(self, mock_get_db):
        from src.audiobook_studio.version_manager import diff_runs

        db = MagicMock()
        mock_get_db.return_value = db

        run_a = _make_run(id=1, status="completed", golden_score=0.8)
        run_b = _make_run(id=2, status="completed", golden_score=0.8)

        query = MagicMock()
        query.filter.return_value.first.side_effect = [run_a, run_b]
        db.query.return_value = query

        result = diff_runs(1, 2)
        assert "note" in result["differences"]

    @patch(f"{VM}._get_db")
    def test_diff_runs_not_found(self, mock_get_db):
        from src.audiobook_studio.version_manager import diff_runs

        db = MagicMock()
        mock_get_db.return_value = db
        query = MagicMock()
        query.filter.return_value.first.return_value = None
        db.query.return_value = query

        result = diff_runs(99, 100)
        assert "error" in result


# ===========================================================================
# restore_state
# ===========================================================================


class TestRestoreState:
    @patch(f"{VM}._get_db")
    def test_restore_state_no_target(self, mock_get_db):
        from src.audiobook_studio.version_manager import restore_state

        db = MagicMock()
        mock_get_db.return_value = db
        query = MagicMock()
        query.filter.return_value.first.return_value = None
        db.query.return_value = query

        result = restore_state(project_id=1, run_id=999)
        assert result == {"chapters_updated": 0, "paragraphs_updated": 0}

    @patch(f"{VM}._collect_stages_config")
    @patch(f"{VM}._get_db")
    def test_restore_state_updates_chapters(self, mock_get_db, mock_collect):
        from src.audiobook_studio.version_manager import restore_state

        db = MagicMock()
        mock_get_db.return_value = db

        target = _make_run(
            id=5,
            stages_completed=["extract", "analyze"],
        )

        ch = _make_chapter(
            id=1,
            extract_status="completed",
            analyze_status="completed",
            annotate_status="completed",
            edit_status="completed",
            synthesize_status="pending",
            quality_status="pending",
        )

        query = MagicMock()
        query.filter.return_value.first.return_value = target

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            q = MagicMock()
            if call_count == 1:
                q.filter.return_value.first.return_value = target
            else:
                q.filter.return_value.all.return_value = [ch]
            return q

        db.query.side_effect = side_effect

        result = restore_state(project_id=1, run_id=5, force=True)
        assert result["chapters_updated"] >= 1

    @patch(f"{VM}._get_db")
    def test_restore_state_with_paragraphs(self, mock_get_db):
        from src.audiobook_studio.version_manager import restore_state

        db = MagicMock()
        mock_get_db.return_value = db

        target = _make_run(id=5, stages_completed=["extract"])

        ch = _make_chapter(
            id=1, extract_status="completed", annotate_status="completed"
        )

        para = MagicMock()
        para.status = "annotated"

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            q = MagicMock()
            if call_count == 1:
                q.filter.return_value.first.return_value = target
            elif call_count == 2:
                q.filter.return_value.all.return_value = [ch]
            else:
                q.filter.return_value.all.return_value = [para]
            return q

        db.query.side_effect = side_effect

        result = restore_state(project_id=1, run_id=5, force=True)
        assert isinstance(result, dict)
        assert "paragraphs_updated" in result


# ===========================================================================
# _collect_stages_config
# ===========================================================================


class TestCollectStagesConfig:
    def test_collect_empty_project(self):
        """_collect_stages_config 在没有章节时返回空结果。"""
        from src.audiobook_studio.models import Chapter, Paragraph
        from src.audiobook_studio.version_manager import _collect_stages_config

        db = MagicMock()
        # db.query(Chapter) → 空列表; db.query(Paragraph).filter().count() → 0
        chapter_q = MagicMock()
        chapter_q.filter.return_value.order_by.return_value.all.return_value = []

        para_q = MagicMock()
        para_q.filter.return_value.count.return_value = 0

        def fake_query(model):
            if model is Chapter:
                return chapter_q
            return para_q

        db.query.side_effect = fake_query

        result = _collect_stages_config(db, project_id=1)

        assert result["stages_completed"] == []
        assert result["total_paragraphs"] == 0
        assert result["chapter_count"] == 0

    def test_collect_with_chapters(self):
        """_collect_stages_config 正确汇总已完成的阶段。"""
        from src.audiobook_studio.models import Chapter, Paragraph
        from src.audiobook_studio.version_manager import _collect_stages_config

        db = MagicMock()

        ch1 = _make_chapter(
            id=1, extract_status="completed", analyze_status="completed"
        )

        chapter_q = MagicMock()
        chapter_q.filter.return_value.order_by.return_value.all.return_value = [ch1]

        # Paragraph count queries: 10 total, 5 processed
        para_q_total = MagicMock()
        para_q_total.filter.return_value.count.return_value = 10

        para_q_processed = MagicMock()
        para_q_processed.filter.return_value.count.return_value = 5

        # db.query(Chapter) → chapter_q
        # db.query(Paragraph) with first .filter() → para_q_total
        # db.query(Paragraph) with second .filter() → para_q_processed
        # The Paragraph queries are: first .filter(Paragraph.project_id == pid, Paragraph.chapter_id == ch.id).count()
        #                            second .filter(..., Paragraph.status != "pending").count()
        # We use a counter to return different mock chains for consecutive Paragraph queries.
        call_count = 0

        def fake_query(model):
            nonlocal call_count
            if model is Chapter:
                return chapter_q
            call_count += 1
            if call_count == 1:
                return para_q_total
            return para_q_processed

        db.query.side_effect = fake_query

        result = _collect_stages_config(db, project_id=1)

        assert "extract" in result["stages_completed"]
        assert "analyze" in result["stages_completed"]
        assert result["chapter_count"] == 1
        assert result["total_paragraphs"] == 10
        assert result["processed_paragraphs"] == 5
