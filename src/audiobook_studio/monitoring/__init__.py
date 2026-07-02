"""
Monitoring and Baseline Recording Package
"""

from .alert import AlertConfig, AlertLevel, AlertManager, AlertRecord, send_dingtalk_alert, send_slack_alert
from .baseline import (
    BaselineRecorder,
    GrowthMetric,
    PerformanceMetric,
    get_baseline_recorder,
    record_growth_metric,
    record_stage_performance,
)
from .compliance import (
    ComplianceMonitor,
    ComplianceRecord,
    StageComplianceSummary,
    get_compliance_monitor,
    record_pipeline_compliance,
)
from .cost_dashboard import CostBreakdown, CostDashboard, generate_cost_report
from .dashboard import MonitoringDashboard, collect_logs, compute_summary, format_dashboard
from .langfuse_client import (
    flush_langfuse,
    get_langfuse_client,
    init_langfuse,
    is_enabled,
    observe_llm_call,
    observe_quality_check,
    observe_tts_synthesis,
    score_trace,
    span,
    trace,
    trace_analyze,
    trace_annotate,
    trace_edit,
    trace_extract,
    trace_function,
    trace_quality,
    trace_synthesize,
)
from .metrics_exporter import (
    export_all_metrics,
    export_compliance_rate,
    export_contract_version,
    export_fallback_rate,
    get_metrics_for_ci,
)
from .offline_monitoring import OfflineMonitor, create_offline_monitor

__all__ = [
    "BaselineRecorder",
    "PerformanceMetric",
    "GrowthMetric",
    "get_baseline_recorder",
    "record_stage_performance",
    "record_growth_metric",
    "ComplianceMonitor",
    "ComplianceRecord",
    "StageComplianceSummary",
    "get_compliance_monitor",
    "record_pipeline_compliance",
    "export_fallback_rate",
    "export_compliance_rate",
    "export_contract_version",
    "export_all_metrics",
    "get_metrics_for_ci",
    # Langfuse
    "init_langfuse",
    "get_langfuse_client",
    "is_enabled",
    "flush_langfuse",
    "trace",
    "span",
    "observe_llm_call",
    "observe_tts_synthesis",
    "observe_quality_check",
    "trace_function",
    "trace_extract",
    "trace_analyze",
    "trace_annotate",
    "trace_edit",
    "trace_synthesize",
    "trace_quality",
    "score_trace",
    # Alerting
    "AlertLevel",
    "AlertConfig",
    "AlertRecord",
    "AlertManager",
    "send_dingtalk_alert",
    "send_slack_alert",
    # Cost Dashboard
    "CostDashboard",
    "CostBreakdown",
    "generate_cost_report",
    # Offline Monitoring
    "OfflineMonitor",
    "create_offline_monitor",
    # Dashboard
    "MonitoringDashboard",
    "collect_logs",
    "compute_summary",
    "format_dashboard",
]
