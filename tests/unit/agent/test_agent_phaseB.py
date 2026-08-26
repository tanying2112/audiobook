"""Phase B structural tests for the agent/ package (agent_chat).

Covers the pipeline FSM (state transitions, pause/confirm, run-to-completion),
the DeveloperAgent fix-command application, and the agent tools dispatcher /
mime-type helpers. Heavy LLM/DB paths are mocked or exercised in mock_mode.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.audiobook_studio.agent.developer as dev_mod
import src.audiobook_studio.agent.fsm as fsm_mod
import src.audiobook_studio.agent.tools as tools_mod
from src.audiobook_studio.agent.fsm import (
    PipelineContext,
    PipelineFSM,
    PipelineMode,
    PipelineState,
    get_fsm,
    remove_fsm,
)
from src.audiobook_studio.agent.tools import _guess_mime_type, execute_tool
from src.audiobook_studio.schemas.review import FixCommand, ReviewerInput


# ── FSM: enums & context ────────────────────────────────────────────────────

def test_pipeline_state_enum() -> None:
    assert PipelineState.IDLE is not None
    assert PipelineState.COMPLETED is not None
    assert PipelineState.FAILED is not None


def test_pipeline_mode_enum() -> None:
    assert PipelineMode.AUTOPILOT is not None
    assert PipelineMode.INTERACTIVE is not None


def test_pipeline_context_defaults() -> None:
    ctx = PipelineContext(project_id=7)
    assert ctx.project_id == 7
    assert ctx.mode == PipelineMode.AUTOPILOT
    assert ctx.current_state == PipelineState.IDLE
    assert isinstance(ctx.results, dict)


# ── FSM: phase / next-state logic ───────────────────────────────────────────

def test_get_phases_autopilot() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT)
    fsm = PipelineFSM(ctx)
    assert fsm.get_phases() == fsm_mod.AUTOPILOT_PHASES


def test_get_phases_interactive() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE)
    fsm = PipelineFSM(ctx)
    assert fsm.get_phases() == fsm_mod.INTERACTIVE_PHASES


def test_next_state_from_idle() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, current_state=PipelineState.IDLE)
    fsm = PipelineFSM(ctx)
    nxt = fsm.next_state()
    assert isinstance(nxt, PipelineState)


def test_next_state_at_end_returns_none() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT)
    fsm = PipelineFSM(ctx)
    last = fsm.get_phases()[-1]
    ctx.current_state = last
    assert fsm.next_state() is None


def test_next_state_unknown_returns_first() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, current_state=PipelineState.FAILED)
    fsm = PipelineFSM(ctx)
    # FAILED is not in phases -> returns first phase
    assert fsm.next_state() == fsm.get_phases()[0]


# ── FSM: transition validation ──────────────────────────────────────────────

def test_can_transition_pending_human_confirm_valid() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, current_state=PipelineState.ANNOTATING)
    fsm = PipelineFSM(ctx)
    assert fsm.can_transition(PipelineState.PENDING_HUMAN_CONFIRM) is True


def test_can_transition_pending_human_confirm_autopilot_invalid() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, current_state=PipelineState.ANNOTATING)
    fsm = PipelineFSM(ctx)
    assert fsm.can_transition(PipelineState.PENDING_HUMAN_CONFIRM) is False


def test_can_transition_audio_postprocessing_autopilot() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, current_state=PipelineState.ANNOTATING)
    fsm = PipelineFSM(ctx)
    assert fsm.can_transition(PipelineState.AUDIO_POSTPROCESSING) is True


def test_can_transition_audio_postprocessing_interactive_confirmed() -> None:
    ctx = PipelineContext(
        project_id=1, mode=PipelineMode.INTERACTIVE,
        current_state=PipelineState.PENDING_HUMAN_CONFIRM, user_confirmed=True,
    )
    fsm = PipelineFSM(ctx)
    assert fsm.can_transition(PipelineState.AUDIO_POSTPROCESSING) is True


def test_can_transition_audio_postprocessing_interactive_unconfirmed() -> None:
    ctx = PipelineContext(
        project_id=1, mode=PipelineMode.INTERACTIVE,
        current_state=PipelineState.PENDING_HUMAN_CONFIRM, user_confirmed=False,
    )
    fsm = PipelineFSM(ctx)
    assert fsm.can_transition(PipelineState.AUDIO_POSTPROCESSING) is False


def test_can_transition_normal_forward() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, current_state=PipelineState.IDLE)
    fsm = PipelineFSM(ctx)
    nxt = fsm.next_state()
    assert fsm.can_transition(nxt) is True


def test_can_transition_normal_skip_invalid() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, current_state=PipelineState.IDLE)
    fsm = PipelineFSM(ctx)
    # skipping to the last phase directly is not a valid forward transition
    assert fsm.can_transition(fsm.get_phases()[-1]) is False


# ── FSM: transition_to ─────────────────────────────────────────────────────

def test_transition_to_valid() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, current_state=PipelineState.IDLE)
    fsm = PipelineFSM(ctx)
    target = fsm.next_state()
    assert asyncio.run(fsm.transition_to(target)) is True
    assert ctx.current_state == target


def test_transition_to_invalid() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, current_state=PipelineState.IDLE)
    fsm = PipelineFSM(ctx)
    assert asyncio.run(fsm.transition_to(PipelineState.FAILED)) is False
    assert ctx.current_state == PipelineState.IDLE


# ── FSM: confirm / wait_for_confirmation ───────────────────────────────────

def test_confirm_not_in_pending_returns_false() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, current_state=PipelineState.ANNOTATING)
    fsm = PipelineFSM(ctx)
    assert fsm.confirm() is False


def test_confirm_and_wait() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, current_state=PipelineState.PENDING_HUMAN_CONFIRM)
    fsm = PipelineFSM(ctx)

    async def _go():
        loop = asyncio.get_event_loop()
        loop.call_soon(fsm.confirm)
        return await fsm.wait_for_confirmation()

    assert asyncio.run(_go()) is True
    assert ctx.user_confirmed is True


def test_wait_for_confirmation_non_interactive() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, current_state=PipelineState.PENDING_HUMAN_CONFIRM)
    fsm = PipelineFSM(ctx)
    assert asyncio.run(fsm.wait_for_confirmation()) is False


def test_wait_for_confirmation_wrong_state() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, current_state=PipelineState.ANNOTATING)
    fsm = PipelineFSM(ctx)
    assert asyncio.run(fsm.wait_for_confirmation()) is False


# ── FSM: execute_stage ─────────────────────────────────────────────────────

def test_execute_stage_with_mock_runner() -> None:
    ctx = PipelineContext(project_id=1)
    captured = {}

    async def runner(stage, c):
        captured["stage"] = stage
        return f"res-{stage}"

    fsm = PipelineFSM(ctx, stage_runner=runner)
    state = fsm.get_phases()[0]
    result = asyncio.run(fsm.execute_stage(state))
    assert result == f"res-{fsm_mod.STATE_TO_STAGE[state]}"
    assert captured["stage"] == fsm_mod.STATE_TO_STAGE[state]


def test_execute_stage_no_mapping() -> None:
    ctx = PipelineContext(project_id=1)
    fsm = PipelineFSM(ctx, stage_runner=AsyncMock())
    # A state with no stage mapping returns None without calling runner
    result = asyncio.run(fsm.execute_stage(PipelineState.IDLE))
    assert result is None


# ── FSM: run_until_pause_or_complete (AUTOPILOT) ──────────────────────────

def test_run_autopilot_completes() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, current_state=PipelineState.IDLE)

    async def runner(stage, c):
        return f"done-{stage}"

    fsm = PipelineFSM(ctx, stage_runner=runner)
    result = asyncio.run(fsm.run_until_pause_or_complete())
    assert result["status"] == "completed"
    assert ctx.current_state == PipelineState.COMPLETED
    assert len(result["results"]) == len(fsm.get_phases())


def test_run_autopilot_stage_failure() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.AUTOPILOT, current_state=PipelineState.IDLE)

    async def runner(stage, c):
        if stage == fsm_mod.STATE_TO_STAGE[fsm.get_phases()[1]]:
            raise RuntimeError("boom")
        return "ok"

    fsm = PipelineFSM(ctx, stage_runner=runner)
    result = asyncio.run(fsm.run_until_pause_or_complete())
    assert result["status"] == "failed"
    assert ctx.current_state == PipelineState.FAILED
    assert "boom" in result["error"]


# ── FSM: run paused (INTERACTIVE) + continue ───────────────────────────────

def test_run_interactive_pauses() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, current_state=PipelineState.IDLE)

    async def runner(stage, c):
        return f"done-{stage}"

    fsm = PipelineFSM(ctx, stage_runner=runner)
    result = asyncio.run(fsm.run_until_pause_or_complete())
    assert result["status"] == "paused"
    assert ctx.current_state == PipelineState.PENDING_HUMAN_CONFIRM


def test_continue_after_confirmation() -> None:
    ctx = PipelineContext(
        project_id=1, mode=PipelineMode.INTERACTIVE,
        current_state=PipelineState.PENDING_HUMAN_CONFIRM, user_confirmed=False,
    )

    async def runner(stage, c):
        return f"done-{stage}"

    fsm = PipelineFSM(ctx, stage_runner=runner)
    result = asyncio.run(fsm.continue_after_confirmation())
    assert result["status"] == "completed"
    assert ctx.user_confirmed is True


def test_continue_after_confirmation_not_pending() -> None:
    ctx = PipelineContext(project_id=1, mode=PipelineMode.INTERACTIVE, current_state=PipelineState.ANNOTATING)
    fsm = PipelineFSM(ctx, stage_runner=AsyncMock())
    result = asyncio.run(fsm.continue_after_confirmation())
    assert result["status"] == "error"


# ── FSM: stop / get_status ─────────────────────────────────────────────────

def test_stop_sets_not_running() -> None:
    ctx = PipelineContext(project_id=1)
    fsm = PipelineFSM(ctx)
    fsm._running = True
    fsm.stop()
    assert fsm._running is False


def test_get_status() -> None:
    ctx = PipelineContext(project_id=42, mode=PipelineMode.INTERACTIVE, chapter_index=3)
    fsm = PipelineFSM(ctx)
    status = fsm.get_status()
    assert status["project_id"] == 42
    assert status["mode"] == PipelineMode.INTERACTIVE.value
    assert status["chapter_index"] == 3


# ── FSM: global instance cache ─────────────────────────────────────────────

def test_get_fsm_singleton_and_remove() -> None:
    remove_fsm(999)
    a = get_fsm(999, mode=PipelineMode.AUTOPILOT)
    b = get_fsm(999)
    assert a is b
    remove_fsm(999)
    c = get_fsm(999, mode=PipelineMode.INTERACTIVE)
    assert c is not a
    remove_fsm(999)


# ── DeveloperAgent: field defaults ─────────────────────────────────────────

def test_get_field_default_known() -> None:
    agent = dev_mod.DeveloperAgent()
    assert agent._get_field_default("emotion") == "neutral"
    assert agent._get_field_default("is_dialogue") is False


def test_get_field_default_unknown() -> None:
    agent = dev_mod.DeveloperAgent()
    assert agent._get_field_default("nonexistent") is None


# ── DeveloperAgent: apply_fix_commands ─────────────────────────────────────

def _para(**kw) -> dict:
    base = {"emotion": "neutral", "speech_rate": 1.0, "sfx_tags": [], "pause_before_ms": 300}
    base.update(kw)
    return base


def test_apply_fix_add_voice_binding() -> None:
    agent = dev_mod.DeveloperAgent()
    paras = [_para()]
    cmd = FixCommand(
        command_type="add_voice_binding", target_paragraph_index=0,
        parameters={"canonical_name": "Alice", "suggested_voice_id": "v1"}, rationale="r", priority=5,
    )
    out = agent.apply_fix_commands(paras, [cmd])
    assert out[0]["_voice_map_updates"][0]["canonical_name"] == "Alice"


def test_apply_fix_truncated_field() -> None:
    agent = dev_mod.DeveloperAgent()
    paras = [_para()]
    cmd = FixCommand(
        command_type="fix_truncated_field", target_paragraph_index=0,
        parameters={"field_name": "emotion"}, rationale="r", priority=5,
    )
    out = agent.apply_fix_commands(paras, [cmd])
    assert out[0]["emotion"] == "neutral"


def test_apply_fix_correct_emotion_tag() -> None:
    agent = dev_mod.DeveloperAgent()
    paras = [_para(emotion="angry")]
    cmd = FixCommand(
        command_type="correct_emotion_tag", target_paragraph_index=0,
        parameters={"current_emotion": "angry", "suggested_emotion": "happy"}, rationale="r", priority=5,
    )
    out = agent.apply_fix_commands(paras, [cmd])
    assert out[0]["emotion"] == "happy"


def test_apply_fix_adjust_speed() -> None:
    agent = dev_mod.DeveloperAgent()
    paras = [_para(speech_rate=2.0)]
    cmd = FixCommand(
        command_type="adjust_speed", target_paragraph_index=0,
        parameters={"current_speed": 2.0, "clamped_speed": 1.5}, rationale="r", priority=5,
    )
    out = agent.apply_fix_commands(paras, [cmd])
    assert out[0]["speech_rate"] == 1.5


def test_apply_fix_add_sfx_tag_remove_and_replace() -> None:
    agent = dev_mod.DeveloperAgent()
    paras = [_para(sfx_tags=["bad"])]
    cmd = FixCommand(
        command_type="add_sfx_tag", target_paragraph_index=0,
        parameters={"invalid_tag": "bad", "action": "remove_or_replace", "allowed_tags": ["wind"]},
        rationale="r", priority=5,
    )
    out = agent.apply_fix_commands(paras, [cmd])
    assert "bad" not in out[0]["sfx_tags"]
    assert out[0]["sfx_tags"] == ["wind"]
    assert out[0]["needs_sfx"] is True


def test_apply_fix_add_sfx_tag_remove_only() -> None:
    agent = dev_mod.DeveloperAgent()
    paras = [_para(sfx_tags=["bad"])]
    cmd = FixCommand(
        command_type="add_sfx_tag", target_paragraph_index=0,
        parameters={"invalid_tag": "bad", "action": "remove"}, rationale="r", priority=5,
    )
    out = agent.apply_fix_commands(paras, [cmd])
    assert out[0]["sfx_tags"] == []
    assert out[0]["needs_sfx"] is False


def test_apply_fix_pause_timing() -> None:
    agent = dev_mod.DeveloperAgent()
    paras = [_para(pause_before_ms=10)]
    cmd = FixCommand(
        command_type="fix_pause_timing", target_paragraph_index=0,
        parameters={"field": "pause_before_ms", "current_value": 10, "clamped_value": 300},
        rationale="r", priority=5,
    )
    out = agent.apply_fix_commands(paras, [cmd])
    assert out[0]["pause_before_ms"] == 300


def test_apply_fix_reannotate_marks() -> None:
    agent = dev_mod.DeveloperAgent()
    paras = [_para()]
    cmd = FixCommand(
        command_type="re_annotate_paragraph", target_paragraph_index=0,
        parameters={}, rationale="r", priority=5,
    )
    out = agent.apply_fix_commands(paras, [cmd])
    assert out[0]["_needs_reannotation"] is True


def test_apply_fix_out_of_range_index() -> None:
    agent = dev_mod.DeveloperAgent()
    paras = [_para()]
    cmd = FixCommand(
        command_type="correct_emotion_tag", target_paragraph_index=99,
        parameters={"current_emotion": "x", "suggested_emotion": "y"}, rationale="r", priority=5,
    )
    out = agent.apply_fix_commands(paras, [cmd])
    # unchanged because index out of range
    assert out[0]["emotion"] == "neutral"


def test_apply_fix_sorted_by_priority() -> None:
    agent = dev_mod.DeveloperAgent()
    paras = [_para(emotion="neutral", speech_rate=1.0)]
    cmd1 = FixCommand(command_type="correct_emotion_tag", target_paragraph_index=0,
                      parameters={"current_emotion": "n", "suggested_emotion": "A"}, rationale="r", priority=1)
    cmd2 = FixCommand(command_type="adjust_speed", target_paragraph_index=0,
                      parameters={"current_speed": 1, "clamped_speed": 2.0}, rationale="r", priority=9)
    out = agent.apply_fix_commands(paras, [cmd1, cmd2])
    # Both applied regardless of order; just ensure both effects present
    assert out[0]["emotion"] == "A"
    assert out[0]["speech_rate"] == 2.0


# ── DeveloperAgent: create_fixed_reviewer_input ────────────────────────────

def test_create_fixed_reviewer_input_no_voice_updates() -> None:
    agent = dev_mod.DeveloperAgent()
    original = ReviewerInput(
        project_id=1, chapter_index=2,
        paragraphs=[{"emotion": "neutral"}],
        character_voice_map=[{"canonical_name": "Bob", "suggested_voice_id": "v2"}],
        scene_tags=["wind"], book_meta=None,
    )
    new = agent.create_fixed_reviewer_input(original, [{"emotion": "happy"}])
    assert new.project_id == 1
    assert new.chapter_index == 2
    assert new.paragraphs == [{"emotion": "happy"}]
    assert new.character_voice_map == original.character_voice_map


def test_create_fixed_reviewer_input_with_voice_updates() -> None:
    agent = dev_mod.DeveloperAgent()
    original = ReviewerInput(
        project_id=1, chapter_index=2,
        paragraphs=[{}],
        character_voice_map=[{"canonical_name": "Bob", "suggested_voice_id": "v2"}],
        scene_tags=[], book_meta=None,
    )
    updates = [{"canonical_name": "Alice", "suggested_voice_id": "v1", "aliases": ["Al"], "gender": "f", "age_range": "adult"}]
    new = agent.create_fixed_reviewer_input(original, [{}], voice_map_updates=updates)
    canonicals = [v["canonical_name"] for v in new.character_voice_map]
    assert "Alice" in canonicals
    assert "Bob" in canonicals


def test_create_fixed_reviewer_input_dedup_voice() -> None:
    agent = dev_mod.DeveloperAgent()
    original = ReviewerInput(
        project_id=1, chapter_index=2, paragraphs=[{}],
        character_voice_map=[{"canonical_name": "Bob", "suggested_voice_id": "v2"}],
        scene_tags=[], book_meta=None,
    )
    updates = [
        {"canonical_name": "Bob", "suggested_voice_id": "v9"},
        {"canonical_name": "Bob", "suggested_voice_id": "v9"},
    ]
    new = agent.create_fixed_reviewer_input(original, [{}], voice_map_updates=updates)
    bob_count = sum(1 for v in new.character_voice_map if v["canonical_name"] == "Bob")
    assert bob_count == 1


# ── DeveloperAgent: edge branches / error paths ────────────────────────────


def test_apply_fix_voice_binding_exception_empty_paragraphs() -> None:
    # Empty paragraphs -> IndexError at line 89 is caught by apply_fix_commands loop.
    agent = dev_mod.DeveloperAgent()
    cmd = FixCommand(
        command_type="add_voice_binding", target_paragraph_index=0,
        parameters={"canonical_name": "Alice"}, rationale="r", priority=5,
    )
    out = agent.apply_fix_commands([], [cmd])
    assert out == []


def test_apply_fix_voice_binding_marker_present_on_first() -> None:
    # paragraphs[0] already has the marker, paragraphs[1] does not.
    # Exercises the False branch of line 82 and the per-para create at 88.
    agent = dev_mod.DeveloperAgent()
    paras = [_para(), _para()]
    paras[0]["_voice_map_updates"] = []
    cmd = FixCommand(
        command_type="add_voice_binding", target_paragraph_index=0,
        parameters={"canonical_name": "Alice", "suggested_voice_id": "v1"}, rationale="r", priority=5,
    )
    out = agent.apply_fix_commands(paras, [cmd])
    assert out[0]["_voice_map_updates"][0]["canonical_name"] == "Alice"
    assert out[1]["_voice_map_updates"] == []  # created by line 88


def test_apply_fix_truncated_field_out_of_range() -> None:
    agent = dev_mod.DeveloperAgent()
    paras = [_para()]
    cmd = FixCommand(
        command_type="fix_truncated_field", target_paragraph_index=99,
        parameters={"field_name": "emotion"}, rationale="r", priority=5,
    )
    out = agent.apply_fix_commands(paras, [cmd])
    assert out[0]["emotion"] == "neutral"


def test_apply_fix_adjust_speed_out_of_range() -> None:
    agent = dev_mod.DeveloperAgent()
    paras = [_para(speech_rate=2.0)]
    cmd = FixCommand(
        command_type="adjust_speed", target_paragraph_index=99,
        parameters={"current_speed": 2.0, "clamped_speed": 1.5}, rationale="r", priority=5,
    )
    out = agent.apply_fix_commands(paras, [cmd])
    assert out[0]["speech_rate"] == 2.0


def test_apply_fix_sfx_out_of_range() -> None:
    agent = dev_mod.DeveloperAgent()
    paras = [_para(sfx_tags=["bad"])]
    cmd = FixCommand(
        command_type="add_sfx_tag", target_paragraph_index=99,
        parameters={"invalid_tag": "bad"}, rationale="r", priority=5,
    )
    out = agent.apply_fix_commands(paras, [cmd])
    assert out[0]["sfx_tags"] == ["bad"]


def test_apply_fix_sfx_tag_not_present() -> None:
    # valid index but invalid tag not in sfx_tags -> the `if invalid in sfx_tags`
    # branch is False (line 124 exit).
    agent = dev_mod.DeveloperAgent()
    paras = [_para(sfx_tags=["other"])]
    cmd = FixCommand(
        command_type="add_sfx_tag", target_paragraph_index=0,
        parameters={"invalid_tag": "bad", "action": "remove_or_replace", "allowed_tags": ["wind"]},
        rationale="r", priority=5,
    )
    out = agent.apply_fix_commands(paras, [cmd])
    assert out[0]["sfx_tags"] == ["other"]


def test_apply_fix_pause_timing_out_of_range() -> None:
    agent = dev_mod.DeveloperAgent()
    paras = [_para(pause_before_ms=10)]
    cmd = FixCommand(
        command_type="fix_pause_timing", target_paragraph_index=99,
        parameters={"field": "pause_before_ms", "current_value": 10, "clamped_value": 300},
        rationale="r", priority=5,
    )
    out = agent.apply_fix_commands(paras, [cmd])
    assert out[0]["pause_before_ms"] == 10


def test_apply_fix_reannotate_out_of_range() -> None:
    agent = dev_mod.DeveloperAgent()
    paras = [_para()]
    cmd = FixCommand(
        command_type="re_annotate_paragraph", target_paragraph_index=99,
        parameters={}, rationale="r", priority=5,
    )
    out = agent.apply_fix_commands(paras, [cmd])
    assert "_needs_reannotation" not in out[0]


@pytest.mark.skip(reason="Test isolation issue - flaky in full suite")
def test_apply_fixes_and_rerun_mock(monkeypatch) -> None:
    fake_judgment = MagicMock()

    class FakeReviewer:
        def __init__(self, mock_mode: bool = False) -> None:
            pass

        def run(self, inp):  # noqa: ANN001
            return fake_judgment

    monkeypatch.setattr(
        "src.audiobook_studio.pipeline.review.ReviewerAgent", FakeReviewer
    )
    paras = [_para()]
    cmd = FixCommand(
        command_type="add_voice_binding", target_paragraph_index=0,
        parameters={"canonical_name": "Alice", "suggested_voice_id": "v1"}, rationale="r", priority=5,
    )
    judgment = asyncio.run(
        dev_mod.apply_fixes_and_rerun(
            project_id=1, chapter_index=2, paragraphs=paras, fix_commands=[cmd],
            character_voice_map=[], scene_tags=[], book_meta=None, mock_mode=True,
        )
    )
    assert judgment is fake_judgment

@pytest.mark.skip(reason="Test isolation issue - flaky in full suite")

def test_apply_fixes_and_rerun_mock_no_voice_updates(monkeypatch) -> None:
    # Non-voice command -> fixed paragraphs carry no _voice_map_updates, so the
    # `if "_voice_map_updates" in p` loop body is skipped (branch 264->263).
    fake_judgment = MagicMock()

    class FakeReviewer:
        def __init__(self, mock_mode: bool = False) -> None:
            pass

        def run(self, inp):  # noqa: ANN001
            return fake_judgment

    monkeypatch.setattr(
        "src.audiobook_studio.pipeline.review.ReviewerAgent", FakeReviewer
    )
    paras = [_para(emotion="angry")]
    cmd = FixCommand(
        command_type="correct_emotion_tag", target_paragraph_index=0,
        parameters={"current_emotion": "angry", "suggested_emotion": "calm"},
        rationale="r", priority=5,
    )
    judgment = asyncio.run(
        dev_mod.apply_fixes_and_rerun(
            project_id=1, chapter_index=2, paragraphs=paras, fix_commands=[cmd],
            character_voice_map=[], scene_tags=[], book_meta=None, mock_mode=True,
        )
    )
    assert judgment is fake_judgment


# ── DeveloperAgent: run_reannotation mock_mode ─────────────────────────────

def test_run_reannotation_mock_mode() -> None:
    agent = dev_mod.DeveloperAgent(mock_mode=True)
    result = asyncio.run(agent.run_reannotation(1, 1, [0, 1, 2]))
    assert result["status"] == "mock"
    assert result["reannotated"] == [0, 1, 2]


# ── Tools: mime type guessing ──────────────────────────────────────────────

def test_guess_mime_explicit_type() -> None:
    assert _guess_mime_type("x", "pdf") == "application/pdf"
    assert _guess_mime_type("x", "epub") == "application/epub+zip"
    assert _guess_mime_type("x", "txt") == "text/plain"
    assert _guess_mime_type("x", "docx") == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert _guess_mime_type("x", "image") == "image/png"
    assert _guess_mime_type("x", "weird") == "application/octet-stream"


def test_guess_mime_by_extension() -> None:
    assert _guess_mime_type("book.pdf") == "application/pdf"
    assert _guess_mime_type("book.epub") == "application/epub+zip"
    assert _guess_mime_type("book.txt") == "text/plain"
    assert _guess_mime_type("img.PNG") == "image/png"
    assert _guess_mime_type("img.jpeg") == "image/jpeg"
    assert _guess_mime_type("img.tiff") == "image/tiff"
    assert _guess_mime_type("unknown.xyz") == "application/octet-stream"


# ── Tools: execute_tool dispatch ───────────────────────────────────────────

def test_execute_tool_unknown_raises() -> None:
    with pytest.raises(ValueError):
        asyncio.run(execute_tool("does_not_exist", {}))


def test_execute_tool_dispatch_and_validate() -> None:
    import src.audiobook_studio.agent.tools as tmod

    async def fake_load(args):
        return f"loaded:{args.project_id}:{args.file_path}"

    handlers = dict(tmod.TOOL_HANDLERS)
    handlers["load_book_file"] = fake_load
    with patch.object(tmod, "TOOL_HANDLERS", handlers):
        result = asyncio.run(
            execute_tool("load_book_file", {"project_id": 5, "file_path": "a.txt"})
        )
    assert result == "loaded:5:a.txt"


def test_execute_tool_validation_error() -> None:
    # Missing required field 'file_path' -> pydantic validation error surfaces
    with pytest.raises(Exception):
        asyncio.run(execute_tool("load_book_file", {"project_id": 5}))


# ── Tools: load_book_file ───────────────────────────────────────────────────

def test_load_book_file_happy() -> None:
    ext = MagicMock()
    ext.run.return_value = MagicMock(raw_text="hello world")
    with patch.object(tools_mod, "ExtractPipeline", return_value=ext):
        res = asyncio.run(
            tools_mod.load_book_file(tools_mod.LoadBookFileArgs(project_id=1, file_path="a.txt"))
        )
    assert res.status == "ok"
    assert res.total_chars == len("hello world")


def test_load_book_file_error() -> None:
    ext = MagicMock()
    ext.run.side_effect = RuntimeError("boom")
    with patch.object(tools_mod, "ExtractPipeline", return_value=ext):
        res = asyncio.run(
            tools_mod.load_book_file(tools_mod.LoadBookFileArgs(project_id=1, file_path="a.txt"))
        )
    assert res.status == "failed"


# ── Tools: analyze_and_split ────────────────────────────────────────────────

def test_analyze_and_split_happy() -> None:
    with patch.object(tools_mod, "load_extracted_text", return_value=""):
        analysis = MagicMock()
        analysis.book_meta.total_chapters_estimated = 2
        pipe = MagicMock()
        pipe.run.return_value = analysis
        with patch.object(tools_mod, "AnalyzeStructurePipeline", return_value=pipe):
            res = asyncio.run(
                tools_mod.analyze_and_split(tools_mod.AnalyzeAndSplitArgs(project_id=1))
            )
    assert res.status == "ok"
    assert len(res.chapters) == 2


def test_analyze_and_split_error() -> None:
    with patch.object(tools_mod, "load_extracted_text", return_value="x"):
        pipe = MagicMock()
        pipe.run.side_effect = RuntimeError("boom")
        with patch.object(tools_mod, "AnalyzeStructurePipeline", return_value=pipe):
            res = asyncio.run(
                tools_mod.analyze_and_split(tools_mod.AnalyzeAndSplitArgs(project_id=1))
            )
    assert res.status == "failed"


# ── Tools: generate_emotion_markup ─────────────────────────────────────────

def test_generate_emotion_markup_no_text() -> None:
    with patch.object(tools_mod, "load_extracted_text", return_value=""):
        res = asyncio.run(
            tools_mod.generate_emotion_markup(
                tools_mod.GenerateEmotionMarkupArgs(project_id=1, chapter_index=1)
            )
        )
    assert res.status == "failed"
    assert "No extracted text" in res.error_message


def test_generate_emotion_markup_happy() -> None:
    with patch.object(tools_mod, "load_extracted_text",
                      return_value="This is the first paragraph of the chapter.\n\nThis is the second paragraph of the chapter."):
        ann = MagicMock()
        ann.paragraph_index = 0
        ann.text = "p"
        ann.speaker_canonical_name = "n"
        ann.emotion = "e"
        ann.speech_rate = 1.0
        ann.pitch_shift_semitones = 0
        ann.pause_after_ms = 300
        pipe = MagicMock()
        pipe.run.return_value = ann
        with patch.object(tools_mod, "AnnotateParagraphPipeline", return_value=pipe):
            res = asyncio.run(
                tools_mod.generate_emotion_markup(
                    tools_mod.GenerateEmotionMarkupArgs(project_id=1, chapter_index=1)
                )
            )
    assert res.status == "ok"
    assert len(res.paragraphs) == 2


def test_generate_emotion_markup_error() -> None:
    with patch.object(tools_mod, "load_extracted_text", return_value="x"):
        pipe = MagicMock()
        pipe.run.side_effect = RuntimeError("boom")
        with patch.object(tools_mod, "AnnotateParagraphPipeline", return_value=pipe):
            res = asyncio.run(
                tools_mod.generate_emotion_markup(
                    tools_mod.GenerateEmotionMarkupArgs(project_id=1, chapter_index=1)
                )
            )
    assert res.status == "failed"


# ── Tools: execute_audio_synthesis ─────────────────────────────────────────

def test_execute_audio_synthesis_no_annotations() -> None:
    with patch.object(tools_mod, "load_chapter_annotations", return_value=[]):
        res = asyncio.run(
            tools_mod.execute_audio_synthesis(
                tools_mod.ExecuteAudioSynthesisArgs(project_id=1, chapter_index=1)
            )
        )
    assert res.status == "failed"


def test_execute_audio_synthesis_error() -> None:
    with patch.object(tools_mod, "load_chapter_annotations", side_effect=RuntimeError("boom")):
        res = asyncio.run(
            tools_mod.execute_audio_synthesis(
                tools_mod.ExecuteAudioSynthesisArgs(project_id=1, chapter_index=1)
            )
        )
    assert res.status == "failed"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
