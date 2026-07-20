"""Pipeline FSM (Finite State Machine) for Autopilot/Interactive modes.

Defines the state machine for pipeline execution with support for:
- Autopilot mode: linear execution through all stages
- Interactive mode: pauses at PENDING_HUMAN_CONFIRM after annotate stage
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from ..database import SessionLocal
from ..pipeline.orchestrator import run_pipeline

logger = logging.getLogger(__name__)


class PipelineState(Enum):
    """Pipeline execution states."""

    IDLE = "idle"
    EXTRACTING = "extracting"
    ANALYZING = "analyzing"
    ANNOTATING = "annotating"
    PENDING_HUMAN_CONFIRM = "pending_human_confirm"
    AUDIO_POSTPROCESSING = "audio_postprocessing"
    SYNTHESIZING = "synthesizing"
    QUALITY_CHECK = "quality_check"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineMode(Enum):
    """Pipeline execution modes."""

    AUTOPILOT = "autopilot"
    INTERACTIVE = "interactive"


# Phase names for state transitions
AUTOPILOT_PHASES = [
    PipelineState.EXTRACTING,
    PipelineState.ANALYZING,
    PipelineState.ANNOTATING,
    PipelineState.AUDIO_POSTPROCESSING,
    PipelineState.SYNTHESIZING,
    PipelineState.QUALITY_CHECK,
    PipelineState.EXPORTING,
]

# Interactive pauses after ANNOTATING
INTERACTIVE_PHASES = [
    PipelineState.EXTRACTING,
    PipelineState.ANALYZING,
    PipelineState.ANNOTATING,
    PipelineState.PENDING_HUMAN_CONFIRM,  # Pause here for human review
    PipelineState.AUDIO_POSTPROCESSING,
    PipelineState.SYNTHESIZING,
    PipelineState.QUALITY_CHECK,
    PipelineState.EXPORTING,
]

# Stage name mapping for orchestrator
STAGE_TO_STATE = {
    "extract": PipelineState.EXTRACTING,
    "analyze": PipelineState.ANALYZING,
    "annotate": PipelineState.ANNOTATING,
    "audio_postprocess": PipelineState.AUDIO_POSTPROCESSING,
    "synthesize": PipelineState.SYNTHESIZING,
    "quality": PipelineState.QUALITY_CHECK,
    "export": PipelineState.EXPORTING,
}

STATE_TO_STAGE = {v: k for k, v in STAGE_TO_STATE.items()}


@dataclass
class PipelineContext:
    """Context for pipeline execution."""

    project_id: int
    mode: PipelineMode = PipelineMode.AUTOPILOT
    current_state: PipelineState = PipelineState.IDLE
    chapter_index: int = 0
    chapter_id: Optional[int] = None
    paused_at: Optional[PipelineState] = None
    user_confirmed: bool = False
    error: Optional[str] = None
    results: Dict[str, Any] = field(default_factory=dict)
    # Async event for waiting on human confirmation
    _confirmation_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    def __post_init__(self):
        self._confirmation_event = asyncio.Event()


class PipelineFSM:
    """Finite State Machine for pipeline execution.

    Supports two modes:
    - AUTOPILOT: Runs all stages sequentially without pausing
    - INTERACTIVE: Pauses after ANNOTATING at PENDING_HUMAN_CONFIRM,
      waits for user confirmation before continuing
    """

    def __init__(
        self,
        context: PipelineContext,
        stage_runner: Optional[Callable] = None,
    ):
        """Initialize FSM.

        Args:
            context: Pipeline execution context
            stage_runner: Async function to run a pipeline stage.
                         Signature: async def run_stage(stage_name, context) -> result
        """
        self.context = context
        self.stage_runner = stage_runner or self._default_stage_runner
        self._running = False
        self._current_task: Optional[asyncio.Task] = None

    async def _default_stage_runner(self, stage: str, ctx: PipelineContext) -> Any:
        """Default stage runner using orchestrator.run_pipeline."""
        db = SessionLocal()
        try:
            results = await run_pipeline(
                stages=[stage],
                db=db,
                project_id=ctx.project_id,
                chapter_index=ctx.chapter_index,
                chapter_id=ctx.chapter_id,
            )
            return results[0] if results else None
        finally:
            db.close()

    @property
    def current_state(self) -> PipelineState:
        return self.context.current_state

    @property
    def mode(self) -> PipelineMode:
        return self.context.mode

    def get_phases(self) -> List[PipelineState]:
        """Get the phase sequence for current mode."""
        return INTERACTIVE_PHASES if self.context.mode == PipelineMode.INTERACTIVE else AUTOPILOT_PHASES

    def next_state(self) -> Optional[PipelineState]:
        """Get the next state in the sequence."""
        phases = self.get_phases()
        try:
            idx = phases.index(self.context.current_state)
            if idx + 1 < len(phases):
                return phases[idx + 1]
        except ValueError:
            # Current state not in phases (e.g., IDLE)
            return phases[0] if phases else None
        return None

    def can_transition(self, target_state: PipelineState) -> bool:
        """Check if transition to target state is valid."""
        if target_state == PipelineState.PENDING_HUMAN_CONFIRM:
            # Only valid transition to PENDING_HUMAN_CONFIRM is from ANNOTATING in INTERACTIVE mode
            return (
                self.context.current_state == PipelineState.ANNOTATING and self.context.mode == PipelineMode.INTERACTIVE
            )

        if target_state == PipelineState.AUDIO_POSTPROCESSING:
            # Can transition from ANNOTATING (AUTOPILOT) or PENDING_HUMAN_CONFIRM (INTERACTIVE + confirmed)
            if self.context.mode == PipelineMode.AUTOPILOT:
                return self.context.current_state == PipelineState.ANNOTATING
            return self.context.current_state == PipelineState.PENDING_HUMAN_CONFIRM and self.context.user_confirmed

        # Normal forward transitions
        next_state = self.next_state()
        return target_state == next_state

    async def transition_to(self, target_state: PipelineState) -> bool:
        """Transition to a target state if valid."""
        if not self.can_transition(target_state):
            logger.warning(
                "Invalid transition: %s -> %s (mode=%s)",
                self.context.current_state,
                target_state,
                self.context.mode,
            )
            return False

        self.context.current_state = target_state
        logger.info("FSM transition: %s -> %s", self.context.current_state, target_state)
        return True

    async def wait_for_confirmation(self, timeout: Optional[float] = None) -> bool:
        """Wait for human confirmation (INTERACTIVE mode only).

        Args:
            timeout: Optional timeout in seconds. None = wait forever.

        Returns:
            True if confirmed, False if timeout or not in interactive mode.
        """
        if self.context.mode != PipelineMode.INTERACTIVE:
            return False

        if self.context.current_state != PipelineState.PENDING_HUMAN_CONFIRM:
            return False

        logger.info("Waiting for human confirmation...")
        try:
            await asyncio.wait_for(self.context._confirmation_event.wait(), timeout=timeout)
            self.context._confirmation_event.clear()
            self.context.user_confirmed = True
            logger.info("Human confirmation received")
            return True
        except asyncio.TimeoutError:
            logger.warning("Confirmation timeout")
            return False

    def confirm(self) -> bool:
        """Signal human confirmation (call from API endpoint)."""
        if self.context.current_state != PipelineState.PENDING_HUMAN_CONFIRM:
            logger.warning("Cannot confirm: not in PENDING_HUMAN_CONFIRM state")
            return False

        self.context._confirmation_event.set()
        return True

    async def execute_stage(self, state: PipelineState) -> Any:
        """Execute the stage corresponding to the given state."""
        stage_name = STATE_TO_STAGE.get(state)
        if not stage_name:
            logger.warning("No stage mapped for state: %s", state)
            return None

        logger.info("Executing stage: %s (%s)", stage_name, state)
        result = await self.stage_runner(stage_name, self.context)
        self.context.results[stage_name] = result
        return result

    async def run_until_pause_or_complete(self) -> Dict[str, Any]:
        """Run pipeline until pause point (INTERACTIVE) or completion (AUTOPILOT).

        Returns:
            Dict with status, current_state, and results
        """
        self._running = True
        phases = self.get_phases()

        # Find starting phase index
        start_idx = 0
        if self.context.current_state in phases:
            start_idx = phases.index(self.context.current_state)
        elif self.context.current_state == PipelineState.PENDING_HUMAN_CONFIRM:
            # Already paused, start from after confirmation
            start_idx = phases.index(PipelineState.PENDING_HUMAN_CONFIRM) + 1

        for i in range(start_idx, len(phases)):
            if not self._running:
                break

            state = phases[i]
            self.context.current_state = state

            if state == PipelineState.PENDING_HUMAN_CONFIRM:
                # Pause for human confirmation
                logger.info("Pipeline paused at PENDING_HUMAN_CONFIRM")
                self.context.paused_at = state
                return {
                    "status": "paused",
                    "current_state": state.value,
                    "paused_at": state.value,
                    "results": self.context.results,
                    "chapter_index": self.context.chapter_index,
                }

            # Execute stage
            try:
                await self.execute_stage(state)
            except Exception as e:
                logger.exception("Stage %s failed: %s", state, e)
                self.context.current_state = PipelineState.FAILED
                self.context.error = str(e)
                self._running = False
                return {
                    "status": "failed",
                    "current_state": PipelineState.FAILED.value,
                    "error": str(e),
                    "results": self.context.results,
                }

        # All phases completed
        self.context.current_state = PipelineState.COMPLETED
        self._running = False
        return {
            "status": "completed",
            "current_state": PipelineState.COMPLETED.value,
            "results": self.context.results,
            "chapter_index": self.context.chapter_index,
        }

    async def continue_after_confirmation(self) -> Dict[str, Any]:
        """Continue pipeline after human confirmation."""
        if self.context.current_state != PipelineState.PENDING_HUMAN_CONFIRM:
            logger.warning("Not in PENDING_HUMAN_CONFIRM state, cannot continue")
            return {
                "status": "error",
                "current_state": self.context.current_state.value,
                "message": "Not waiting for confirmation",
            }

        self.context.user_confirmed = True
        self.context.paused_at = None

        # Transition state to the next phase after PENDING_HUMAN_CONFIRM
        # so that run_until_pause_or_complete starts from the correct position
        phases = self.get_phases()
        pending_idx = phases.index(PipelineState.PENDING_HUMAN_CONFIRM)
        if pending_idx + 1 < len(phases):
            self.context.current_state = phases[pending_idx + 1]

        return await self.run_until_pause_or_complete()

    def stop(self) -> None:
        """Stop pipeline execution."""
        self._running = False
        if self._current_task:
            self._current_task.cancel()

    def get_status(self) -> Dict[str, Any]:
        """Get current FSM status."""
        return {
            "project_id": self.context.project_id,
            "mode": self.context.mode.value,
            "current_state": self.context.current_state.value,
            "chapter_index": self.context.chapter_index,
            "chapter_id": self.context.chapter_id,
            "paused_at": self.context.paused_at.value if self.context.paused_at else None,
            "user_confirmed": self.context.user_confirmed,
            "error": self.context.error,
            "completed_stages": list(self.context.results.keys()),
        }


# Global FSM instances per project
_fsm_instances: Dict[int, PipelineFSM] = {}


def get_fsm(
    project_id: int,
    mode: PipelineMode = PipelineMode.AUTOPILOT,
    chapter_index: int = 0,
    chapter_id: Optional[int] = None,
) -> PipelineFSM:
    """Get or create FSM instance for a project."""
    if project_id not in _fsm_instances:
        context = PipelineContext(
            project_id=project_id,
            mode=mode,
            chapter_index=chapter_index,
            chapter_id=chapter_id,
        )
        _fsm_instances[project_id] = PipelineFSM(context)
    return _fsm_instances[project_id]


def remove_fsm(project_id: int) -> None:
    """Remove FSM instance for a project."""
    if project_id in _fsm_instances:
        _fsm_instances[project_id].stop()
        del _fsm_instances[project_id]
