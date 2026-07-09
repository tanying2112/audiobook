"""Regression: ``_run_export_sync`` must call ``export_project`` with 3 args.

Background — the real signature is::

    def export_project(project_id, session, job) -> ExportJob   # batch_exporter.py:254

Sprint L's integration added a ``progress_callback`` machinery and called::

    export_project(project_id, db, job, progress_callback)   # 4 positional args

which raised ``TypeError: export_project() takes 3 ... argument`` on every
export task → Celery retry×3 → FAILURE. The 20+ existing tests already call it
with 3 args; only ``export_tasks._run_export_sync`` passed a phantom 4th.

This test pins the contract: only 3 positional args reach ``export_project``
and the returned job is returned up the stack. Before the fix it failed with
``TypeError`` (the spy accepts exactly 3 args).
"""

from unittest.mock import MagicMock, patch

import src.audiobook_studio.tasks.export_tasks as etmod


def test_run_export_sync_passes_three_args_to_export_project() -> None:
    captured: dict = {}

    def fake_export_project(project_id, session, job):
        captured["args"] = (project_id, session, job)
        return job

    job = MagicMock(name="ExportJob")
    db = MagicMock(name="db_session")
    task_self = MagicMock(name="task_self")

    with patch.object(etmod, "export_project", side_effect=fake_export_project) as spy:
        result = etmod._run_export_sync(1, job, db, task_self)

    # Exactly 3 positional args reach export_project — the 4th progress_callback
    # that Sprint L added was the defect (real signature is 3 args).
    assert spy.call_count == 1
    assert len(spy.call_args.args) == 3
    assert captured["args"] == (1, db, job)
    assert result is job
