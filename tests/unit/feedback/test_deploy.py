"""M4 — 候选部署/回滚 + 晋升门禁（release.PromotionGate 4 项硬指标）。"""

from __future__ import annotations

from pathlib import Path

from audiobook_studio.feedback.deploy import deploy_prompt, promote_candidate, rollback_prompt, served_version


def _setup_edit(tmp_path: Path):
    d = tmp_path / "edit_for_tts"
    d.mkdir(parents=True)
    (d / "v1.j2").write_text("BASE v1 PROMPT", encoding="utf-8")
    (d / "v2.j2").write_text("CANDIDATE v2 PROMPT", encoding="utf-8")
    (d / "v3.j2").write_text("CANDIDATE v3 PROMPT", encoding="utf-8")
    return d


def test_deploy_prompt_copies_to_v1_and_records_served(tmp_path: Path):
    d = _setup_edit(tmp_path)
    assert served_version("edit", tmp_path) == 0
    assert deploy_prompt("edit", 2, prompts_dir=tmp_path) is True
    assert (d / "v1.j2").read_text(encoding="utf-8") == "CANDIDATE v2 PROMPT"
    assert served_version("edit", tmp_path) == 2
    # v2.j2 原文件保持不动（候选保留，可回滚）
    assert (d / "v2.j2").exists()


def test_deploy_missing_version_fails(tmp_path: Path):
    _setup_edit(tmp_path)
    assert deploy_prompt("edit", 99, prompts_dir=tmp_path) is False
    assert served_version("edit", tmp_path) == 0


def test_rollback_to_earlier_version(tmp_path: Path):
    d = _setup_edit(tmp_path)
    deploy_prompt("edit", 3, prompts_dir=tmp_path)
    assert served_version("edit", tmp_path) == 3
    # 回滚到 v1
    assert rollback_prompt("edit", 1, prompts_dir=tmp_path) is True
    assert (d / "v1.j2").read_text(encoding="utf-8") == "BASE v1 PROMPT"
    assert served_version("edit", tmp_path) == 1
    # 回滚到 >= 当前 served 应失败
    assert rollback_prompt("edit", 1, prompts_dir=tmp_path) is False
    assert rollback_prompt("edit", 5, prompts_dir=tmp_path) is False


def test_promote_candidate_passes_gate_then_deploys(tmp_path: Path):
    _setup_edit(tmp_path)
    # 完美候选：金数据集通过率 1.0，质量比基线 +100%（>=1.02），格式/人工满分
    decision = promote_candidate(
        "edit",
        2,
        golden_dataset_pass_rate=1.0,
        quality_score_ratio=2.0,
        format_compliance_rate=1.0,
        human_preference_score=1.0,
        prompts_dir=tmp_path,
        auto_deploy=True,
    )
    assert decision.passed is True
    assert decision.deployed is True
    assert served_version("edit", tmp_path) == 2


def test_promote_candidate_fails_gate_does_not_deploy(tmp_path: Path):
    d = _setup_edit(tmp_path)
    # 金数据集通过率不达标（< 0.95）→ 拒绝部署
    decision = promote_candidate(
        "edit",
        2,
        golden_dataset_pass_rate=0.5,
        quality_score_ratio=2.0,
        format_compliance_rate=1.0,
        human_preference_score=1.0,
        prompts_dir=tmp_path,
        auto_deploy=True,
    )
    assert decision.passed is False
    assert decision.deployed is False
    assert "金数据集通过率" in "".join(decision.failed_criteria)
    # v1.j2 仍为基线，未被污染
    assert (d / "v1.j2").read_text(encoding="utf-8") == "BASE v1 PROMPT"
    assert served_version("edit", tmp_path) == 0
