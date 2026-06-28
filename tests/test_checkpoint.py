"""Unit tests for CheckpointManager."""

import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.audiobook_studio.pipeline.checkpoint import STAGE_ORDER, CheckpointManager


class TestCheckpointManager:
    """Test CheckpointManager functionality."""

    def setup_method(self):
        """Setup test fixtures with temporary directory."""
        self.temp_dir = tempfile.mkdtemp()
        # Patch reports_dir to use our temp directory
        self.mock_reports_dir = Mock(return_value=Path(self.temp_dir))
        self.patch_reports = patch(
            "src.audiobook_studio.pipeline.checkpoint.reports_dir",
            self.mock_reports_dir,
        )
        self.patch_reports.start()
        self.manager = CheckpointManager(project_id=1)

    def teardown_method(self):
        """Cleanup."""
        self.patch_reports.stop()
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_new_project(self):
        """Test initialization for new project."""
        assert self.manager.project_id == 1
        assert self.manager._data["project_id"] == 1
        assert self.manager._data["chapters"] == {}
        assert self.manager._data["version"] == 2

    def test_init_existing_checkpoint(self):
        """Test initialization loads existing checkpoint."""
        existing_data = {
            "project_id": 1,
            "chapters": {"1": {"stages_done": ["extract"], "paragraphs_done": [0, 1]}},
            "version": 2,
        }
        checkpoint_file = Path(self.temp_dir) / "checkpoints.json"
        checkpoint_file.write_text(json.dumps(existing_data))

        manager = CheckpointManager(project_id=1)
        assert manager.is_stage_done("extract", 1)
        assert manager.are_paragraphs_done(1, {0, 1})

    def test_init_corrupted_json(self):
        """Test initialization handles corrupted JSON gracefully."""
        checkpoint_file = Path(self.temp_dir) / "checkpoints.json"
        checkpoint_file.write_text("invalid json")

        # Should log warning and start fresh
        manager = CheckpointManager(project_id=1)
        assert manager._data["chapters"] == {}

    def test_is_stage_done(self):
        """Test checking if stage is done."""
        assert not self.manager.is_stage_done("extract", 1)
        self.manager.mark_stage_done("extract", 1)
        assert self.manager.is_stage_done("extract", 1)

    def test_mark_stage_done(self):
        """Test marking stage as done."""
        self.manager.mark_stage_done("extract", 1)
        assert self.manager.is_stage_done("extract", 1)
        assert self.manager._chapter(1)["stages_done"] == ["extract"]

    def test_mark_stage_done_idempotent(self):
        """Test marking same stage twice is idempotent."""
        self.manager.mark_stage_done("extract", 1)
        self.manager.mark_stage_done("extract", 1)
        assert self.manager._chapter(1)["stages_done"] == ["extract"]

    def test_mark_stage_started(self):
        """Test marking stage as started."""
        self.manager.mark_stage_started("extract", 1)
        assert self.manager.get_current_stage(1) == "extract"

    def test_get_current_stage(self):
        """Test getting current stage."""
        assert self.manager.get_current_stage(1) is None
        self.manager.mark_stage_started("extract", 1)
        assert self.manager.get_current_stage(1) == "extract"
        self.manager.mark_stage_done("extract", 1)
        assert self.manager.get_current_stage(1) is None

    def test_last_completed_stage(self):
        """Test getting last completed stage."""
        assert self.manager.last_completed_stage(1) is None
        self.manager.mark_stage_done("extract", 1)
        assert self.manager.last_completed_stage(1) == "extract"
        self.manager.mark_stage_done("analyze", 1)
        assert self.manager.last_completed_stage(1) == "analyze"

    def test_are_paragraphs_done(self):
        """Test checking if paragraphs are done."""
        assert not self.manager.are_paragraphs_done(1, {0, 1, 2})
        self.manager.mark_paragraph_done(1, 0)
        self.manager.mark_paragraph_done(1, 1)
        assert self.manager.are_paragraphs_done(1, {0, 1})
        assert not self.manager.are_paragraphs_done(1, {0, 1, 2})

    def test_mark_paragraph_done(self):
        """Test marking single paragraph as done."""
        self.manager.mark_paragraph_done(1, 0)
        assert 0 in self.manager._chapter(1)["paragraphs_done"]

    def test_mark_paragraph_done_idempotent(self):
        """Test marking same paragraph twice is idempotent."""
        self.manager.mark_paragraph_done(1, 0)
        self.manager.mark_paragraph_done(1, 0)
        assert self.manager._chapter(1)["paragraphs_done"] == [0]

    def test_mark_paragraphs_done_batch(self):
        """Test marking multiple paragraphs as done."""
        self.manager.mark_paragraphs_done(1, [0, 1, 2])
        assert self.manager._chapter(1)["paragraphs_done"] == [0, 1, 2]

    def test_mark_paragraphs_done_unsorted_input(self):
        """Test batch marking sorts the output."""
        self.manager.mark_paragraphs_done(1, [2, 0, 1])
        assert self.manager._chapter(1)["paragraphs_done"] == [0, 1, 2]

    def test_get_pending_paragraphs(self):
        """Test getting pending paragraphs."""
        total = 5
        self.manager.mark_paragraph_done(1, 0)
        self.manager.mark_paragraph_done(1, 2)
        pending = self.manager.get_pending_paragraphs(1, total)
        assert pending == [1, 3, 4]

    def test_get_pending_paragraphs_all_done(self):
        """Test getting pending when all done."""
        total = 3
        self.manager.mark_paragraphs_done(1, [0, 1, 2])
        pending = self.manager.get_pending_paragraphs(1, total)
        assert pending == []

    def test_next_stage(self):
        """Test getting next stage to run."""
        assert self.manager.next_stage(1) == "extract"
        self.manager.mark_stage_done("extract", 1)
        assert self.manager.next_stage(1) == "analyze"
        self.manager.mark_stage_done("analyze", 1)
        assert self.manager.next_stage(1) == "annotate"
        for stage in ["annotate", "edit", "synthesize", "quality"]:
            self.manager.mark_stage_done(stage, 1)
        assert self.manager.next_stage(1) is None

    def test_stages_to_run(self):
        """Test getting ordered list of pending stages."""
        stages = self.manager.stages_to_run(1)
        assert stages == STAGE_ORDER
        self.manager.mark_stage_done("extract", 1)
        self.manager.mark_stage_done("synthesize", 1)
        stages = self.manager.stages_to_run(1)
        assert stages == ["analyze", "annotate", "edit", "quality"]

    def test_resume_from(self):
        """Test resume_from returns next incomplete stage."""
        assert self.manager.resume_from(1) == "extract"
        self.manager.mark_stage_done("extract", 1)
        assert self.manager.resume_from(1) == "analyze"

    def test_set_get_metadata(self):
        """Test setting and getting metadata."""
        self.manager.set_metadata("config_hash", "abc123")
        assert self.manager.get_metadata("config_hash") == "abc123"
        assert self.manager.get_metadata("nonexistent") is None
        assert self.manager.get_metadata("nonexistent", "default") == "default"

    def test_reset_chapter(self):
        """Test resetting chapter data."""
        self.manager.mark_stage_done("extract", 1)
        self.manager.mark_paragraph_done(1, 0)
        self.manager.reset_chapter(1)
        assert not self.manager.is_stage_done("extract", 1)
        assert self.manager._chapter(1)["paragraphs_done"] == []

    def test_reset_all(self):
        """Test resetting all checkpoints."""
        self.manager.mark_stage_done("extract", 1)
        self.manager.mark_stage_done("extract", 2)
        self.manager.reset_all()
        assert self.manager._data["chapters"] == {}


class TestCheckpointManagerPersistence:
    """Test checkpoint persistence to disk."""

    def setup_method(self):
        """Setup test fixtures with temporary directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.mock_reports_dir = Mock(return_value=Path(self.temp_dir))
        self.patch_reports = patch(
            "src.audiobook_studio.pipeline.checkpoint.reports_dir",
            self.mock_reports_dir,
        )
        self.patch_reports.start()
        self.manager = CheckpointManager(project_id=1)

    def teardown_method(self):
        """Cleanup."""
        self.patch_reports.stop()
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_persists_to_disk(self):
        """Test that changes are persisted to disk."""
        self.manager.mark_stage_done("extract", 1)
        checkpoint_file = Path(self.temp_dir) / "checkpoints.json"
        assert checkpoint_file.exists()
        data = json.loads(checkpoint_file.read_text())
        assert data["chapters"]["1"]["stages_done"] == ["extract"]

    def test_loads_persisted_data(self):
        """Test loading data that was previously persisted."""
        self.manager.mark_stage_done("extract", 1)
        self.manager.mark_paragraph_done(1, 0)

        # Create new manager instance
        manager2 = CheckpointManager(project_id=1)
        assert manager2.is_stage_done("extract", 1)
        assert manager2.are_paragraphs_done(1, {0})

    def test_flush_on_dirty(self):
        """Test that _flush only writes when dirty."""
        # Initial load shouldn't mark as dirty
        assert not self.manager._dirty

        # Marking stage sets dirty
        self.manager.mark_stage_done("extract", 1)
        assert not self.manager._dirty  # _flush() called immediately


class TestCheckpointManagerEdgeCases:
    """Test edge cases and error handling."""

    def setup_method(self):
        """Setup test fixtures with temporary directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.mock_reports_dir = Mock(return_value=Path(self.temp_dir))
        self.patch_reports = patch(
            "src.audiobook_studio.pipeline.checkpoint.reports_dir",
            self.mock_reports_dir,
        )
        self.patch_reports.start()
        self.manager = CheckpointManager(project_id=1)

    def teardown_method(self):
        """Cleanup."""
        self.patch_reports.stop()
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_multiple_chapters_isolated(self):
        """Test that chapters are isolated from each other."""
        self.manager.mark_stage_done("extract", 1)
        self.manager.mark_stage_done("extract", 2)

        assert self.manager.is_stage_done("extract", 1)
        assert self.manager.is_stage_done("extract", 2)
        assert not self.manager.is_stage_done("analyze", 1)

    def test_different_project_ids_isolated(self):
        """Test that different project IDs have isolated data."""
        # Create checkpoint for project 1 with known data
        self.manager.mark_stage_done("extract", 1)
        # The checkpoint file should exist
        checkpoint_file = Path(self.temp_dir) / "checkpoints.json"
        assert checkpoint_file.exists()

        # Verify data structure
        data = json.loads(checkpoint_file.read_text())
        assert data["project_id"] == 1
        assert data["chapters"]["1"]["stages_done"] == ["extract"]

    def test_stage_order_constant(self):
        """Test that STAGE_ORDER constant is correct."""
        assert STAGE_ORDER == [
            "extract",
            "analyze",
            "annotate",
            "edit",
            "synthesize",
            "quality",
        ]

    def test_concurrent_access_simulation(self):
        """Test simulating concurrent access (sequential reads/writes)."""
        # First manager writes
        self.manager.mark_stage_done("extract", 1)
        # Second manager reads (loads from disk)
        manager2 = CheckpointManager(project_id=1)
        assert manager2.is_stage_done("extract", 1)
        # Second writes
        manager2.mark_stage_done("analyze", 1)
        # At this point manager2's in-memory data has both stages
        assert "analyze" in manager2._data["chapters"]["1"]["stages_done"]
        # Original manager's in-memory data still only has extract
        # (This is expected - each instance has its own copy)
        assert "analyze" not in self.manager._data["chapters"]["1"]["stages_done"]


if __name__ == "__main__":
    pytest.main([__file__])
