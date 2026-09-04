"""P0.3.5 — 进化守卫（Evolution Guard）：kill-switch 升级为"回滚+剪枝"。

对应执行手册 docs/EVOLUTION_ROADMAP.md P0.3 子任务 5，解决审计 §6.2：原
`feedback/kill_switch.py` 只是"LLM 不可用 → 降级到规则"，对**进化退化**无能为力——
一个跑偏的自动驾驶会连续晋升越走越糟的配置。本模块补上"连续 2 格留出集退化 →
自动回滚到上一基线 + 剪枝被回滚节点的后代"。

设计原则（红线 #1 主路径真实性）：
  - 配置历史是只追加的线性流水（baseline 节点链），每个晋升 append 一条；回滚**不删
    历史**，只是把 active 指针移回上一基线，并标记被回滚分支 pruned（可审计、可复盘）。
  - 留出集退化用 P0.3.1 `HeldOutDataset.evaluate_candidate` 的 `mean_score` 判定：连续
    `regression_streak`（默认 2）次 active 之后的候选 mean_score < active.mean_score
    即记一记退化；达到阈值触发 `_rollback_and_prune()`。
  - 这一格的"好坏"必须基于**留出集实跑真值**（promotion_gate 注入），不接受 mock。
  - 不持久化文件（SSOT red line #3）：状态在进程内 + 通过 `to_snapshot()`/`from_snapshot()`
    供上层在 docs/PROJECT.md 或状态库登记；本模块不擅自写 docs。

接点：
  - promotion_gate 在每次评估后 `guard.record(promotion)`：成功晋升则 append 节点，
    失败但跑出留出集分则参与退化计数。
  - kill_switch 现有 DegradationLevel（LLM 健康降级）与本 guard（进化退化）**正交**：
    LLM 健康降级经 `get_kill_switch()`，进化退化经 `get_evolution_guard()`，互不混淆。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PromNode:
    """晋升历史节点（不可变）。append-only DAG 的一个顶点。"""

    node_id: str  # 配置版本标识，如 "edit_for_tts:prom-7"
    parent_id: Optional[str]  # 父节点 id（根为 None）
    stage: str
    held_out_mean: float  # 该配置在留出集上的 mean_score（真值）
    effect_size: float  # 相对父节点的 effect_size
    promoted_at: str  # ISO 时间戳（由上层注入，避免 Date.now 依赖）
    config_digest: str  # 配置内容指纹（CI 元门禁可比对）


@dataclass
class RollbackResult:
    """回滚操作结果。"""

    rolled_back_from: str
    rolled_back_to: str
    pruned_node_ids: List[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rolled_back_from": self.rolled_back_from,
            "rolled_back_to": self.rolled_back_to,
            "pruned_node_ids": list(self.pruned_node_ids),
            "reason": self.reason,
        }


class EvolutionGuard:
    """升级版 kill-switch：连续退化自动回滚 + 剪枝被回滚分支后代。"""

    def __init__(
        self,
        regression_streak: int = 2,
        min_effect_to_promote: float = 0.25,
    ) -> None:
        # 节点链：node_id → PromNode（只追加，不删）
        self._nodes: Dict[str, PromNode] = {}
        # 子→父；用于剪枝后代
        self._children: Dict[str, List[str]] = {}
        # 被剪枝的节点 id 集合（保留在 _nodes 供审计，但不再可晋升）
        self._pruned: set[str] = set()
        # 当前生效基线指针
        self._active_id: Optional[str] = None
        # 根节点 id（第一个无父的节点）
        self._root_id: Optional[str] = None
        # 连续退化计数
        self._regression_streak: int = 0
        self._streak_limit: int = max(1, int(regression_streak))
        self._min_effect: float = float(min_effect_to_promote)
        # 最近一次回滚
        self._last_rollback: Optional[RollbackResult] = None

    # ── 属性 ───────────────────────────────────────────────────────────────
    @property
    def active_id(self) -> Optional[str]:
        return self._active_id

    @property
    def active_node(self) -> Optional[PromNode]:
        return self._nodes.get(self._active_id) if self._active_id else None

    @property
    def root_id(self) -> Optional[str]:
        return self._root_id

    @property
    def last_rollback(self) -> Optional[RollbackResult]:
        return self._last_rollback

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def pruned_ids(self) -> Tuple[str, ...]:
        return tuple(self._pruned)

    @property
    def regression_streak(self) -> int:
        return self._regression_streak

    # ── 核心：记录一次评估/晋升 ─────────────────────────────────────────────
    def record(
        self,
        node_id: str,
        stage: str,
        held_out_mean: float,
        effect_size: float,
        promoted_at: str,
        config_digest: str = "",
        treat_as_regression_on_drop: bool = True,
    ) -> Optional[RollbackResult]:
        """记录一次留出集评估结果。

        - 若 effect_size >= min_effect：append 为 active 的子节点，移 active 指针，重置退化计数。
        - 若候选 mean 低于 active（退化）： increments regression_streak；
          达 `regression_streak`（默认2）次 → 触发回滚+剪枝，返回 RollbackResult。
          该候选**不 append 为节点**（它没晋升），但其退化已计入计数。
        """
        parent = self.active_node
        parent_id = parent.node_id if parent else None
        parent_mean = parent.held_out_mean if parent else held_out_mean

        # 退化判定：候选真值低于当前 active 且未达最小效应量晋升门槛
        is_regression = treat_as_regression_on_drop and (
            held_out_mean < parent_mean - 1e-9 and effect_size < self._min_effect
        )

        if is_regression:
            self._regression_streak += 1
            logger.warning(
                "EvolutionGuard regression #%d/%d: candidate mean %.3f < active %.3f (effect %.3f)",
                self._regression_streak,
                self._streak_limit,
                held_out_mean,
                parent_mean,
                effect_size,
            )
            if self._regression_streak >= self._streak_limit:
                result = self._rollback_and_prune(
                    reason=f"连续 {self._regression_streak} 格留出集退化，自动回滚基线+剪枝后代"
                )
                self._regression_streak = 0
                self._last_rollback = result
                return result
            return None

        # 晋升：append 节点
        node = PromNode(
            node_id=node_id,
            parent_id=parent_id,
            stage=stage,
            held_out_mean=float(held_out_mean),
            effect_size=float(effect_size),
            promoted_at=promoted_at,
            config_digest=config_digest,
        )
        self._nodes[node_id] = node
        if parent_id is not None:
            self._children.setdefault(parent_id, []).append(node_id)
        if self._root_id is None:
            self._root_id = node_id
        self._active_id = node_id
        # 一次成功晋升重置退化计数
        self._regression_streak = 0
        logger.info(
            "EvolutionGuard promoted: %s (stage=%s mean=%.3f effect=%.3f parent=%s)",
            node_id,
            stage,
            held_out_mean,
            effect_size,
            parent_id,
        )
        return None

    # ── 回滚 + 剪枝后代 ────────────────────────────────────────────────────
    def _rollback_and_prune(self, reason: str) -> RollbackResult:
        """回滚 active 到其父节点，并把 active（含所有后代）标记为 pruned。

        历史节点不删除（只追加与标记），保证可审计。剪枝 = 把被回滚分支的所有节点
        id 移入 `_pruned` 集合，它们此后 record 不可作为 parent / active。
        """
        active = self.active_node
        if active is None:
            # 无 active：退化计数清零，无可回滚（root 都没建立）
            return RollbackResult(rolled_back_from="", rolled_back_to="", reason="no active baseline")
        pruned_ids: List[str] = self._collect_descendants(active.node_id)
        pruned_ids.append(active.node_id)
        # 回滚到父节点
        parent_id = active.parent_id
        # 把被回滚分支全部标 pruned
        for nid in pruned_ids:
            self._pruned.add(nid)
            # 从 children 索引里摘掉（不影响 _nodes 历史记录）
            p = self._nodes[nid].parent_id
            if p and p in self._children:
                self._children[p] = [c for c in self._children[p] if c != nid]
        # active 指针移回父节点；若父本身也 pruned（理论不应），回退到根
        new_active = parent_id
        if new_active is None or new_active in self._pruned:
            new_active = self._root_id if self._root_id not in self._pruned else None
        self._active_id = new_active

        result = RollbackResult(
            rolled_back_from=active.node_id,
            rolled_back_to=new_active or "",
            pruned_node_ids=pruned_ids,
            reason=reason,
        )
        logger.warning(
            "EvolutionGuard ROLLBACK: %s → %s, pruned %d descendants (%s)",
            result.rolled_back_from,
            result.rolled_back_to,
            len(pruned_ids),
            reason,
        )
        return result

    def _collect_descendants(self, node_id: str) -> List[str]:
        collected: List[str] = []
        for child in self._children.get(node_id, []):
            collected.append(child)
            collected.extend(self._collect_descendants(child))
        return collected

    # ── 可运维查询 ──────────────────────────────────────────────────────────
    def is_pruned(self, node_id: str) -> bool:
        return node_id in self._pruned

    def lineage(self) -> List[PromNode]:
        """当前 active 自根的祖先链（只含未剪枝的晋升路径，回溯只读）。"""
        chain: List[PromNode] = []
        cur = self.active_node
        seen: set[str] = set()
        while cur is not None and cur.node_id not in seen:
            seen.add(cur.node_id)
            chain.append(cur)
            cur = self._nodes.get(cur.parent_id) if cur.parent_id else None
        chain.reverse()
        return chain

    def to_snapshot(self) -> Dict[str, Any]:
        """导出当前进化状态（上层按 SSOT 登记到 docs/PROJECT.md / 状态库）。"""
        return {
            "nodes": [
                {
                    "node_id": n.node_id,
                    "parent_id": n.parent_id,
                    "stage": n.stage,
                    "held_out_mean": n.held_out_mean,
                    "effect_size": n.effect_size,
                    "promoted_at": n.promoted_at,
                    "config_digest": n.config_digest,
                    "pruned": n.node_id in self._pruned,
                }
                for n in self._nodes.values()
            ],
            "active_id": self._active_id,
            "root_id": self._root_id,
            "pruned_ids": sorted(self._pruned),
            "regression_streak": self._regression_streak,
            "last_rollback": self._last_rollback.to_dict() if self._last_rollback else None,
        }


# ── 模块级单例 ───────────────────────────────────────────────────────────────
_evolution_guard: Optional[EvolutionGuard] = None


def get_evolution_guard() -> EvolutionGuard:
    """全局进化守卫单例（与 get_kill_switch 正交：LLM健康 vs 进化退化）。"""
    global _evolution_guard
    if _evolution_guard is None:
        _evolution_guard = EvolutionGuard()
    return _evolution_guard


def reset_evolution_guard() -> None:
    """重置单例（测试用）。"""
    global _evolution_guard
    _evolution_guard = None
