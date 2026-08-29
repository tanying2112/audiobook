"""M4 — 部署与回滚：把候选 prompt 经晋升门禁后部署到 live（v1.j2），并支持回滚。

关键约定（与运行时一致）：
* 生产运行时读取的是 ``prompts/<dir>/v1.j2``（见 ``pipeline/annotate_paragraph.py`` 等）。
* M3 编译只写出 ``v{N+1}.j2``（候选），**不**触碰 v1.j2；M4 显式 ``deploy`` 才把候选
  内容覆盖到 v1.j2 使之生效。这样「编译」与「部署」解耦，门禁不通过则永不污染线上。
* 用 ``prompts/<dir>/deployed.txt`` 记录当前 live 版本号（区别于「最大编译版本」），
  使 served 版本与最新编译版本清晰分离，回滚到任意历史版本均可追溯。
* 晋升门禁用 ``release.PromotionGate`` 的 4 项硬指标（格式合规 / 金数据集通过率 /
  质量相对基线 / 人工抽检偏好），不通过即拒绝部署。
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .prompt_compiler import stage_to_prompt_dir
from .prompt_store import PromptStore
from .release import PromotionGate

logger = logging.getLogger(__name__)

DEFAULT_PROMPTS_DIR = Path("prompts")


def _deployed_marker(prompt_dir: str, prompts_root: Path) -> Path:
    return prompts_root / prompt_dir / "deployed.txt"


def _live_path(prompts_root: Path, prompt_dir: str) -> Path:
    """运行时读取的 live prompt 槽（prompts/<dir>/v1.j2）。"""
    return prompts_root / prompt_dir / "v1.j2"


def _base_backup(prompts_root: Path, prompt_dir: str) -> Path:
    """首次部署前对基线(v1.j2)的快照，保证可回滚到原始基线。"""
    return prompts_root / prompt_dir / "v1.j2.base"


def served_version(stage: str, prompts_dir: Optional[Path] = None) -> int:
    """当前 live（已部署）版本号；未部署过返回 0。"""
    root = prompts_dir or DEFAULT_PROMPTS_DIR
    marker = _deployed_marker(stage_to_prompt_dir(stage), root)
    if not marker.exists():
        return 0
    try:
        return int(marker.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return 0


def deploy_prompt(stage: str, version: int, prompts_dir: Optional[Path] = None) -> bool:
    """把候选 v{version}.j2 部署为 live（v1.j2），并记录 served 版本。

    Returns:
        是否成功部署。
    """
    root = prompts_dir or DEFAULT_PROMPTS_DIR
    prompt_dir = stage_to_prompt_dir(stage)
    src = root / prompt_dir / f"v{version}.j2"
    dst = _live_path(root, prompt_dir)
    if not src.exists():
        logger.error(f"[M4] 候选版本不存在，无法部署: {src}")
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    # 固化「当前 live」内容，保证任意历史版本都可回滚：
    #  - 已部署过：把当前 live 内容按它的版本号落盘为 v{current}.j2（若尚缺）。
    #  - 首次部署：把基线 v1.j2 备份为 v1.j2.base，便于回滚到原始基线。
    current = served_version(stage, root)
    if current > 0:
        prev = root / prompt_dir / f"v{current}.j2"
        if not prev.exists():
            shutil.copyfile(dst, prev)
    else:
        base = _base_backup(root, prompt_dir)
        if not base.exists():
            shutil.copyfile(dst, base)
    # 原子替换 v1.j2，避免半写状态
    tmp = dst.with_suffix(".j2.tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)
    # 记录 served 版本（区别于最大编译版本）
    _deployed_marker(prompt_dir, root).write_text(str(version), encoding="utf-8")
    # 同步 VersionStore 的 current 指针
    try:
        PromptStore(prompts_dir=root).promote(stage, version)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[M4] VersionStore 指针更新失败（不影响文件部署）: {e}")
    logger.info(f"[M4] 部署 {stage} -> v{version} (live=v1.j2)")
    return True


def rollback_prompt(stage: str, version: int, prompts_dir: Optional[Path] = None) -> bool:
    """回滚 live 到指定历史版本 v{version}.j2（必须 < 当前 served 版本）。"""
    root = prompts_dir or DEFAULT_PROMPTS_DIR
    prompt_dir = stage_to_prompt_dir(stage)
    current = served_version(stage, root)
    if version >= current:
        logger.warning(f"[M4] 回滚目标 v{version} 必须 < 当前 served v{current}")
        return False
    if version == 1:
        # 回滚到基线：优先用首次部署前的快照，否则直接用未被覆盖过的 v1.j2
        src = _base_backup(root, prompt_dir)
        if not src.exists():
            src = root / prompt_dir / "v1.j2"
    else:
        src = root / prompt_dir / f"v{version}.j2"
    dst = _live_path(root, prompt_dir)
    if not src.exists():
        logger.error(f"[M4] 回滚目标版本不存在: {src}")
        return False
    tmp = dst.with_suffix(".j2.tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)
    _deployed_marker(prompt_dir, root).write_text(str(version), encoding="utf-8")
    try:
        PromptStore(prompts_dir=root).rollback(stage, version)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[M4] VersionStore 回滚指针更新失败（不影响文件回滚）: {e}")
    logger.info(f"[M4] 回滚 {stage} -> v{version}")
    return True


@dataclass
class PromotionDecision:
    """晋升门禁裁决 + 后续动作结果。"""

    stage: str
    candidate_version: int
    passed: bool
    deployed: bool = False
    metrics: Dict[str, float] = field(default_factory=dict)
    failed_criteria: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.metrics:
            self.metrics = {}
        if not self.failed_criteria:
            self.failed_criteria = []


def evaluate_promotion_gate(
    stage: str,
    candidate_version: int,
    *,
    golden_dataset_pass_rate: float,
    quality_score_ratio: float,
    format_compliance_rate: float = 1.0,
    human_preference_score: float = 1.0,
    gate: Optional[PromotionGate] = None,
) -> PromotionDecision:
    """用 release.PromotionGate 的 4 项硬指标裁决候选是否可晋升。"""
    g = gate or PromotionGate()
    result = g.evaluate(
        format_compliance_rate=format_compliance_rate,
        golden_dataset_pass_rate=golden_dataset_pass_rate,
        quality_score_ratio=quality_score_ratio,
        human_preference_score=human_preference_score,
    )
    return PromotionDecision(
        stage=stage,
        candidate_version=candidate_version,
        passed=result.passed,
        metrics={
            "format_compliance_rate": format_compliance_rate,
            "golden_dataset_pass_rate": golden_dataset_pass_rate,
            "quality_score_ratio": quality_score_ratio,
            "human_preference_score": human_preference_score,
        },
        failed_criteria=list(result.failed_criteria),
    )


def promote_candidate(
    stage: str,
    candidate_version: int,
    *,
    golden_dataset_pass_rate: float,
    quality_score_ratio: float,
    format_compliance_rate: float = 1.0,
    human_preference_score: float = 1.0,
    prompts_dir: Optional[Path] = None,
    auto_deploy: bool = True,
) -> PromotionDecision:
    """端到端晋升：先过门禁，通过则部署候选到 live。

    不通过时绝不部署（fail-closed），并返回未通过的原因。
    """
    decision = evaluate_promotion_gate(
        stage,
        candidate_version,
        golden_dataset_pass_rate=golden_dataset_pass_rate,
        quality_score_ratio=quality_score_ratio,
        format_compliance_rate=format_compliance_rate,
        human_preference_score=human_preference_score,
    )
    if decision.passed and auto_deploy:
        decision.deployed = deploy_prompt(stage, candidate_version, prompts_dir=prompts_dir)
    return decision
