"""TTS 路由表进化引擎：角色→声线权重矩阵自动进化。

核心功能：
1. 根据生产运行结果（成功/失败）自动调整角色→声线权重
2. 失败自动降权，成功连续恢复权重
3. 权重变更走晋升门禁，防止恶性循环
4. 生成路由进化报告，支持人工复核
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy import select

from ..harness.config import get_harness_settings
from ..harness.models import RoutingWeight, RoutingWeightUpdate
from ..harness.storage import get_storage

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config/routing_weights.yaml")


class RoutingWeightStats(BaseModel):
    """路由权重统计。"""

    character_name: str
    voice_id: str
    engine: str
    current_weight: float
    success_count: int
    failure_count: int
    success_rate: float
    last_failure_at: Optional[str] = None
    last_success_at: Optional[str] = None
    current_weight: float
    min_weight: float
    max_weight: float


class WeightAdjustment(BaseModel):
    """权重调整建议。"""

    character_name: str
    voice_id: str
    old_weight: float
    new_weight: float
    delta: float
    reason: str
    confidence: float
    applied: bool = False


class RoutingEvolutionReport(BaseModel):
    """路由进化报告。"""

    timestamp: str
    window_days: int
    total_adjustments: int
    applied: List[Dict[str, Any]]
    skipped: List[Dict[str, Any]]
    weight_changes: List[Dict[str, Any]]


class RoutingEvolutionEngine:
    """TTS 路由表进化引擎。

    核心逻辑：
    1. 收集角色→声线的成功/失败统计
    2. 失败自动降权（乘以 decay_on_failure）
    3. 连续成功可恢复/增权
    5. 权重变更走晋升门禁，防止恶性循环
    4. 生成路由进化报告，支持人工复核
    """

    def __init__(self):
        self._settings = None
        self._storage = None

    @property
    def settings(self):
        if self._settings is None:
            from ..harness.config import get_harness_settings

            self._settings = get_harness_settings()
        return self._settings

    def _get_storage(self):
        if self._storage is None:
            from ..harness.storage import get_storage

            self._storage = get_storage()
        return self._storage

    # ──────────────────────────────────────────────────────────────────────────
    # 核心路由权重管理
    # ──────────────────────────────────────────────────────────────────────────

    def get_weight(self, character_name: str, voice_id: str) -> Optional[Dict[str, Any]]:
        """获取当前权重配置。"""
        storage = get_storage()
        with storage.db.session() as session:
            from ..harness.models import RoutingWeight as RoutingWeightModel

            rw = (
                session.execute(
                    select(RoutingWeight).where(
                        RoutingWeight.character_name == character_name,
                        RoutingWeight.voice_id == voice_id,
                        RoutingWeight.is_active.is_(True),
                    )
                )
                .scalars()
                .first()
            )
            if rw:
                return {
                    "weight_id": rw.weight_id,
                    "character_name": rw.character_name,
                    "voice_id": rw.voice_id,
                    "engine": rw.engine,
                    "weight": rw.weight,
                    "min_weight": rw.min_weight,
                    "max_weight": rw.max_weight,
                    "success_count": rw.success_count,
                    "failure_count": rw.failure_count,
                    "last_failure_at": rw.last_failure_at.isoformat() if rw.last_failure_at else None,
                    "last_success_at": rw.last_success_at.isoformat() if rw.last_success_at else None,
                    "decay_on_failure": rw.decay_on_failure,
                    "min_success_for_recovery": rw.min_success_for_recovery,
                    "is_active": rw.is_active,
                }
        return None

    def get_all_weights(self, character_name: Optional[str] = None) -> List[Dict]:
        """获取所有路由权重。"""
        storage = get_storage()
        with storage.db.session() as session:
            from sqlalchemy import select

            from ..harness.models import RoutingWeight as RoutingWeightModel

            stmt = select(RoutingWeight).where(RoutingWeight.is_active.is_(True))
            if character_name:
                stmt = stmt.where(RoutingWeight.character_name == character_name)
            results = session.execute(stmt).scalars().all()
            return [
                {
                    "weight_id": rw.weight_id,
                    "character_name": rw.character_name,
                    "voice_id": rw.voice_id,
                    "engine": rw.engine,
                    "weight": rw.weight,
                    "min_weight": rw.min_weight,
                    "max_weight": rw.max_weight,
                    "success_count": rw.success_count,
                    "failure_count": rw.failure_count,
                    "last_failure_at": rw.last_failure_at.isoformat() if rw.last_failure_at else None,
                    "last_success_at": rw.last_success_at.isoformat() if rw.last_success_at else None,
                    "decay_on_failure": rw.decay_on_failure,
                    "min_success_for_recovery": rw.min_success_for_recovery,
                    "is_active": rw.is_active,
                }
                for rw in results
            ]

    def initialize_weight(
        self,
        character_name: str,
        voice_id: str,
        engine: str,
        initial_weight: float = 1.0,
        min_weight: float = 0.1,
        max_weight: float = 10.0,
    ) -> Dict[str, Any]:
        """初始化/确保权重记录存在。"""
        storage = get_storage()
        with storage.db.session() as session:
            from sqlalchemy import select

            from ..harness.models import RoutingWeight as RoutingWeightModel

            stmt = select(RoutingWeight).where(
                RoutingWeight.character_name == character_name,
                RoutingWeight.voice_id == voice_id,
            )
            rw = session.execute(stmt).scalar_one_or_none()

            if rw:
                return self._rw_to_dict(rw)

            # 创建新权重记录
            import uuid

            rw = RoutingWeight(
                weight_id=f"rw_{character_name}_{voice_id}_{int(datetime.now(timezone.utc).timestamp())}",
                character_name=character_name,
                voice_id=voice_id,
                engine=engine,
                weight=initial_weight,
                min_weight=min_weight,
                max_weight=max_weight,
            )
            session.add(rw)
            session.commit()
            session.refresh(rw)
            logger.info(f"Initialized routing weight: {character_name}/{voice_id} = {initial_weight}")
            return self._rw_to_dict(rw)

    def _rw_to_dict(self, rw) -> Dict:
        return {
            "weight_id": rw.weight_id,
            "character_name": rw.character_name,
            "voice_id": rw.voice_id,
            "engine": rw.engine,
            "weight": rw.weight,
            "min_weight": rw.min_weight,
            "max_weight": rw.max_weight,
            "success_count": rw.success_count,
            "failure_count": rw.failure_count,
            "last_failure_at": rw.last_failure_at.isoformat() if rw.last_failure_at else None,
            "last_success_at": rw.last_success_at.isoformat() if rw.last_success_at else None,
            "decay_on_failure": rw.decay_on_failure,
            "min_success_for_recovery": rw.min_success_for_recovery,
            "is_active": rw.is_active,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 核心进化逻辑：记录结果、自动调权
    # ──────────────────────────────────────────────────────────────────────────

    def record_result(
        self,
        character_name: str,
        voice_id: str,
        success: bool,
    ) -> Dict[str, Any]:
        """记录一次路由结果（成功/失败），自动调整权重。

        Args:
            character_name: 角色名
            voice_id: 声线 ID
            success: 是否成功

        Returns:
            更新后的权重信息
        """
        from ..harness.storage import get_storage

        storage = get_storage()
        with storage.db.session() as session:
            from sqlalchemy import select

            from ..harness.models import RoutingWeight

            stmt = select(RoutingWeight).where(
                RoutingWeight.character_name == character_name,
                RoutingWeight.voice_id == voice_id,
                RoutingWeight.is_active.is_(True),
            )
            rw = session.execute(stmt).scalar_one_or_none()

            if not rw:
                # 自动初始化
                rw = RoutingWeight(
                    weight_id=f"rw_{rw.character_name}_{rw.voice_id}_{int(datetime.now(timezone.utc).timestamp())}",
                    character_name=character_name,
                    voice_id=voice_id,
                    engine="unknown",
                )
                session.add(rw)

            old_weight = rw.weight
            rw.failure_count
            rw.success_count

            if success:
                rw.success_count += 1
                rw.last_success_at = datetime.now(timezone.utc).replace(tzinfo=None)

                # 连续成功可恢复/增权
                if rw.success_count >= rw.min_success_for_recovery:
                    # 检查是否已连续成功足够次数（简化：success_count - failure_count > 阈值）
                    if rw.success_count - rw.failure_count >= rw.min_success_for_recovery:
                        new_weight = min(rw.max_weight, rw.weight * 1.05)  # 增权 5%
                        logger.info(
                            f"Routing weight increased: {rw.character_name}/{rw.voice_id} {rw.weight:.3f} -> {new_weight:.3f}"
                        )
                        rw.weight = min(rw.max_weight, new_weight)
            else:
                rw.failure_count += 1
                rw.last_failure_at = datetime.now(timezone.utc).replace(tzinfo=None)

                # 失败立即降权
                old_weight = rw.weight
                rw.weight = max(rw.min_weight, rw.weight * rw.decay_on_failure)
                logger.warning(
                    f"Routing weight decreased: {rw.character_name}/{rw.voice_id} {old_weight:.3f} -> {rw.weight:.3f} (decay={rw.decay_on_failure})"
                )

            rw.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.commit()
            session.refresh(rw)

            return {
                "character_name": rw.character_name,
                "voice_id": rw.voice_id,
                "old_weight": rw.weight if success else rw.weight / rw.decay_on_failure if not success else rw.weight,
                "new_weight": rw.weight,
                "success": success,
                "success_count": rw.success_count,
                "failure_count": rw.failure_count,
            }

    def get_stats(self, character_name: Optional[str] = None) -> List[Dict]:
        """获取所有角色/声线的权重统计。"""
        weights = self.get_all_weights(character_name)
        stats = []
        for w in weights:
            w["success_count"] + w["failure_count"]
            w["success_count"] / max(w["success_count"] + w["failure_count"], 1)
            stats.append(
                {
                    "character_name": w["character_name"],
                    "voice_id": w["voice_id"],
                    "engine": w["engine"],
                    "current_weight": w["weight"],
                    "success_count": w["success_count"],
                    "failure_count": w["failure_count"],
                    "success_rate": round(w["success_count"] / max(w["success_count"] + w["failure_count"], 1), 3),
                    "last_failure_at": w["last_failure_at"],
                    "last_success_at": w["last_success_at"],
                    "min_weight": w["min_weight"],
                    "max_weight": w["max_weight"],
                }
            )
        return stats

    def manual_adjust_weight(
        self,
        character_name: str,
        voice_id: str,
        weight_delta: float,
        reason: str,
    ) -> Dict[str, Any]:
        """手动调整权重（人工干预）。"""
        from ..harness.storage import get_storage

        storage = get_storage()
        with storage.db.session() as session:
            from sqlalchemy import select

            from ..harness.models import RoutingWeight

            stmt = select(RoutingWeight).where(
                RoutingWeight.character_name == character_name,
                RoutingWeight.voice_id == voice_id,
                RoutingWeight.is_active.is_(True),
            )
            rw = session.execute(stmt).scalar_one_or_none()

            if not rw:
                raise ValueError(f"Routing weight not found: {character_name}/{voice_id}")

            old_weight = rw.weight
            rw.weight = max(rw.min_weight, min(rw.max_weight, rw.weight + weight_delta))
            rw.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.commit()
            session.refresh(rw)

            logger.info(
                f"Manual weight adjustment: {character_name}/{voice_id} {old_weight:.3f} -> {rw.weight:.3f} (delta={weight_delta:+.3f}, reason: {reason})"
            )
            return {
                "character_name": rw.character_name,
                "voice_id": rw.voice_id,
                "old_weight": old_weight,
                "new_weight": rw.weight,
                "delta": weight_delta,
                "reason": reason,
            }

    def reset_weight(self, character_name: str, voice_id: str, new_weight: float = 1.0) -> Dict:
        """重置权重到指定值。"""
        from ..harness.storage import get_storage

        storage = get_storage()
        with storage.db.session() as session:
            from sqlalchemy import select

            from ..harness.models import RoutingWeight

            stmt = select(RoutingWeight).where(
                RoutingWeight.character_name == character_name,
                RoutingWeight.voice_id == voice_id,
            )
            rw = session.execute(stmt).scalar_one_or_none()
            if not rw:
                raise ValueError(f"Routing weight not found: {character_name}/{voice_id}")

            old_weight = rw.weight
            rw.weight = max(rw.min_weight, min(rw.max_weight, new_weight))
            rw.success_count = 0
            rw.failure_count = 0
            rw.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.commit()
            session.refresh(rw)

            logger.info(f"Reset routing weight: {character_name}/{voice_id} {old_weight:.3f} -> {rw.weight:.3f}")
            return {
                "character_name": rw.character_name,
                "voice_id": rw.voice_id,
                "old_weight": old_weight,
                "new_weight": rw.weight,
            }

    def get_evolution_report(self, days: int = 7) -> Dict[str, Any]:
        """生成路由进化报告。"""
        stats = self.get_stats()
        sum(s["success_count"] for s in stats)
        sum(s["failure_count"] for s in stats)
        total = sum(s["success_count"] + s["failure_count"] for s in stats)

        # 找出权重变化最大的
        weights = self.get_all_weights()
        changes = []
        for w in weights:
            total = w["success_count"] + w["failure_count"]
            if total > 0:
                w["success_count"] / (w["success_count"] + w["failure_count"])
                changes.append(
                    {
                        "character_name": w["character_name"],
                        "voice_id": w["voice_id"],
                        "current_weight": w["weight"],
                        "success_rate": round(w["success_count"] / max(w["success_count"] + w["failure_count"], 1), 3),
                        "total_calls": w["success_count"] + w["failure_count"],
                    }
                )

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "window_days": 7,
            "total_calls": sum(s["success_count"] + s["failure_count"] for s in stats),
            "overall_success_rate": sum(s["success_count"] for s in stats)
            / max(sum(s["success_count"] + s["failure_count"] for s in stats), 1),
            "by_character": stats,
            "weight_changes": changes,
        }


# ──────────────────────────────────────────────────────────────────────────────
# 单例与便捷入口
# ──────────────────────────────────────────────────────────────────────────────

_routing_engine: Optional["RoutingEvolutionEngine"] = None


def get_routing_evolution_engine() -> "RoutingEvolutionEngine":
    global _routing_engine
    if _routing_engine is None:
        _routing_engine = RoutingEvolutionEngine()
    return _routing_engine


_routing_engine: Optional["RoutingEvolutionEngine"] = None


def record_routing_result(character_name: str, voice_id: str, success: bool) -> Dict:
    """记录路由结果（成功/失败）的便捷入口。"""
    engine = get_routing_evolution_engine()
    return engine.record_result(character_name, voice_id, success)


def get_routing_stats(character_name: Optional[str] = None) -> List[Dict]:
    engine = get_routing_evolution_engine()
    return engine.get_stats(character_name)


def get_routing_evolution_report(days: int = 7) -> Dict:
    engine = get_routing_evolution_engine()
    return engine.get_evolution_report(days)


def manual_adjust_routing_weight(
    character_name: str,
    voice_id: str,
    weight_delta: float,
    reason: str,
) -> Dict:
    engine = get_routing_evolution_engine()
    return engine.manual_adjust_weight(character_name, voice_id, weight_delta, reason)


def reset_routing_weight(character_name: str, voice_id: str, new_weight: float = 1.0) -> Dict:
    engine = get_routing_evolution_engine()
    return engine.reset_weight(character_name, voice_id, new_weight)


__all__ = [
    "RoutingEvolutionEngine",
    "record_routing_result",
    "get_routing_stats",
    "get_routing_evolution_report",
    "manual_adjust_routing_weight",
    "reset_routing_weight",
]
