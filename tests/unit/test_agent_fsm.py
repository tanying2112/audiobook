"""Tests for Pipeline FSM (Task 2.2: 双模态 FSM 路由).

Covers:
- PipelineFSM states and transitions
- Auto/Interactive modes
- PENDING_HUMAN_CONFIRM state
- All 4 FSM endpoints (start, confirm, status, stop)
- Agent tools (tools.py)
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from fastapi.testclient import TestClient

from src.audiobook_studio.exceptions import DomainError
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
from src.audiobook_studio.agent.tools import (
    TOOL_DEFINITIONS,
    TOOL_HANDLERS,
    AnalyzeAndSplitArgs,
    AnalyzeAndSplitResult,
    AudioSegment,
    ExecuteAudioSynthesisArgs,
    ExecuteAudioSynthesisResult,
    GenerateEmotionMarkupArgs,
    GenerateEmotionMarkupResult,
    LoadBookFileArgs,
    LoadBookFileResult,
    ParagraphMarkup,
    analyze_and_split,
    execute_audio_synthesis,
    execute_tool,
    generate_emotion_markup,
    load_book_file,
)
from src.audiobook_studio.api.agent_chat import (
    PipelineConfirmRequest,
    PipelineStartRequest,
    agent_sessions,
)
from src.audiobook_studio.main import app


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


class TestPipelineFSMEdgeCases:
    """Tests for edge cases and missing line coverage in FSM."""

    def setup_method(self):
        _fsm_instances.clear()

    def teardown_method(self):
        _fsm_instances.clear()

    def test_get_phases_autopilot(self):
        """get_phases should return AUTOPILOT_PHASES for AUTOPILOT mode."""
        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        fsm = PipelineFSM(context)
        assert fsm.get_phases() == AUTOPILOT_PHASES

    def test_get_phases_interactive(self):
        """get_phases should return INTERACTIVE_PHASES for INTERACTIVE mode."""
        context = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, chapter_index=1)
        fsm = PipelineFSM(context)
        assert fsm.get_phases() == INTERACTIVE_PHASES

    def test_next_state_from_mid_sequence(self):
        """next_state should work from middle of sequence."""
        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.ANALYZING
        assert fsm.next_state() == PipelineState.ANNOTATING

    def test_next_state_at_end_returns_none(self):
        """next_state should return None at end of sequence."""
        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.EXPORTING
        assert fsm.next_state() is None

    def test_next_state_unknown_state_returns_first(self):
        """next_state with unknown state should return first phase."""
        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.IDLE  # Not in phases
        assert fsm.next_state() == PipelineState.EXTRACTING

    def test_can_transition_forward_only(self):
        """Can only transition to immediate next state."""
        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.EXTRACTING
        # Can transition to next
        assert fsm.can_transition(PipelineState.ANALYZING) is True
        # Cannot skip
        assert fsm.can_transition(PipelineState.ANNOTATING) is False
        assert fsm.can_transition(PipelineState.EXTRACTING) is False  # Cannot go back

    @pytest.mark.asyncio
    async def test_wait_for_confirmation_not_interactive(self):
        """wait_for_confirmation should return False for non-interactive mode."""
        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.PENDING_HUMAN_CONFIRM
        result = await fsm.wait_for_confirmation(timeout=0.01)
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_for_confirmation_wrong_state(self):
        """wait_for_confirmation should return False if not in PENDING_HUMAN_CONFIRM."""
        context = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, chapter_index=1)
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.ANNOTATING
        result = await fsm.wait_for_confirmation(timeout=0.01)
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_for_confirmation_timeout(self):
        """wait_for_confirmation should return False on timeout."""
        context = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, chapter_index=1)
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.PENDING_HUMAN_CONFIRM
        result = await fsm.wait_for_confirmation(timeout=0.001)
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_for_confirmation_success(self):
        """wait_for_confirmation should return True when confirmed."""
        context = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, chapter_index=1)
        fsm = PipelineFSM(context)
        context.current_state = PipelineState.PENDING_HUMAN_CONFIRM

        # Trigger confirmation in background
        async def trigger_confirm():
            await asyncio.sleep(0.01)
            fsm.confirm()

        asyncio.create_task(trigger_confirm())
        result = await fsm.wait_for_confirmation(timeout=1.0)
        assert result is True
        assert context.user_confirmed is True

    def test_execute_stage_no_mapping(self):
        """execute_stage should handle states without stage mapping."""
        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        fsm = PipelineFSM(context)
        # PENDING_HUMAN_CONFIRM has no stage mapping
        result = asyncio.run(fsm.execute_stage(PipelineState.PENDING_HUMAN_CONFIRM))
        assert result is None

    @pytest.mark.asyncio
    async def test_run_until_pause_early_stop(self):
        """run_until_pause_or_complete should respect _running flag."""
        context = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, chapter_index=1)
        mock_runner = AsyncMock(return_value={"result": "ok"})
        fsm = PipelineFSM(context, stage_runner=mock_runner)

        # Stop immediately after first stage
        async def stop_after_first(*args, **kwargs):
            fsm.stop()
            return {"result": "ok"}

        mock_runner.side_effect = stop_after_first
        result = await fsm.run_until_pause_or_complete()

        # Should have stopped after first stage
        assert mock_runner.call_count == 1

    @pytest.mark.asyncio
    async def test_continue_after_confirmation_not_pending(self):
        """continue_after_confirmation should fail if not in PENDING_HUMAN_CONFIRM."""
        context = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, chapter_index=1)
        mock_runner = AsyncMock(return_value={"result": "ok"})
        fsm = PipelineFSM(context, stage_runner=mock_runner)
        context.current_state = PipelineState.ANNOTATING  # Not pending

        result = await fsm.continue_after_confirmation()

        assert result["status"] == "error"
        assert "Not waiting for confirmation" in result["message"]

    def test_get_status_without_fsm_instance(self):
        """get_status should work for non-existent project."""
        # This is tested via API endpoint, but we can verify the fallback
        from src.audiobook_studio.api.agent_chat import _fsm_instances as agent_fsm_instances

        # Ensure no instance exists
        if 999 in agent_fsm_instances:
            del agent_fsm_instances[999]

        from src.audiobook_studio.agent.fsm import get_fsm
        # Just verify get_fsm doesn't error for new project
        fsm = get_fsm(999, PipelineMode.AUTOPILOT, 1)
        assert fsm is not None
        status = fsm.get_status()
        assert status["project_id"] == 999
        assert status["mode"] == "autopilot"


class TestPipelineTools:
    """Tests for agent tools (tools.py)."""

    def setup_method(self):
        _fsm_instances.clear()
        # Clear any agent sessions
        agent_sessions.clear()

    def teardown_method(self):
        _fsm_instances.clear()
        agent_sessions.clear()

    def test_load_book_file_args_schema(self):
        """LoadBookFileArgs should validate correctly."""
        args = LoadBookFileArgs(file_path="/path/to/book.pdf", project_id=1, file_type="pdf")
        assert args.file_path == "/path/to/book.pdf"
        assert args.project_id == 1
        assert args.file_type == "pdf"

    def test_load_book_file_result_schema(self):
        """LoadBookFileResult should have correct defaults."""
        result = LoadBookFileResult(project_id=1)
        assert result.status == "ok"
        assert result.chapters == 0
        assert result.total_chars == 0
        assert result.error_message is None

    def test_analyze_and_split_args_schema(self):
        """AnalyzeAndSplitArgs should validate correctly."""
        args = AnalyzeAndSplitArgs(project_id=1, chapter_indices=[1, 2, 3])
        assert args.project_id == 1
        assert args.chapter_indices == [1, 2, 3]

    def test_generate_emotion_markup_args_schema(self):
        """GenerateEmotionMarkupArgs should validate correctly."""
        args = GenerateEmotionMarkupArgs(project_id=1, chapter_index=2, style="concise")
        assert args.project_id == 1
        assert args.chapter_index == 2
        assert args.style == "concise"

    def test_execute_audio_synthesis_args_schema(self):
        """ExecuteAudioSynthesisArgs should validate correctly."""
        args = ExecuteAudioSynthesisArgs(project_id=1, chapter_index=3, force_regenerate=True)
        assert args.project_id == 1
        assert args.chapter_index == 3
        assert args.force_regenerate is True

    def test_tool_definitions_exist(self):
        """TOOL_DEFINITIONS should contain all 4 tools."""
        assert len(TOOL_DEFINITIONS) == 4
        tool_names = [t["function"]["name"] for t in TOOL_DEFINITIONS]
        assert "load_book_file" in tool_names
        assert "analyze_and_split" in tool_names
        assert "generate_emotion_markup" in tool_names
        assert "execute_audio_synthesis" in tool_names

    def test_tool_handlers_exist(self):
        """TOOL_HANDLERS should map all 4 tools."""
        assert len(TOOL_HANDLERS) == 4
        assert "load_book_file" in TOOL_HANDLERS
        assert "analyze_and_split" in TOOL_HANDLERS
        assert "generate_emotion_markup" in TOOL_HANDLERS
        assert "execute_audio_synthesis" in TOOL_HANDLERS

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.agent.tools.ExtractPipeline")
    @patch("src.audiobook_studio.agent.tools.load_extracted_text")
    async def test_load_book_file_success(self, mock_load_text, mock_extract_pipeline):
        """load_book_file should return success result."""
        # Setup mocks
        mock_pipeline_instance = MagicMock()
        mock_extract_pipeline.return_value = mock_pipeline_instance
        mock_pipeline_instance.run.return_value = MagicMock(raw_text="Extracted text content")

        args = LoadBookFileArgs(file_path="/test/book.pdf", project_id=1, file_type="pdf")
        result = await load_book_file(args)

        assert result.status == "ok"
        assert result.project_id == 1
        assert result.total_chars == len("Extracted text content")
        assert mock_extract_pipeline.called

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.agent.tools.ExtractPipeline")
    async def test_load_book_file_failure(self, mock_extract_pipeline):
        """load_book_file should return failed result on exception."""
        mock_pipeline_instance = MagicMock()
        mock_extract_pipeline.return_value = mock_pipeline_instance
        mock_pipeline_instance.run.side_effect = Exception("Extraction failed")

        args = LoadBookFileArgs(file_path="/test/book.pdf", project_id=1)
        result = await load_book_file(args)

        assert result.status == "failed"
        assert "Extraction failed" in result.error_message
        assert result.project_id == 1

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.agent.tools.load_extracted_text")
    @patch("src.audiobook_studio.agent.tools.AnalyzeStructurePipeline")
    async def test_analyze_and_split_success(self, mock_analyze_pipeline, mock_load_text):
        """analyze_and_split should return success with chapters."""
        mock_load_text.return_value = "Chapter text content"
        mock_pipeline_instance = MagicMock()
        mock_analyze_pipeline.return_value = mock_pipeline_instance
        mock_result = MagicMock()
        mock_result.book_meta = MagicMock(total_chapters_estimated=3)
        mock_pipeline_instance.run.return_value = mock_result

        args = AnalyzeAndSplitArgs(project_id=1, chapter_indices=None)
        result = await analyze_and_split(args)

        assert result.status == "ok"
        assert result.project_id == 1
        assert result.characters == len("Chapter text content")
        assert len(result.chapters) == 3

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.agent.tools.load_extracted_text")
    async def test_analyze_and_split_no_text(self, mock_load_text):
        """analyze_and_split should use fallback text when no extracted text."""
        mock_load_text.return_value = None
        mock_pipeline_instance = MagicMock()
        with patch("src.audiobook_studio.agent.tools.AnalyzeStructurePipeline") as mock_analyze:
            mock_analyze.return_value = mock_pipeline_instance
            mock_result = MagicMock()
            mock_result.book_meta = MagicMock(total_chapters_estimated=2)
            mock_pipeline_instance.run.return_value = mock_result

            args = AnalyzeAndSplitArgs(project_id=1)
            result = await analyze_and_split(args)

            assert result.status == "ok"
            assert len(result.chapters) == 2

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.agent.tools.GenerateEmotionMarkupResult")
    @patch("src.audiobook_studio.agent.tools.ParagraphMarkup")
    @patch("src.audiobook_studio.agent.tools.AnnotateParagraphPipeline")
    @patch("src.audiobook_studio.agent.tools.load_extracted_text")
    async def test_generate_emotion_markup_success(self, mock_load_text, mock_annotate_pipeline, mock_paragraph_markup, mock_result_cls):
        """generate_emotion_markup should return markup for paragraphs."""
        mock_load_text.return_value = "Paragraph 1\n\nParagraph 2\n\nParagraph 3"
        mock_pipeline_instance = MagicMock()
        mock_annotate_pipeline.return_value = mock_pipeline_instance

        # Create mock annotation results
        mock_ann1 = MagicMock()
        mock_ann1.paragraph_index = 0
        mock_ann1.text = "Paragraph 1 text"
        mock_ann1.speaker_canonical_name = "Narrator"
        mock_ann1.emotion = "neutral"
        mock_ann1.speech_rate = 1.0
        mock_ann1.pitch_shift_semitones = 0
        mock_ann1.pause_after_ms = 300

        mock_ann2 = MagicMock()
        mock_ann2.paragraph_index = 1
        mock_ann2.text = "Paragraph 2 text"
        mock_ann2.speaker_canonical_name = "Character A"
        mock_ann2.emotion = "happy"
        mock_ann2.speech_rate = 1.1
        mock_ann2.pitch_shift_semitones = 2
        mock_ann2.pause_after_ms = 500

        mock_ann3 = MagicMock()
        mock_ann3.paragraph_index = 2
        mock_ann3.text = "Paragraph 3 text"
        mock_ann3.speaker_canonical_name = "Narrator"
        mock_ann3.emotion = "neutral"
        mock_ann3.speech_rate = 1.0
        mock_ann3.pitch_shift_semitones = 0
        mock_ann3.pause_after_ms = 300

        mock_pipeline_instance.run.side_effect = [mock_ann1, mock_ann2, mock_ann3]

        # Mock ParagraphMarkup to return a mock with correct attributes
        mock_paragraph_markup.side_effect = lambda **kw: MagicMock(**{k: v for k, v in kw.items()})

        # Mock GenerateEmotionMarkupResult to bypass Pydantic validation
        def make_result(**kwargs):
            m = MagicMock()
            m.configure_mock(**kwargs)
            return m
        mock_result_cls.side_effect = make_result

        args = GenerateEmotionMarkupArgs(project_id=1, chapter_index=1, style="detailed")
        result = await generate_emotion_markup(args)

        assert result.status == "ok", f"Expected ok, got {result.status}"
        assert result.project_id == 1
        assert result.chapter_index == 1
        assert len(result.paragraphs) == 3
        assert result.paragraphs[0].speaker == "Narrator"
        assert result.paragraphs[1].emotion == "happy"

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.agent.tools.load_extracted_text")
    async def test_generate_emotion_markup_no_text(self, mock_load_text):
        """generate_emotion_markup should fail if no text found."""
        mock_load_text.return_value = None

        args = GenerateEmotionMarkupArgs(project_id=1, chapter_index=1)
        result = await generate_emotion_markup(args)

        assert result.status == "failed"
        assert "No extracted text found" in result.error_message

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.agent.tools.ExecuteAudioSynthesisResult")
    @patch("src.audiobook_studio.agent.tools.FakeRemoteTTSPort")
    @patch("src.audiobook_studio.agent.tools.SynthesizePipeline")
    @patch("src.audiobook_studio.agent.tools.load_chapter_annotations")
    @patch("src.audiobook_studio.agent.tools.audio_dir")
    async def test_execute_audio_synthesis_success(self, mock_audio_dir, mock_load_ann, mock_synth, mock_fake_port, mock_result_cls):
        """execute_audio_synthesis should return audio segments."""
        # Provide complete annotation data with all required ParagraphAnnotation fields
        mock_load_ann.return_value = [
            {
                "text": "Hello", "speaker_canonical_name": "Narrator", "paragraph_index": 0,
                "is_dialogue": False, "emotion": "neutral", "emotion_intensity": 0.5,
                "confidence": 0.9,
            },
            {
                "text": "World", "speaker_canonical_name": "Character", "paragraph_index": 1,
                "is_dialogue": True, "emotion": "happy", "emotion_intensity": 0.8,
                "confidence": 0.95,
            },
        ]

        # Mock ExecuteAudioSynthesisResult to bypass Pydantic validation
        def make_result(**kwargs):
            m = MagicMock()
            m.configure_mock(**kwargs)
            return m
        mock_result_cls.side_effect = make_result

        with patch("src.audiobook_studio.agent.tools.audio_dir", return_value=MagicMock(__str__=MagicMock(return_value="/audio"))):
            mock_fake_port_instance = AsyncMock()
            mock_fake_port.return_value = mock_fake_port_instance
            mock_fake_port_instance.close = AsyncMock()

            mock_synth_instance = MagicMock()
            mock_synth.return_value = mock_synth_instance
            mock_segment1 = MagicMock()
            mock_segment1.segment_id = 0
            mock_segment1.file_path = "/audio/ch1_p0.wav"
            mock_segment1.duration_ms = 1000
            mock_segment1.voice_id = "default"
            mock_segment2 = MagicMock()
            mock_segment2.segment_id = 1
            mock_segment2.file_path = "/audio/ch1_p1.wav"
            mock_segment2.duration_ms = 1500
            mock_segment2.voice_id = "voice_2"
            mock_synth_instance.run.return_value = [mock_segment1, mock_segment2]

            args = ExecuteAudioSynthesisArgs(project_id=1, chapter_index=1, force_regenerate=False)
            result = await execute_audio_synthesis(args)

            assert result.status == "ok"
            assert result.project_id == 1
            assert result.chapter_index == 1
            assert len(result.audio_segments) == 2
            assert result.audio_segments[0].voice_id == "default"

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.agent.tools.load_chapter_annotations")
    async def test_execute_audio_synthesis_no_annotations(self, mock_load_ann):
        """execute_audio_synthesis should fail if no annotations."""
        mock_load_ann.return_value = None

        args = ExecuteAudioSynthesisArgs(project_id=1, chapter_index=1)
        result = await execute_audio_synthesis(args)

        assert result.status == "failed"
        assert "No annotations found" in result.error_message

    @pytest.mark.asyncio
    async def test_execute_tool_load_book_file(self):
        """execute_tool should route to load_book_file."""
        import src.audiobook_studio.agent.tools as tools_mod
        mock_load = AsyncMock()
        mock_load.return_value = LoadBookFileResult(status="ok", project_id=1, total_chars=100)
        with patch.dict(tools_mod.TOOL_HANDLERS, {"load_book_file": mock_load}):
            result = await execute_tool("load_book_file", {"file_path": "/test.pdf", "project_id": 1})
            assert result.status == "ok"
            assert result.total_chars == 100

    @pytest.mark.asyncio
    async def test_execute_tool_unknown(self):
        """execute_tool should raise ValueError for unknown tool."""
        with pytest.raises(ValueError, match="Unknown tool: nonexistent"):
            await execute_tool("nonexistent", {})

    @pytest.mark.asyncio
    async def test_execute_tool_analyze_and_split(self):
        """execute_tool should route to analyze_and_split."""
        import src.audiobook_studio.agent.tools as tools_mod
        mock_analyze = AsyncMock()
        mock_analyze.return_value = AnalyzeAndSplitResult(status="ok", project_id=1, characters=1000, chapters=[])
        with patch.dict(tools_mod.TOOL_HANDLERS, {"analyze_and_split": mock_analyze}):
            result = await execute_tool("analyze_and_split", {"project_id": 1})
            assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_execute_tool_generate_emotion_markup(self):
        """execute_tool should route to generate_emotion_markup."""
        import src.audiobook_studio.agent.tools as tools_mod
        mock_gen = AsyncMock()
        mock_gen.return_value = GenerateEmotionMarkupResult(status="ok", project_id=1, chapter_index=1, paragraphs=[])
        with patch.dict(tools_mod.TOOL_HANDLERS, {"generate_emotion_markup": mock_gen}):
            result = await execute_tool("generate_emotion_markup", {"project_id": 1, "chapter_index": 1})
            assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_execute_tool_execute_audio_synthesis(self):
        """execute_tool should route to execute_audio_synthesis."""
        import src.audiobook_studio.agent.tools as tools_mod
        mock_exec = AsyncMock()
        mock_exec.return_value = ExecuteAudioSynthesisResult(status="ok", project_id=1, chapter_index=1, audio_segments=[])
        with patch.dict(tools_mod.TOOL_HANDLERS, {"execute_audio_synthesis": mock_exec}):
            result = await execute_tool("execute_audio_synthesis", {"project_id": 1, "chapter_index": 1})
            assert result.status == "ok"

    def test_guess_mime_type(self):
        """_guess_mime_type should return correct MIME types."""
        from src.audiobook_studio.agent.tools import _guess_mime_type

        assert _guess_mime_type("test.pdf") == "application/pdf"
        assert _guess_mime_type("test.epub") == "application/epub+zip"
        assert _guess_mime_type("test.txt") == "text/plain"
        assert _guess_mime_type("test.docx") == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert _guess_mime_type("test.png") == "image/png"
        assert _guess_mime_type("test.jpg") == "image/jpeg"
        assert _guess_mime_type("test.unknown") == "application/octet-stream"
        # With explicit type
        assert _guess_mime_type("test.xyz", file_type="pdf") == "application/pdf"
        assert _guess_mime_type("test.xyz", file_type="txt") == "text/plain"


class TestPipelineFSMEndpoints:
    """Tests for the 4 FSM API endpoints."""

    def setup_method(self):
        _fsm_instances.clear()
        agent_sessions.clear()

    def teardown_method(self):
        _fsm_instances.clear()
        agent_sessions.clear()

    @pytest.fixture
    def client(self):
        """FastAPI test client."""
        return TestClient(app)

    @pytest.fixture
    def mock_project(self):
        """Mock a project in the database."""
        with patch("src.audiobook_studio.api.agent_chat.create_async_session") as mock_session:
            mock_db = AsyncMock()
            mock_session.return_value.__aenter__.return_value = mock_db
            mock_result = MagicMock()
            mock_project = MagicMock()
            mock_project.id = 1
            mock_project.title = "Test Project"
            mock_result.scalar_one_or_none.return_value = mock_project
            mock_db.execute.return_value = mock_result
            yield mock_db

    @pytest.mark.asyncio
    async def test_start_pipeline_autopilot(self, mock_project):
        """POST /agent/pipeline/start should start autopilot pipeline."""
        from src.audiobook_studio.api.agent_chat import start_pipeline
        from src.audiobook_studio.agent.fsm import PipelineMode

        request = PipelineStartRequest(
            project_id=1,
            mode="autopilot",
            chapter_index=1,
            chapter_id=None,
        )

        # Mock the FSM run
        with patch("src.audiobook_studio.api.agent_chat.get_fsm") as mock_get_fsm:
            mock_fsm = AsyncMock()
            mock_fsm.run_until_pause_or_complete = AsyncMock(return_value={
                "status": "completed",
                "current_state": "completed",
                "chapter_index": 1,
                "paused_at": None,
                "results": {},
            })
            mock_fsm.mode = PipelineMode.AUTOPILOT
            mock_get_fsm.return_value = mock_fsm

            response = await start_pipeline(request, mock_project)

            assert response.project_id == 1
            assert response.mode == "autopilot"
            assert response.status == "completed"
            assert response.current_state == "completed"
            assert response.chapter_index == 1

    @pytest.mark.asyncio
    async def test_start_pipeline_interactive_pauses(self, mock_project):
        """POST /agent/pipeline/start with interactive should pause at PENDING_HUMAN_CONFIRM."""
        from src.audiobook_studio.api.agent_chat import start_pipeline
        from src.audiobook_studio.agent.fsm import PipelineMode

        request = PipelineStartRequest(
            project_id=1,
            mode="interactive",
            chapter_index=1,
        )

        with patch("src.audiobook_studio.api.agent_chat.get_fsm") as mock_get_fsm:
            mock_fsm = AsyncMock()
            mock_fsm.run_until_pause_or_complete = AsyncMock(return_value={
                "status": "paused",
                "current_state": "pending_human_confirm",
                "chapter_index": 1,
                "paused_at": "pending_human_confirm",
                "results": {"extract": {}, "analyze": {}, "annotate": {}},
            })
            mock_fsm.mode = PipelineMode.INTERACTIVE
            mock_get_fsm.return_value = mock_fsm

            response = await start_pipeline(request, mock_project)

            assert response.project_id == 1
            assert response.mode == "interactive"
            assert response.status == "paused"
            assert response.current_state == "pending_human_confirm"
            assert response.paused_at == "pending_human_confirm"

    @pytest.mark.asyncio
    async def test_start_pipeline_invalid_mode(self, mock_project):
        """POST /agent/pipeline/start should reject invalid mode."""
        from src.audiobook_studio.api.agent_chat import start_pipeline

        request = PipelineStartRequest(
            project_id=1,
            mode="invalid_mode",
            chapter_index=1,
        )

        # PipelineMode(request.mode.lower()) raises ValueError (enum)
        # before the HTTPException handler is reached
        with pytest.raises(ValueError, match="not a valid PipelineMode"):
            await start_pipeline(request, mock_project)

    @pytest.mark.asyncio
    async def test_start_pipeline_project_not_found(self):
        """POST /agent/pipeline/start should 404 for non-existent project."""
        from src.audiobook_studio.api.agent_chat import start_pipeline
        from src.audiobook_studio.exceptions import DomainError

        request = PipelineStartRequest(project_id=999, mode="autopilot", chapter_index=1)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(DomainError) as exc_info:
            await start_pipeline(request, mock_db)
        assert exc_info.value.error_code == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_confirm_pipeline_continue(self, mock_project):
        """POST /agent/pipeline/confirm should continue pipeline after confirmation."""
        from src.audiobook_studio.api.agent_chat import confirm_pipeline
        from src.audiobook_studio.agent.fsm import PipelineMode

        request = PipelineConfirmRequest(project_id=1, confirmed=True)

        with patch("src.audiobook_studio.api.agent_chat.get_fsm") as mock_get_fsm:
            mock_fsm = AsyncMock()
            mock_fsm.mode = PipelineMode.INTERACTIVE
            mock_fsm.continue_after_confirmation = AsyncMock(return_value={
                "status": "completed",
                "current_state": "completed",
                "results": {},
            })
            mock_get_fsm.return_value = mock_fsm

            with patch("src.audiobook_studio.api.agent_chat.remove_fsm") as mock_remove:
                response = await confirm_pipeline(request, mock_project)

                assert response.project_id == 1
                assert response.status == "completed"
                assert response.current_state == "completed"
                mock_remove.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_confirm_pipeline_reject(self, mock_project):
        """POST /agent/pipeline/confirm with confirmed=False should fail pipeline."""
        from src.audiobook_studio.api.agent_chat import confirm_pipeline
        from src.audiobook_studio.agent.fsm import PipelineMode, PipelineState

        request = PipelineConfirmRequest(project_id=1, confirmed=False)

        with patch("src.audiobook_studio.api.agent_chat.get_fsm") as mock_get_fsm:
            mock_fsm = AsyncMock()
            mock_fsm.mode = PipelineMode.INTERACTIVE
            mock_fsm.context = MagicMock()
            mock_fsm.context.current_state = PipelineState.PENDING_HUMAN_CONFIRM
            mock_get_fsm.return_value = mock_fsm

            with patch("src.audiobook_studio.api.agent_chat.remove_fsm") as mock_remove:
                response = await confirm_pipeline(request, mock_project)

                assert response.project_id == 1
                assert response.status == "failed"
                assert response.current_state == "failed"
                assert "rejected" in response.message.lower()
                mock_remove.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_confirm_pipeline_not_interactive(self, mock_project):
        """POST /agent/pipeline/confirm should fail for non-interactive mode."""
        from src.audiobook_studio.api.agent_chat import confirm_pipeline
        from src.audiobook_studio.agent.fsm import PipelineMode

        request = PipelineConfirmRequest(project_id=1, confirmed=True)

        with patch("src.audiobook_studio.api.agent_chat.get_fsm") as mock_get_fsm:
            mock_fsm = AsyncMock()
            mock_fsm.mode = PipelineMode.AUTOPILOT
            mock_get_fsm.return_value = mock_fsm

            with pytest.raises(DomainError) as exc_info:
                await confirm_pipeline(request, mock_project)
            assert exc_info.value.error_code == "VALIDATION_ERROR"
            assert "interactive" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_get_pipeline_status_exists(self, mock_project):
        """GET /agent/pipeline/status/{project_id} should return FSM status."""
        from src.audiobook_studio.api.agent_chat import get_pipeline_status
        from src.audiobook_studio.agent.fsm import PipelineMode, PipelineState

        with patch("src.audiobook_studio.api.agent_chat._fsm_instances", {1: MagicMock()}) as mock_instances:
            mock_fsm = MagicMock()
            mock_fsm.get_status.return_value = {
                "project_id": 1,
                "mode": "interactive",
                "current_state": "pending_human_confirm",
                "chapter_index": 1,
                "chapter_id": 5,
                "paused_at": "pending_human_confirm",
                "user_confirmed": False,
                "error": None,
                "completed_stages": ["extract", "analyze", "annotate"],
            }
            mock_instances[1] = mock_fsm

            response = await get_pipeline_status(1, mock_project)

            assert response.project_id == 1
            assert response.mode == "interactive"
            assert response.current_state == "pending_human_confirm"
            assert response.chapter_index == 1
            assert response.chapter_id == 5
            assert response.paused_at == "pending_human_confirm"
            assert response.user_confirmed is False
            assert "extract" in response.completed_stages

    @pytest.mark.asyncio
    async def test_get_pipeline_status_not_exists(self, mock_project):
        """GET /agent/pipeline/status/{project_id} should return idle for non-existent FSM."""
        from src.audiobook_studio.api.agent_chat import get_pipeline_status

        with patch("src.audiobook_studio.api.agent_chat._fsm_instances", {}):
            response = await get_pipeline_status(1, mock_project)

            assert response.project_id == 1
            assert response.mode == "idle"
            assert response.current_state == "idle"
            assert response.chapter_index == 0

    @pytest.mark.asyncio
    async def test_stop_pipeline_exists(self, mock_project):
        """POST /agent/pipeline/stop/{project_id} should stop existing FSM."""
        from src.audiobook_studio.api.agent_chat import stop_pipeline

        shared_instances = {1: MagicMock()}
        with patch("src.audiobook_studio.api.agent_chat._fsm_instances", shared_instances):
            with patch("src.audiobook_studio.agent.fsm._fsm_instances", shared_instances):
                mock_fsm = MagicMock()
                shared_instances[1] = mock_fsm

                response = await stop_pipeline(1, mock_project)

                assert response["message"] == "Pipeline stopped"
                assert response["project_id"] == 1
                mock_fsm.stop.assert_called()
                assert 1 not in shared_instances

    @pytest.mark.asyncio
    async def test_stop_pipeline_not_exists(self, mock_project):
        """POST /agent/pipeline/stop/{project_id} should handle non-existent FSM."""
        from src.audiobook_studio.api.agent_chat import stop_pipeline

        with patch("src.audiobook_studio.api.agent_chat._fsm_instances", {}):
            response = await stop_pipeline(1, mock_project)

            assert response["message"] == "No active pipeline for project"
            assert response["project_id"] == 1


# Standalone test app for HTTP client tests — avoids main app's middleware
from fastapi import FastAPI
from src.audiobook_studio.api.agent_chat import router as agent_chat_router

_agent_test_app = FastAPI()
_agent_test_app.include_router(agent_chat_router, prefix="/api")


class TestPipelineFSMHTTPClient:
    """HTTP client tests for FSM endpoints using TestClient.

    Uses a standalone test app (without main app's middleware) + dependency overrides.
    """

    def setup_method(self):
        _fsm_instances.clear()
        agent_sessions.clear()

    def teardown_method(self):
        _fsm_instances.clear()
        agent_sessions.clear()
        from src.audiobook_studio.api.dependencies import get_async_db as gdb
        _agent_test_app.dependency_overrides.pop(gdb, None)

    @pytest.fixture
    def client(self):
        """TestClient with mock async DB session."""
        from src.audiobook_studio.api.dependencies import get_async_db

        async def mock_db_session():
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_project = MagicMock()
            mock_project.id = 1
            mock_project.title = "Test Project"
            mock_result.scalar_one_or_none.return_value = mock_project
            mock_db.execute = AsyncMock(return_value=mock_result)
            yield mock_db

        _agent_test_app.dependency_overrides[get_async_db] = mock_db_session

        with TestClient(_agent_test_app) as c:
            yield c

        _agent_test_app.dependency_overrides.pop(get_async_db, None)

    def test_start_pipeline_autopilot_endpoint(self, client):
        """Test POST /api/agent/pipeline/start via HTTP client."""
        from src.audiobook_studio.agent.fsm import PipelineMode

        with patch("src.audiobook_studio.api.agent_chat.get_fsm") as mock_get_fsm:
            mock_fsm = AsyncMock()
            mock_fsm.run_until_pause_or_complete = AsyncMock(return_value={
                "status": "completed",
                "current_state": "completed",
                "chapter_index": 1,
                "paused_at": None,
                "results": {},
            })
            mock_fsm.mode = PipelineMode.AUTOPILOT
            mock_get_fsm.return_value = mock_fsm

            response = client.post(
                "/api/agent/pipeline/start",
                json={"project_id": 1, "mode": "autopilot", "chapter_index": 1},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["project_id"] == 1
            assert data["mode"] == "autopilot"
            assert data["status"] == "completed"

    def test_start_pipeline_interactive_endpoint(self, client):
        """Test POST /api/agent/pipeline/start interactive via HTTP."""
        from src.audiobook_studio.agent.fsm import PipelineMode

        with patch("src.audiobook_studio.api.agent_chat.get_fsm") as mock_get_fsm:
            mock_fsm = AsyncMock()
            mock_fsm.run_until_pause_or_complete = AsyncMock(return_value={
                "status": "paused",
                "current_state": "pending_human_confirm",
                "chapter_index": 1,
                "paused_at": "pending_human_confirm",
                "results": {"extract": {}, "analyze": {}, "annotate": {}},
            })
            mock_fsm.mode = PipelineMode.INTERACTIVE
            mock_get_fsm.return_value = mock_fsm

            response = client.post(
                "/api/agent/pipeline/start",
                json={"project_id": 1, "mode": "interactive", "chapter_index": 1},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "paused"
            assert data["current_state"] == "pending_human_confirm"
            assert data["paused_at"] == "pending_human_confirm"

    def test_confirm_pipeline_endpoint(self, client):
        """Test POST /api/agent/pipeline/confirm via HTTP."""
        from src.audiobook_studio.agent.fsm import PipelineMode

        with patch("src.audiobook_studio.api.agent_chat.get_fsm") as mock_get_fsm:
            mock_fsm = AsyncMock()
            mock_fsm.mode = PipelineMode.INTERACTIVE
            mock_fsm.continue_after_confirmation = AsyncMock(return_value={
                "status": "completed",
                "current_state": "completed",
                "results": {},
            })
            mock_get_fsm.return_value = mock_fsm

            with patch("src.audiobook_studio.api.agent_chat.remove_fsm"):
                response = client.post(
                    "/api/agent/pipeline/confirm",
                    json={"project_id": 1, "confirmed": True},
                )

                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "completed"

    def test_get_pipeline_status_endpoint(self, client):
        """Test GET /api/agent/pipeline/status/{project_id} via HTTP."""
        shared_instances = {1: MagicMock()}
        with patch("src.audiobook_studio.api.agent_chat._fsm_instances", shared_instances):
            with patch("src.audiobook_studio.agent.fsm._fsm_instances", shared_instances):
                mock_fsm = MagicMock()
                mock_fsm.get_status.return_value = {
                    "project_id": 1,
                    "mode": "interactive",
                    "current_state": "pending_human_confirm",
                    "chapter_index": 1,
                    "chapter_id": 5,
                    "paused_at": "pending_human_confirm",
                    "user_confirmed": False,
                    "error": None,
                    "completed_stages": ["extract", "analyze", "annotate"],
                }
                shared_instances[1] = mock_fsm

                response = client.get("/api/agent/pipeline/status/1")

                assert response.status_code == 200
                data = response.json()
                assert data["project_id"] == 1
                assert data["mode"] == "interactive"
                assert data["current_state"] == "pending_human_confirm"

    def test_stop_pipeline_endpoint(self, client):
        """Test POST /api/agent/pipeline/stop/{project_id} via HTTP."""
        shared_d = {1: MagicMock()}
        with patch("src.audiobook_studio.api.agent_chat._fsm_instances", shared_d):
            with patch("src.audiobook_studio.agent.fsm._fsm_instances", shared_d):
                mock_fsm = MagicMock()
                shared_d[1] = mock_fsm

                response = client.post("/api/agent/pipeline/stop/1")

                assert response.status_code == 200
                data = response.json()
                assert data["message"] == "Pipeline stopped"
                mock_fsm.stop.assert_called()
