#!/usr/bin/env python3
"""Regression suite snapshot tests.

每版 prompt 固化输出快照 (JSON) - 自动阻断退化。
运行方式：
  python -m pytest tests/regression/test_regression_snapshots.py -v
  python -m pytest tests/regression/test_regression_snapshots.py --update-snapshots  # 更新快照
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

# Import from the split modules
from src.audiobook_studio.feedback.canary import (
    _golden_to_pipeline_stage,
    _load_golden_examples,
    _run_stage_with_prompt_version,
)
from src.audiobook_studio.feedback.promotion import (
    check_format_compliance,
    check_golden_dataset,
    check_quality_improvement,
    evaluate_promotion,
)

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
UPDATE_SNAPSHOTS = os.getenv("UPDATE_SNAPSHOTS", "false").lower() in ("true", "1", "yes")

# Stages to test
STAGES = [
    "extract",
    "analyze_structure",
    "annotate_paragraph",
    "edit_for_tts",
    "translate",
    "quality_judge",
    "quality_check",
]

# Prompt versions to test per stage
VERSIONS = [1, 2, 3]  # v1, v2, v3


def load_snapshot(stage: str, version: int) -> Dict[str, Any]:
    """Load a snapshot for a stage and version."""
    snapshot_file = SNAPSHOT_DIR / f"{stage}_v{version}.json"
    if snapshot_file.exists():
        return json.loads(snapshot_file.read_text(encoding="utf-8"))
    return {}


def save_snapshot(stage: str, version: int, data: Dict[str, Any]) -> None:
    """Save a snapshot for a stage and version."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_file = SNAPSHOT_DIR / f"{stage}_v{version}.json"
    snapshot_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_golden_inputs(stage: str) -> List[Dict[str, Any]]:
    """Load golden examples and extract inputs for a stage."""
    examples = _load_golden_examples(stage)
    inputs = []
    for ex in examples:
        if "input" in ex:
            inputs.append(ex["input"])
    return inputs


def run_stage_on_inputs(stage: str, version: int, inputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Run a pipeline stage with a specific prompt version on given inputs."""
    pipeline_stage = _golden_to_pipeline_stage(stage)
    outputs = []
    for inp in inputs:
        try:
            output = _run_stage_with_prompt_version(pipeline_stage, version, inp, mock_mode=True)
            if hasattr(output, "model_dump"):
                output = output.model_dump()
            outputs.append(output)
        except Exception as e:
            outputs.append({"error": str(e)})
    return outputs


def generate_promotion_snapshot(
    stage: str,
    old_version: int,
    new_version: int,
    human_samples: List[bool] = None,
) -> Dict[str, Any]:
    """Generate a promotion evaluation snapshot."""
    verdict = evaluate_promotion(
        stage=stage,
        old_version=old_version,
        new_version=new_version,
        human_samples=human_samples,
        regression_fn=None,
        candidate_id=f"test_{stage}_{old_version}_to_{new_version}",
    )
    return {
        "stage": stage,
        "old_version": old_version,
        "new_version": new_version,
        "passed": verdict.passed,
        "summary": verdict.summary,
        "gates": [
            {
                "name": g.name,
                "passed": g.passed,
                "score": g.score,
                "threshold": g.threshold,
                "details": g.details,
            }
            for g in verdict.gates
        ],
        "pass_rate": verdict.pass_rate,
        "evaluated_at": verdict.evaluated_at,
    }


class TestRegressionSnapshots:
    """Regression snapshot tests for each prompt version."""

    @pytest.mark.parametrize("stage", STAGES)
    @pytest.mark.parametrize("version", VERSIONS)
    def test_format_compliance_snapshot(self, stage: str, version: int):
        """Test format compliance for each prompt version."""
        from src.audiobook_studio.feedback.canary import _load_prompt_version

        prompt = _load_prompt_version(stage, version)
        if prompt is None:
            pytest.skip(f"Prompt v{version} not found for stage {stage}")

        result = check_format_compliance(prompt)

        snapshot = load_snapshot(stage, version).get("format_compliance", {})

        current = {
            "name": result.name,
            "passed": result.passed,
            "score": result.score,
            "threshold": result.threshold,
            "details": result.details,
        }

        if UPDATE_SNAPSHOTS or not snapshot:
            save_snapshot(stage, version, {**load_snapshot(stage, version), "format_compliance": current})
            print(f"Updated snapshot: {stage}_v{version}_format")
        else:
            assert current == snapshot, f"Format compliance snapshot mismatch for {stage} v{version}"

    @pytest.mark.parametrize("stage", STAGES)
    @pytest.mark.parametrize("version", VERSIONS)
    def test_golden_dataset_pass_rate_snapshot(self, stage: str, version: int):
        """Test golden dataset pass rate for each prompt version."""
        result = check_golden_dataset(stage, version)

        snapshot = load_snapshot(stage, version).get("golden_dataset", {})

        current = {
            "name": result.name,
            "passed": result.passed,
            "score": result.score,
            "threshold": result.threshold,
            "details": result.details,
        }

        if UPDATE_SNAPSHOTS or not snapshot:
            save_snapshot(stage, version, {**load_snapshot(stage, version), "golden_dataset": current})
            print(f"Updated snapshot: {stage}_v{version}_golden")
        else:
            assert current == snapshot, f"Golden dataset snapshot mismatch for {stage} v{version}"

    @pytest.mark.parametrize("stage", STAGES)
    @pytest.mark.parametrize("old_version,new_version", [(1, 2), (2, 3)])
    def test_quality_improvement_snapshot(self, stage: str, old_version: int, new_version: int):
        """Test quality improvement between versions."""
        result = check_quality_improvement(stage, old_version, new_version)

        snapshot = load_snapshot(stage, new_version).get("quality_improvement", {})

        current = {
            "name": result.name,
            "passed": result.passed,
            "score": result.score,
            "threshold": result.threshold,
            "details": result.details,
        }

        if UPDATE_SNAPSHOTS or not snapshot:
            save_snapshot(stage, new_version, {**load_snapshot(stage, new_version), "quality_improvement": current})
            print(f"Updated snapshot: {stage}_v{new_version}_quality")
        else:
            assert (
                current == snapshot
            ), f"Quality improvement snapshot mismatch for {stage} v{old_version}->{new_version}"

    @pytest.mark.parametrize("stage", STAGES)
    @pytest.mark.parametrize("old_version,new_version", [(1, 2), (2, 3)])
    def test_promotion_evaluation_snapshot(self, stage: str, old_version: int, new_version: int):
        """Test full promotion evaluation."""
        human_samples = [True, True, True, True]  # 4/4 pass = 100%

        result = generate_promotion_snapshot(stage, old_version, new_version, human_samples)

        snapshot = load_snapshot(stage, new_version).get("promotion", {})

        # Normalize timestamp for comparison
        current = {k: v for k, v in result.items() if k != "evaluated_at"}
        snapshot_compare = {k: v for k, v in snapshot.items() if k != "evaluated_at"}

        if UPDATE_SNAPSHOTS or not snapshot:
            save_snapshot(stage, new_version, {**load_snapshot(stage, new_version), "promotion": current})
            print(f"Updated snapshot: {stage}_v{new_version}_promotion")
        else:
            assert current == snapshot_compare, f"Promotion snapshot mismatch for {stage} v{old_version}->{new_version}"

    @pytest.mark.parametrize("stage", STAGES)
    @pytest.mark.parametrize("version", VERSIONS)
    def test_stage_output_snapshot(self, stage: str, version: int):
        """Test stage output on golden inputs."""
        inputs = get_golden_inputs(stage)
        if not inputs:
            pytest.skip(f"No golden inputs for stage {stage}")

        outputs = run_stage_on_inputs(stage, version, inputs)

        snapshot = load_snapshot(stage, version).get("outputs", [])

        # Compare outputs (simplified - just check first 3 outputs)
        compare_outputs = outputs[:3]  # Only compare first 3
        if UPDATE_SNAPSHOTS or not snapshot:
            save_snapshot(stage, version, {**load_snapshot(stage, version), "outputs": compare_outputs})
            print(f"Updated snapshot: {stage}_v{version}_outputs")
        else:
            assert len(compare_outputs) == len(snapshot), f"Output count mismatch for {stage} v{version}"
            # Compare first output structure
            if compare_outputs and snapshot:
                out_keys = set(compare_outputs[0].keys()) if isinstance(compare_outputs[0], dict) else set()
                snap_keys = set(snapshot[0].keys()) if isinstance(snapshot[0], dict) else set()
                assert out_keys == snap_keys, f"Output structure mismatch for {stage} v{version}"


class TestRegressionSuiteDiff:
    """Test regression suite diff before promotion."""

    def test_regression_suite_blocks_degraded_candidate(self):
        """Test that regression suite blocks candidates with known failures."""
        from src.audiobook_studio.feedback.regression_suite import KnownFailure, get_regression_suite

        suite = get_regression_suite()
        suite.add_failure(
            stage="edit",
            description="Test failure: over-editing",
            payload={"text": "test", "difficulty": "B"},
            producer_id="bad_producer_v1",
        )

        # Candidate that regresses
        def failing_eval_fn(case: KnownFailure):
            return True, None  # regressed = True

        verdict = suite.check_candidate("new_candidate", failing_eval_fn)
        assert verdict.rejected
        assert "regressed_on" in verdict.to_dict()

    def test_regression_suite_allows_improved_candidate(self):
        """Test that regression suite allows candidates without regressions."""
        from src.audiobook_studio.feedback.regression_suite import KnownFailure, get_regression_suite

        suite = get_regression_suite()
        suite.add_failure(
            stage="edit",
            description="Test failure: over-editing",
            payload={"text": "test", "difficulty": "B"},
            producer_id="bad_producer_v1",
        )

        # Candidate that doesn't regress
        def passing_eval_fn(case: KnownFailure):
            return False, None  # regressed = False

        verdict = suite.check_candidate("good_candidate", passing_eval_fn)
        assert verdict.passed

    def test_regression_suite_captures_new_failures(self):
        """Test that regression suite captures new failures when evaluating existing cases."""
        from src.audiobook_studio.feedback.regression_suite import KnownFailure, get_regression_suite

        suite = get_regression_suite()
        # First add a known failure
        suite.add_failure(
            stage="edit",
            description="Original failure: over-editing",
            payload={"text": "test", "difficulty": "B"},
            producer_id="bad_producer_v1",
        )
        initial_count = suite.active_cases

        # Candidate that introduces a NEW failure when evaluating the existing case
        def new_failure_eval_fn(case: KnownFailure):
            # Return a new failure detected during evaluation
            return False, KnownFailure(
                failure_id="",
                stage="edit",
                description="New failure: under-editing",
                payload={"text": "new_test", "difficulty": "C"},
                producer_id="test_candidate",
            )

        suite.check_candidate("test_candidate", new_failure_eval_fn, auto_add_new=True)

        # Should have added the new failure (in addition to the original)
        assert suite.active_cases == initial_count + 1
        assert any("under-editing" in f.description for f in suite.active_failures())


if __name__ == "__main__":
    # Allow running directly to update snapshots
    import sys

    if "--update-snapshots" in sys.argv:
        os.environ["UPDATE_SNAPSHOTS"] = "true"
    pytest.main([__file__, "-v"])
