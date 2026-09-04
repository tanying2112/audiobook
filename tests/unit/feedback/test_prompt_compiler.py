"""M3 — 从 golden train 编译候选提示词（DSPy 退化为确定性 few-shot 编译）。"""

from __future__ import annotations

import shutil
from pathlib import Path

from audiobook_studio.feedback.prompt_compiler import (
    compile_candidate_prompt,
    select_fewshot_examples,
    stage_to_prompt_dir,
    write_candidate_prompt,
)


def test_stage_to_prompt_dir_covers_judge_and_quality():
    assert stage_to_prompt_dir("judge") == "quality_judge"
    assert stage_to_prompt_dir("quality") == "quality_judge"
    assert stage_to_prompt_dir("edit") == "edit_for_tts"
    assert stage_to_prompt_dir("annotate") == "annotate_paragraph"


def test_select_fewshot_prefers_passing_high_score():
    samples = [
        {"output": {"needs_regeneration": True, "overall_score": 0.2}, "sample_hash": "a"},
        {"output": {"needs_regeneration": False, "overall_score": 0.95}, "sample_hash": "b"},
        {"output": {"needs_regeneration": False, "overall_score": 0.6}, "sample_hash": "c"},
    ]
    top = select_fewshot_examples(samples, 2, "judge")
    assert [s["sample_hash"] for s in top] == ["b", "c"]


def test_compile_candidate_prompt_reads_train_and_embeds_examples(tmp_path: Path):
    # 用真实 train 金标（judge 阶段有 24 条），编译候选不落盘。
    # 使用隔离 prompts 沙箱（仅放入 v1 基线），避免受 prompts/quality_judge 下
    # 残留 v*.j2 影响版本号判定，使测试可重复运行。
    sandbox = tmp_path / "quality_judge"
    sandbox.mkdir(parents=True, exist_ok=True)
    base_src = Path("prompts") / "quality_judge" / "v1.j2"
    if base_src.exists():
        shutil.copy(base_src, sandbox / "v1.j2")
    cp = compile_candidate_prompt("judge", k=3, prompts_root=tmp_path)
    assert cp.stage == "judge"
    assert cp.prompt_dir == "quality_judge"
    assert cp.version == 2  # quality_judge 当前 active 为 v1 → 候选 v2
    assert cp.base_version == 1
    # 候选文本应包含 base 模板与 few-shot 样例
    assert "样例" in cp.prompt_text
    assert "自迭代编译" in cp.prompt_text
    assert len(cp.exemplars) == 3


def test_compile_candidate_prompt_with_injected_exemplars_is_deterministic():
    ex = [{"input": {"x": 1}, "output": {"y": 2}}]
    cp1 = compile_candidate_prompt("edit", k=1, exemplars=ex, prompts_root=Path("prompts"))
    cp2 = compile_candidate_prompt("edit", k=1, exemplars=ex, prompts_root=Path("prompts"))
    assert cp1.prompt_text == cp2.prompt_text
    # 候选版本号应为「当前最大版本 + 1」
    versions = sorted(int(p.stem[1:]) for p in (Path("prompts") / "edit_for_tts").glob("v*.j2"))
    assert cp1.version == versions[-1] + 1
    assert cp1.base_version == versions[-1]


def test_write_candidate_prompt_lands_vnext_and_not_promote(tmp_path: Path):
    # 在临时 prompts 根写入候选，验证落盘到 v{N+1}.j2
    # 先放一个 v1 基线
    (tmp_path / "edit_for_tts").mkdir(parents=True)
    (tmp_path / "edit_for_tts" / "v1.j2").write_text("BASE EDIT PROMPT", encoding="utf-8")

    cp = write_candidate_prompt(
        "edit",
        k=2,
        prompts_root=tmp_path,
        exemplars=[
            {"input": {"p": 1}, "output": {"v": 1}},
            {"input": {"p": 2}, "output": {"v": 2}},
        ],
    )
    target = tmp_path / "edit_for_tts" / "v2.j2"
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert text.startswith("BASE EDIT PROMPT")
    assert "样例" in text
    # 编译 ≠ 部署：运行时读取的是 v1.j2（live prompt），编译只写 v2.j2，
    # 不触碰 v1.j2；直到 M4 显式 promote 才会把 v2.j2 覆盖到 v1.j2。
    served = tmp_path / "edit_for_tts" / "v1.j2"
    assert served.read_text(encoding="utf-8") == "BASE EDIT PROMPT"
    assert cp.version == 2
