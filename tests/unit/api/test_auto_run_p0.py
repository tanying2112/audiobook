"""P0 coverage tests for api/auto_run.py.

Targets (Phase 1 P0):
- State machine full paths: _run_auto_pipeline success / paused / failed transitions
- Dependency failure simulation: DB errors, missing project, stage exceptions
- _run_single_stage: chapter/paragraph branches, checkpoint skips, empty-text skips
- All REST endpoints incl. pause/resume/cancel state guards and autopilot config heuristics
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks

from src.audiobook_studio.api.auto_run import (
    AutopilotConfig,
    AutoRunConfig,
    AutoRunStartRequest,
    StagePausePoint,
    _active_runs,
    _create_paragraphs_from_chapters,
    _generate_autopilot_config,
    _run_auto_pipeline,
    _run_single_stage,
    cancel_auto_run,
    get_auto_run_status,
    get_intermediate_product,
    pause_auto_run,
    preview_autopilot_config,
    resume_auto_run,
    start_auto_run,
    start_autopilot,
)
from src.audiobook_studio.exceptions import DomainError


def _code(exc: DomainError) -> str:
    return getattr(exc, "error_code", "")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_active_runs():
    """Isolate the module-level run-state dict between tests."""
    _active_runs.clear()
    yield
    _active_runs.clear()


def make_result(scalar=None, items=None, first=None):
    """Build a MagicMock imitating a SQLAlchemy Result."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    r.scalars.return_value.all.return_value = items if items is not None else []
    r.scalars.return_value.first.return_value = first
    return r


def make_db(results):
    """Async session mock whose execute() pops from a list of results."""
    db = AsyncMock()
    results = list(results)

    async def execute(*a, **k):
        if results:
            return results.pop(0)
        return make_result()

    db.execute = execute
    db.close = AsyncMock()
    return db


def make_project(chapters=None):
    p = MagicMock()
    p.id = 1
    p.chapters = chapters or []
    return p


def make_chapter(index=1, cid=10, raw_text="hello", **extra):
    ch = MagicMock()
    ch.id = cid
    ch.index = index
    ch.raw_text = raw_text
    ch.extracted_text = ""
    ch.analyzed_json = None
    for k, v in extra.items():
        setattr(ch, k, v)
    return ch


def make_paragraph(pid=100, chapter_id=10, index=1, text="some text", **extra):
    pa = MagicMock()
    pa.id = pid
    pa.chapter_id = chapter_id
    pa.index = index
    pa.text = text
    pa.edited_text = ""
    for k, v in extra.items():
        setattr(pa, k, v)
    return pa


MODULE = "src.audiobook_studio.api.auto_run"


# ─────────────────────────────────────────────────────────────────────────────
# _create_paragraphs_from_chapters
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateParagraphsFromChapters:
    @pytest.mark.asyncio
    async def test_missing_project_returns_silently(self):
        db = make_db([make_result(scalar=None)])
        await _create_paragraphs_from_chapters(db, 999)
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_existing_paragraphs_are_skipped(self):
        project = make_project(chapters=[make_chapter()])
        db = make_db(
            [
                make_result(scalar=project),  # Project lookup
                make_result(items=[MagicMock()]),  # existing paragraphs
            ]
        )
        await _create_paragraphs_from_chapters(db, 1)
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_paragraphs_and_empty_text_chapter(self):
        ch = make_chapter(index=3, raw_text="para one.\n\n para two. \n\n\n\n")
        project = make_project(chapters=[ch])
        db = make_db(
            [
                make_result(scalar=project),
                make_result(items=[]),  # no existing paragraphs
            ]
        )
        with (
            patch(f"{MODULE}.Paragraph") as mock_para_cls,
            patch(f"{MODULE}.select"),  # avoid real coercion of mocked models
        ):
            await _create_paragraphs_from_chapters(db, 1)
            assert mock_para_cls.call_count == 2
            created_kwargs = mock_para_cls.call_args_list[0].kwargs
            assert created_kwargs["chapter_index"] == 3
            assert created_kwargs["index"] == 1
            db.commit.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# _run_auto_pipeline — state machine full paths
# ─────────────────────────────────────────────────────────────────────────────


class TestRunAutoPipeline:
    @pytest.mark.asyncio
    async def test_success_completes_all_stages(self):
        config = AutoRunConfig()
        with (
            patch(f"{MODULE}.emit_pipeline_event", new_callable=AsyncMock),
            patch(f"{MODULE}._run_single_stage", new_callable=AsyncMock) as rs,
            patch(f"{MODULE}._get_checkpoint_manager"),
        ):
            await _run_auto_pipeline(1, "run-1", config)

        assert _active_runs[1]["status"] == "completed"
        assert _active_runs[1]["completed_at"] is not None
        assert len(_active_runs[1]["completed_stages"]) == 7
        # start + per-stage enter/exit + completed
        assert rs.await_count == 7

    @pytest.mark.asyncio
    async def test_pause_point_blocks_until_resumed(self):
        config = AutoRunConfig()
        pp = StagePausePoint(stage="analyze", pause_after=True)

        with (
            patch(f"{MODULE}.emit_pipeline_event", new_callable=AsyncMock),
            patch(f"{MODULE}._run_single_stage", new_callable=AsyncMock),
            patch(f"{MODULE}._get_checkpoint_manager"),
        ):
            task = asyncio.create_task(_run_auto_pipeline(2, "run-2", config, pause_points=[pp]))
            # Wait until pipeline reaches paused state at 'analyze'
            for _ in range(200):
                await asyncio.sleep(0.01)
                if _active_runs[2]["status"] == "paused":
                    break
            assert _active_runs[2]["status"] == "paused"
            assert _active_runs[2]["completed_stages"] == ["extract", "analyze"]

            # Resume → loop exits and pipeline completes
            _active_runs[2]["status"] = "running"
            await asyncio.wait_for(task, timeout=5)

        assert _active_runs[2]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_pause_point_with_pause_after_false_is_ignored(self):
        config = AutoRunConfig()
        pp = StagePausePoint(stage="extract", pause_after=False)
        with (
            patch(f"{MODULE}.emit_pipeline_event", new_callable=AsyncMock),
            patch(f"{MODULE}._run_single_stage", new_callable=AsyncMock),
            patch(f"{MODULE}._get_checkpoint_manager"),
        ):
            await asyncio.wait_for(_run_auto_pipeline(3, "run-3", config, pause_points=[pp]), timeout=5)
        assert _active_runs[3]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_stage_failure_marks_failed_and_emits_error(self):
        config = AutoRunConfig()
        with (
            patch(f"{MODULE}.emit_pipeline_event", new_callable=AsyncMock) as ev,
            patch(
                f"{MODULE}._run_single_stage",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom: dependency down"),
            ),
            patch(f"{MODULE}._get_checkpoint_manager"),
        ):
            await _run_auto_pipeline(4, "run-4", config)

        assert _active_runs[4]["status"] == "failed"
        assert "boom" in _active_runs[4]["error_message"]
        error_events = [c for c in ev.await_args_list if c.kwargs.get("event_type") == "error"]
        assert error_events, "expected an ERROR pipeline event"


# ─────────────────────────────────────────────────────────────────────────────
# _run_single_stage — all branches with simulated dependency failures
# ─────────────────────────────────────────────────────────────────────────────


class TestRunSingleStage:
    @pytest.mark.asyncio
    async def test_missing_project_raises_value_error(self):
        db = make_db([make_result(scalar=None)])
        with patch(f"{MODULE}.create_async_session", return_value=db), patch(f"{MODULE}.CheckpointManager"):
            with pytest.raises(ValueError, match="not found"):
                await _run_single_stage(404, "extract", AutoRunConfig())
        db.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_extract_no_chapters_emits_full_progress(self):
        db = make_db(
            [
                make_result(scalar=make_project()),
                make_result(items=[]),  # chapters
            ]
        )
        with (
            patch(f"{MODULE}.create_async_session", return_value=db),
            patch(f"{MODULE}.CheckpointManager") as cm,
            patch(f"{MODULE}.emit_pipeline_event", new_callable=AsyncMock) as ev,
            patch(f"{MODULE}.run_stage", new_callable=AsyncMock) as rs,
        ):
            await _run_single_stage(1, "extract", AutoRunConfig())
        rs.assert_not_awaited()
        progress_calls = [c for c in ev.await_args_list if c.kwargs.get("event_type") == "stage_progress"]
        assert progress_calls and progress_calls[-1].kwargs["progress"] == 1.0
        cm.return_value.mark_stage_done.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_skipped_when_all_chapters_extracted(self):
        chapters = [make_chapter(i, extract_status="completed", raw_text=f"t{i}") for i in range(1, 3)]
        db = make_db(
            [
                make_result(scalar=make_project()),
                make_result(items=chapters),
            ]
        )
        with (
            patch(f"{MODULE}.create_async_session", return_value=db),
            patch(f"{MODULE}.CheckpointManager") as cm,
            patch(f"{MODULE}.emit_pipeline_event", new_callable=AsyncMock),
            patch(f"{MODULE}.run_stage", new_callable=AsyncMock) as rs,
        ):
            await _run_single_stage(1, "extract", AutoRunConfig())
        rs.assert_not_awaited()
        assert cm.return_value.mark_stage_done.call_count == len(chapters)

    @pytest.mark.asyncio
    async def test_extract_checkpoint_skip_per_chapter(self):
        chapters = [make_chapter(1), make_chapter(2)]
        db = make_db(
            [
                make_result(scalar=make_project()),
                make_result(items=chapters),
            ]
        )
        ckpt = MagicMock()
        ckpt.is_stage_done.side_effect = [True, False]  # ch1 done, ch2 pending
        with (
            patch(f"{MODULE}.create_async_session", return_value=db),
            patch(f"{MODULE}.CheckpointManager", return_value=ckpt),
            patch(f"{MODULE}.emit_pipeline_event", new_callable=AsyncMock),
            patch(f"{MODULE}.run_stage", new_callable=AsyncMock) as rs,
        ):
            await _run_single_stage(1, "extract", AutoRunConfig())
        assert rs.await_count == 1  # only ch2 ran

    @pytest.mark.asyncio
    async def test_analyze_creates_paragraphs_afterwards(self):
        chapters = [make_chapter(1)]
        db = make_db(
            [
                make_result(scalar=make_project()),
                make_result(items=chapters),
            ]
        )
        with (
            patch(f"{MODULE}.create_async_session", return_value=db),
            patch(f"{MODULE}.CheckpointManager"),
            patch(f"{MODULE}.emit_pipeline_event", new_callable=AsyncMock),
            patch(f"{MODULE}.run_stage", new_callable=AsyncMock),
            patch(f"{MODULE}._create_paragraphs_from_chapters", new_callable=AsyncMock) as cp,
        ):
            await _run_single_stage(1, "analyze", AutoRunConfig(target_difficulty="C"))
        cp.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_paragraph_stage_no_paragraphs(self):
        db = make_db(
            [
                make_result(scalar=make_project()),
                make_result(items=[]),  # paragraphs
            ]
        )
        with (
            patch(f"{MODULE}.create_async_session", return_value=db),
            patch(f"{MODULE}.CheckpointManager"),
            patch(f"{MODULE}.emit_pipeline_event", new_callable=AsyncMock),
            patch(f"{MODULE}.run_stage", new_callable=AsyncMock) as rs,
        ):
            await _run_single_stage(1, "synthesize", AutoRunConfig())
        rs.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_paragraph_stage_empty_text_skipped_without_checkpoint(self):
        paras = [
            make_paragraph(pid=1, chapter_id=None, index=1, text="   "),  # empty -> skip
            make_paragraph(pid=2, chapter_id=10, index=2, text="real content"),
        ]
        chapter_row = make_chapter(1)
        db_results = [
            make_result(scalar=make_project()),
            make_result(items=paras),
            make_result(scalar=chapter_row),  # para2 chapter lookup
        ]

        db = AsyncMock()
        db.close = AsyncMock()

        async def exec_fn(*a, **k):
            return db_results.pop(0)

        db.execute = exec_fn
        with (
            patch(f"{MODULE}.create_async_session", return_value=db),
            patch(f"{MODULE}.CheckpointManager") as cm,
            patch(f"{MODULE}.emit_pipeline_event", new_callable=AsyncMock),
            patch(f"{MODULE}.run_stage", new_callable=AsyncMock) as rs,
        ):
            cm.return_value.is_stage_done.return_value = False
            await _run_single_stage(1, "edit", AutoRunConfig(target_difficulty="B"))
        assert rs.await_count == 1
        ckpt = cm.return_value
        # Empty-text paragraph skipped before any checkpoint bookkeeping
        ckpt.is_stage_done.assert_called_once_with("edit", 1, 2)
        ckpt.mark_stage_done.assert_called_once_with("edit", 1, 2)

    @pytest.mark.asyncio
    async def test_paragraph_stage_checkpoint_skip(self):
        paras = [make_paragraph(1), make_paragraph(2)]
        chapter_row = make_chapter(1)
        db_results = [
            make_result(scalar=make_project()),
            make_result(items=paras),
            make_result(scalar=chapter_row),
            make_result(scalar=chapter_row),
        ]

        db = AsyncMock()
        db.close = AsyncMock()
        results = list(db_results)

        async def exec_fn(*a, **k):
            return results.pop(0)

        db.execute = exec_fn
        ckpt = MagicMock()
        ckpt.is_stage_done.side_effect = [True, True]
        with (
            patch(f"{MODULE}.create_async_session", return_value=db),
            patch(f"{MODULE}.CheckpointManager", return_value=ckpt),
            patch(f"{MODULE}.emit_pipeline_event", new_callable=AsyncMock),
            patch(f"{MODULE}.run_stage", new_callable=AsyncMock) as rs,
        ):
            await _run_single_stage(1, "annotate", AutoRunConfig())
        rs.assert_not_awaited()
        ckpt.mark_stage_done.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_stage_logs_warning_only(self):
        db = make_db([make_result(scalar=make_project())])
        with (
            patch(f"{MODULE}.create_async_session", return_value=db),
            patch(f"{MODULE}.CheckpointManager"),
            patch(f"{MODULE}.emit_pipeline_event", new_callable=AsyncMock),
            patch(f"{MODULE}.run_stage", new_callable=AsyncMock) as rs,
        ):
            await _run_single_stage(1, "does_not_exist", AutoRunConfig())
        rs.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_db_failure_propagates_and_closes_session(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=RuntimeError("db connection lost"))
        db.close = AsyncMock()
        with patch(f"{MODULE}.create_async_session", return_value=db):
            with pytest.raises(RuntimeError, match="connection lost"):
                await _run_single_stage(1, "extract", AutoRunConfig())
        db.close.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint state-machine guards: start/status/pause/resume/cancel
# ─────────────────────────────────────────────────────────────────────────────


class TestStartEndpoint:
    @pytest.mark.asyncio
    async def test_start_404_when_project_missing(self):
        db = make_db([make_result(scalar=None)])
        with pytest.raises(DomainError) as ei:
            await start_auto_run(42, AutoRunStartRequest(), BackgroundTasks(), db)
        assert _code(ei.value) == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_start_rejects_duplicate_running_run(self):
        db = make_db([make_result(scalar=make_project())])
        _active_runs[1] = {"run_id": "r1", "status": "running"}
        with pytest.raises(DomainError) as ei:
            await start_auto_run(1, AutoRunStartRequest(), BackgroundTasks(), db)
        assert _code(ei.value) == "CONFLICT"

    @pytest.mark.asyncio
    async def test_start_allows_restart_after_previous_completed(self):
        db = make_db([make_result(scalar=make_project())])
        _active_runs[1] = {"run_id": "old", "status": "completed"}
        bt = BackgroundTasks()
        resp = await start_auto_run(1, AutoRunStartRequest(config=AutoRunConfig(cost_limit_usd=2.0)), bt, db)
        assert resp.status == "running"
        assert resp.run_id.startswith("autorun_1_")
        assert bt.tasks  # background task registered


class TestStatusEndpoint:
    @pytest.mark.asyncio
    async def test_status_not_started(self):
        resp = await get_auto_run_status(7)
        assert resp.status == "not_started"
        assert resp.run_id == "unknown"

    @pytest.mark.asyncio
    async def test_status_running_progress_and_flags(self):
        _active_runs[9] = {
            "run_id": "r9",
            "status": "running",
            "current_stage": "synthesize",
            "completed_stages": ["extract", "analyze", "annotate"],
            "started_at": "2026-08-25T00:00:00Z",
        }
        resp = await get_auto_run_status(9)
        assert resp.progress == pytest.approx(3 / 7)
        assert resp.can_pause is True
        assert resp.can_resume is False
        assert resp.can_cancel is True

    @pytest.mark.asyncio
    async def test_status_paused_flags(self):
        _active_runs[9] = {
            "run_id": "r9",
            "status": "paused",
            "current_stage": None,
            "completed_stages": ["extract"],
            "started_at": None,
        }
        resp = await get_auto_run_status(9)
        assert resp.can_pause is False
        assert resp.can_resume is True


class TestActionEndpoints:
    def seed(self, pid, status):
        _active_runs[pid] = {"run_id": f"r-{pid}", "status": status}

    @pytest.mark.asyncio
    async def test_pause_requires_existing_run(self):
        with pytest.raises(DomainError) as ei:
            await pause_auto_run(1)
        assert _code(ei.value) == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_pause_rejects_paused_run(self):
        self.seed(1, "paused")
        with pytest.raises(DomainError) as ei:
            await pause_auto_run(1)
        assert _code(ei.value) == "CONFLICT"

    @pytest.mark.asyncio
    async def test_pause_sets_pending_flag(self):
        self.seed(1, "running")
        resp = await pause_auto_run(1)
        assert resp.action == "pause"
        assert resp.status == "pending"
        assert _active_runs[1]["pending_pause"] is True

    @pytest.mark.asyncio
    async def test_resume_requires_paused(self):
        self.seed(2, "running")
        with pytest.raises(DomainError) as ei:
            await resume_auto_run(2)
        assert _code(ei.value) == "CONFLICT"

    @pytest.mark.asyncio
    async def test_resume_emits_resumed_event(self):
        self.seed(2, "paused")
        with patch(f"{MODULE}.emit_pipeline_event", new_callable=AsyncMock) as ev:
            resp = await resume_auto_run(2)
        assert resp.status == "resumed"
        assert _active_runs[2]["status"] == "running"
        ev.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancel_requires_active(self):
        with pytest.raises(DomainError) as ei:
            await cancel_auto_run(3)
        assert _code(ei.value) == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_cancel_rejects_terminal_state(self):
        self.seed(3, "completed")
        with pytest.raises(DomainError) as ei:
            await cancel_auto_run(3)
        assert _code(ei.value) == "CONFLICT"

    @pytest.mark.asyncio
    async def test_cancels_running_and_removes_state(self):
        self.seed(3, "running")
        resp = await cancel_auto_run(3)
        assert resp.status == "cancelled"
        assert 3 not in _active_runs

    @pytest.mark.asyncio
    async def test_cancels_paused(self):
        self.seed(4, "paused")
        resp = await cancel_auto_run(4)
        assert resp.status == "cancelled"


# ─────────────────────────────────────────────────────────────────────────────
# Autopilot endpoints + heuristic config generation
# ─────────────────────────────────────────────────────────────────────────────


class TestAutopilotEndpoints:
    @pytest.mark.asyncio
    async def test_start_autopilot_404(self):
        db = make_db([make_result(scalar=None)])
        with pytest.raises(DomainError) as ei:
            await start_autopilot(99, BackgroundTasks(), db)
        assert _code(ei.value) == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_start_autopilot_conflict_with_running_run(self):
        db = make_db([make_result(scalar=make_project())])
        _active_runs[5] = {"run_id": "x", "status": "running"}
        with pytest.raises(DomainError) as ei:
            await start_autopilot(5, BackgroundTasks(), db)
        assert _code(ei.value) == "CONFLICT"

    @pytest.mark.asyncio
    async def test_start_autopilot_success(self):
        db = make_db([make_result(scalar=make_project())])
        fake_cfg = AutopilotConfig(
            target_difficulty="B",
            primary_voice_preference="female",
            speech_rate_preference="standard",
            cost_limit_usd=5.0,
            quality_threshold=0.8,
            max_regeneration_attempts=3,
            enable_background_music=False,
            enable_sfx=True,
            reasoning="auto",
            confidence=0.85,
        )
        bt = BackgroundTasks()
        with patch(f"{MODULE}._generate_autopilot_config", new_callable=AsyncMock, return_value=fake_cfg) as gen:
            resp = await start_autopilot(5, bt, db)
        gen.assert_awaited_once()
        assert resp.run_id.startswith("autorun_5_")
        assert bt.tasks

    @pytest.mark.asyncio
    async def test_preview_404(self):
        db = make_db([make_result(scalar=None)])
        with pytest.raises(DomainError) as ei:
            await preview_autopilot_config(77, db)
        assert _code(ei.value) == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_preview_success(self):
        db = make_db([make_result(scalar=make_project())])
        fake_cfg = AutopilotConfig(
            target_difficulty="D",
            primary_voice_preference="neutral",
            speech_rate_preference="slow",
            cost_limit_usd=1.0,
            quality_threshold=0.7,
            max_regeneration_attempts=2,
            enable_background_music=False,
            enable_sfx=True,
            reasoning="auto",
            confidence=0.85,
        )
        with patch(f"{MODULE}._generate_autopilot_config", new_callable=AsyncMock, return_value=fake_cfg):
            resp = await preview_autopilot_config(77, db)
        assert resp.target_difficulty == "D"


def make_analysis_chapter(raw_len=100, extracted_len=0, analyzed=None):
    ch = MagicMock()
    ch.raw_text = "x" * raw_len
    ch.extracted_text = "y" * extracted_len
    ch.analyzed_json = analyzed
    return ch


class TestGenerateAutopilotConfigHeuristics:
    async def run_cfg(self, chapters):
        db = make_db([make_result(scalar=make_project(chapters=chapters))])
        return await _generate_autopilot_config(1, db)

    @pytest.mark.asyncio
    async def test_tiny_project_difficulty_d_neutral_slow_min_cost(self):
        cfg = await self.run_cfg([make_analysis_chapter(100)])
        assert cfg.target_difficulty == "D"
        assert cfg.primary_voice_preference == "neutral"
        assert cfg.speech_rate_preference == "slow"  # no dialogue info
        assert cfg.cost_limit_usd == 1.0  # floor applied
        assert cfg.quality_threshold == 0.7
        assert cfg.max_regeneration_attempts == 2
        assert cfg.enable_background_music is False

    @pytest.mark.asyncio
    async def test_medium_project_difficulty_c(self):
        cfg = await self.run_cfg([make_analysis_chapter(raw_len=60_000)])
        assert cfg.target_difficulty == "C"

    @pytest.mark.asyncio
    async def test_large_project_difficulty_b_bgm_on(self):
        cfg = await self.run_cfg([make_analysis_chapter(raw_len=250_000)])
        assert cfg.target_difficulty == "B"
        assert cfg.enable_background_music is True
        assert cfg.quality_threshold == 0.8
        assert cfg.max_regeneration_attempts == 3

    @pytest.mark.asyncio
    async def test_huge_project_difficulty_a_cost_cap(self):
        cfg = await self.run_cfg([make_analysis_chapter(raw_len=600_000)])
        assert cfg.target_difficulty == "A"
        assert cfg.cost_limit_usd <= 50.0

    @pytest.mark.asyncio
    async def test_voice_pref_female_majority(self):
        analyzed = {"characters": [{"gender": "Female"}, {"gender": "woman"}, {"gender": "male"}]}
        cfg = await self.run_cfg([make_analysis_chapter(analyzed=analyzed)])
        assert cfg.primary_voice_preference == "female"

    @pytest.mark.asyncio
    async def test_voice_pref_male_alias_man(self):
        analyzed = {"characters": [{"gender": "man"}, {"gender": "boy"}]}
        cfg = await self.run_cfg([make_analysis_chapter(analyzed=analyzed)])
        assert cfg.primary_voice_preference == "male"

    @pytest.mark.asyncio
    async def test_analyzed_json_string_form_parsed(self):
        import json

        analyzed = json.dumps({"characters": [{"gender": "woman"}]})
        cfg = await self.run_cfg([make_analysis_chapter(analyzed=analyzed)])
        assert cfg.primary_voice_preference == "female"

    @pytest.mark.asyncio
    async def test_malformed_gender_values_do_not_crash(self):
        # gender non-string triggers AttributeError inside handler -> swallowed
        analyzed = {"characters": [{"gender": 123}, {"dialogue_count": 5}]}
        cfg = await self.run_cfg([make_analysis_chapter(analyzed=analyzed)])
        assert cfg.primary_voice_preference == "neutral"

    @pytest.mark.asyncio
    async def test_non_dict_analyzed_json_swallowed(self):
        cfg = await self.run_cfg([make_analysis_chapter(analyzed=12345)])  # TypeError branch
        assert isinstance(cfg, AutopilotConfig)

    @pytest.mark.asyncio
    async def test_dialogue_heavy_standard_rate_high_ratio(self):
        analyzed = {"characters": [{"gender": "male", "dialogue_count": 500}]}
        cfg = await self.run_cfg([make_analysis_chapter(raw_len=1000, extracted_len=0, analyzed=analyzed)])
        # dialogue_chars = 500*50 = 25000 > total_chars → ratio capped at 1.0 > 0.6
        assert cfg.speech_rate_preference == "standard"

    @pytest.mark.asyncio
    async def test_moderate_dialogue_ratio_branch(self):
        # ratio between 0.3 and 0.6 → still standard but exercises second branch
        analyzed = {"characters": [{"gender": "male", "dialogue_count": 8}]}
        # dialogue_chars = 400; total = 1000 → ratio 0.4
        cfg = await self.run_cfg([make_analysis_chapter(raw_len=1000, analyzed=analyzed)])
        assert cfg.speech_rate_preference == "standard"

    @pytest.mark.asyncio
    async def test_reasoning_mentions_counts(self):
        cfg = await self.run_cfg([make_analysis_chapter(raw_len=100)])
        assert "chapters" in cfg.reasoning
        assert cfg.confidence == 0.85


# ─────────────────────────────────────────────────────────────────────────────
# get_intermediate_product — every stage product type
# ─────────────────────────────────────────────────────────────────────────────


class TestIntermediateProduct:
    async def call(self, results, stage, chapter_id=None):
        results.insert(0, make_result(scalar=make_project()))
        db = make_db(results)
        return await get_intermediate_product(1, stage, chapter_id=chapter_id, db=db)

    @pytest.mark.asyncio
    async def test_project_missing_404(self):
        db = make_db([make_result(scalar=None)])
        with pytest.raises(DomainError) as ei:
            await get_intermediate_product(1, "extract", db=db)
        assert _code(ei.value) == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_invalid_stage_400(self):
        db = make_db([make_result(scalar=make_project())])
        with pytest.raises(DomainError) as ei:
            await get_intermediate_product(1, "nope", db=db)
        assert _code(ei.value) == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_explicit_chapter_not_in_project_404(self):
        db = make_db(
            [
                make_result(scalar=make_project()),
                make_result(scalar=None),  # chapter lookup misses
            ]
        )
        with pytest.raises(DomainError) as ei:
            await get_intermediate_product(1, "extract", chapter_id=555, db=db)
        assert _code(ei.value) == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_default_first_chapter_missing_404(self):
        db = make_db([make_result(scalar=make_project()), make_result(first=None)])
        with pytest.raises(DomainError) as ei:
            await get_intermediate_product(1, "extract", db=db)
        assert _code(ei.value) == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_extract_product(self):
        ch = make_chapter(1, raw_text="raw!", extracted_text="clean!")
        prod = await self.call([make_result(first=ch)], "extract")
        assert prod.product_type == "text"
        assert prod.data["raw_text"] == "raw!"
        assert prod.data["extracted_text"] == "clean!"

    @pytest.mark.asyncio
    async def test_analyze_product(self):
        ch = make_chapter(1, analyzed_json={"characters": []})
        prod = await self.call([make_result(first=ch)], "analyze")
        assert prod.data["analyzed"] == {"characters": []}

    def paragraph_stage_results(self, paras):
        return [make_result(items=paras)]

    @pytest.mark.asyncio
    async def test_annotate_product(self):
        p = make_paragraph(1, speaker_canonical_name="narrator", is_dialogue=False)
        ch = make_chapter(1)
        prod = await self.call([make_result(first=ch), make_result(items=[p])], "annotate")
        ann = prod.data["annotations"][0]
        assert ann["paragraph_id"] == 1
        assert ann["speaker_canonical_name"] == "narrator"

    @pytest.mark.asyncio
    async def test_edit_product(self):
        p = make_paragraph(2, edited_text="edited!")
        ch = make_chapter(2)
        prod = await self.call([make_result(first=ch), make_result(items=[p])], "edit")
        edit = prod.data["edits"][0]
        assert edit["edited_text"] == "edited!"

    @pytest.mark.asyncio
    async def test_audio_postprocess_product(self):
        p = make_paragraph(3, needs_sfx=True, sfx_tags=["boom"])
        ch = make_chapter(1)
        prod = await self.call([make_result(first=ch), make_result(items=[p])], "audio_postprocess")
        params = prod.data["audio_postprocess_params"][0]
        assert params["needs_sfx"] is True
        assert params["sfx_tags"] == ["boom"]

    @pytest.mark.asyncio
    async def test_synthesize_product_audio_type(self):
        seg = MagicMock(
            id=900, file_path="/tmp/a.wav", format="wav", duration_ms=1200, engine="edge", voice_id="v1", status="DONE"
        )
        p = make_paragraph(4, audio_segment_id=900)
        ch = make_chapter(1)
        prod = await self.call(
            [
                make_result(first=ch),
                make_result(items=[p]),
                make_result(scalar=seg),  # AudioSegment lookup
            ],
            "synthesize",
        )
        assert prod.product_type == "audio"
        assert prod.data["audio_segments"][0]["segment_id"] == 900

    @pytest.mark.asyncio
    async def test_synthesize_skips_paragraph_without_segment(self):
        p = make_paragraph(5, audio_segment_id=None)
        ch = make_chapter(1)
        prod = await self.call([make_result(first=ch), make_result(items=[p])], "synthesize")
        assert prod.data["audio_segments"] == []

    @pytest.mark.asyncio
    async def test_quality_product(self):
        qual = MagicMock(
            id=70,
            speaker_clarity=0.9,
            emotion_match=0.8,
            text_audio_alignment=0.95,
            overall_score=0.88,
            issues=[],
            fix_suggestions=[],
            needs_regeneration=False,
        )
        p = make_paragraph(6)
        ch = make_chapter(1)
        prod = await self.call(
            [
                make_result(first=ch),
                make_result(items=[p]),
                make_result(scalar=qual),
            ],
            "quality",
        )
        q = prod.data["quality_results"][0]
        assert q["overall_score"] == 0.88
