"""HarnessDashboard：监控看板、周报生成器、审计日志 API。

提供：
1. 实时状态 API
2. 周报自动生成
3. 审计日志查询
4. 健康检查
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..harness.config import get_harness_settings
from ..harness.golden import GoldenDatasetManager
from ..harness.models import (
    AuditLog,
    AuditLogEntry,
    CanaryTest,
    FeedbackRecord,
    GoldenDatasetStats,
    GoldenSample,
    HealthCheckResponse,
    PromptVersion,
    QualityThreshold,
    RoutingWeight,
    SOPRule,
    WeeklyReportResponse,
)
from ..harness.sop_store import get_sop_store
from ..harness.storage import get_storage

logger = logging.getLogger(__name__)


class DashboardStats(BaseModel):
    """仪表盘统计快照。"""

    timestamp: str
    golden_stats: Dict[str, int]
    active_canaries: int
    pending_promotions: int
    total_feedback_unprocessed: int
    sop_rules_active: int
    prompt_versions_live: int
    quality_thresholds_active: int
    routing_weights_active: int


class HarnessDashboard:
    """Harness 仪表盘：聚合所有监控指标、生成周报、提供审计查询。"""

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
    # 实时状态
    # ──────────────────────────────────────────────────────────────────────────

    def get_status(self) -> DashboardStats:
        """获取实时仪表盘快照。"""
        from ..harness.storage import get_storage

        storage = get_storage()

        with storage.db.session() as session:
            from sqlalchemy import func, select

            from ..harness.models import (
                AuditLog,
                CanaryTest,
                FeedbackRecord,
                GoldenSample,
                PromptVersion,
                QualityThreshold,
                RoutingWeight,
                SOPRule,
            )

            # 金标统计
            golden_stats = {}
            for split in ["train", "val", "test"]:
                count = session.execute(
                    select(func.count()).select_from(GoldenSample).where(GoldenSample.split == split)
                ).scalar()
                golden_stats[split] = count or 0

            # 活跃金丝雀
            active_canaries = (
                session.execute(
                    select(func.count()).select_from(CanaryTest).where(CanaryTest.status == "running")
                ).scalar()
                or 0
            )

            # 待晋升
            pending_promotions = (
                session.execute(
                    select(func.count()).select_from(PromptVersion).where(PromptVersion.status == "candidate")
                ).scalar()
                or 0
            )

            # 未处理反馈
            total_feedback_unprocessed = (
                session.execute(
                    select(func.count()).select_from(FeedbackRecord).where(FeedbackRecord.processed.is_(False))
                ).scalar()
                or 0
            )

            # 活跃 SOP 规则
            sop_rules_active = (
                session.execute(select(func.count()).select_from(SOPRule).where(SOPRule.status == "active")).scalar()
                or 0
            )

            # 线上 Prompt 版本
            prompt_versions_live = (
                session.execute(
                    select(func.count()).select_from(PromptVersion).where(PromptVersion.status == "live")
                ).scalar()
                or 0
            )

            # 活跃质量阈值
            quality_thresholds_active = (
                session.execute(
                    select(func.count()).select_from(QualityThreshold).where(QualityThreshold.is_active.is_(True))
                ).scalar()
                or 0
            )

            # 活跃路由权重
            routing_weights_active = (
                session.execute(
                    select(func.count()).select_from(RoutingWeight).where(RoutingWeight.is_active.is_(True))
                ).scalar()
                or 0
            )

        return DashboardStats(
            timestamp=datetime.now(timezone.utc).isoformat(),
            golden_stats=golden_stats,
            active_canaries=active_canaries,
            pending_promotions=pending_promotions,
            total_feedback_unprocessed=total_feedback_unprocessed,
            sop_rules_active=sop_rules_active,
            prompt_versions_live=prompt_versions_live,
            quality_thresholds_active=quality_thresholds_active,
            routing_weights_active=routing_weights_active,
        )

    def get_health(self) -> "HealthCheckResponse":
        """健康检查。"""
        from sqlalchemy import func, select

        from ..harness.models import CanaryTest, GoldenSample, PromptVersion
        from ..harness.storage import get_storage

        storage = get_storage()
        db_healthy = storage.db.health_check()

        # 实时聚合关键计数（测试环境 DB 为空时均为 0，但结构与生产一致）。
        with storage.db.session() as session:
            golden_stats = {
                split: (
                    session.execute(
                        select(func.count()).select_from(GoldenSample).where(GoldenSample.split == split)
                    ).scalar()
                    or 0
                )
                for split in ["train", "val", "test"]
            }
            active_canaries = (
                session.execute(
                    select(func.count()).select_from(CanaryTest).where(CanaryTest.status == "running")
                ).scalar()
                or 0
            )
            pending_promotions = (
                session.execute(
                    select(func.count()).select_from(PromptVersion).where(PromptVersion.status == "candidate")
                ).scalar()
                or 0
            )

        components = {
            "database": "healthy" if db_healthy else "unhealthy",
            "storage": "healthy",
            "harness": "enabled" if self.settings.ENABLED else "disabled",
        }

        return HealthCheckResponse(
            status="healthy" if db_healthy else "degraded",
            components=components,
            golden_stats=golden_stats,
            active_canaries=active_canaries,
            pending_promotions=pending_promotions,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # 周报生成
    # ──────────────────────────────────────────────────────────────────────────

    def generate_weekly_report(self, week_start: Optional[datetime] = None) -> "WeeklyReportResponse":
        """生成周报。"""
        if week_start is None:
            # 本周一 00:00
            now = datetime.now(timezone.utc)
            week_start = now - timedelta(days=now.weekday())
            week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

        week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)

        from ..harness.storage import get_storage

        storage = get_storage()
        with storage.db.session() as session:
            from sqlalchemy import and_, func, select

            from ..harness.models import (
                AuditLog,
                CanaryTest,
                GoldenSample,
                PromptVersion,
                QualityThreshold,
                RoutingWeight,
                SOPRule,
            )

            # 迭代次数
            total_iterations = session.execute(select(func.count()).select_from(CanaryTest)).scalar() or 0

            # 晋升数
            total_promotions = (
                session.execute(
                    select(func.count()).select_from(PromptVersion).where(PromptVersion.deployed.is_(True))
                ).scalar()
                or 0
            )

            # 回滚数
            total_rollbacks = (
                session.execute(
                    select(func.count()).select_from(PromptVersion).where(PromptVersion.status == "rolled_back")
                ).scalar()
                or 0
            )

            # 新增金标样本
            week_start_ts = week_start.replace(tzinfo=None)
            week_end_ts = (week_start + timedelta(days=7)).replace(tzinfo=None)
            golden_samples_added = (
                session.execute(
                    select(func.count())
                    .select_from(GoldenSample)
                    .where(
                        GoldenSample.created_at >= week_start_ts,
                        GoldenSample.created_at <= week_end_ts,
                    )
                ).scalar()
                or 0
            )

            # 新增 SOP 规则
            sop_rules_added = (
                session.execute(
                    select(func.count())
                    .select_from(SOPRule)
                    .where(
                        SOPRule.created_at >= week_start_ts,
                        SOPRule.created_at <= week_end_ts,
                    )
                ).scalar()
                or 0
            )

            # 晋升的 Prompt
            promoted_prompts = session.execute(
                select(PromptVersion.version, PromptVersion.stage).where(
                    PromptVersion.deployed_at >= week_start_ts,
                    PromptVersion.deployed_at <= week_end_ts,
                )
            ).all()
            prompts_promoted = [{"stage": stage, "version": version} for version, stage in promoted_prompts]

            # 阈值变更
            threshold_changes = session.execute(
                select(QualityThreshold.threshold_id, QualityThreshold.value).where(
                    QualityThreshold.last_calibrated_at >= week_start_ts,
                    QualityThreshold.last_calibrated_at <= week_end_ts,
                )
            ).all()
            threshold_changes = [{"threshold_id": t.threshold_id, "value": t.value} for t in threshold_changes]

            # 路由变更
            routing_changes = session.execute(
                select(RoutingWeight.character_name, RoutingWeight.voice_id, RoutingWeight.weight).where(
                    RoutingWeight.updated_at >= week_start_ts,
                    RoutingWeight.updated_at <= week_end_ts,
                )
            ).all()
            routing_changes = [
                {"character_name": c.character_name, "voice_id": c.voice_id, "weight": c.weight}
                for c in routing_changes
            ]

            # 金标统计
            golden_stats = {}
            for split in ["train", "val", "test"]:
                count = (
                    session.execute(
                        select(func.count()).select_from(GoldenSample).where(GoldenSample.split == split)
                    ).scalar()
                    or 0
                )
                golden_stats[split] = count

            # Top patterns
            top_patterns = []  # 可扩展：统计 pattern_tags 高频项

            return WeeklyReportResponse(
                week_start=week_start.isoformat(),
                week_end=week_end.isoformat(),
                total_iterations=total_iterations,
                total_promotions=total_promotions,
                total_rollbacks=total_rollbacks,
                golden_samples_added=golden_samples_added,
                sop_rules_added=sop_rules_added,
                prompts_promoted=prompts_promoted,
                threshold_changes=threshold_changes,
                routing_changes=routing_changes,
                golden_stats=golden_stats,
                top_patterns=top_patterns,
            )

    def save_weekly_report(self, report: "WeeklyReportResponse") -> None:
        """保存周报到磁盘。"""
        report_dir = Path("data/reports/weekly")
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / f"weekly_{report.week_start[:10]}.json"
        report_file.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        logger.info(f"Weekly report saved: {report_file}")

    def get_weekly_report(self, week_start: str) -> Optional["WeeklyReportResponse"]:
        """读取已保存的周报。"""
        report_dir = Path("data/reports/weekly")
        report_file = report_dir / f"weekly_{week_start}.json"
        if not report_file.exists():
            return None
        try:
            return WeeklyReportResponse.model_validate_json(report_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to load weekly report: {e}")
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # 审计日志
    # ──────────────────────────────────────────────────────────────────────────

    def query_audit_logs(
        self,
        event_type: Optional[str] = None,
        user_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditLogEntry]:
        """查询审计日志。"""
        from ..harness.storage import get_storage

        storage = get_storage()
        with storage.db.session() as session:
            from sqlalchemy import and_, desc, select

            from ..harness.models import AuditLog

            stmt = select(AuditLog)
            if event_type:
                stmt = stmt.where(AuditLog.event_type == event_type)
            if user_id:
                stmt = stmt.where(AuditLog.user_id == user_id)
            if start_date:
                stmt = stmt.where(AuditLog.timestamp >= start_date)
            if end_date:
                stmt = stmt.where(AuditLog.timestamp <= end_date)

            stmt = stmt.order_by(desc(AuditLog.timestamp)).limit(limit).offset(offset)
            results = session.execute(stmt).scalars().all()

            return [
                AuditLogEntry(
                    id=r.id,
                    event_type=r.event_type,
                    user_id=r.user_id,
                    username=r.username,
                    ip_address=r.ip_address,
                    user_agent=r.user_agent,
                    details=r.details or {},
                    timestamp=r.timestamp,
                )
                for r in results
            ]

    # ──────────────────────────────────────────────────────────────────────────
    # 金标数据集统计
    # ──────────────────────────────────────────────────────────────────────────

    def get_golden_stats(self) -> GoldenDatasetStats:
        """获取金标数据集统计。"""
        manager = GoldenDatasetManager()
        return manager.get_stats()

    # ──────────────────────────────────────────────────────────────────────────
    # SOP 规则统计
    # ──────────────────────────────────────────────────────────────────────────

    def get_sop_stats(self) -> Dict[str, Any]:
        """获取 SOP 规则统计。"""
        store = get_sop_store()
        stats = store.get_hit_stats()
        return {
            "total_rules": len(stats),
            "active_rules": len([s for s in stats if s["status"] == "active"]),
            "archived_rules": len([s for s in stats if s["status"] == "archived"]),
            "total_hits": sum(s["hit_count"] for s in stats),
            "total_success": sum(s["success_count"] for s in stats),
            "avg_success_rate": sum(s["success_rate"] for s in stats) / max(len(stats), 1),
            "by_stage": {},
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 定时任务：生成周报
    # ──────────────────────────────────────────────────────────────────────────

    async def scheduled_weekly_report(self) -> None:
        """定时生成周报（由调度器每周调用）。"""
        if not self.settings.WEEKLY_REPORT_ENABLED:
            return

        report = self.generate_weekly_report()
        self.save_weekly_report(report)

        # 可选：发送 Webhook 通知
        if self.settings.ALERT_WEBHOOK_URL:
            try:
                import httpx

                async with httpx.AsyncClient() as client:
                    await client.post(
                        self.settings.ALERT_WEBHOOK_URL,
                        json={
                            "type": "weekly_report",
                            "week_start": report.week_start,
                            "summary": f"迭代 {report.total_iterations} 次，晋升 {report.total_promotions} 个，回滚 {report.total_rollbacks} 次",
                        },
                        timeout=10.0,
                    )
            except Exception as e:
                logger.warning(f"Failed to send weekly report webhook: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# 单例与便捷入口
# ──────────────────────────────────────────────────────────────────────────────

_dashboard: Optional["HarnessDashboard"] = None


def get_harness_dashboard() -> "HarnessDashboard":
    global _dashboard
    if _dashboard is None:
        _dashboard = HarnessDashboard()
    return _dashboard


_dashboard: Optional["HarnessDashboard"] = None


def get_harness_status() -> Dict[str, Any]:
    """获取马具迭代系统整体状态。"""
    dashboard = get_harness_dashboard()
    return dashboard.get_status().model_dump()


def get_harness_health() -> "HealthCheckResponse":
    dashboard = get_harness_dashboard()
    return dashboard.get_health()


def generate_weekly_report(week_start: Optional[datetime] = None) -> "WeeklyReportResponse":
    dashboard = get_harness_dashboard()
    report = dashboard.generate_weekly_report()
    dashboard.save_weekly_report(report)
    return report


def get_weekly_report(week_start: str) -> Optional["WeeklyReportResponse"]:
    dashboard = get_harness_dashboard()
    return dashboard.get_weekly_report(week_start)


def get_audit_logs(
    event_type: Optional[str] = None,
    user_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0,
) -> List["AuditLogEntry"]:
    dashboard = get_harness_dashboard()
    return dashboard.query_audit_logs(event_type, user_id, start_date, end_date, limit, offset)


def get_golden_stats() -> "GoldenDatasetStats":
    dashboard = get_harness_dashboard()
    return dashboard.get_golden_stats()


def get_sop_stats() -> Dict[str, Any]:
    dashboard = get_harness_dashboard()
    return dashboard.get_sop_stats()


def trigger_weekly_report() -> None:
    """手动触发周报生成（用于测试/手动触发）。"""
    import asyncio

    dashboard = get_harness_dashboard()
    asyncio.run(dashboard.scheduled_weekly_report())


__all__ = [
    "HarnessDashboard",
    "DashboardStats",
    "get_harness_dashboard",
    "get_harness_status",
    "get_harness_health",
    "generate_weekly_report",
    "get_weekly_report",
    "get_audit_logs",
    "get_golden_stats",
    "get_sop_stats",
    "trigger_weekly_report",
]
