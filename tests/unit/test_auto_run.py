"""Tests for api/auto_run.py — schemas, helpers, endpoints, background logic."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ===========================================================================
# Schema / dataclass tests
# ===========================================================================


class TestAutoRunSchemas:
    def test_auto_run_config_defaults(self):
        from src.audiobook_studio.api.auto_run import AutoRunConfig

        cfg = AutoRunConfig()
        assert cfg.target_difficulty == "B"
        assert cfg.primary_voice_preference == "female"
        assert cfg.speech_rate_preference == "standard"
        assert cfg.cost_limit_usd is None
        assert cfg.quality_threshold == 0.7
        assert cfg.max_regeneration_attempts == 3
        assert cfg.enable_background_music is False
        assert cfg.enable_sfx is True

    def test_auto_run_config_custom(self):
        from src.audiobook_studio.api.auto_run import AutoRunConfig

        cfg = AutoRunConfig(
            target_difficulty="A",
            cost_limit_usd=10.0,
            quality_threshold=0.9,
            enable_background_music=True,
        )
        assert cfg.target_difficulty == "A"
        assert cfg.cost_limit_usd == 10.0
        assert cfg.quality_threshold == 0.9
        assert cfg.enable_background_music is True

    def test_auto_run_status_response_defaults(self):
        from src.audiobook_studio.api.auto_run import AutoRunStatusResponse

        resp = AutoRunStatusResponse(project_id=1, run_id="r1")
        assert resp.status == "pending"
        assert resp.current_stage is None
        assert resp.completed_stages == []
        assert resp.progress == 0.0
        assert resp.cost_usd == 0.0
        assert resp.quality_score is None
        assert resp.can_pause is True
        assert resp.can_resume is False
        assert resp.can_cancel is True

    def test_auto_run_action_response(self):
        from src.audiobook_studio.api.auto_run import AutoRunActionResponse

        resp = AutoRunActionResponse(
            action="pause",
            status="pending",
            message="ok",
            run_id="r1",
        )
        assert resp.action == "pause"
        assert resp.run_id == "r1"

    def test_intermediate_product(self):
        from src.audiobook_studio.api.auto_run import IntermediateProduct

        p = IntermediateProduct(
            stage="extract",
            project_id=1,
            product_type="text",
            data={"k": "v"},
            created_at="2025-01-01",
        )
        assert p.stage == "extract"
        assert p.can_view is True
        assert p.can_edit is False

    def test_auto_run_start_request_defaults(self):
        from src.audiobook_studio.api.auto_run import AutoRunStartRequest

        req = AutoRunStartRequest()
        assert req.config is not None
        assert req.pause_points is None

    def test_stage_pause_point(self):
        from src.audiobook_studio.api.auto_run import StagePausePoint

        sp = StagePausePoint(stage="extract", pause_after=True, requires_approval=False)
        assert sp.stage == "extract"
        assert sp.pause_after is True
        assert sp.requires_approval is False


# ===========================================================================
# Helper function tests
# ===========================================================================


class TestAutoRunHelpers:
    def test_generate_run_id_format(self):
        from src.audiobook_studio.api.auto_run import _generate_run_id

        rid = _generate_run_id(42)
        assert rid.startswith("autorun_42_")
        assert len(rid) > len("autorun_42_")

    def test_stage_order_defined(self):
        from src.audiobook_studio.api.auto_run import _stage_order

        assert len(_stage_order) == 7
        assert _stage_order[0] == "extract"
        assert _stage_order[-1] == "quality"


# ===========================================================================
# Endpoint tests (using asyncio.run for Python 3.14 compat)
# ===========================================================================


def _run_async(coro):
    """Helper to run async functions in sync tests."""
    return asyncio.run(coro)


class TestAutoRunEndpoints:
    def test_get_status_no_active_run(self):
        from src.audiobook_studio.api.auto_run import _active_runs, get_auto_run_status

        _active_runs.clear()
        resp = _run_async(get_auto_run_status(project_id=9999))
        assert resp.status == "not_started"

    def test_pause_no_active_run(self):
        from src.audiobook_studio.api.auto_run import _active_runs, pause_auto_run

        _active_runs.clear()
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            _run_async(pause_auto_run(project_id=9999))

    def test_resume_no_active_run(self):
        from src.audiobook_studio.api.auto_run import _active_runs, resume_auto_run

        _active_runs.clear()
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            _run_async(resume_auto_run(project_id=9999))

    def test_cancel_no_active_run(self):
        from src.audiobook_studio.api.auto_run import _active_runs, cancel_auto_run

        _active_runs.clear()
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            _run_async(cancel_auto_run(project_id=9999))

    def test_get_intermediate_unknown_stage(self):
        from fastapi import HTTPException

        from src.audiobook_studio.api.auto_run import get_intermediate_product

        # Mock database to provide a project
        mock_db = MagicMock()
        mock_project = MagicMock()
        mock_project.chapters = []
        mock_db.query.return_value.filter.return_value.first.return_value = mock_project
        with pytest.raises(HTTPException):
            _run_async(get_intermediate_product(project_id=1, stage="unknown", db=mock_db))

    def test_get_intermediate_valid_stage(self):
        from src.audiobook_studio.api.auto_run import get_intermediate_product

        # Mock database to provide a project with chapter
        mock_db = MagicMock()
        mock_project = MagicMock()
        mock_chapter = MagicMock()
        mock_chapter.id = 1
        mock_chapter.index = 1
        mock_chapter.raw_text = "test"
        mock_chapter.extracted_text = "test extracted"
        mock_project.chapters = [mock_chapter]
        mock_db.query.return_value.filter.return_value.first.return_value = mock_project
        resp = _run_async(get_intermediate_product(project_id=1, stage="extract", db=mock_db))
        assert resp.stage == "extract"
        assert resp.project_id == 1

    def test_all_intermediate_stages(self):
        from src.audiobook_studio.api.auto_run import _stage_order, get_intermediate_product

        # Test that all stage names are recognized by checking _stage_order exists
        assert len(_stage_order) == 7
        for stage in _stage_order:
            assert stage in (
                "extract",
                "analyze",
                "annotate",
                "edit",
                "audio_postprocess",
                "synthesize",
                "quality",
            )

    def test_get_status_with_active_run(self):
        from src.audiobook_studio.api.auto_run import _active_runs, get_auto_run_status

        _active_runs[42] = {
            "run_id": "autorun_42_123",
            "status": "running",
            "config": {},
            "started_at": "2025-01-01T00:00:00Z",
            "current_stage": "analyze",
            "completed_stages": ["extract"],
            "completed_at": None,
        }
        resp = _run_async(get_auto_run_status(project_id=42))
        assert resp.status == "running"
        assert resp.current_stage == "analyze"
        assert "extract" in resp.completed_stages
        assert resp.can_pause is True
        assert resp.can_resume is False
        _active_runs.clear()

    def test_pause_running_run(self):
        from src.audiobook_studio.api.auto_run import _active_runs, pause_auto_run

        _active_runs[42] = {
            "run_id": "autorun_42_123",
            "status": "running",
        }
        resp = _run_async(pause_auto_run(project_id=42))
        assert resp.action == "pause"
        assert _active_runs[42]["pending_pause"] is True
        _active_runs.clear()

    def test_pause_non_running_fails(self):
        from src.audiobook_studio.api.auto_run import _active_runs, pause_auto_run

        _active_runs[42] = {"run_id": "r1", "status": "completed"}
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            _run_async(pause_auto_run(project_id=42))
        _active_runs.clear()

    def test_resume_paused_run(self):
        from src.audiobook_studio.api.auto_run import _active_runs, resume_auto_run

        _active_runs[42] = {"run_id": "r1", "status": "paused"}
        with patch(
            "src.audiobook_studio.api.auto_run.emit_pipeline_event",
            new_callable=AsyncMock,
        ):
            resp = _run_async(resume_auto_run(project_id=42))
        assert resp.status == "resumed"
        assert _active_runs[42]["status"] == "running"
        _active_runs.clear()

    def test_cancel_running_run(self):
        from src.audiobook_studio.api.auto_run import _active_runs, cancel_auto_run

        _active_runs[42] = {"run_id": "r1", "status": "running"}
        resp = _run_async(cancel_auto_run(project_id=42))
        assert resp.action == "cancel"
        assert 42 not in _active_runs

    def test_get_status_completed_run(self):
        from src.audiobook_studio.api.auto_run import _active_runs, get_auto_run_status

        _active_runs[10] = {
            "run_id": "r10",
            "status": "paused",
            "config": {},
            "started_at": None,
            "current_stage": None,
            "completed_stages": ["extract", "analyze", "annotate"],
            "completed_at": None,
        }
        resp = _run_async(get_auto_run_status(project_id=10))
        assert resp.status == "paused"
        assert resp.can_resume is True
        assert resp.can_pause is False
        assert resp.progress == 3 / 7
        _active_runs.clear()

    def test_resume_non_paused_fails(self):
        from src.audiobook_studio.api.auto_run import _active_runs, resume_auto_run

        _active_runs[42] = {"run_id": "r1", "status": "running"}
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            _run_async(resume_auto_run(project_id=42))
        _active_runs.clear()

    def test_cancel_paused_run(self):
        from src.audiobook_studio.api.auto_run import _active_runs, cancel_auto_run

        _active_runs[42] = {"run_id": "r1", "status": "paused"}
        resp = _run_async(cancel_auto_run(project_id=42))
        assert resp.status == "cancelled"
        assert 42 not in _active_runs


# ===========================================================================
# Business logic tests — _run_auto_pipeline and _run_single_stage
# ===========================================================================


class TestRunAutoPipeline:
    """Test the _run_auto_pipeline background task logic."""

    def test_pipeline_initializes_active_run(self):
        """Pipeline sets up _active_runs entry with correct initial state."""
        from src.audiobook_studio.api.auto_run import AutoRunConfig, _active_runs, _run_auto_pipeline

        _active_runs.clear()

        config = AutoRunConfig(target_difficulty="A", quality_threshold=0.8)
        run_id = "autorun_99_000"

        async def run():
            with patch(
                "src.audiobook_studio.api.auto_run.emit_pipeline_event",
                new_callable=AsyncMock,
            ):
                with patch("src.audiobook_studio.api.auto_run._get_checkpoint_manager") as mock_cp:
                    mock_cp.return_value.has_checkpoint.return_value = False
                    with patch(
                        "src.audiobook_studio.api.auto_run._run_single_stage",
                        new_callable=AsyncMock,
                    ):
                        # Set status to "completed" after first call to avoid infinite loop
                        async def complete_run(*args, **kwargs):
                            pid = args[0]
                            _active_runs[pid]["status"] = "completed"

                        from src.audiobook_studio.api.auto_run import _stage_order

                        call_count = [0]
                        original_stage_count = len(_stage_order)

                        async def fake_run_stage(*args, **kwargs):
                            call_count[0] += 1
                            if call_count[0] >= original_stage_count:
                                _active_runs[args[0]]["status"] = "completed"

                        with patch(
                            "src.audiobook_studio.api.auto_run._run_single_stage",
                            side_effect=fake_run_stage,
                        ):
                            await _run_auto_pipeline(99, run_id, config)

        _run_async(run())

        assert 99 in _active_runs
        run_info = _active_runs[99]
        assert run_info["run_id"] == run_id
        assert run_info["config"]["target_difficulty"] == "A"
        assert run_info["config"]["quality_threshold"] == 0.8
        assert run_info["started_at"] is not None
        _active_runs.clear()

    def test_pipeline_skips_checkpointed_stages(self):
        """Pipeline skips stages that have existing checkpoints."""
        from src.audiobook_studio.api.auto_run import AutoRunConfig, _active_runs, _run_auto_pipeline, _stage_order

        _active_runs.clear()

        config = AutoRunConfig()
        run_id = "autorun_99_001"

        async def run():
            with patch(
                "src.audiobook_studio.api.auto_run.emit_pipeline_event",
                new_callable=AsyncMock,
            ):
                with patch("src.audiobook_studio.api.auto_run._get_checkpoint_manager") as mock_cp:
                    # Mark extract and analyze as checkpointed
                    def has_ckpt(stage):
                        return stage in ("extract", "analyze")

                    mock_cp.return_value.has_checkpoint.side_effect = has_ckpt

                    async def fake_run_stage(*args, **kwargs):
                        _active_runs[args[0]]["status"] = "completed"

                    with patch(
                        "src.audiobook_studio.api.auto_run._run_single_stage",
                        side_effect=fake_run_stage,
                    ):
                        await _run_auto_pipeline(99, run_id, config)

        _run_async(run())

        run_info = _active_runs[99]
        # extract and analyze should be in completed_stages (skipped via checkpoint)
        assert "extract" in run_info["completed_stages"]
        assert "analyze" in run_info["completed_stages"]
        _active_runs.clear()

    def test_pipeline_marks_status_on_exception(self):
        """Pipeline sets status to 'failed' when an exception occurs."""
        from src.audiobook_studio.api.auto_run import AutoRunConfig, _active_runs, _run_auto_pipeline

        _active_runs.clear()

        config = AutoRunConfig()
        run_id = "autorun_99_err"

        async def run():
            with patch(
                "src.audiobook_studio.api.auto_run.emit_pipeline_event",
                new_callable=AsyncMock,
            ):
                with patch("src.audiobook_studio.api.auto_run._get_checkpoint_manager") as mock_cp:
                    mock_cp.return_value.has_checkpoint.return_value = False
                    with patch(
                        "src.audiobook_studio.api.auto_run._run_single_stage",
                        new_callable=AsyncMock,
                        side_effect=ValueError("DB connection lost"),
                    ):
                        await _run_auto_pipeline(99, run_id, config)

        _run_async(run())

        run_info = _active_runs[99]
        assert run_info["status"] == "failed"
        assert "DB connection lost" in run_info["error_message"]
        _active_runs.clear()

    def test_pipeline_pause_points(self):
        """Pipeline pauses at configured pause points."""
        from src.audiobook_studio.api.auto_run import AutoRunConfig, StagePausePoint, _active_runs, _run_auto_pipeline

        _active_runs.clear()

        config = AutoRunConfig()
        run_id = "autorun_99_pause"
        pause_points = [StagePausePoint(stage="annotate", pause_after=True)]

        stage_calls = []

        async def resume_after_pause(project_id):
            """Concurrent task that resumes the pipeline after it pauses."""
            await asyncio.sleep(0.1)  # Let pipeline set status to "paused"
            for _ in range(50):  # Max 5 seconds of polling
                if _active_runs.get(project_id, {}).get("status") == "paused":
                    _active_runs[project_id]["status"] = "running"
                    return
                await asyncio.sleep(0.1)

        async def run():
            with patch(
                "src.audiobook_studio.api.auto_run.emit_pipeline_event",
                new_callable=AsyncMock,
            ):
                with patch("src.audiobook_studio.api.auto_run._get_checkpoint_manager") as mock_cp:
                    mock_cp.return_value.has_checkpoint.return_value = False

                    async def track_stages(project_id, stage, config):
                        stage_calls.append(stage)

                    with patch(
                        "src.audiobook_studio.api.auto_run._run_single_stage",
                        side_effect=track_stages,
                    ):
                        # Launch concurrent resume task
                        asyncio.create_task(resume_after_pause(99))
                        await _run_auto_pipeline(99, run_id, config, pause_points)

        _run_async(run())

        # annotate should have been called
        assert "annotate" in [s for s in stage_calls]
        _active_runs.clear()

    def test_pipeline_status_progress_calculation(self):
        """Pipeline status shows correct progress for completed stages."""
        from src.audiobook_studio.api.auto_run import _active_runs, _stage_order, get_auto_run_status

        _active_runs.clear()

        _active_runs[77] = {
            "run_id": "autorun_77_000",
            "status": "running",
            "config": {},
            "started_at": "2025-01-01T00:00:00Z",
            "current_stage": "edit",
            "completed_stages": ["extract", "analyze", "annotate"],
            "completed_at": None,
        }

        resp = _run_async(get_auto_run_status(project_id=77))
        assert resp.current_stage == "edit"
        assert len(resp.completed_stages) == 3
        assert resp.progress == 3 / len(_stage_order)
        _active_runs.clear()


class TestRunSingleStage:
    """Test the _run_single_stage function."""

    def test_single_stage_project_not_found(self):
        """_run_single_stage raises ValueError when project doesn't exist."""
        from src.audiobook_studio.api.auto_run import AutoRunConfig, _run_single_stage

        config = AutoRunConfig()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        async def run():
            with patch("src.audiobook_studio.api.auto_run._get_checkpoint_manager") as mock_cp:
                mock_cp.return_value.is_stage_done.return_value = False
                # Patch SessionLocal in the auto_run module directly
                with patch(
                    "src.audiobook_studio.api.auto_run.SessionLocal",
                    return_value=mock_db,
                ):
                    with patch(
                        "src.audiobook_studio.api.auto_run.emit_pipeline_event",
                        new_callable=AsyncMock,
                    ):
                        with patch("src.audiobook_studio.api.auto_run.run_stage"):
                            await _run_single_stage(9999, "extract", config)

        # Should raise ValueError about project not found
        with pytest.raises(ValueError, match="Project 9999 not found"):
            _run_async(run())

    def test_single_stage_extract_no_chapters(self):
        """_run_single_stage emits progress=1.0 when no chapters exist for extract stage."""
        from src.audiobook_studio.api.auto_run import AutoRunConfig, _run_single_stage

        config = AutoRunConfig()
        mock_project = MagicMock()
        mock_project.chapters = []  # No chapters

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_project

        async def run():
            with patch("src.audiobook_studio.api.auto_run._get_checkpoint_manager") as mock_cp:
                mock_cp.return_value.is_stage_done.return_value = False
                with patch(
                    "src.audiobook_studio.api.auto_run.SessionLocal",
                    return_value=mock_db,
                ):
                    with patch(
                        "src.audiobook_studio.api.auto_run.emit_pipeline_event",
                        new_callable=AsyncMock,
                    ) as mock_emit:
                        await _run_single_stage(42, "extract", config)
                        # Should emit progress=1.0 to signal empty chapter list
                        calls = mock_emit.call_args_list
                        assert any(c.kwargs.get("progress") == 1.0 for c in calls)

        _run_async(run())

    def test_single_stage_annotate_no_paragraphs(self):
        """_run_single_stage emits progress=1.0 when no paragraphs exist for annotate stage."""
        from src.audiobook_studio.api.auto_run import AutoRunConfig, _run_single_stage

        config = AutoRunConfig()
        mock_project = MagicMock()
        mock_project.paragraphs = []  # No paragraphs

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_project

        async def run():
            with patch("src.audiobook_studio.api.auto_run._get_checkpoint_manager") as mock_cp:
                mock_cp.return_value.is_stage_done.return_value = False
                with patch(
                    "src.audiobook_studio.api.auto_run.SessionLocal",
                    return_value=mock_db,
                ):
                    with patch(
                        "src.audiobook_studio.api.auto_run.emit_pipeline_event",
                        new_callable=AsyncMock,
                    ) as mock_emit:
                        await _run_single_stage(42, "annotate", config)
                        calls = mock_emit.call_args_list
                        assert any(c.kwargs.get("progress") == 1.0 for c in calls)

        _run_async(run())

    def test_single_stage_unknown_stage_warns(self):
        """_run_single_stage logs warning for unknown stage names."""
        from src.audiobook_studio.api.auto_run import AutoRunConfig, _run_single_stage

        config = AutoRunConfig()
        mock_project = MagicMock()
        mock_project.chapters = [MagicMock(index=1)]
        mock_project.paragraphs = [MagicMock(id=1, chapter_id=1)]

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_project

        async def run():
            with patch("src.audiobook_studio.api.auto_run._get_checkpoint_manager") as mock_cp:
                mock_cp.return_value.is_stage_done.return_value = False
                with patch(
                    "src.audiobook_studio.api.auto_run.SessionLocal",
                    return_value=mock_db,
                ):
                    with patch(
                        "src.audiobook_studio.api.auto_run.emit_pipeline_event",
                        new_callable=AsyncMock,
                    ):
                        # Should not raise, just warn
                        await _run_single_stage(42, "nonexistent_stage", config)

        _run_async(run())  # Should not raise

    def test_single_stage_passes_target_difficulty(self):
        """_run_single_stage passes target_difficulty from config to run_stage for paragraph stages."""
        from src.audiobook_studio.api.auto_run import AutoRunConfig, _run_single_stage

        config = AutoRunConfig(target_difficulty="C")
        mock_para = MagicMock(id=10, chapter_id=5)
        mock_project = MagicMock()
        mock_project.paragraphs = [mock_para]

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_project

        async def run():
            with patch("src.audiobook_studio.api.auto_run._get_checkpoint_manager") as mock_cp:
                mock_cp.return_value.is_stage_done.return_value = False
                with patch(
                    "src.audiobook_studio.api.auto_run.SessionLocal",
                    return_value=mock_db,
                ):
                    with patch(
                        "src.audiobook_studio.api.auto_run.emit_pipeline_event",
                        new_callable=AsyncMock,
                    ):
                        with patch("src.audiobook_studio.api.auto_run.run_stage") as mock_run:
                            await _run_single_stage(42, "annotate", config)
                            mock_run.assert_called_once()
                            call_kwargs = mock_run.call_args
                            assert call_kwargs.kwargs.get("target_difficulty") == "C"

        _run_async(run())
