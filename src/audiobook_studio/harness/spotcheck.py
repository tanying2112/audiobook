"""人工抽检（human spot-check）存储：把人工偏好评分接入晋升门禁。

现状：``feedback.deploy.promote_candidate`` 的 ``human_preference_score`` 默认 1.0 直接放行。
本模块提供可持久化的抽检评分，使 harness 在晋升时读取真实人工偏好，而非恒为满分。

存储位置使用 harness 专用前缀 ``data/harness/spotcheck.jsonl``，与 feedback 数据隔离。
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SPOTCHECK_PATH = Path("data") / "harness" / "spotcheck.jsonl"

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_spot_check(
    stage: str,
    candidate_version: int,
    score: float,
    reviewer: Optional[str] = None,
    note: Optional[str] = None,
    ts: Optional[str] = None,
    path: Path = SPOTCHECK_PATH,
) -> Dict[str, Any]:
    """记录一条人工抽检评分（score ∈ [0,1]）。返回被写入的记录。"""
    if not 0.0 <= float(score) <= 1.0:
        raise ValueError(f"spot-check score 必须在 [0,1]，收到: {score}")
    record = {
        "stage": stage,
        "candidate_version": int(candidate_version),
        "score": float(score),
        "reviewer": reviewer,
        "note": note,
        "ts": ts or _now_iso(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def load_spot_checks(
    stage: Optional[str] = None,
    since: Optional[str] = None,
    path: Path = SPOTCHECK_PATH,
) -> List[Dict[str, Any]]:
    """加载抽检记录；可按 stage / 时间（ISO 字符串）过滤。"""
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    with _lock:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if stage is not None and rec.get("stage") != stage:
                    continue
                if since is not None and rec.get("ts", "") < since:
                    continue
                records.append(rec)
    return records


def human_preference_score_for(
    stage: str,
    default: float = 1.0,
    since: Optional[str] = None,
    path: Path = SPOTCHECK_PATH,
) -> float:
    """返回某 stage 的人工偏好均分；无抽检记录时回退 ``default``（默认 1.0）。"""
    recs = load_spot_checks(stage=stage, since=since, path=path)
    if not recs:
        return float(default)
    mean = sum(float(r["score"]) for r in recs) / len(recs)
    return mean


def reset_spot_checks(path: Path = SPOTCHECK_PATH) -> None:
    """清空抽检记录（测试用）。"""
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
