"""Metrics Exporter for CI Integration.

Exports HealthProbe, CircuitBreaker, KeyPool, and Router metrics to
logs/metrics_YYYYMMDD.json for CI consumption.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..llm.circuit_breaker import CircuitBreaker
from ..llm.health_probe import HealthProbe, HealthStatus
from ..llm.key_pool import KeyPoolManager
from ..llm.router import LLMRouter
from .compliance import ComplianceMonitor, get_compliance_monitor

logger = logging.getLogger(__name__)


def _get_metrics_file_path() -> Path:
    """Get the daily metrics file path."""
    logs_dir = Path(os.getenv("AUDIOBOOK_LOGS_DIR", "./logs"))
    logs_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    return logs_dir / f"metrics_{date_str}.json"


def _read_existing_metrics(file_path: Path) -> Dict[str, Any]:
    """Read existing metrics from file if it exists."""
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read existing metrics file: {e}")
    return {}


def _write_metrics(file_path: Path, metrics: Dict[str, Any]) -> None:
    """Write metrics to file."""
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
        logger.debug(f"Metrics written to {file_path}")
    except OSError as e:
        logger.error(f"Failed to write metrics file: {e}")
        raise


def export_circuit_breaker_metrics(
    circuit_breakers: Dict[str, CircuitBreaker],
) -> Dict[str, Any]:
    """Export circuit breaker metrics for all providers."""
    return {name: cb.get_status() for name, cb in circuit_breakers.items()}


def export_health_probe_metrics(health_probe: Optional[HealthProbe]) -> Dict[str, Any]:
    """Export health probe metrics for all providers."""
    if health_probe is None:
        return {"error": "Health probe not initialized"}

    statuses = health_probe.get_all_statuses()
    return {name: status.to_dict() for name, status in statuses.items()}


def export_key_pool_metrics(key_pool: KeyPoolManager) -> Dict[str, Any]:
    """Export key pool metrics for all providers."""
    return key_pool.get_all_stats()


def export_router_metrics(router: LLMRouter) -> Dict[str, Any]:
    """Export router metrics including free tier health and cost status."""
    return {
        "free_tier_health": router.get_free_tier_health(),
        "cost_status": router.get_cost_status(),
        "stage_configs": {
            stage: {
                "models": [
                    {
                        "name": m.name,
                        "priority": m.priority,
                        "enabled": m.enabled,
                        "max_daily_cost_usd": m.max_daily_cost_usd,
                    }
                    for m in config.models
                ],
                "fallback_model": config.fallback_model,
            }
            for stage, config in router.stage_configs.items()
        },
    }


def export_fallback_rate(
    router: Optional[LLMRouter] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Export fallback rate metrics.

    Falls back to heuristic fallback rate when LLMRouter is available.
    Returns the fallback rate as a percentage.

    Args:
        router: LLMRouter instance (optional, will create if not provided)
        output_path: Custom output path (optional, defaults to logs/metrics_YYYYMMDD.json)

    Returns:
        Dict containing fallback_rate and related metrics
    """
    file_path = Path(output_path) if output_path else _get_metrics_file_path()

    # Read existing metrics
    metrics = _read_existing_metrics(file_path)

    fallback_data = {}

    if router is not None:
        free_tier_health = router.get_free_tier_health()

        total_free = free_tier_health.get("total_free_providers", 0)
        healthy_free = free_tier_health.get("healthy_free_providers", 0)
        success_rate = free_tier_health.get("free_quota_success_rate", 1.0)

        # Fallback rate = 1 - success_rate for free tier
        fallback_rate = round((1.0 - success_rate) * 100, 2)

        fallback_data = {
            "timestamp": datetime.now().isoformat(),
            "fallback_rate_pct": fallback_rate,
            "free_tier_total_providers": total_free,
            "free_tier_healthy_providers": healthy_free,
            "free_quota_success_rate": success_rate,
            "free_quota_success": free_tier_health.get("free_quota_success", 0),
            "free_quota_fail": free_tier_health.get("free_quota_fail", 0),
            "local_model_available": free_tier_health.get("local_model_available", False),
            "overall_health": free_tier_health.get("overall_health", "unknown"),
            "circuit_breaker_states": free_tier_health.get("circuit_breaker_states", {}),
        }
    else:
        fallback_data = {
            "timestamp": datetime.now().isoformat(),
            "fallback_rate_pct": 0.0,
            "note": "Router not provided, cannot compute fallback rate",
        }

    # Update metrics
    metrics["fallback_rate"] = fallback_data
    _write_metrics(file_path, metrics)

    logger.info(f"Fallback rate exported: {fallback_data.get('fallback_rate_pct', 'N/A')}%")
    return fallback_data


def export_compliance_rate(
    monitor: Optional[ComplianceMonitor] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Export schema compliance rate metrics.

    Returns overall and per-stage compliance rates.

    Args:
        monitor: ComplianceMonitor instance (optional, uses global if not provided)
        output_path: Custom output path (optional, defaults to logs/metrics_YYYYMMDD.json)

    Returns:
        Dict containing compliance rates
    """
    file_path = Path(output_path) if output_path else _get_metrics_file_path()

    # Read existing metrics
    metrics = _read_existing_metrics(file_path)

    if monitor is None:
        monitor = get_compliance_monitor()

    overall_rate = monitor.get_overall_compliance_rate()
    stage_summaries = monitor.get_all_summaries()
    contract_dist = monitor.get_contract_version_distribution()

    compliance_data = {
        "timestamp": datetime.now().isoformat(),
        "overall_compliance_rate": round(overall_rate, 4),
        "overall_compliance_pct": round(overall_rate * 100, 2),
        "contract_version_distribution": contract_dist,
        "stage_compliance": {
            stage: {
                "total_calls": summary.total_calls,
                "compliant_calls": summary.compliant_calls,
                "compliance_rate": round(summary.compliance_rate, 4),
                "compliance_pct": round(summary.compliance_rate * 100, 2),
                "avg_quality_score": round(summary.avg_quality_score, 4),
                "avg_latency_ms": round(summary.avg_latency_ms, 2),
                "avg_cost_usd": round(summary.avg_cost_usd, 6),
            }
            for stage, summary in stage_summaries.items()
        },
    }

    # Update metrics
    metrics["compliance_rate"] = compliance_data
    _write_metrics(file_path, metrics)

    logger.info(f"Compliance rate exported: {compliance_data['overall_compliance_pct']}%")
    return compliance_data


def export_contract_version(
    monitor: Optional[ComplianceMonitor] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Export contract version distribution metrics.

    Returns the distribution of contract versions across all records.

    Args:
        monitor: ComplianceMonitor instance (optional, uses global if not provided)
        output_path: Custom output path (optional, defaults to logs/metrics_YYYYMMDD.json)

    Returns:
        Dict containing contract version distribution
    """
    file_path = Path(output_path) if output_path else _get_metrics_file_path()

    # Read existing metrics
    metrics = _read_existing_metrics(file_path)

    if monitor is None:
        monitor = get_compliance_monitor()

    contract_dist = monitor.get_contract_version_distribution()
    total_records = sum(contract_dist.values())

    contract_data = {
        "timestamp": datetime.now().isoformat(),
        "contract_version_distribution": contract_dist,
        "total_records": total_records,
        "versions_used": len(contract_dist),
        "latest_version": max(contract_dist.keys()) if contract_dist else 1,
    }

    # Update metrics
    metrics["contract_version"] = contract_data
    _write_metrics(file_path, metrics)

    logger.info(f"Contract version exported: {contract_data}")
    return contract_data


def export_all_metrics(
    router: Optional[LLMRouter] = None,
    monitor: Optional[ComplianceMonitor] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Export all metrics in a single call.

    This is the main entry point for CI to collect all metrics.

    Args:
        router: LLMRouter instance (optional)
        monitor: ComplianceMonitor instance (optional)
        output_path: Custom output path (optional)

    Returns:
        Complete metrics dictionary
    """
    file_path = Path(output_path) if output_path else _get_metrics_file_path()

    metrics = {
        "exported_at": datetime.now().isoformat(),
        "format_version": 1,
    }

    # Export router metrics
    if router is not None:
        metrics["router"] = export_router_metrics(router)
        metrics["circuit_breakers"] = export_circuit_breaker_metrics(router.circuit_breakers)
        metrics["health_probe"] = export_health_probe_metrics(router.health_probe)
        metrics["key_pool"] = export_key_pool_metrics(router.key_pool)

    # Export fallback rate (returns dict with fallback_rate_pct)
    fallback_result = export_fallback_rate(router, output_path)
    metrics["fallback_rate"] = fallback_result

    # Export compliance rate
    compliance_result = export_compliance_rate(monitor, output_path)
    metrics["compliance_rate"] = compliance_result

    # Export contract version
    contract_result = export_contract_version(monitor, output_path)
    metrics["contract_version"] = contract_result

    # Write final consolidated metrics
    _write_metrics(file_path, metrics)

    logger.info(f"All metrics exported to {file_path}")
    return metrics


# Convenience function for CI usage
def get_metrics_for_ci() -> Dict[str, Any]:
    """Get metrics formatted for CI consumption.

    Returns a dict with the key metrics CI needs:
    - fallback_rate: fallback rate percentage
    - compliance_rate: overall schema compliance rate
    - contract_version: latest contract version
    """
    file_path = _get_metrics_file_path()
    metrics = _read_existing_metrics(file_path)

    return {
        "fallback_rate_pct": metrics.get("fallback_rate", {}).get("fallback_rate_pct", 0.0),
        "overall_compliance_rate": metrics.get("compliance_rate", {}).get("overall_compliance_rate", 0.0),
        "overall_compliance_pct": metrics.get("compliance_rate", {}).get("overall_compliance_pct", 0.0),
        "contract_version_distribution": metrics.get("contract_version", {}).get("contract_version_distribution", {}),
        "latest_contract_version": metrics.get("contract_version", {}).get("latest_version", 1),
        "exported_at": metrics.get("exported_at", datetime.now().isoformat()),
    }


if __name__ == "__main__":
    # Demo usage
    logging.basicConfig(level=logging.INFO)

    # Create mock router and monitor for demo
    router = LLMRouter()
    monitor = ComplianceMonitor()

    # Add some mock compliance data
    for stage in ["extract", "analyze", "annotate", "edit", "synthesize", "quality"]:
        for i in range(10):
            monitor.record(
                stage=stage,
                schema_compliance=True,
                contract_version=1,
                quality_score=0.95,
            )
        monitor.record(
            stage=stage,
            schema_compliance=False,
            contract_version=1,
            quality_score=0.5,
            errors=["schema_validation_failed"],
        )

    # Export all metrics
    all_metrics = export_all_metrics(router=router, monitor=monitor)
    logger.info(json.dumps(all_metrics, indent=2, ensure_ascii=False))

    # Get CI metrics
    ci_metrics = get_metrics_for_ci()
    logger.info("\n--- CI Metrics ---")
    logger.info(json.dumps(ci_metrics, indent=2, ensure_ascii=False))
