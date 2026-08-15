"""P0.3.6 — 追加式回归套件（Regression Suite）：历史坏例的"不许复发"账本。

对应执行手册 docs/EVOLUTION_ROADMAP.md P0.3 子任务 6，补 split_eval / 宪法 / 杀开关
之外的一条**回归侧防线**：把历史上踩过的坑（读错 / 循环 / 节奏乱 / 破音复现）冻结成
坏例，任何候选配置在晋升前都不得使这些坏例**复发**；新出现的失败自动入库，使下一代
候选无法"装作没发生过"。

设计原则（红线 #1 主路径真实性）：
  - 坏例是**追加式**的：只允许 `add_failure()` 增条，不允许静默删除；被回滚/废弃的坏例
    经显式 `retire()` 标记 retired（保留在册可审计，不再用做主动拒绝判据）。
  - `check_candidate(producer_id, eval_fn)`：在所有 active 坏例上跑候选 eval_fn（真值，
    非打分），若任一坏例上的判定 `regressed=True`，即拒绝该候选。**新增失败自动入库**：
    check 阶段若候选在某历史以外的新输入上失败，也 add 一条，使其 producer 未来不可逃避。
  - 与 EvolutionGuard 互补：guard 防"留出集退化"（量），regression_app防"已知坑复发"（质）。

接点：
  - promotion_gate 在宪法 + 留出集 + 双裁判之外，再过一遍 `suite.check_candidate`：
    任一历史坏例复发 → `check` 返回拒绝，候选不晋升。
  - kill_switch / evolution_guard 回滚后可调用 `suite.snapshot_for_guard()`，把当前
    active 坏例集合一并冻结（回滚到旧基线时旧基线已知的坑仍要防）。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KnownFailure:
    """一个已知历史坏例（不可变）。"""

    failure_id: str               # 内容指纹生成的稳定 id
    stage: str
    description: str
    payload: Mapping[str, Any]   # 触发坏例的输入/上下文（冻结只读）
    producer_id: Optional[str] = None  # 产出该坏例的候选配置 id
    added_at: str = ""           # ISO 时间戳（上层注入）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "stage": self.stage,
            "description": self.description,
            "payload": dict(self.payload),
            "producer_id": self.producer_id,
            "added_at": self.added_at,
        }


@dataclass
class RegressionVerdict:
    """候选在回归套件上的裁决。"""

    candidate_id: str
    active_cases: int
    regressed_on: List[str] = field(default_factory=list)  # 复发的坏例 id
    new_failures_added: List[str] = field(default_factory=list)  # check 中新入库的坏例 id
    passed: bool = True

    @property
    def rejected(self) -> bool:
        return not self.passed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "active_cases": self.active_cases,
            "regressed_on": list(self.regressed_on),
            "new_failures_added": list(self.new_failures_added),
            "passed": self.passed,
            "rejected": self.rejected,
        }


class RegressionSuite:
    """追加式回归套件：active 坏例不得被候选生产者复发，新失败自动入册。"""

    def __init__(self) -> None:
        # failure_id → KnownFailure（在册，无论 active/retired）
        self._failures: Dict[str, KnownFailure] = {}
        # 已退役（不再用作主动拒绝判据，但仍审计在册）
        self._retired: set[str] = set()
        # 反查：坏例 id → 产出它的 producer（便于"新失败入库后能拒绝其 producer"）
        self._producer_to_failures: Dict[str, List[str]] = {}

    # ── 属性 ───────────────────────────────────────────────────────────────
    @property
    def total_cases(self) -> int:
        return len(self._failures)

    @property
    def active_cases(self) -> int:
        return len(self._failures) - len(self._retired)

    def active_failures(self) -> Tuple[KnownFailure, ...]:
        return tuple(f for fid, f in self._failures.items() if fid not in self._retired)

    def is_known_failure(self, failure_id: str) -> bool:
        return failure_id in self._failures

    # ── 入册：追加式（不可静默删除）───────────────────────────────────────
    @staticmethod
    def _digest(stage: str, description: str, payload: Mapping[str, Any]) -> str:
        body = json.dumps(
            {"stage": stage, "description": description, "payload": dict(payload)},
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]

    def add_failure(
        self,
        stage: str,
        description: str,
        payload: Mapping[str, Any],
        producer_id: Optional[str] = None,
        added_at: str = "",
    ) -> KnownFailure:
        """追加一个历史坏例。同内容（指纹相同）入册幂等：返回已存在条目。

        追加式：只允许加，不允许删。若该坏例被误标 retired 但此处再次 add，自动"复活"
        为 active——保证已知坑不被悄悄退役绕过。
        """
        fid = self._digest(stage, description, payload)
        if fid in self._failures:
            self._retired.discard(fid)  # 复活
            if producer_id:
                self._producer_to_failures.setdefault(producer_id, [])
                if fid not in self._producer_to_failures[producer_id]:
                    self._producer_to_failures[producer_id].append(fid)
            logger.info("RegressionSuite dup-add (re-activated): %s — %s", fid, description)
            return self._failures[fid]
        case = KnownFailure(
            failure_id=fid,
            stage=stage,
            description=description,
            payload=payload,  # KnownFailure 存储（MappingProxyType 传入则天然只读）
            producer_id=producer_id,
            added_at=added_at,
        )
        self._failures[fid] = case
        if producer_id:
            self._producer_to_failures.setdefault(producer_id, []).append(fid)
        logger.info("RegressionSuite add failure: %s — %s (producer=%s)", fid, description, producer_id)
        return case

    def retire(self, failure_id: str) -> bool:
        """显式退役一个坏例（仍审计在册，但不再用作主动拒绝）。追加式不删。"""
        if failure_id not in self._failures:
            return False
        self._retired.add(failure_id)
        logger.info("RegressionSuite retire: %s", failure_id)
        return True

    def failures_by_producer(self, producer_id: str) -> Tuple[KnownFailure, ...]:
        """某 producer 历史上产出的所有坏例（DoD：新失败入库后能拒绝其 producer）。"""
        ids = self._producer_to_failures.get(producer_id, [])
        return tuple(self._failures[i] for i in ids if i in self._failures)

    # ── 候选检查：active 坏例不得复发；新失败自动入册并拒绝其 producer ───────
    def check_candidate(
        self,
        candidate_id: str,
        eval_fn: Callable[[KnownFailure], Tuple[bool, Optional[KnownFailure]]],
        auto_add_new: bool = True,
    ) -> RegressionVerdict:
        """跑候选在所有 active 坏例上的判定。

        eval_fn(case) -> (regressed: bool, new_failure: Optional[KnownFailure])
          - regressed=True：候选使该历史坏例复发 → 拒绝候选。
          - new_failure：候选在该 case 上下文暴露了**新的**失败 → 自动入册，并标记
            candidate_id 为其 producer；后续 `failures_by_producer(candidate_id)` 即可拒绝
            该 producer 再被晋升。

        返回 RegressionVerdict；regressed_on / new_failures_added 记录明细。
        """
        regressed_on: List[str] = []
        new_added: List[str] = []
        for case in self.active_failures():
            try:
                regressed, new_failure = eval_fn(case)
            except Exception as ex:  # noqa: BLE001
                # 评估崩溃视作"未能确定无复发"→ 安全侧：保守拒绝并记新失败
                logger.warning(
                    "RegressionSuite check raised on %s (%s): %s — 保守拒绝并记新失败",
                    case.failure_id, type(ex).__name__, ex,
                )
                regressed, new_failure = True, None
                if new_failure is None:
                    new_failure = KnownFailure(
                        failure_id="",
                        stage=case.stage,
                        description=f"check_candidate raised: {ex}",
                        payload=case.payload,
                        producer_id=candidate_id,
                    )
            if regressed:
                regressed_on.append(case.failure_id)
            if new_failure is not None and auto_add_new:
                added = self.add_failure(
                    stage=new_failure.stage,
                    description=new_failure.description,
                    payload=new_failure.payload,
                    producer_id=candidate_id,
                    added_at=new_failure.added_at,
                )
                # 仅当该新失败是本次循环里**第一次**新增时记入；幂等 add 在去重后不重复计
                if added.failure_id not in new_added:
                    new_added.append(added.failure_id)
                    # 产出新失败的候选 → 自动视为拒绝其 producer（DoD 单测断言点）
                    regressed_on.append(added.failure_id)

        # 去重：同一 failure_id 在 regressed_on 中只出现一次（regress + new-add 不双计）
        seen: set[str] = set()
        dedup: List[str] = []
        for fid in regressed_on:
            if fid not in seen:
                seen.add(fid)
                dedup.append(fid)
        verdict = RegressionVerdict(
            candidate_id=candidate_id,
            active_cases=self.active_cases,
            regressed_on=dedup,
            new_failures_added=new_added,
            passed=(len(dedup) == 0),
        )
        if verdict.rejected:
            logger.warning(
                "RegressionSuite REJECT candidate %s: regressed_on=%s new=%s",
                candidate_id, verdict.regressed_on, new_added,
            )
        return verdict

    # ── 快照（供 evolution_guard 回滚时冻结已知坑集合，SSOT 登记用）────────────
    def snapshot(self) -> Dict[str, Any]:
        return {
            "total": len(self._failures),
            "active": self.active_cases,
            "retired": sorted(self._retired),
            "failures": [f.to_dict() for f in self._failures.values()],
        }


# ── 模块级单例 ───────────────────────────────────────────────────────────────
_regression_suite: Optional[RegressionSuite] = None


def get_regression_suite() -> RegressionSuite:
    """全局回归套件单例。"""
    global _regression_suite
    if _regression_suite is None:
        _regression_suite = RegressionSuite()
    return _regression_suite


def reset_regression_suite() -> None:
    """重置单例（测试用）。"""
    global _regression_suite
    _regression_suite = None
