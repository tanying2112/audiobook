"""Phase C structural tests for feedback/held_out_eval.py (frozen held-out set)."""

import json
import math
from pathlib import Path

import pytest

from src.audiobook_studio.feedback.held_out_eval import (
    CandidateEvalResult,
    DatasetManifest,
    HeldOutCase,
    HeldOutDataset,
    _safe_score,
)


def _row(cid):
    return {
        "id": cid,
        "input": {"text": f"input-{cid}"},
        "expected_output": {"score": 1},
        "reference_audio_key": f"k-{cid}",
    }


def _make_golden(tmp_path: Path, stage: str, rows):
    d = tmp_path / stage
    d.mkdir(parents=True)
    (d / "a.json").write_text(json.dumps(rows[0], ensure_ascii=False), encoding="utf-8")
    with (d / "b.jsonl").open("w", encoding="utf-8") as f:
        for r in rows[1:]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n\n")  # trailing blank line
    # corrupt file should be skipped with a warning
    (d / "bad.json").write_text("{not valid json", encoding="utf-8")
    return d


# ── Value objects ──────────────────────────────────────────────────────────────


def test_held_out_case_signature_and_to_dict():
    case = HeldOutCase(case_id="c1", input={"a": 1}, expected_output={"b": 2}, stage="s")
    sig = case.signature()
    assert isinstance(sig, str) and len(sig) == 16
    d = case.to_dict()
    assert d["case_id"] == "c1"
    assert d["input"] == {"a": 1}


def test_dataset_manifest_to_dict():
    man = DatasetManifest(
        stage="s", case_count=2, signatures=("aa", "bb"), dataset_signature="ds",
        golden_root="/x", origin_status="loaded", held_out_commit_note="note",
    )
    d = man.to_dict()
    assert d["case_count"] == 2
    assert d["signatures"] == ["aa", "bb"]
    assert d["origin_status"] == "loaded"


def test_candidate_result_beat_baseline():
    r = CandidateEvalResult(
        candidate_id="x", baseline_id="b", case_count=2, scores=(0.9, 0.9),
        mean_score=0.9, baseline_mean=0.5, effect_size=0.4,
    )
    assert r.beat_baseline_by_025 is True
    d = r.to_dict()
    assert d["beat_baseline_by_025"] is True

    r2 = CandidateEvalResult(
        candidate_id="x", baseline_id="b", case_count=2, scores=(0.9, 0.9),
        mean_score=0.9, baseline_mean=0.8, effect_size=0.1,
    )
    assert r2.beat_baseline_by_025 is False  # effect < 0.25

    r3 = CandidateEvalResult(
        candidate_id="x", baseline_id="b", case_count=2, scores=(0.9, 0.9), mean_score=0.9,
    )
    assert r3.beat_baseline_by_025 is False  # effect None


# ── Dataset loading ──────────────────────────────────────────────────────────


def test_dataset_loads_from_golden(tmp_path):
    golden = _make_golden(tmp_path, "extract", [_row("c1"), _row("c2")])
    ds = HeldOutDataset("extract", golden_root=tmp_path)
    assert ds.stage == "extract"
    assert ds.case_count == 2
    assert set(ds.case_ids) == {"c1", "c2"}
    # the cases property exposes the immutable tuple
    assert isinstance(ds.cases, tuple) and len(ds.cases) == 2
    assert ds.by_id["c1"].case_id == "c1"
    assert isinstance(ds.signature, str) and len(ds.signature) == 64
    man = ds.manifest
    assert man.case_count == 2
    assert man.origin_status == "loaded"


def test_missing_golden_dir_returns_empty(tmp_path):
    ds = HeldOutDataset("nope", golden_root=tmp_path / "missing")
    assert ds.case_count == 0
    assert ds.manifest.origin_status.startswith("empty:not-found")


def test_parse_row_non_mapping_raises():
    with pytest.raises(KeyError):
        HeldOutDataset._parse_row([1, 2, 3], "s", "x.json")


def test_parse_row_generates_id_when_missing():
    case = HeldOutDataset._parse_row({"input": {"a": 1}}, "s", "f.json")
    assert case.case_id.startswith("f.json:")
    # input/expected_output are read-only MappingProxyType
    with pytest.raises(TypeError):
        case.input["a"] = 99  # type: ignore[index]


# ── Immutability ───────────────────────────────────────────────────────────────


def test_immutable_private_field_reassign(tmp_path):
    golden = _make_golden(tmp_path, "extract", [_row("c1")])
    ds = HeldOutDataset("extract", golden_root=tmp_path)
    with pytest.raises(TypeError):
        ds._cases = ()  # type: ignore[misc]


def test_immutable_non_private_attr(tmp_path):
    golden = _make_golden(tmp_path, "extract", [_row("c1")])
    ds = HeldOutDataset("extract", golden_root=tmp_path)
    with pytest.raises(TypeError):
        ds.foo = 1  # type: ignore[attr-defined]


# ── Candidate evaluation ───────────────────────────────────────────────────────


def test_evaluate_candidate_empty_set(tmp_path):
    ds = HeldOutDataset("nope", golden_root=tmp_path / "missing")
    res = ds.evaluate_candidate(lambda c: 1.0)
    assert res.case_count == 0
    assert res.mean_score == 0.0
    assert res.effect_size is None
    assert res.notes and "empty" in res.notes[0]


def test_evaluate_candidate_with_baseline(tmp_path):
    golden = _make_golden(tmp_path, "extract", [_row("c1"), _row("c2")])
    ds = HeldOutDataset("extract", golden_root=tmp_path)
    res = ds.evaluate_candidate(
        lambda c: 0.9, candidate_id="C", baseline_fn=lambda c: 0.5, baseline_id="B",
    )
    assert res.case_count == 2
    assert res.mean_score == 0.9
    assert res.baseline_mean == 0.5
    assert res.effect_size == 0.4
    assert res.beat_baseline_by_025 is True


# ── _safe_score helper ─────────────────────────────────────────────────────────


def test_safe_score_clamps_nan_and_error():
    case = HeldOutCase(case_id="c1", input={}, expected_output={}, stage="s")
    assert _safe_score(lambda c: 1.5, case) == 1.0  # clamp high
    assert _safe_score(lambda c: -1.0, case) == 0.0  # clamp low
    assert _safe_score(lambda c: float("nan"), case) == 0.0  # NaN -> 0
    assert _safe_score(lambda c: 1 / 0, case) == 0.0  # exception -> 0
