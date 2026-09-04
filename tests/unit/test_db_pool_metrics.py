"""L-05: DB connection-pool monitoring — Prometheus export + CI JSON export."""

from __future__ import annotations

from src.audiobook_studio.core.telemetry import get_telemetry
from src.audiobook_studio.monitoring.metrics_exporter import _collect_db_pool_metrics, export_db_pool_metrics


def test_db_pool_prometheus_metrics_present():
    """Pool gauges must appear in the Prometheus text export."""
    prom = get_telemetry().export_prometheus()
    for metric in (
        "audiobook_db_pool_size",
        "audiobook_db_pool_checked_in",
        "audiobook_db_pool_checked_out",
        "audiobook_db_pool_overflow",
        "audiobook_db_pool_connections",
    ):
        assert metric in prom, f"missing Prometheus metric: {metric}"


def test_db_pool_json_export(tmp_path, monkeypatch):
    """export_db_pool_metrics writes pool stats to the CI metrics file."""
    monkeypatch.setenv("AUDIOBOOK_LOGS_DIR", str(tmp_path))
    result = export_db_pool_metrics()
    assert isinstance(result, dict)
    # sync and/or async pool sampled (this project uses QueuePool for both)
    assert result, "expected at least one sampled pool"
    for name, stats in result.items():
        assert set(stats.keys()) == {
            "size",
            "checked_in",
            "checked_out",
            "overflow",
            "connections",
        }, name
        # connections gauge == checked_in + checked_out
        assert stats["connections"] == stats["checked_in"] + stats["checked_out"]


def test_collect_db_pool_metrics_keys():
    collected = _collect_db_pool_metrics()
    for stats in collected.values():
        assert set(stats.keys()) == {
            "size",
            "checked_in",
            "checked_out",
            "overflow",
            "connections",
        }
