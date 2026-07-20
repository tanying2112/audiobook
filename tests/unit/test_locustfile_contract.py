"""Static contract regression for tests/stress/locustfile.py.

The locustfile must speak the real API contract of ``api/export.py``
(``ExportRequest`` request schema + ``TaskStatusOut`` status schema) and
``api/websocket.py`` (``/api/ws/pipeline/{project_id}``). The Sprint L version
had 5+2 mismatches that made the load test only ever produce 404/422 and poll
fields that don't exist (``data["status"] == "completed"``,
``data["audio_duration_seconds"]``, ...).

We pin the contract WITHOUT importing locust (it may be uninstalled in the dev
venv, and importing the locustfile would also spin up locust decorators). The
source is parsed as AST and scanned for the literal contract strings.
"""

import ast
from pathlib import Path

_LOCUSTFILE = Path(__file__).resolve().parents[2] / "tests" / "stress" / "locustfile.py"


def _src() -> str:
    return _LOCUSTFILE.read_text(encoding="utf-8")


def test_locustfile_parses_cleanly() -> None:
    """The rewrite must remain syntactically valid Python (catches typos)."""
    ast.parse(_src())


def test_export_post_path_is_project_scoped() -> None:
    s = _src()
    assert "/api/projects/{project_id}/export" in s
    # old phantom POST path removed
    assert 'name="POST /api/export"' not in s


def test_status_poll_path_uses_export_tasks_route() -> None:
    s = _src()
    assert "/api/export/tasks/{task_id}/status" in s
    # old phantom poll path '/api/export/{task_id}/status' (no 'tasks/' segment) removed
    assert "/api/export/{task_id}/status" not in s


def test_export_payload_matches_export_request_schema() -> None:
    s = _src()
    assert '"chapter_ids"' in s
    assert '"formats"' in s
    # phantom ExportRequest keys removed (ExportRequest has no format/quality/
    # chapters/voice_settings — those caused 422)
    assert '"format":' not in s
    assert '"quality":' not in s
    assert '"voice_settings"' not in s
    assert '"chapters":' not in s


def test_completion_reads_state_not_status_completed() -> None:
    s = _src()
    # TaskStatusOut exposes `state` (Celery) + `progress` (str), not `status`
    assert 'data.get("state")' in s
    assert '"complete"' in s  # progress terminal value (ExportProgress.COMPLETE)
    assert '"SUCCESS"' in s  # Celery SUCCESS state
    # The phantom `status == "completed"` comparison is gone from status-reading
    # code (TaskStatusOut exposes no `status` field). A regression that reads it
    # re-introduces `data.get("status")`, which is the tighter code-level guard.
    assert 'data.get("status")' not in s


def test_project_id_is_ensured_before_export() -> None:
    """Export endpoint is project-scoped → locustfile must pre-supply a project id."""
    s = _src()
    assert "/api/projects/" in s
    assert "201" in s  # POST /api/projects/ returns 201 Created


def test_websocket_uses_real_pipeline_route() -> None:
    s = _src()
    assert "/api/ws/pipeline/{project_id}" in s
    # The phantom tts-stream fallback endpoint must stay gone (no such route).
    # (Sprint L's /api/ws/stream phantom is only mentioned in a comment now;
    # the real endpoint is pinned above via "/api/ws/pipeline/{project_id}".)
    assert "/api/tts/stream" not in s


def test_rtf_handled_honestly_when_audio_duration_absent() -> None:
    """TaskStatusOut has no audio_duration_seconds → RTF must skip, not fake."""
    s = _src()
    assert "audio_duration_seconds" in s  # referenced where it would be checked
    assert "skipped" in s  # explicit skip messaging
    # client-side processing_time is measured (wall-clock POST→SUCCESS)
    assert "processing_time" in s


def test_performance_asserts_use_locust2_events_api() -> None:
    """RTF/TTFB custom asserts must fire via the locust 2.x unified
    ``events.request.fire(...)`` API, NOT the removed 1.x
    ``events.request_success`` / ``events.request_failure`` pair — those raise
    ``AttributeError: 'Events' object has no attribute 'request_success'`` at
    runtime under locust >= 2 (caught live in the Task 7.3 locust run).
    """
    s = _src()
    assert "events.request.fire(" in s
    assert "request_success" not in s
    assert "request_failure" not in s
