import json
import sys
import time
from unittest import mock

import pytest

sys.modules.setdefault("streamlit", mock.MagicMock())
sys.modules.setdefault("pandas", mock.MagicMock())

_pm = mock.MagicMock()
sys.modules.setdefault("plotly", _pm)
sys.modules.setdefault("plotly.express", _pm.express)
sys.modules.setdefault("plotly.graph_objects", _pm.graph_objects)

import dashboard.app as D  # noqa: E402

st = sys.modules["streamlit"]


class FakeRedisD:
    def __init__(self, heartbeats=None, tasks=None):
        self.heartbeats = heartbeats or {}
        self.tasks = tasks or {}

    def scan(self, cursor=0, match=None, count=None):
        if match == "worker:heartbeat:*":
            return (0, list(self.heartbeats.keys()))
        return (0, list(self.tasks.keys()))

    def mget(self, keys):
        out = []
        for k in keys:
            if k in self.heartbeats:
                out.append(self.heartbeats[k])
            elif k in self.tasks:
                out.append(self.tasks[k])
            else:
                out.append(None)
        return out

    def llen(self, key):
        return 0

    def lrange(self, key, start, end):
        return []


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
            "studio_id": "s",
        }
    )


@pytest.fixture
def redis_d():
    hb = {
        "worker:heartbeat:modal-1": _hb("w1", "modal", "processing", time.time(), backend="torch"),
        "worker:heartbeat:paddle-2": _hb(
            "w2", "paddle", "idle", time.time() - 99999, used=0, total=4000, backend="paddle"
        ),
    }
    return FakeRedisD(heartbeats=hb)


@pytest.fixture
def setup(monkeypatch, redis_d):
    st.session_state = {}

    def _cols(spec):
        n = spec if isinstance(spec, int) else len(spec)
        return [mock.MagicMock() for _ in range(n)]

    def _tabs(labels):
        return [mock.MagicMock() for _ in labels]

    monkeypatch.setattr(st, "session_state", st.session_state)
    monkeypatch.setattr(st, "columns", _cols)
    monkeypatch.setattr(st, "tabs", _tabs)
    monkeypatch.setattr(D.redis, "Redis", lambda *a, **k: redis_d)
    monkeypatch.setattr(D, "get_redis_client", lambda config: redis_d)
    monkeypatch.setattr(D, "REFRESH_INTERVAL", 0)
    return redis_d


def test_scan_and_states(setup):
    workers = D.scan_worker_heartbeats(setup)
    assert len(workers) == 2
    assert D.get_queue_depth(setup) == 0
    assert D.get_results_count(setup) == 0
    states = D.get_task_states(setup)
    assert states["PENDING"] == 0


def test_compute_fleet_metrics():
    workers = [
        {
            "platform": "modal",
            "status": "processing",
            "gpu_mem_used_mb": 1000,
            "gpu_mem_total_mb": 2000,
            "ts": time.time(),
            "idle_timeout": 900,
        },
        {
            "platform": "modal",
            "status": "idle",
            "gpu_mem_used_mb": 0,
            "gpu_mem_total_mb": 2000,
            "ts": time.time() - 99999,
            "idle_timeout": 900,
        },
    ]
    m = D.compute_fleet_metrics(workers, time.time())
    assert m["total_workers"] == 2
    assert m["active_workers"] == 1
    assert m["stale_workers"] == 1


def test_render_alert_banner_branches():
    D.render_alert_banner({"active_workers": 0, "total_workers": 3, "stale_workers": 0}, 100)
    D.render_alert_banner({"active_workers": 1, "total_workers": 3, "stale_workers": 3}, 0)
    D.render_alert_banner({"active_workers": 1, "total_workers": 3, "stale_workers": 1}, 0)
    D.render_alert_banner({"active_workers": 0, "total_workers": 0, "stale_workers": 0}, 0)


def test_main_runs(setup, monkeypatch):
    # No API server in unit tests: make the fetch raise a handled ConnectionError
    ce = D.requests.exceptions.ConnectionError("no api in unit tests")
    monkeypatch.setattr(D.requests, "get", mock.MagicMock(side_effect=ce))
    monkeypatch.setattr(D.requests, "post", mock.MagicMock(side_effect=ce))
    D.main()


def test_quality_console_fetch_and_report(setup, monkeypatch):
    report = {
        "project_id": 1,
        "chapter_index": 0,
        "overall_passed": False,
        "total_segments": 2,
        "passed_segments": 1,
        "failed_segments": 1,
        "segment_results": [
            {
                "segment_id": "s1",
                "passed": True,
                "issues": [],
                "file_path": "/a/b.wav",
                "duration_ms": 100,
                "silence_ratio": 0.1,
                "silence_detected": False,
                "clipping_detected": False,
                "peak_db": -3.0,
                "rms_db": -12.0,
                "corruption_detected": False,
            },
            {
                "segment_id": "s2",
                "passed": False,
                "issues": ["clip"],
                "file_path": "/a/c.wav",
                "duration_ms": 100,
                "silence_ratio": 0.5,
                "silence_detected": True,
                "clipping_detected": True,
                "peak_db": -1.0,
                "rms_db": -6.0,
                "corruption_detected": True,
            },
        ],
    }
    resp = mock.MagicMock()
    resp.status_code = 200
    resp.json.return_value = report
    monkeypatch.setattr(D.requests, "get", lambda *a, **k: resp)
    st.session_state = {"fetch_quality": True, "quality_project_id": 1, "quality_chapter": 0}
    monkeypatch.setattr(st, "session_state", st.session_state)
    D.render_quality_console(D.DashboardConfig())


def test_quality_console_404(setup, monkeypatch):
    resp = mock.MagicMock()
    resp.status_code = 404
    monkeypatch.setattr(D.requests, "get", lambda *a, **k: resp)
    st.session_state = {"fetch_quality": True, "quality_project_id": 1, "quality_chapter": 0}
    monkeypatch.setattr(st, "session_state", st.session_state)
    D.render_quality_console(D.DashboardConfig())


def test_quality_console_connerror(setup, monkeypatch):
    def boom(*a, **k):
        raise __import__("requests").exceptions.ConnectionError("x")

    monkeypatch.setattr(D.requests, "get", boom)
    st.session_state = {"fetch_quality": True, "quality_project_id": 1, "quality_chapter": 0}
    monkeypatch.setattr(st, "session_state", st.session_state)
    D.render_quality_console(D.DashboardConfig())
