"""Tests for Pipeline FSM (Task 2.2: 双模态 FSM 路由)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audiobook_studio.agent.fsm import (
    AUTOPILOT_PHASES,
    INTERACTIVE_PHASES,
    STATE_TO_STAGE,
    PipelineContext,
    PipelineFSM,
    PipelineMode,
    PipelineState,
    _fsm_instances,
    get_fsm,
    remove_fsm,
)


class TestPipelineFSM:
    """Core FSM logic tests."""

    def setup_method(self):
        """Clear FSM instances before each test."""
        _fsm_instances.clear()

    def teardown_method(self):
        """Clean up after each test."""
        _fsm_instances.clear()

    def test_autopilot_phases_sequence(self):
        """Verify AUTOPILOT phases match expected order."""
        expected = [
            PipelineState.EXTRACTING,
            PipelineState.ANALYZING,
            PipelineState.ANNOTATING,
            PipelineState.AUDIO_POSTPROCESSING,
            PipelineState.SYNTHESIZING,
            PipelineState.QUALITY_CHECK,
            PipelineState.EXPORTING,
        ]
        assert AUTOPILOT_PHASES == expected

    def test_interactive_phases_sequence(self):
        """Verify INTERACTIVE phases include PENDING_HUMAN_CONFIRM after ANNOTATING."""
        expected = [
            PipelineState.EXTRACTING,
            PipelineState.ANALYZING,
            PipelineState.ANNOTATING,
            PipelineState.PENDING_HUMAN_CONFIRM,
            PipelineState.AUDIO_POSTPROCESSING,
            PipelineState.SYNTHESIZING,
            PipelineState.QUALITY_CHECK,
            PipelineState.EXPORTING,
        ]
        assert INTERACTIVE_PHASES == expected

    def test_initial_state_idle(self):
        """FSM starts in IDLE state."""
        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        fsm = PipelineFSM(context)
        assert fsm.current_state == PipelineState.IDLE

    def test_next_state_from_idle_autopilot(self):
        """Next state from IDLE should be EXTRACTING in AUTOPILOT."""
        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        fsm = PipelineFSM(context)
        assert fsm.next_state() == PipelineState.EXTRACTING

    def test_next_state_from_idle_interactive(self):
        """Next state from IDLE should be EXTRACTING in INTERACTIVE."""
        context = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, chapter_index=1)
        fsm = PipelineFSM(context)
        assert fsm.next_state() == PipelineState.EXTRACTING

    def test_can_transition_autopilot_annotate_to_audio_postprocess(self):
        """AUTOPILOT: can transition ANNOTATING -> AUDIO_POSTPROCESSING."""
        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.ANNOTATING
        assert fsm.can_transition(PipelineState.AUDIO_POSTPROCESSING) is True

    def test_cannot_transition_autopilot_annotate_to_pending_confirm(self):
        """AUTOPILOT: cannot transition ANNOTATING -> PENDING_HUMAN_CONFIRM."""
        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.ANNOTATING
        assert fsm.can_transition(PipelineState.PENDING_HUMAN_CONFIRM) is False

    def test_can_transition_interactive_annotate_to_pending_confirm(self):
        """INTERACTIVE: can transition ANNOTATING -> PENDING_HUMAN_CONFIRM."""
        context = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, chapter_index=1)
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.ANNOTATING
        assert fsm.can_transition(PipelineState.PENDING_HUMAN_CONFIRM) is True

    def test_can_transition_interactive_pending_to_audio_postprocess(self):
        """INTERACTIVE: can transition PENDING_HUMAN_CONFIRM -> AUDIO_POSTPROCESSING after confirmation."""
        context = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, chapter_index=1, user_confirmed=True)
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.PENDING_HUMAN_CONFIRM
        assert fsm.can_transition(PipelineState.AUDIO_POSTPROCESSING) is True

    def test_cannot_transition_interactive_pending_to_audio_postprocess_unconfirmed(self):
        """INTERACTIVE: cannot transition PENDING_HUMAN_CONFIRM -> AUDIO_POSTPROCESSING without confirmation."""
        context = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, chapter_index=1, user_confirmed=False)
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.PENDING_HUMAN_CONFIRM
        assert fsm.can_transition(PipelineState.AUDIO_POSTPROCESSING) is False

    @pytest.mark.asyncio
    async def test_transition_to_valid_state(self):
        """Valid state transition should succeed."""
        context = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, chapter_index=1)
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.ANNOTATING
        result = await fsm.transition_to(PipelineState.PENDING_HUMAN_CONFIRM)
        assert result is True
        assert fsm.current_state == PipelineState.PENDING_HUMAN_CONFIRM

    @pytest.mark.asyncio
    async def test_transition_to_invalid_state(self):
        """Invalid state transition should fail."""
        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.ANNOTATING
        result = await fsm.transition_to(PipelineState.PENDING_HUMAN_CONFIRM)
        assert result is False
        assert fsm.current_state == PipelineState.ANNOTATING  # unchanged

    @pytest.mark.asyncio
    async def test_confirm_interactive_mode(self):
        """confirm() should set confirmation event and return True.

        Note: user_confirmed is set by wait_for_confirmation() or continue_after_confirmation(),
        not directly by confirm().
        """
        context = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, chapter_index=1)
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.PENDING_HUMAN_CONFIRM
        result = fsm.confirm()
        assert result is True
        # confirm() only sets the event; user_confirmed becomes True after wait_for_confirmation()
        assert context._confirmation_event.is_set()
        assert context._confirmation_event.is_set()

    def test_confirm_wrong_state(self):
        """confirm() in wrong state should return False."""
        context = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, chapter_index=1)
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.ANNOTATING
        result = fsm.confirm()
        assert result is False

    def test_get_status(self):
        """get_status() should return proper dict."""
        context = PipelineContext(
            project_id=1,
            mode=PipelineMode.INTERACTIVE,
            chapter_index=2,
            chapter_id=5,
        )
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.ANNOTATING
        status = fsm.get_status()
        assert status["project_id"] == 1
        assert status["mode"] == "interactive"
        assert status["chapter_index"] == 2
        assert status["chapter_id"] == 5
        assert status["current_state"] == "annotating"
        assert "completed_stages" in status

    def test_stop_clears_running(self):
        """stop() should set _running to False."""
        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        fsm = PipelineFSM(context)
        fsm._running = True
        fsm.stop()
        assert fsm._running is False

    def test_get_fsm_creates_instance(self):
        """get_fsm should create and cache instance."""
        fsm1 = get_fsm(1, PipelineMode.AUTOPILOT, 1)
        fsm2 = get_fsm(1, PipelineMode.AUTOPILOT, 1)
        assert fsm1 is fsm2  # same instance
        assert fsm1.context.project_id == 1
        assert fsm1.context.mode == PipelineMode.AUTOPILOT
        assert fsm1.context.chapter_index == 1

    def test_remove_fsm(self):
        """remove_fsm should delete instance."""
        fsm = get_fsm(1, PipelineMode.AUTOPILOT, 1)
        remove_fsm(1)
        assert 1 not in _fsm_instances


class TestPipelineFSMExecution:
    """Tests for pipeline execution with mocked stage runner."""

    def setup_method(self):
        _fsm_instances.clear()

    def teardown_method(self):
        _fsm_instances.clear()

    @pytest.mark.asyncio
    async def test_autopilot_runs_all_phases(self):
        """AUTOPILOT should execute all phases to completion."""
        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        mock_runner = AsyncMock(return_value={"result": "ok"})
        fsm = PipelineFSM(context, stage_runner=mock_runner)

        result = await fsm.run_until_pause_or_complete()

        assert result["status"] == "completed"
        assert result["current_state"] == PipelineState.COMPLETED.value
        # Should have called runner for each phase except IDLE
        expected_calls = len(AUTOPILOT_PHASES)
        assert mock_runner.call_count == expected_calls

    @pytest.mark.asyncio
    async def test_interactive_pauses_at_pending_confirm(self):
        """INTERACTIVE should pause at PENDING_HUMAN_CONFIRM."""
        context = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, chapter_index=1)
        mock_runner = AsyncMock(return_value={"result": "ok"})
        fsm = PipelineFSM(context, stage_runner=mock_runner)

        result = await fsm.run_until_pause_or_complete()

        assert result["status"] == "paused"
        assert result["current_state"] == PipelineState.PENDING_HUMAN_CONFIRM.value
        assert result["paused_at"] == PipelineState.PENDING_HUMAN_CONFIRM.value
        # Should have called runner for EXTRACTING, ANALYZING, ANNOTATING (3 phases)
        assert mock_runner.call_count == 3

    @pytest.mark.asyncio
    async def test_continue_after_confirmation_completes(self):
        """After confirmation, INTERACTIVE should complete remaining phases."""
        context = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, chapter_index=1)
        mock_runner = AsyncMock(return_value={"result": "ok"})
        fsm = PipelineFSM(context, stage_runner=mock_runner)

        # First run: pauses at PENDING_HUMAN_CONFIRM
        await fsm.run_until_pause_or_complete()
        assert mock_runner.call_count == 3

        # Continue after confirmation
        result = await fsm.continue_after_confirmation()

        assert result["status"] == "completed"
        assert result["current_state"] == PipelineState.COMPLETED.value
        # Should have called runner for remaining 4 phases (AUDIO_POSTPROCESSING through EXPORTING)
        total_phases = len(INTERACTIVE_PHASES) - 1  # minus PENDING_HUMAN_CONFIRM
        assert mock_runner.call_count == total_phases

    @pytest.mark.asyncio
    async def test_autopilot_handles_stage_failure(self):
        """AUTOPILOT should return failed status on stage error."""
        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        mock_runner = AsyncMock(side_effect=Exception("Stage failed"))
        fsm = PipelineFSM(context, stage_runner=mock_runner)

        result = await fsm.run_until_pause_or_complete()

        assert result["status"] == "failed"
        assert result["current_state"] == PipelineState.FAILED.value
        assert "Stage failed" in result["error"]

    @pytest.mark.asyncio
    async def test_stage_results_stored_in_context(self):
        """Stage results should be stored in context.results."""
        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        mock_runner = AsyncMock(return_value={"stage": "extract", "data": "text"})
        fsm = PipelineFSM(context, stage_runner=mock_runner)

        await fsm.run_until_pause_or_complete()

        # Results should be stored by stage name
        assert "extract" in context.results
        assert context.results["extract"]["stage"] == "extract"


class TestSTATE_TO_STAGE_Mapping:
    """Verify STATE_TO_STAGE mapping covers all expected states."""

    def test_all_states_mapped(self):
        """All pipeline states should have corresponding stage names."""
        expected_mappings = {
            PipelineState.EXTRACTING: "extract",
            PipelineState.ANALYZING: "analyze",
            PipelineState.ANNOTATING: "annotate",
            PipelineState.AUDIO_POSTPROCESSING: "audio_postprocess",
            PipelineState.SYNTHESIZING: "synthesize",
            PipelineState.QUALITY_CHECK: "quality",
            PipelineState.EXPORTING: "export",
        }
        for state, stage in expected_mappings.items():
            assert STATE_TO_STAGE[state] == stage

    def test_no_unknown_states(self):
        """All non-terminal states should be mapped."""
        for state in PipelineState:
            if state not in [
                PipelineState.IDLE,
                PipelineState.PENDING_HUMAN_CONFIRM,
                PipelineState.COMPLETED,
                PipelineState.FAILED,
            ]:
                assert state in STATE_TO_STAGE


class TestPipelineContext:
    """Tests for PipelineContext dataclass."""

    def test_default_values(self):
        """Context should have correct defaults."""
        context = PipelineContext(
            project_id=1,
            mode=PipelineMode.AUTOPILOT,
            chapter_index=1,
        )
        assert context.current_state == PipelineState.IDLE
        assert context.chapter_id is None
        assert context.paused_at is None
        assert context.user_confirmed is False
        assert context.error is None
        assert context.results == {}

    def test_confirmation_event_initialized(self):
        """Confirmation event should be initialized in __post_init__."""
        context = PipelineContext(
            project_id=1,
            mode=PipelineMode.INTERACTIVE,
            chapter_index=1,
        )
        assert hasattr(context, "_confirmation_event")
        assert isinstance(context._confirmation_event, asyncio.Event)


class TestPipelineFSMIntegration:
    """Integration-style tests with real orchestrator (mocked)."""

    def setup_method(self):
        _fsm_instances.clear()

    def teardown_method(self):
        _fsm_instances.clear()

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.agent.fsm.SessionLocal")
    @patch("src.audiobook_studio.agent.fsm.run_pipeline")
    async def test_default_runner_uses_orchestrator(self, mock_run_pipeline, mock_session_local):
        """Default stage runner should use orchestrator.run_pipeline."""
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_run_pipeline.return_value = [{"result": "ok"}]

        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        fsm = PipelineFSM(context)  # Uses default runner

        await fsm.execute_stage(PipelineState.EXTRACTING)

        mock_run_pipeline.assert_called_once()
        call_args = mock_run_pipeline.call_args
        assert call_args[1]["stages"] == ["extract"]
        assert call_args[1]["project_id"] == 1
        assert call_args[1]["chapter_index"] == 1
        mock_db.close.assert_called_once()
