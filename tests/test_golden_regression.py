"""C-01 golden regression test.

Locks in the mock↔real self-iteration switch (C-01-2) and the golden-dataset
path that the canary / promotion-gate / A-B evolution chain relies on (C-01-3).

Default behavior must stay *mock* (``SELF_ITERATION_MOCK=true``) so nothing in
the existing harness changes until an operator flips it to ``false`` for the
real-LLM evolution loop — that regression is the core guarantee here.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.audiobook_studio.feedback.promotion_gate import (
    _load_golden_examples,
    _resolve_mock_mode,
    _self_iteration_mock_enabled,
    _run_stage_with_prompt_version,
)

#: Golden dataset directories under tests/golden/ (C-01-3).
GOLDEN_STAGES: tuple[str, ...] = (
    "extract",
    "analyze_structure",
    "annotate_paragraph",
    "edit_for_tts",
    "quality_check",
    "synthesize",
    "quality_judge",
    "tts_routing",
)


class TestSelfIterationMockSwitch:
    """C-01-2: SELF_ITERATION_MOCK env drives mock_mode resolution."""

    def test_default_is_mock(self, monkeypatch):
        """Unset env ⇒ mock mode (true) — preserves existing harness behavior."""
        monkeypatch.delenv("SELF_ITERATION_MOCK", raising=False)
        assert _self_iteration_mock_enabled() is True
        assert _resolve_mock_mode(None) is True

    def test_env_false_turns_off_mock(self, monkeypatch):
        """SELF_ITERATION_MOCK=false ⇒ real mode (false)."""
        monkeypatch.setenv("SELF_ITERATION_MOCK", "false")
        assert _self_iteration_mock_enabled() is False
        assert _resolve_mock_mode(None) is False

    def test_env_truthy_variants(self, monkeypatch):
        monkeypatch.setenv("SELF_ITERATION_MOCK", "0")
        assert _resolve_mock_mode(None) is False
        monkeypatch.setenv("SELF_ITERATION_MOCK", "no")
        assert _resolve_mock_mode(None) is False
        monkeypatch.setenv("SELF_ITERATION_MOCK", "true")
        assert _resolve_mock_mode(None) is True

    def test_explicit_arg_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("SELF_ITERATION_MOCK", "false")
        assert _resolve_mock_mode(True) is True


class TestGoldenDataset:
    """C-01-3: the role the evolution chain reads golden examples from."""

    @pytest.mark.parametrize("stage", GOLDEN_STAGES)
    def test_golden_examples_load(self, stage):
        examples = _load_golden_examples(stage)
        assert examples, f"Stage {stage} golden dataset should not be empty"
        for ex in examples:
            assert "input" in ex, f"Stage {stage} example missing 'input': {ex}"

    def test_load_missing_stage_returns_empty(self):
        assert _load_golden_examples("does_not_exist_stage") == []


class TestMockModeForwardedToStage:
    """C-01-2: resolved mock_mode reaches the stage pipeline constructor."""

    def _run_edit_stage(self, tmp_path, monkeypatch) -> bool:
        """Run _run_stage_with_prompt_version('edit', 1, ...) and return the
        mock_mode the EditForTtsPipeline constructor received."""
        # Prompt-swap reads `prompts/edit_for_tts/v1.j2` relative to CWD.
        prompt_dir = tmp_path / "prompts" / "edit_for_tts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "v1.j2").write_text("j2: prompt", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        captured: dict[str, bool] = {}

        class FakeEdit:
            def __init__(self, *, mock_mode: bool):
                captured["mock_mode"] = mock_mode

            def run(self, input_data):
                return input_data

        with patch(
            "src.audiobook_studio.pipeline.edit_for_tts.EditForTtsPipeline", FakeEdit
        ):
            _run_stage_with_prompt_version("edit", 1, SimpleNamespace(text="x"))

        return captured["mock_mode"]

    def test_forwards_mock_true_by_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SELF_ITERATION_MOCK", raising=False)
        assert self._run_edit_stage(tmp_path, monkeypatch) is True

    def test_forwards_real_false_when_opt_out(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SELF_ITERATION_MOCK", "false")
        assert self._run_edit_stage(tmp_path, monkeypatch) is False