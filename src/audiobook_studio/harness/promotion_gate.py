"""晋升门禁：4 项硬指标裁决，统一入口 promote_candidate。

复用 feedback/promotion 的真实 check_* 函数（格式合规、质量比基线、人工偏好），
对 run_iteration_cycle 已算好的指标做统一门禁裁决；金标通过率与质量比由迭代闭环
预计算后传入，避免重复跑 pipeline。晋升执行委托给 feedback/deploy.promote_candidate
（真引擎），其 human_preference_score 等参数被如实透传。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from ..feedback.promotion import GateResult, check_format_compliance, check_human_sample
from ..feedback.prompt_compiler import stage_to_prompt_dir
from .config import get_harness_settings

logger = logging.getLogger(__name__)


@dataclass
class PromotionDecision:
    """晋升决策结果。"""

    passed: bool
    gates: List[GateResult]
    summary: str
    candidate_version: int
    stage: str
    failed_criteria: List[str] = field(default_factory=list)
    deployed: bool = False


def _samples_from_score(score: float, n: int = 100) -> List[bool]:
    """把连续偏好分 [0,1] 还原为 n 条抽样布尔，供复用的真实 check_human_sample。"""
    k = int(round(max(0.0, min(1.0, score)) * n))
    return [True] * k + [False] * (n - k)


def _read_candidate_content(stage: str, version: int, prompts_dir: Path) -> Optional[str]:
    """读取候选 prompt 内容（harness 自有沙箱 prompts/harness/<dir>/vN.j2）。"""
    candidate = Path(prompts_dir) / stage_to_prompt_dir(stage) / f"v{version}.j2"
    if candidate.exists():
        try:
            return candidate.read_text(encoding="utf-8")
        except OSError:
            return None
    # 兼容真实 prompts/<dir>/vN.j2 布局
    alt = Path(prompts_dir) / stage / f"v{version}.j2"
    if alt.exists():
        try:
            return alt.read_text(encoding="utf-8")
        except OSError:
            return None
    return None


@dataclass
class PromotionGate:
    """可配置门禁：4 项硬指标裁决。"""

    golden_pass_rate_min: float = 0.95
    quality_ratio_min: float = 1.0
    format_compliance_min: float = 1.0
    human_preference_min: float = 1.0

    @classmethod
    def from_settings(cls) -> "PromotionGate":
        s = get_harness_settings()
        return cls(
            golden_pass_rate_min=s.PROMOTION_GOLDEN_PASS_RATE_MIN,
            quality_ratio_min=s.PROMOTION_QUALITY_RATIO_MIN,
            format_compliance_min=s.PROMOTION_FORMAT_COMPLIANCE_MIN,
            human_preference_min=s.PROMOTION_HUMAN_PREFERENCE_MIN,
        )

    def evaluate(
        self,
        stage: str,
        candidate_version: int,
        golden_dataset_pass_rate: float,
        quality_score_ratio: float,
        human_preference_score: float,
        prompts_dir: Path,
        format_compliance_rate: float = 1.0,
    ) -> PromotionDecision:
        """对 4 项硬指标逐一裁决，返回晋级决策。"""
        gates: List[GateResult] = []

        # Gate 1: 格式合规率 —— 读取候选 prompt 内容做真实语法/结构检查。
        content = _read_candidate_content(stage, candidate_version, prompts_dir)
        if content is None:
            gates.append(
                GateResult(
                    name="格式合规率",
                    passed=False,
                    score=0.0,
                    threshold=self.format_compliance_min,
                    details="候选 prompt 文件未找到，无法检查格式",
                )
            )
        else:
            gates.append(check_format_compliance(content, threshold=self.format_compliance_min))

        # Gate 2: 金标数据集通过率（迭代闭环预计算值）。
        gates.append(
            GateResult(
                name="金标数据集通过率",
                passed=golden_dataset_pass_rate >= self.golden_pass_rate_min,
                score=float(golden_dataset_pass_rate),
                threshold=self.golden_pass_rate_min,
                details=f"通过率 {golden_dataset_pass_rate:.2%}",
            )
        )

        # Gate 3: 质量比基线（>= 1.0 即不退化）。
        gates.append(
            GateResult(
                name="质量 ≥ 基线",
                passed=quality_score_ratio >= self.quality_ratio_min,
                score=float(quality_score_ratio),
                threshold=self.quality_ratio_min,
                details=f"质量比 {quality_score_ratio:.3f}",
            )
        )

        # Gate 4: 人工偏好分（来自抽检库；复用的真实 check_human_sample）。
        gates.append(
            check_human_sample(
                _samples_from_score(human_preference_score),
                threshold=self.human_preference_min,
            )
        )

        all_passed = all(g.passed for g in gates)
        failed = [g.name for g in gates if not g.passed]
        return PromotionDecision(
            passed=all_passed,
            gates=gates,
            summary="全部门禁通过" if all_passed else f"失败项: {', '.join(failed)}",
            candidate_version=candidate_version,
            stage=stage,
            failed_criteria=failed,
            deployed=False,
        )


def promote_candidate(
    stage: str,
    candidate_version: int,
    golden_dataset_pass_rate: float,
    quality_score_ratio: float,
    format_compliance_rate: float,
    human_preference_score: float,
    prompts_dir: Path,
    auto_deploy: bool = True,
) -> "PromotionDecision":
    """统一晋升入口：4 项硬指标裁决 + 委托真引擎部署。

    Args:
        stage: pipeline stage 名
        candidate_version: 候选版本号
        golden_dataset_pass_rate: 金标数据集通过率
        quality_score_ratio: 质量比基线比率
        format_compliance_rate: 格式合规率（保留参数，格式门禁直接读取候选内容）
        human_preference_score: 人工偏好分（来自抽检库；默认 1.0 放行）
        prompts_dir: prompts 根目录
        auto_deploy: 是否自动部署
    """
    gate = PromotionGate.from_settings()
    decision = gate.evaluate(
        stage=stage,
        candidate_version=candidate_version,
        golden_dataset_pass_rate=golden_dataset_pass_rate,
        quality_score_ratio=quality_score_ratio,
        human_preference_score=human_preference_score,
        prompts_dir=prompts_dir,
        format_compliance_rate=format_compliance_rate,
    )

    # 晋升执行委托给 feedback/deploy.promote_candidate（真引擎）；
    # 关键指标（含金标通过率、质量比、人工偏好）如实透传，保证「人工抽检分替代默认
    # 1.0 放行」在部署路径上生效。
    if decision.passed and auto_deploy:
        try:
            from ..feedback.deploy import promote_candidate as deploy_promote

            deploy_promote(
                stage,
                candidate_version,
                golden_dataset_pass_rate=golden_dataset_pass_rate,
                quality_score_ratio=quality_score_ratio,
                format_compliance_rate=format_compliance_rate,
                human_preference_score=human_preference_score,
                prompts_dir=Path(prompts_dir),
                auto_deploy=True,
            )
            decision.deployed = True
        except Exception as e:  # noqa: BLE001
            logger.error(f"[promotion_gate] 自动部署失败: {e}")

    return decision


# 兼容旧接口
def promote_candidate_legacy(
    stage: str,
    candidate_version: int,
    golden_dataset_pass_rate: float,
    quality_score_ratio: float,
    format_compliance_rate: float,
    human_preference_score: float,
    prompts_dir: Path,
    auto_deploy: bool = True,
) -> Tuple[bool, List[GateResult]]:
    """兼容旧接口。"""
    decision = promote_candidate(
        stage=stage,
        candidate_version=candidate_version,
        golden_dataset_pass_rate=golden_dataset_pass_rate,
        quality_score_ratio=quality_score_ratio,
        format_compliance_rate=format_compliance_rate,
        human_preference_score=human_preference_score,
        prompts_dir=Path(prompts_dir),
        auto_deploy=auto_deploy,
    )
    return decision.passed, list(decision.gates)


def rollback_prompt(stage: str, target_version: int, prompts_dir: Path) -> bool:
    """回滚到指定版本。"""
    try:
        from ..feedback.deploy import rollback_prompt as deploy_rollback

        deploy_rollback(stage, target_version, prompts_dir)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"[promotion_gate] 回滚失败: {e}")
        return False


def rollback_canary(test_id: str, reason: str = "Manual rollback") -> bool:
    """回滚金丝雀测试。"""
    try:
        from .canary import get_canary_abtest

        canary = get_canary_abtest()
        return canary.rollback(test_id, reason)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[promotion_gate] 回滚金丝雀失败: {e}")
        return False
