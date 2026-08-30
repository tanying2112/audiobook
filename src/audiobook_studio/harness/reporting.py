"""常态化运营件：周报 / 月度 SOP 治理 / 7 天 shadow 对比。

这些都是「可自我迭代」系统的运营护栏：让闭环不只在代码里转，还要有可审计的
人工可读产出与灰度对照。所有函数均为纯读取/聚合，不修改状态，可安全周期调用。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SEVEN_DAYS_ISO = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()


def _seven_days_ago_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()


def generate_weekly_report() -> Dict[str, Any]:
    """生成最近 7 天的迭代运营周报（结构化 dict）。

    内容：金标三集规模、本周人工抽检条数、当前晋升阈值配置摘要。
    """
    from .config import get_harness_settings
    from .golden import GoldenDatasetManager
    from .spotcheck import load_spot_checks

    stats = GoldenDatasetManager().get_stats()
    since = _seven_days_ago_iso()
    spot = load_spot_checks(since=since)
    settings = get_harness_settings()
    return {
        "report": "weekly",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": 7,
        "golden_stats": {
            "train": stats.train_count,
            "val": stats.val_count,
            "test": stats.test_count,
            "total": stats.total_count,
        },
        "spotcheck_count_7d": len(spot),
        "spotcheck_avg_score_7d": (round(sum(float(r["score"]) for r in spot) / len(spot), 4) if spot else None),
        "thresholds": {
            "golden_pass_rate_min": getattr(settings, "PROMOTION_GOLDEN_PASS_RATE_MIN", None),
            "quality_ratio_min": getattr(settings, "PROMOTION_QUALITY_RATIO_MIN", None),
        },
    }


def generate_monthly_sop_report() -> Dict[str, Any]:
    """生成月度 SOP 治理报告：各状态规则数量与近期变更。"""
    from .sop_store import get_sop_store

    store = get_sop_store()
    try:
        rules = store.list_rules()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[reporting] 读取 SOP 规则失败：%s", exc)
        rules = []

    by_status: Dict[str, int] = {}
    for r in rules:
        status = getattr(r, "status", "unknown")
        key = status.value if hasattr(status, "value") else str(status)
        by_status[key] = by_status.get(key, 0) + 1
    return {
        "report": "monthly_sop",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rule_total": len(rules),
        "by_status": by_status,
    }


def seven_day_shadow(
    stage: str,
    candidate_metrics: Dict[str, float],
    baseline_metrics: Dict[str, float],
    tolerance: float = 0.05,
) -> Dict[str, Any]:
    """7 天 shadow 对照：比较候选 vs 基线在多个指标上的差异。

    ``*_metrics`` 形如 ``{"mean_score": 0.92, "pass_rate": 0.95}``。
    返回每指标的 delta 与整体是否落在容忍区间内（可用于「先 shadow 再晋升」门禁。
    """
    deltas: Dict[str, Any] = {}
    all_within = True
    for key in set(candidate_metrics) | set(baseline_metrics):
        cand = float(candidate_metrics.get(key, 0.0))
        base = float(baseline_metrics.get(key, 0.0))
        delta = round(cand - base, 4)
        within = abs(delta) <= tolerance
        all_within = all_within and within
        deltas[key] = {
            "candidate": round(cand, 4),
            "baseline": round(base, 4),
            "delta": round(delta, 4),
            "within_tolerance": within,
        }
    return {
        "stage": stage,
        "tolerance": tolerance,
        "deltas": deltas,
        "all_within_tolerance": all_within,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
