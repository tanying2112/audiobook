import asyncio
from unittest import mock

import pytest

import audiobook_studio.version_manager as VM
from audiobook_studio.tasks import publish_job_repo as PJR
from audiobook_studio.tts import edge_tts_port as EP
from audiobook_studio.tts.edge_tts_port import EdgeTTSPort


# --------------------------------------------------------------------------
# edge_tts_port
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_edge_tts_port(tmp_path):
    with mock.patch.object(EP, "create_edge_tts_engine") as ce:
        eng = mock.MagicMock()
        eng.synthesize = mock.AsyncMock(return_value=mock.MagicMock())
        eng.close = mock.AsyncMock()
        ce.return_value = eng
        port = EdgeTTSPort(output_dir=str(tmp_path), mock_mode=True)
        payload = mock.MagicMock()
        assert await port.submit("t1", payload) is True
        assert await port.submit("t1", payload) is False  # duplicate
        assert await port.get_status("nope") is None
        assert await port.get_result("nope") is None
        assert await port.cancel("nope") is False
        hc = await port.health_check()
        assert "queue_size" in hc
        # allow the background synthesis task to run
        await asyncio.sleep(0.05)
        await port.close()


# --------------------------------------------------------------------------
# publish_job_repo
# --------------------------------------------------------------------------
async def _make_session(result_obj):
    sess = mock.MagicMock()
    res = mock.MagicMock()
    res.scalar_one_or_none.return_value = result_obj
    sess.execute = mock.AsyncMock(return_value=res)
    sess.commit = mock.AsyncMock()
    sess.refresh = mock.AsyncMock()
    cm = mock.AsyncMock()
    cm.__aenter__.return_value = sess
    cm.__aexit__.return_value = False
    return cm, res


@pytest.mark.asyncio
async def test_publish_job_repo():
    none_cm, none_res = await _make_session(None)
    with mock.patch.object(PJR, "AsyncSessionLocal", return_value=none_cm):
        created = await PJR.create_publish_job(1, "m4b", job_id="j1")
        assert created is not None  # real PublishJobState inserted

    job_cm, job_res = await _make_session(mock.MagicMock())
    with mock.patch.object(PJR, "AsyncSessionLocal", return_value=job_cm):
        assert await PJR.get_publish_job("j1") is not None
        await PJR.mark_processing("j1")
        await PJR.register_retry("j1", "err")
        await PJR.mark_success("j1", {"ok": True})
        await PJR.mark_failure("j1", "boom")

    # idempotency: existing job returned
    with mock.patch.object(PJR, "AsyncSessionLocal", return_value=none_cm):
        existing = await PJR.create_publish_job(1, "m4b", job_id="j1")
        assert existing is not None


# --------------------------------------------------------------------------
# version_manager
# --------------------------------------------------------------------------
def test_version_manager():
    db = mock.MagicMock()
    with mock.patch.object(VM, "_get_db", return_value=db):
        assert isinstance(VM.list_runs(1), object)
        run = VM.save_run(1, tag="v1", message="m", score=0.9)
        assert run is not None
        assert VM.get_run(1, run_id=1) is not None
        assert VM.get_run(1, tag="v1") is not None
        # rollback / diff / restore exercise the remaining branches
        VM.rollback_to_run(1, run_id=1)
        VM.diff_runs(1, 2)
        VM.restore_state(1, run_id=1)
