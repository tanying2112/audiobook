"""金丝雀 A/B 测试框架：Shadow 部署、流量分发、自动晋升/回滚。

核心功能：
1. Shadow 部署：候选版本在 10% 流量上运行，基线版本跑 90%
2. 实时指标收集：通过率、均值得分、错误率、延迟
3. 自动晋升/回滚：基于晋升门禁自动决策
4. 手动干预接口：暂停、回滚、调整流量
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from ..harness.config import get_harness_settings

logger = logging.getLogger(__name__)

CANARY_DIR = Path("data/canary")


class CanaryMetrics(BaseModel):
    """金丝雀指标。"""

    candidate_pass_rate: float = 0.0
    baseline_pass_rate: float = 0.0
    candidate_mean_score: float = 0.0
    baseline_mean_score: float = 0.0
    candidate_error_rate: float = 0.0
    baseline_error_rate: float = 0.0
    candidate_avg_latency_ms: float = 0.0
    baseline_avg_latency_ms: float = 0.0
    sample_count: int = 0


class CanaryConfig(BaseModel):
    """金丝雀测试配置。"""

    test_id: str
    stage: str
    candidate_version: int
    baseline_version: int
    traffic_percentage: float = 10.0
    observation_days: int = 7
    auto_promote: bool = True
    min_samples: int = 8


class CanaryState(BaseModel):
    """金丝雀运行时状态。"""

    test_id: str
    config: "CanaryConfig"
    status: str  # running/promoted/rolled_back/stopped
    metrics: "CanaryMetrics"
    created_at: str
    updated_at: str
    promoted_at: Optional[str] = None
    rolled_back_at: Optional[str] = None
    stopped_reason: Optional[str] = None


class CanaryABTest:
    """金丝雀 A/B 测试管理器。

    核心流程：
    1. 创建金丝雀测试配置
    2. 启动 Shadow 部署（流量分发）
    3. 实时收集指标
    4. 定期评估晋升门禁
    5. 自动晋升/回滚/继续观察
    """

    def __init__(self):
        self._settings = None
        self._canary_dir = Path("data/canary")
        self._lock = __import__("threading").Lock()

    @property
    def settings(self):
        if self._settings is None:
            from ..harness.config import get_harness_settings

            self._settings = get_harness_settings()
        return self._settings

    def _get_lock(self):
        return self._lock

    def _canary_file(self, test_id: str) -> Path:
        self._canary_dir.mkdir(parents=True, exist_ok=True)
        return self._canary_dir / f"{test_id}.json"

    def _load_state(self, test_id: str) -> Optional[Dict]:
        path = self._canary_file(test_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _save_state(self, state: Dict) -> None:
        self._canary_file(state["test_id"])
        tmp = Path(str(self._canary_dir / f"{state['test_id']}.tmp"))
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._canary_file(state["test_id"]))

    # ──────────────────────────────────────────────────────────────────────────
    # 核心 API
    # ──────────────────────────────────────────────────────────────────────────

    def create_canary(
        self,
        stage: str,
        candidate_version: int,
        baseline_version: int,
        traffic_percentage: float = 10.0,
        observation_days: int = 7,
        auto_promote: bool = True,
        min_samples: int = 8,
    ) -> Dict[str, Any]:
        """创建金丝雀测试。"""
        with self._lock:
            test_id = f"canary_{stage}_{candidate_version}_{int(datetime.now(timezone.utc).timestamp())}"
            config = CanaryConfig(
                test_id=test_id,
                stage=stage,
                candidate_version=candidate_version,
                baseline_version=baseline_version,
                traffic_percentage=traffic_percentage,
                observation_days=observation_days,
                auto_promote=auto_promote,
                min_samples=min_samples,
            )

            state = {
                "test_id": test_id,
                "config": config.model_dump(),
                "status": "running",
                "metrics": {
                    "candidate_pass_rate": 0.0,
                    "baseline_pass_rate": 0.0,
                    "candidate_mean_score": 0.0,
                    "baseline_mean_score": 0.0,
                    "candidate_error_rate": 0.0,
                    "baseline_error_rate": 0.0,
                    "candidate_avg_latency_ms": 0.0,
                    "baseline_avg_latency_ms": 0.0,
                    "sample_count": 0,
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            self._save_state(state)
            logger.info(f"Created canary test: {test_id} (stage={stage}, v{candidate_version} vs v{baseline_version})")
            return {"test_id": test_id, "status": "running"}

    def get_canary(self, test_id: str) -> Optional[Dict]:
        """获取金丝雀状态。"""
        return self._load_state(test_id)

    def list_canaries(self, status: Optional[str] = None, stage: Optional[str] = None) -> List[Dict]:
        """列出所有金丝雀测试。"""
        if not self._canary_dir.exists():
            return []

        canaries = []
        for path in self._canary_dir.glob("*.json"):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                if stage and state["config"]["stage"] != stage:
                    continue
                if status and state["status"] != status:
                    continue
                canaries.append(
                    {
                        "test_id": state["test_id"],
                        "stage": state["config"]["stage"],
                        "candidate_version": state["config"]["candidate_version"],
                        "baseline_version": state["config"]["baseline_version"],
                        "status": state["status"],
                        "traffic_percentage": state["config"]["traffic_percentage"],
                        "created_at": state["created_at"],
                        "metrics": state["metrics"],
                    }
                )
            except (json.JSONDecodeError, OSError):
                continue
        return canaries

    def record_metrics(
        self,
        test_id: str,
        is_candidate: bool,
        passed: bool,
        score: float,
        latency_ms: float,
    ) -> bool:
        """记录一次请求的指标（候选或基线）。"""
        with self._lock:
            state = self._load_state(test_id)
            if not state or state["status"] != "running":
                return False

            m = state["metrics"]
            if is_candidate:
                m["sample_count"] += 1
                if passed:
                    m["candidate_pass_rate"] = (m["candidate_pass_rate"] * (m["sample_count"] - 1) + 1) / m[
                        "sample_count"
                    ]
                else:
                    m["candidate_pass_rate"] = (m["candidate_pass_rate"] * (m["sample_count"] - 1)) / m["sample_count"]
                m["candidate_mean_score"] = (m["candidate_mean_score"] * (m["sample_count"] - 1) + score) / m[
                    "sample_count"
                ]
                m["candidate_error_rate"] = 1 - m["candidate_pass_rate"]
            else:
                m["sample_count"] += 1
                if passed:
                    m["baseline_pass_rate"] = (m["baseline_pass_rate"] * (m["sample_count"] - 1) + 1) / m[
                        "sample_count"
                    ]
                else:
                    m["baseline_pass_rate"] = (m["baseline_pass_rate"] * (m["sample_count"] - 1)) / m["sample_count"]
                m["baseline_mean_score"] = (m["baseline_mean_score"] * (m["sample_count"] - 1) + score) / m[
                    "sample_count"
                ]
                m["baseline_error_rate"] = 1 - m["baseline_pass_rate"]

            state["metrics"] = m
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_state(state)
            return True

    def evaluate(self, test_id: str) -> Dict[str, Any]:
        """评估金丝雀测试是否满足晋升门禁。"""
        state = self._load_state(test_id)
        if not state or state["status"] != "running":
            return {"action": "invalid", "reason": "测试不存在或未运行"}

        config = state["config"]
        metrics = state["metrics"]

        # 检查最小样本数
        if metrics["sample_count"] < config["min_samples"]:
            return {"action": "continue", "reason": f"样本数不足 ({metrics['sample_count']} < {config['min_samples']})"}

        # 晋升门禁检查
        settings = get_harness_settings()
        criteria = []

        # 1. 金标通过率
        if state["metrics"]["candidate_pass_rate"] < settings.PROMOTION_GOLDEN_PASS_RATE_MIN:
            criteria.append(
                f"金标通过率 {state['metrics']['candidate_pass_rate']:.2%} < {settings.PROMOTION_GOLDEN_PASS_RATE_MIN:.0%}"
            )

        # 2. 质量比基线
        quality_ratio = state["metrics"]["candidate_mean_score"] / max(state["metrics"]["baseline_mean_score"], 1e-6)
        if quality_ratio < settings.PROMOTION_QUALITY_RATIO_MIN:
            criteria.append(f"质量比 {quality_ratio:.2f} < {settings.PROMOTION_QUALITY_RATIO_MIN}")

        # 3. 格式合规
        format_compliance_rate = self._check_format_compliance(test_id)
        if format_compliance_rate < settings.PROMOTION_FORMAT_COMPLIANCE_MIN:
            criteria.append(f"格式合规率 {format_compliance_rate:.2%} < {settings.PROMOTION_FORMAT_COMPLIANCE_MIN:.0%}")

        # 4. 人工偏好
        human_preference = self._get_human_preference(test_id)
        if human_preference < settings.PROMOTION_HUMAN_PREFERENCE_MIN:
            criteria.append(f"人工偏好 {human_preference:.2f} < {settings.PROMOTION_HUMAN_PREFERENCE_MIN:.0%}")

        # 最小样本数
        if state["metrics"]["sample_count"] < settings.PROMOTION_MIN_SAMPLES:
            criteria.append(f"样本数 {state['metrics']['sample_count']} < {settings.PROMOTION_MIN_SAMPLES}")

        if criteria:
            action = "rollback"
            reason = "; ".join(criteria)
        else:
            action = "promote"
            reason = "所有门禁通过"

        return {
            "action": action,
            "reason": reason,
            "criteria": criteria,
            "metrics": state["metrics"],
        }

    def _check_format_compliance(self, test_id: str) -> float:
        """检查候选 prompt 的格式合规率（简化实现：检查 Jinja2 语法）。"""
        state = self._load_state(test_id)
        if not state:
            return 1.0
        try:
            from ..feedback.prompt_compiler import load_prompt

            prompt_content = load_prompt(state["config"]["stage"], state["config"]["candidate_version"])
            if not prompt_content:
                return 0.0
            # 简单检查：Jinja2 语法完整性
            opens = prompt_content.count("{{")
            closes = prompt_content.count("}}")
            block_opens = prompt_content.count("{%")
            block_closes = prompt_content.count("%}")
            if opens != closes or block_opens != block_closes:
                return 0.0
            return 1.0
        except Exception:
            return 0.5

    def _get_human_preference(self, test_id: str) -> float:
        """获取人工偏好评分（简化实现：从人工评分表查询，暂返回 1.0）。"""
        # TODO: 接入人工评分系统
        return 1.0

    def promote(self, test_id: str) -> bool:
        """手动晋升金丝雀。"""
        with self._lock:
            state = self._load_state(test_id)
            if not state or state["status"] != "running":
                return False

            state["status"] = "promoted"
            state["promoted_at"] = datetime.now(timezone.utc).isoformat()
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_state(state)
            logger.info(f"Canary promoted: {test_id}")
            return True

    def rollback(self, test_id: str, reason: str = "Manual rollback") -> bool:
        """手动回滚金丝雀。"""
        with self._lock:
            state = self._load_state(test_id)
            if not state or state["status"] != "running":
                return False

            state["status"] = "rolled_back"
            state["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
            state["stopped_reason"] = reason
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_state(state)
            logger.info(f"Canary rolled back: {test_id}, reason: {reason}")
            return True

    def pause(self, test_id: str, reason: str = "Paused by user") -> bool:
        """暂停金丝雀测试。"""
        with self._lock:
            state = self._load_state(test_id)
            if not state or state["status"] != "running":
                return False

            state["status"] = "paused"
            state["stopped_reason"] = reason
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_state(state)
            return True

    def resume(self, test_id: str) -> bool:
        """恢复金丝雀测试。"""
        with self._lock:
            state = self._load_state(test_id)
            if not state or state["status"] != "paused":
                return False

            state["status"] = "running"
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_state(state)
            return True

    def stop(self, test_id: str, reason: str = "Stopped by user") -> bool:
        """停止金丝雀测试（不回滚）。"""
        with self._lock:
            state = self._load_state(test_id)
            if not state or state["status"] not in ("running", "paused"):
                return False

            state["status"] = "stopped"
            state["stopped_reason"] = reason
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_state(state)
            return True

    def adjust_traffic(self, test_id: str, new_percentage: float) -> bool:
        """调整流量百分比。"""
        if not 0 <= new_percentage <= 100:
            return False

        with self._lock:
            state = self._load_state(test_id)
            if not state or state["status"] != "running":
                return False

            state["config"]["traffic_percentage"] = new_percentage
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_state(state)
            return True

    def get_status(self, test_id: str) -> Optional[Dict]:
        """获取金丝雀详细状态。"""
        state = self._load_state(test_id)
        if not state:
            return None

        config = state["config"]
        metrics = state["metrics"]

        return {
            "test_id": state["test_id"],
            "config": config,
            "status": state["status"],
            "metrics": metrics,
            "created_at": state["created_at"],
            "updated_at": state["updated_at"],
            "promoted_at": state.get("promoted_at"),
            "rolled_back_at": state.get("rolled_back_at"),
            "stopped_reason": state.get("stopped_reason"),
        }

    def cleanup_old_canaries(self, days: int = 30) -> int:
        """清理旧的金丝雀测试记录。"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        removed = 0
        if not self._canary_dir.exists():
            return 0

        for path in self._canary_dir.glob("*.json"):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                created = datetime.fromisoformat(state["created_at"].replace("Z", "+00:00"))
                if created < cutoff and state["status"] in ("promoted", "rolled_back", "stopped"):
                    path.unlink()
                    removed += 1
            except (json.JSONDecodeError, OSError, KeyError):
                continue

        logger.info(f"Cleaned up {removed} old canary records")
        return removed


# ──────────────────────────────────────────────────────────────────────────────
# 单例与便捷入口
# ──────────────────────────────────────────────────────────────────────────────

_canary_abtest: Optional["CanaryABTest"] = None


def get_canary_abtest() -> "CanaryABTest":
    global _canary_abtest
    if _canary_abtest is None:
        _canary_abtest = CanaryABTest()
    return _canary_abtest


_canary_abtest: Optional["CanaryABTest"] = None


def create_canary(
    stage: str,
    candidate_version: int,
    baseline_version: int,
    traffic_percentage: float = 10.0,
    observation_days: int = 7,
    auto_promote: bool = True,
) -> Dict:
    """创建金丝雀测试的便捷入口。"""
    return get_canary_abtest().create_canary(
        stage=stage,
        candidate_version=candidate_version,
        baseline_version=baseline_version,
        traffic_percentage=traffic_percentage,
        observation_days=observation_days,
        auto_promote=True,
    )


def get_canary(test_id: str) -> Optional[Dict]:
    return get_canary_abtest().get_canary(test_id)


def list_canaries(status: Optional[str] = None, stage: Optional[str] = None) -> List[Dict]:
    return get_canary_abtest().list_canaries(status, stage)


def record_canary_metrics(
    test_id: str,
    is_candidate: bool,
    passed: bool,
    score: float,
    latency_ms: float,
) -> bool:
    return get_canary_abtest().record_metrics(test_id, is_candidate, passed, score, latency_ms)


def evaluate_canary(test_id: str) -> Dict:
    return get_canary_abtest().evaluate(test_id)


def promote_canary(test_id: str) -> bool:
    return get_canary_abtest().promote(test_id)


def rollback_canary(test_id: str, reason: str = "Manual rollback") -> bool:
    return get_canary_abtest().rollback(test_id, reason)


def pause_canary(test_id: str, reason: str = "Paused by user") -> bool:
    return get_canary_abtest().pause(test_id, reason)


def resume_canary(test_id: str) -> bool:
    return get_canary_abtest().resume(test_id)


def stop_canary(test_id: str, reason: str = "Stopped by user") -> bool:
    return get_canary_abtest().stop(test_id, reason)


def adjust_canary_traffic(test_id: str, percentage: float) -> bool:
    return get_canary_abtest().adjust_traffic(test_id, percentage)


def get_canary_status(test_id: str) -> Optional[Dict]:
    return get_canary_abtest().get_status(test_id)


def cleanup_old_canaries(days: int = 30) -> int:
    return get_canary_abtest().cleanup_old_canaries(days)


__all__ = [
    "CanaryABTest",
    "CanaryConfig",
    "CanaryState",
    "CanaryMetrics",
    "create_canary",
    "get_canary",
    "list_canaries",
    "record_canary_metrics",
    "evaluate_canary",
    "promote_canary",
    "rollback_canary",
    "pause_canary",
    "resume_canary",
    "stop_canary",
    "adjust_canary_traffic",
    "get_canary_status",
    "cleanup_old_canaries",
]
