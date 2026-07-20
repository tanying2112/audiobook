"""Tests for GC Manager - Garbage Collection of temporary segment files."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from src.audiobook_studio.utils.gc_manager import GCManager, GCRetentionPolicy, cleanup_after_export


class TestGCRetentionPolicy:
    """Tests for GC retention policy configuration."""

    def test_default_policy(self):
        """Test default policy from environment."""
        os.environ.pop("GC_POLICY", None)
        os.environ.pop("GC_KEEP_DAYS", None)
        os.environ.pop("GC_KEEP_FINAL", None)
        os.environ.pop("GC_MAX_AGE_DAYS", None)

        policy = GCRetentionPolicy()
        assert policy.policy == "clean_on_success"
        assert policy.keep_days == 7
        assert policy.keep_final is True
        assert policy.max_age_days == 30

    def test_custom_env_policy(self):
        """Test policy from custom environment variables."""
        os.environ["GC_POLICY"] = "keep_for_days"
        os.environ["GC_KEEP_DAYS"] = "14"
        os.environ["GC_KEEP_FINAL"] = "false"
        os.environ["GC_MAX_AGE_DAYS"] = "60"

        try:
            policy = GCRetentionPolicy()
            assert policy.policy == "keep_for_days"
            assert policy.keep_days == 14
            assert policy.keep_final is False
            assert policy.max_age_days == 60
        finally:
            os.environ.pop("GC_POLICY", None)
            os.environ.pop("GC_KEEP_DAYS", None)
            os.environ.pop("GC_KEEP_FINAL", None)
            os.environ.pop("GC_MAX_AGE_DAYS", None)

    def test_invalid_policy_fallback(self):
        """Test invalid policy falls back to default."""
        os.environ["GC_POLICY"] = "invalid_policy"
        try:
            policy = GCRetentionPolicy()
            assert policy.policy == "clean_on_success"
        finally:
            os.environ.pop("GC_POLICY", None)


class TestGCManager:
    """Tests for GCManager class."""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for testing."""
        with tempfile.TemporaryDirectory() as tmp:
            pipeline_out = Path(tmp) / "output"
            storage_root = Path(tmp) / "storage" / "books"
            pipeline_out.mkdir(parents=True)
            storage_root.mkdir(parents=True)
            yield pipeline_out, storage_root

    @pytest.fixture
    def policy(self):
        """Create a test policy."""
        return GCRetentionPolicy(policy="clean_on_success", keep_final=True)

    @pytest.fixture
    def gc_manager(self, temp_dirs, policy):
        """Create a GCManager instance."""
        pipeline_out, storage_root = temp_dirs
        return GCManager(
            pipeline_output_dir=str(pipeline_out),
            storage_root=str(storage_root),
            policy=policy,
        )

    def test_initialization(self, gc_manager, temp_dirs):
        """Test GCManager initializes with correct paths."""
        pipeline_out, storage_root = temp_dirs
        assert gc_manager.pipeline_output_dir == pipeline_out
        assert gc_manager.storage_root == storage_root
        assert gc_manager.policy.policy == "clean_on_success"

    def test_get_segment_dirs(self, gc_manager, temp_dirs):
        """Test getting project directories for a project."""
        pipeline_out, storage_root = temp_dirs

        # Create some segment files
        project_out = pipeline_out / "project_1"
        project_out.mkdir()
        (project_out / "segment_1.wav").write_bytes(b"fake audio")
        (project_out / "segment_2.wav").write_bytes(b"fake audio")

        dirs = gc_manager._get_project_dirs(1)
        assert project_out in dirs

    def test_is_final_export_detection(self, gc_manager):
        """Test detection of final export files vs segments."""
        # Final exports
        assert gc_manager._is_final_export(Path("project_1.m4b")) is True
        assert gc_manager._is_final_export(Path("project_1.srt")) is True
        assert gc_manager._is_final_export(Path("project_1.vtt")) is True
        assert gc_manager._is_final_export(Path("project_1.zip")) is True
        assert gc_manager._is_final_export(Path("chapter_1.m4b")) is True

        # Segments
        assert gc_manager._is_final_export(Path("book_ch0_p0.wav")) is False
        assert gc_manager._is_final_export(Path("segment_123.wav")) is False
        assert gc_manager._is_final_export(Path("random.wav")) is False


class TestCleanupAfterExport:
    """Integration tests for cleanup_after_export function."""

    @pytest.fixture
    def temp_structure(self):
        """Create a full temp structure mimicking production."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            # Pipeline output dir
            output_dir = base / "output"
            output_dir.mkdir()

            # Storage dir
            storage_dir = base / "storage" / "books"
            storage_dir.mkdir(parents=True)

            # Project 1: has segments and final exports
            project_out = output_dir / "project_1"
            project_out.mkdir()

            # Segment files (should be cleaned)
            (project_out / "ch0_p0.wav").write_bytes(b"x" * 1000)
            (project_out / "ch0_p1.wav").write_bytes(b"x" * 2000)
            (project_out / "ch1_p0.wav").write_bytes(b"x" * 1500)

            # Final exports (should be kept)
            (project_out / "project_1.m4b").write_bytes(b"x" * 5000)
            (project_out / "project_1.srt").write_bytes(b"x" * 500)
            (project_out / "project_1.zip").write_bytes(b"x" * 5500)

            # Storage segments
            storage_audio = storage_dir / "1" / "audio"
            storage_audio.mkdir(parents=True)
            (storage_audio / "seg_1.wav").write_bytes(b"x" * 800)
            (storage_audio / "seg_2.wav").write_bytes(b"x" * 900)

            yield str(output_dir), str(storage_dir)

    def test_cleanup_keeps_final_exports(self, temp_structure):
        """Test that final exports are preserved."""
        output_dir, storage_dir = temp_structure

        result = cleanup_after_export(
            project_id=1,
            keep_final=True,
            pipeline_output_dir=output_dir,
            storage_root=storage_dir,
        )

        # Check final exports still exist
        project_out = Path(output_dir) / "project_1"
        assert (project_out / "project_1.m4b").exists()
        assert (project_out / "project_1.srt").exists()
        assert (project_out / "project_1.zip").exists()

        # Check result
        assert result["project_id"] == 1
        assert result["freed_bytes"] > 0
        assert len(result["deleted_files"]) >= 3  # At least the 3 segment files

    def test_cleanup_with_keep_final_false(self, temp_structure):
        """Test that keep_final=False removes everything."""
        output_dir, storage_dir = temp_structure

        result = cleanup_after_export(
            project_id=1,
            keep_final=False,
            pipeline_output_dir=output_dir,
            storage_root=storage_dir,
        )

        # Everything should be gone
        project_out = Path(output_dir) / "project_1"
        assert not (project_out / "project_1.m4b").exists()
        assert not (project_out / "project_1.srt").exists()
        assert result["freed_bytes"] > 0

    def test_cleanup_nonexistent_project(self, temp_structure):
        """Test cleanup on non-existent project returns empty result."""
        output_dir, storage_dir = temp_structure

        result = cleanup_after_export(
            project_id=999,
            keep_final=True,
            pipeline_output_dir=output_dir,
            storage_root=storage_dir,
        )

        assert result["project_id"] == 999
        assert result["freed_bytes"] == 0
        assert len(result["deleted_files"]) == 0

    def test_policy_clean_on_success(self, temp_structure):
        """Test clean_on_success policy via environment."""
        os.environ["GC_POLICY"] = "clean_on_success"
        os.environ["GC_KEEP_FINAL"] = "true"
        try:
            output_dir, storage_dir = temp_structure
            result = cleanup_after_export(
                project_id=1,
                pipeline_output_dir=output_dir,
                storage_root=storage_dir,
            )
            assert result["policy"] == "clean_on_success"
        finally:
            os.environ.pop("GC_POLICY", None)
            os.environ.pop("GC_KEEP_FINAL", None)


class TestGCManagerEdgeCases:
    """Edge case tests for GCManager."""

    def test_empty_directories(self):
        """Test cleanup on project with no segments."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            output_dir = base / "output"
            output_dir.mkdir()

            result = cleanup_after_export(
                project_id=999,
                keep_final=True,
                pipeline_output_dir=str(output_dir),
                storage_root=str(base / "storage" / "books"),
            )
            assert result["freed_bytes"] == 0

    def test_only_final_exports_no_segments(self):
        """Test project that only has final exports."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            output_dir = base / "output"
            output_dir.mkdir()

            project_out = output_dir / "project_1"
            project_out.mkdir()
            (project_out / "project_1.m4b").write_bytes(b"final")

            result = cleanup_after_export(
                project_id=1,
                keep_final=True,
                pipeline_output_dir=str(output_dir),
                storage_root=str(base / "storage" / "books"),
            )
            assert result["freed_bytes"] == 0
            assert (project_out / "project_1.m4b").exists()

    def test_max_age_cleanup(self):
        """Test files older than max_age_days are cleaned even if keep_final."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            output_dir = base / "output"
            output_dir.mkdir()

            project_out = output_dir / "project_1"
            project_out.mkdir()

            # Create an old segment file
            old_file = project_out / "old_segment.wav"
            old_file.write_bytes(b"old")

            # Set mtime to 40 days ago
            old_time = __import__("time").time() - (40 * 86400)
            os.utime(old_file, (old_time, old_time))

            result = cleanup_after_export(
                project_id=1,
                keep_final=True,
                pipeline_output_dir=str(output_dir),
                storage_root=str(base / "storage" / "books"),
            )
            # File should be deleted due to max_age
            assert not old_file.exists()
            assert result["freed_bytes"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
