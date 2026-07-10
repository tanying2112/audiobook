"""Regression: task-status endpoint must read Celery state locally, not by
dispatching another Celery task.

Real-run repro (Sprint L defect): ``get_export_status`` is registered as a Celery
``@task`` but is **not** listed in ``celery_app.task_routes`` (celery_app.py) →
it routes to the default ``celery`` queue, which no worker consumes (workers run
``-Q export,pipeline``) → ``get_export_status.delay(task_id).get(timeout=10)``
hung 10s then raised ``TimeoutError`` → the endpoint returned **HTTP 500**.

Crucially, ``get_export_status``'s body only reads
``celery_app.AsyncResult(task_id)`` locally — it never needed to be *dispatched*
to a worker at all. The fix calls it synchronously in the request process.

This test stubs ``get_export_status`` with a plain sync function that has NO
``.delay`` method, then calls the endpoint:

- Before fix: endpoint does ``get_export_status.delay(task_id).get(timeout=10)``
  → ``_stub_status`` has no ``.delay`` → ``AttributeError`` → 500 (red).
- After fix: endpoint does ``get_export_status(task_id)`` synchronously → the
  dict is returned → 200 (green).
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _stub_status(task_id: str) -> dict:
    """Plain sync callable with NO `.delay` — mirrors a non-Celery local read."""
    return {
        "task_id": task_id,
        "state": "SUCCESS",
        "progress": "complete",
        "message": "",
        "current_stage": "",
        "output_paths": {},
        "error": None,
    }


class TestExportTaskStatusEndpointReadsLocally:
    @pytest.fixture()
    def client(self, monkeypatch):
        import src.audiobook_studio.api.export as export_api_module

        # Stub the endpoint's local get_export_status with a plain sync callable
        # that has NO `.delay` method — so a `.delay().get()` call trips.
        monkeypatch.setattr(export_api_module, "get_export_status", _stub_status)
        app = FastAPI()
        app.include_router(export_api_module.export_tasks_router)
        # raise_server_exceptions=False so the pre-fix `.delay` AttributeError
        # surfaces as HTTP 500 (what real users saw) instead of re-raising.
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_status_endpoint_reads_status_without_dispatching_task(self, client):
        r = client.get("/export/tasks/fake-task-id/status")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["task_id"] == "fake-task-id"
        assert body["state"] == "SUCCESS"
        assert body["progress"] == "complete"
