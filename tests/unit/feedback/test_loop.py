"""M0 golden 回流单元测试。"""

from __future__ import annotations

from pathlib import Path

from audiobook_studio.feedback.loop import (
    GoldenSample,
    append_golden_sample,
    correction_to_sample,
    corrections_to_golden,
)
from audiobook_studio.pipeline.sop_reflection import CorrectionBatch, UserCorrection


def _correction(value) -> UserCorrection:
    return UserCorrection(
        timestamp="2026-08-30T00:00:00Z",
        project_id=1,
        chapter_index=1,
        paragraph_index=2,
        field="speech_rate",
        original_value=1.0,
        corrected_value=value,
        genre="fantasy",
        context={"speaker": "narrator"},
    )


def test_golden_sample_hash_is_stable_and_unique():
    a = GoldenSample(stage="edit", input={"x": 1}, output={"v": 9})
    b = GoldenSample(stage="edit", input={"x": 1}, output={"v": 9})
    c = GoldenSample(stage="edit", input={"x": 1}, output={"v": 8})
    assert a.sample_hash == b.sample_hash
    assert a.sample_hash != c.sample_hash
    assert GoldenSample(stage="edit", input=1, output=2).sample_hash  # post-init fills hash


def test_append_golden_sample_writes_and_dedups(tmp_path: Path):
    root = tmp_path / "data" / "golden"
    s = GoldenSample(stage="edit", input={"p": 1}, output={"v": 5})
    assert append_golden_sample("edit", "val", s, golden_root=root) is True
    # 同内容重复 -> 不新增
    assert append_golden_sample("edit", "val", s, golden_root=root) is False
    # 不同内容 -> 新增
    s2 = GoldenSample(stage="edit", input={"p": 1}, output={"v": 6})
    assert append_golden_sample("edit", "val", s2, golden_root=root) is True

    lines = (root / "val" / "edit" / "edit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    # 文件可回读为 GoldenSample
    from audiobook_studio.feedback.loop import _load_samples

    loaded = _load_samples(root / "val" / "edit" / "edit.jsonl")
    assert len(loaded) == 2
    assert loaded[0].stage == "edit"


def test_append_rejects_invalid_split(tmp_path: Path):
    root = tmp_path / "data" / "golden"
    s = GoldenSample(stage="edit", input=1, output=2)
    try:
        append_golden_sample("edit", "bogus", s, golden_root=root)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_corrections_to_golden(tmp_path: Path):
    root = tmp_path / "data" / "golden"
    batch = CorrectionBatch(
        corrections=[_correction(1.2), _correction(1.5)],
        genre="fantasy",
        project_id=1,
        collected_at="2026-08-30T00:00:00Z",
    )
    added = corrections_to_golden(batch, split="val", stage="edit", golden_root=root)
    assert added == 2
    # 再次回流相同修正 -> 去重为 0
    assert corrections_to_golden(batch, split="val", stage="edit", golden_root=root) == 0

    sample = correction_to_sample(_correction(1.2))
    assert sample.stage == "edit"
    assert sample.output == {"field": "speech_rate", "value": 1.2}
    assert sample.source == "user_correction"


def test_seed_golden_idempotent(tmp_path: Path):
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("seed_golden", "scripts/seed_golden.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["seed_golden"] = mod
    spec.loader.exec_module(mod)

    root = tmp_path / "data" / "golden"
    train_dir = root / "train" / "edit"
    train_dir.mkdir(parents=True, exist_ok=True)
    train_dir.joinpath("edit.jsonl").write_text(
        "\n".join(f'{{"input": {{"i": {i}}}, "output": {{"o": {i}}}}}' for i in range(20)) + "\n",
        encoding="utf-8",
    )

    n1 = mod.seed(split="val", ratio=0.5, root=root, dry_run=False)
    assert n1 > 0
    # 幂等：再次运行不新增
    n2 = mod.seed(split="val", ratio=0.5, root=root, dry_run=False)
    assert n2 == 0
    # 确定性：同输入产出条数一致
    lines = (root / "val" / "edit" / "edit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == n1
