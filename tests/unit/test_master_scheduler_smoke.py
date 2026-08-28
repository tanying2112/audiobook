import json
import time
from unittest import mock

import pytest

import master.scheduler as S
from master.scheduler import HermesScheduler, WorkerTelemetry


class FakeRedisS:
    def __init__(self, heartbeats=None):
        self.heartbeats = heartbeats or {}

    def scan(self, cursor=0, match=None, count=None):
        return (0, list(self.heartbeats.keys()))

    def mget(self, keys):
        return [self.heartbeats[k] for k in keys]

    def llen(self, key):
        return 0


def _hb(worker_id, platform, status, ts, used=1000, total=2000, backend=None, qd=0):
    return json.dumps(
        {
            "worker_id": worker_id,
            "status": status,
            "gpu_metrics": {
                "gpu_mem_used_mb": used,
                "gpu_mem_total_mb": total,
                "device_name": "GPU",
                "backend": backend,
            },
            "queue_depth": qd,
            "ts": ts,
            "studio_id": "studio1",
        }
    )


@pytest.fixture
def sched(monkeypatch):
    hb = {
        "worker:heartbeat:modal-1": _hb("w1", "modal", "processing", time.time(), backend="torch"),
        "worker:heartbeat:paddle-2": _hb(
            "w2", "paddle", "idle", time.time() - 9999, used=0, total=4000, backend="paddle"
        ),
    }
    monkeypatch.setattr(S.redis, "Redis", lambda *a, **k: FakeRedisS(hb))
    return HermesScheduler("h", 6379, "auth")


def test_worker_telemetry():
    wt = WorkerTelemetry(
        worker_id="w",
        platform="modal",
        status="idle",
        gpu_mem_used_mb=0,
        gpu_mem_total_mb=2000,
        device_name="GPU",
        queue_depth=0,
        ts=time.time(),
        studio_id="s",
    )
    assert wt.gpu_utilization == 0.0
    wt2 = WorkerTelemetry(
        worker_id="w",
        platform="modal",
        status="idle",
        gpu_mem_used_mb=1000,
        gpu_mem_total_mb=2000,
        device_name="GPU",
        queue_depth=0,
        ts=time.time(),
        studio_id="s",
    )
    assert wt2.gpu_utilization == 0.5
    assert wt2.routing_priority == S.PLATFORM_ROUTING["modal"]
    wt2.ts = 0.0
    assert wt2.is_stale(120) is True


def test_scan_worker_heartbeats(sched):
    workers = sched.scan_worker_heartbeats()
    assert len(workers) == 2
    # sorted by routing priority: paddle(99) after modal
    assert workers[0].platform == "modal"


def test_get_fleet_status(sched):
    status = sched.get_fleet_status()
    assert status["total_workers"] == 2
    assert "modal" in status["platforms"]


def test_cleanup_stale_workers(sched):
    assert sched.cleanup_stale_workers() == 0


def test_handle_shutdown(sched):
    sched._handle_shutdown(15, None)
    assert sched.running is False


def test_maintenance_loop(sched, monkeypatch):
    sched.running = True
    states = {"n": 0}

    def fake_sleep(interval):
        states["n"] += 1
        sched.running = False

    monkeypatch.setattr(S.time, "sleep", fake_sleep)
    sched.run_maintenance_loop(interval=0)
    assert states["n"] == 1


def test_main_missing_env(monkeypatch):
    monkeypatch.delenv("REDIS_HOST", raising=False)
    monkeypatch.delenv("REDIS_AUTH", raising=False)
    with pytest.raises(SystemExit):
        S.main()
