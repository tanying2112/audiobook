"""Regression: ``_run_export_async`` must call ``export_project`` with 3 args.

Background — the real signature is::

    def export_project(project_id, session, job) -> ExportJob   # batch_exporter.py:257

Sprint L's integration added a ``progress_callback`` machinery and called::

    export_project(project_id, db, job, progress_callback)   # 4 positional args

which raised ``TypeError: export_project() takes 3 ... argument`` on every
export task -> Celery retry x3 -> FAILURE. The existing tests already call it
with 3 args; only ``export_tasks._run_export_async`` passed a phantom 4th.

This test pins the contract: only 3 positional args reach ``export_project``
and the returned job is returned up the stack. (``_run_export_async`` is the
async wrapper that ``export_project_async`` drives via ``asyncio.run``; the
Sprint-L ``_run_export_sync`` entrypoint was removed during the async refactor.)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.audiobook_studio.tasks.export_tasks as etmod


@pytest.mark.asyncio
async def test_run_export_async_passes_three_args_to_export_project() -> None:
    captured: dict = {}

    async def fake_export_project(project_id, session, job):
        captured["args"] = (project_id, session, job)
        return job

    job = MagicMock(name="ExportJob")
    db = AsyncMock(name="db_session")

    with patch.object(etmod, "export_project", new_callable=AsyncMock, side_effect=fake_export_project) as spy:
        result = await etmod._run_export_async(1, job, db)

    # Exactly 3 positional args reach export_project -- the 4th progress_callback
    # that Sprint L added was the defect (real signature is 3 args).
    assert spy.call_count == 1
    assert len(spy.call_args.args) == 3
    assert captured["args"] == (1, db, job)
    assert result is job
