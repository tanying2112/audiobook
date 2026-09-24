"""Regression tests for ADR-005: per-paragraph checkpoint granularity.

The v2 ``CheckpointManager`` tracked all stages at chapter granularity
(``is_stage_done(stage, chapter_index)``). This silently broke paragraph-level
stages (``annotate``/``edit``/``audio_postprocess``/``synthesize``/``quality``):
once paragraph 1 completed ``annotate`` for chapter 1, the checkpoint recorded
``annotate`` as done for the whole chapter, so paragraphs 2..N were skipped on
the next ``run_pipeline`` call (see ``storage/books/4/logs/pipe_fix8.log``).

ADR-005 upgraded the granularity to ``(stage, chapter_index, paragraph_index)``
for paragraph-level stages. These tests lock the new behaviour in.
"""

from __future__ import annotations

import json

import pytest

from src.audiobook_studio.pipeline.checkpoint import CheckpointManager


@pytest.fixture
def cp(tmp_path, monkeypatch):
    """CheckpointManager writing into an isolated tmp project dir.

    The CheckpointManager module imports ``reports_dir`` by name from
    ``..storage``, so the binding lives in the ``checkpoint`` module's
    namespace. Patching ``storage.reports_dir`` would NOT affect
    ``checkpoint.reports_dir``. We patch the binding at its actual use site.
    """
    from src.audiobook_studio.pipeline import checkpoint as cp_mod

    monkeypatch.setattr(cp_mod, "reports_dir", lambda pid, ensure=False: tmp_path)
    return CheckpointManager(project_id=999)


def test_paragraph_level_stage_isolated_between_paragraphs(cp):
    """Paragraph 1 completing annotate MUST NOT mark annotate done for paragraph 2.

    Regression for the root cause documented in ADR-005: the v2 code pathed
    ``is_stage_done("annotate", chapter_index=1)`` ignoring ``paragraph_index``
    entirely, so once any paragraph finished the stage, all others were
    silently skipped.
    """
    # paragraph 1 finishes annotate
    cp.mark_stage_done("annotate", chapter_index=1, paragraph_index=1)
    assert cp.is_stage_done("annotate", 1, paragraph_index=1)
    # paragraph 2 must NOT inherit paragraph 1's completion
    assert not cp.is_stage_done("annotate", 1, paragraph_index=2)
    assert not cp.is_stage_done("annotate", 1, paragraph_index=3)


def test_paragraph_level_stage_done_does_not_pollute_chapter_level(cp):
    """Marking a paragraph-level stage as done must NOT also mark it done at the chapter level.

    v2 stored every completed stage in ``chapters[c].stages_done``; v3 stores
    paragraph-level stages under ``chapters[c].paragraphs[str(p)].stages_done``.
    The chapter-level list must remain free of paragraph-level stage names so
    that chapter-level resume logic (``next_stage``/``stages_to_run``) does
    not falsely conclude the chapter is fully complete.
    """
    cp.mark_stage_done("annotate", chapter_index=1, paragraph_index=1)
    cp.mark_stage_done("edit", chapter_index=1, paragraph_index=1)
    cp.mark_stage_done("synthesize", chapter_index=1, paragraph_index=1)
    cp.mark_stage_done("quality", chapter_index=1, paragraph_index=1)

    # Chapter-level lookup (no paragraph_index) must be False for these:
    assert not cp.is_stage_done("annotate", 1)
    assert not cp.is_stage_done("edit", 1)
    assert not cp.is_stage_done("synthesize", 1)
    assert not cp.is_stage_done("quality", 1)

    # Chapter-level stages (extract/analyze/review) still go to the chapter list
    cp.mark_stage_done("extract", 1)
    assert cp.is_stage_done("extract", 1)
    assert cp.last_completed_stage(1) == "extract"


def test_persistence_round_trip_per_paragraph(cp):
    """Per-paragraph stage completion must survive a save+reload round-trip."""
    cp.mark_stage_done("annotate", chapter_index=1, paragraph_index=1)
    cp.mark_stage_done("annotate", chapter_index=1, paragraph_index=2)
    cp.mark_stage_done("edit", chapter_index=1, paragraph_index=2)
    cp.mark_stage_done("extract", 1)
    cp._flush()

    # Reload from disk into a new instance pointing at the same project dir.
    reloaded = CheckpointManager(project_id=999)
    assert reloaded.is_stage_done("annotate", 1, paragraph_index=1)
    assert reloaded.is_stage_done("annotate", 1, paragraph_index=2)
    assert reloaded.is_stage_done("edit", 1, paragraph_index=2)
    assert not reloaded.is_stage_done("edit", 1, paragraph_index=1)
    assert reloaded.is_stage_done("extract", 1)  # chapter-level preserved


def test_v2_migration_drops_buggy_paragraph_level_entries(tmp_path, monkeypatch):
    """A v2 checkpoint file containing buggy chapter-level paragraph-stage
    entries must be migrated to v3 with those entries dropped, so the pipeline
    re-runs the affected paragraph-level stages instead of trusting the bogus
    'done' state.
    """
    from src.audiobook_studio.pipeline import checkpoint as cp_mod

    monkeypatch.setattr(cp_mod, "reports_dir", lambda pid, ensure=False: tmp_path)
    cp_path = tmp_path / "checkpoints.json"
    # Synthesize a v2 file like the one in storage/books/4/reports/checkpoints.json
    # from the bug report: all paragraph-level stages erroneously listed at the
    # chapter level.
    v2_data = {
        "project_id": 999,
        "chapters": {
            "1": {
                "stages_done": [
                    "extract",
                    "analyze",
                    "annotate",
                    "edit",
                    "audio_postprocess",
                    "review",
                    "synthesize",
                    "quality",
                ],
                "paragraphs_done": [],
                "current_stage": None,
            },
        },
        "version": 2,
    }
    cp_path.write_text(json.dumps(v2_data), encoding="utf-8")

    # Loading must trigger the v2→v3 migration in place.
    cp = CheckpointManager(project_id=999)
    # Chapter-level (extract/analyze/review) must be preserved.
    assert cp.is_stage_done("extract", 1)
    assert cp.is_stage_done("analyze", 1)
    assert cp.is_stage_done("review", 1)
    # Paragraph-level stages must NOT be reported as chapter-level done: they
    # were the source of the bug.
    assert not cp.is_stage_done("annotate", 1)
    assert not cp.is_stage_done("edit", 1)
    assert not cp.is_stage_done("audio_postprocess", 1)
    assert not cp.is_stage_done("synthesize", 1)
    assert not cp.is_stage_done("quality", 1)


def test_chapter_level_stage_ignores_paragraph_index(cp):
    """Chapter-level stages (extract/analyze/review) are tracked by STAGE TYPE,
    not by whether paragraph_index was passed. Calling
    ``mark_stage_done("extract", 1, paragraph_index=3)`` must:
      1. record completion in chapters[1].stages_done (chapter-level), AND
      2. NOT create a phantom entries entry in chapters[1].paragraphs.
    And ``is_stage_done("extract", 1, paragraph_index=3)`` must match the
    chapter-level result (paragraph_index is silently ignored for
    chapter-level stages), because “extract” is a chapter-level milestone
    and asking for it with paragraph_index shouldn't fabricate its absence.
    """
    cp.mark_stage_done("extract", 1, paragraph_index=3)
    # (1) chapter-level stage completion recorded at chapter granularity.
    assert cp.is_stage_done("extract", 1)
    # (2) no per-paragraph entry was created (paragraph index 3 doesn't exist).
    assert "3" not in cp._chapter(1).get("paragraphs", {})
    # (3) Asking with paragraph_index returns the chapter-level answer.
    assert cp.is_stage_done("extract", 1, paragraph_index=3)


def test_mark_stage_started_then_done_idempotent_per_paragraph(cp):
    """``mark_stage_done`` per paragraph must be idempotent (same as v2 chapter case)."""
    cp.mark_stage_done("annotate", 1, paragraph_index=5)
    cp.mark_stage_done("annotate", 1, paragraph_index=5)  # second call no-op
    cp._flush()
    reloaded = CheckpointManager(project_id=999)
    assert reloaded.is_stage_done("annotate", 1, paragraph_index=5)
