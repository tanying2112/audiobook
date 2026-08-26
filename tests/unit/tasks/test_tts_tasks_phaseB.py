"""Phase B structural coverage tests for tasks/tts_tasks.py.

Targets the module's heavy branches behind external boundaries:
- Redis (idempotency / semaphore / failed-paragraph / checkpoint)
- RemoteTTSPort (HTTP submission + polling to Hermes)
- AsyncSessionLocal (DB project/chapter lookup)
- ffprobe (audio duration)

By mocking these boundaries we exercise the real orchestration logic and
its branch decisions without a live broker/Redis/DB.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.audiobook_studio.tasks.tts_tasks as tts_mod
from src.audiobook_studio.tasks.tts_tasks import (
    TTSChapterTask,
    TTSStatus,
    _build_port_payload,
    _download_audio,
    _get_audio_duration,
    _run_synthesize_paragraph_async,
    _synthesize_via_port,
    resume_chapter_task,
    synthesize_paragraph_task,
)


class _FakeRedis:
    """Minimal Redis stand-in that records calls and yields configurable results."""

    def __init__(self, *, evalsha_result: Any = 1, set_result: Any = True,
                 smembers: set | None = None, get_result: Any = None,
                 raise_on: set[str] = frozenset()):
        self._evalsha = evalsha_result
        self._set = set_result
        self._smembers = smembers or set()
        self._get = get_result
        self._raise_on = raise_on
        self.calls: list[str] = []

    def evalsha(self, *args, **kwargs):
        self.calls.append("evalsha")
        if "evalsha" in self._raise_on:
            raise RuntimeError("boom evalsha")
        return self._evalsha

    def set(self, *args, **kwargs):
        self.calls.append("set")
        if "set" in self._raise_on:
            raise RuntimeError("boom set")
        return self._set

    def sadd(self, *args, **kwargs):
        self.calls.append("sadd")
        if "sadd" in self._raise_on:
            raise RuntimeError("boom sadd")
        return 1

    def expire(self, *args, **kwargs):
        self.calls.append("expire")
        return True

    def smembers(self, *args, **kwargs):
        self.calls.append("smembers")
        if "smembers" in self._raise_on:
            raise tts_mod.redis.exceptions.RedisError("boom")
        return self._smembers

    def delete(self, *args, **kwargs):
        self.calls.append("delete")
        if "delete" in self._raise_on:
            raise tts_mod.redis.exceptions.RedisError("boom")
        return 1

    def get(self, *args, **kwargs):
        self.calls.append("get")
        if "get" in self._raise_on:
            raise RuntimeError("boom get")
        return self._get


def _make_task() -> TTSChapterTask:
    task = TTSChapterTask()
    task.request = MagicMock()
    task.request.id = "task-123"
    task.request.retries = 0
    task.update_state = MagicMock()
    return task


_SEG_SRC = Path("/tmp/_tts_phaseB_seg_src.wav")


class _SeqDB:
    """Async DB session whose execute() returns queued result descriptors per call."""

    def __init__(self, items):
        self._items = list(items)
        self._i = 0

    async def execute(self, *a, **k):
        item = self._items[self._i]
        self._i += 1

        class _R:
            def __init__(self, it):
                self.it = it

            def scalar_one_or_none(self):
                return self.it.get("scalar")

            def scalars(self):
                class _S:
                    def __init__(self, it):
                        self.it = it

                    def all(self):
                        return self.it.get("scalars", [])

                return _S(self.it)

        return _R(item)

    async def commit(self):
        return None

    async def add(self, *a, **k):
        return None

    async def refresh(self, *a, **k):
        return None


# ── Redis semaphore ──────────────────────────────────────────────────────────

def test_acquire_semaphore_acquired() -> None:
    task = _make_task()
    fake = _FakeRedis(evalsha_result=1)
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        assert task._acquire_semaphore() is True
        assert task._semaphore_acquired is True


def test_acquire_semaphore_limit_reached() -> None:
    task = _make_task()
    fake = _FakeRedis(evalsha_result=0)
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        assert task._acquire_semaphore() is False
        assert task._semaphore_acquired is False


def test_acquire_semaphore_exception_proceeds() -> None:
    task = _make_task()
    fake = _FakeRedis(evalsha_result=1, raise_on={"evalsha"})
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        assert task._acquire_semaphore() is True


def test_release_semaphore_acquired() -> None:
    task = _make_task()
    task._semaphore_acquired = True
    fake = _FakeRedis(evalsha_result=1)
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        task._release_semaphore()
        assert task._semaphore_acquired is False
        assert "evalsha" in fake.calls


def test_release_semaphore_not_acquired_noop() -> None:
    task = _make_task()
    task._semaphore_acquired = False
    fake = _FakeRedis()
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        task._release_semaphore()
        assert "evalsha" not in fake.calls


# ── Idempotency ─────────────────────────────────────────────────────────────

def test_check_and_set_idempotency_acquired() -> None:
    task = _make_task()
    fake = _FakeRedis(set_result=True)
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        assert task._check_and_set_idempotency("tts:idem:abc") is True


def test_check_and_set_idempotency_duplicate() -> None:
    task = _make_task()
    fake = _FakeRedis(set_result=None)
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        assert task._check_and_set_idempotency("tts:idem:abc") is False


def test_check_and_set_idempotency_exception_proceeds() -> None:
    task = _make_task()
    fake = _FakeRedis(set_result=True, raise_on={"set"})
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        assert task._check_and_set_idempotency("tts:idem:abc") is True


# ── Failed paragraphs ───────────────────────────────────────────────────────

def test_record_failed_paragraph() -> None:
    task = _make_task()
    fake = _FakeRedis()
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        task._record_failed_paragraph(1, 2, 3)
        assert "sadd" in fake.calls and "expire" in fake.calls


def test_record_failed_paragraph_exception() -> None:
    task = _make_task()
    fake = _FakeRedis(raise_on={"sadd"})
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        task._record_failed_paragraph(1, 2, 3)  # should not raise


def test_get_failed_paragraphs() -> None:
    task = _make_task()
    fake = _FakeRedis(smembers={"1", "2"})
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        assert task._get_failed_paragraphs(1, 2) == {1, 2}


def test_get_failed_paragraphs_redis_error() -> None:
    task = _make_task()
    fake = _FakeRedis(raise_on={"smembers"})
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        assert task._get_failed_paragraphs(1, 2) == set()


def test_clear_failed_paragraphs() -> None:
    task = _make_task()
    fake = _FakeRedis()
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        task._clear_failed_paragraphs(1, 2)
        assert "delete" in fake.calls


def test_clear_failed_paragraphs_redis_error() -> None:
    task = _make_task()
    fake = _FakeRedis(raise_on={"delete"})
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        task._clear_failed_paragraphs(1, 2)  # should not raise


# ── Checkpoints ─────────────────────────────────────────────────────────────

def test_save_checkpoint() -> None:
    task = _make_task()
    fake = _FakeRedis()
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        task._save_checkpoint(1, 2, [1, 2], [3], None, [{"segment_id": "s"}])
        assert "set" in fake.calls


def test_save_checkpoint_exception() -> None:
    task = _make_task()
    fake = _FakeRedis(raise_on={"set"})
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        task._save_checkpoint(1, 2, [1], [], None, None)  # should not raise


def test_load_checkpoint_present() -> None:
    task = _make_task()
    data = {"completed_paragraphs": [1], "failed_paragraphs": []}
    fake = _FakeRedis(get_result=json.dumps(data))
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        assert task._load_checkpoint(1, 2) == data


def test_load_checkpoint_missing() -> None:
    task = _make_task()
    fake = _FakeRedis(get_result=None)
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        assert task._load_checkpoint(1, 2) is None


def test_load_checkpoint_exception() -> None:
    task = _make_task()
    fake = _FakeRedis(raise_on={"get"})
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        assert task._load_checkpoint(1, 2) is None


def test_clear_checkpoint() -> None:
    task = _make_task()
    fake = _FakeRedis()
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        task._clear_checkpoint(1, 2)
        assert "delete" in fake.calls


def test_clear_checkpoint_redis_error() -> None:
    task = _make_task()
    fake = _FakeRedis(raise_on={"delete"})
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        task._clear_checkpoint(1, 2)  # should not raise


# ── Port payload / synthesis via port (HTTP) ──────────────────────────────────

def test_build_port_payload_emotion() -> None:
    payload = _build_port_payload("hi", "v1", {"rate": 1.5, "pitch": 2.0, "emotion": "happy"})
    assert payload.prosody.rate == 1.5
    assert payload.metadata["prosody_raw"]["emotion"] == "happy"


def test_synthesize_via_port_success(tmp_path: Path) -> None:
    class _Status:
        status = MagicMock()
        status.value = "done"
        progress = 1.0
        error_message = None

    src = tmp_path / "seg.wav"
    src.write_bytes(b"RIFFDATA")

    class _Result:
        audio_path = str(src)
        duration_ms = 1200
        metadata = {"engine": "kokoro"}

    port = MagicMock()
    port.submit = AsyncMock(return_value=True)
    st = _Status(); st.status = TTSStatus.DONE
    port.get_status = AsyncMock(return_value=st)
    port.get_result = AsyncMock(return_value=_Result())

    out = tmp_path / "seg_out.wav"

    async def _run():
        return await _synthesize_via_port(port, "text", "v1", {}, out, "seg1")

    dur, engine = asyncio.run(_run())
    assert dur == 1200
    assert engine == "kokoro"


def test_synthesize_via_port_rejected() -> None:
    port = MagicMock()
    port.submit = AsyncMock(return_value=False)

    async def _run():
        return await _synthesize_via_port(port, "text", "v1", {}, Path("/tmp/x.wav"), "seg1")

    with pytest.raises(RuntimeError):
        asyncio.run(_run())


def test_synthesize_via_port_failed_status() -> None:
    class _Status:
        status = MagicMock()
        progress = 0.0
        error_message = "boom"

    port = MagicMock()
    port.submit = AsyncMock(return_value=True)
    st = _Status(); st.status = TTSStatus.FAILED
    port.get_status = AsyncMock(return_value=st)

    async def _run():
        return await _synthesize_via_port(port, "text", "v1", {}, Path("/tmp/x.wav"), "seg1")

    with pytest.raises(RuntimeError):
        asyncio.run(_run())


def test_synthesize_via_port_unknown_status() -> None:
    class _Status:
        status = MagicMock()
        progress = 0.0
        error_message = None

    class _WeirdStatus:
        value = "weird"

    port = MagicMock()
    port.submit = AsyncMock(return_value=True)
    st = _Status(); st.status = _WeirdStatus()
    port.get_status = AsyncMock(return_value=st)

    async def _run():
        return await _synthesize_via_port(port, "text", "v1", {}, Path("/tmp/x.wav"), "seg1")

    with pytest.raises(RuntimeError):
        asyncio.run(_run())


def test_download_audio_local_copy(tmp_path: Path) -> None:
    src = tmp_path / "src.wav"
    src.write_bytes(b"RIFF")
    dest = tmp_path / "dest.wav"
    asyncio.run(_download_audio(str(src), dest))
    assert dest.exists()


def test_download_audio_r2_local(tmp_path: Path) -> None:
    # Production derives local path via replace("r2://","").replace("/","_")
    real = Path("/tmp/seg.wav")
    real.write_bytes(b"RIFFDATA")
    dest = tmp_path / "dest.wav"
    asyncio.run(_download_audio("r2://seg.wav", dest))
    assert dest.exists()
    real.unlink()


def test_download_audio_not_implemented(tmp_path: Path) -> None:
    dest = tmp_path / "dest.wav"
    with pytest.raises(NotImplementedError):
        asyncio.run(_download_audio("http://nope/seg.wav", dest))


def test_get_audio_duration_ffprobe_success() -> None:
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="2.5\n")
        assert _get_audio_duration(Path("/x.wav")) == 2500


def test_get_audio_duration_ffprobe_fail_fallback(tmp_path: Path) -> None:
    f = tmp_path / "a.wav"
    f.write_bytes(b"0" * 96000)  # ~2s at 48KB/s
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=1, stdout="")
        assert _get_audio_duration(f) == 2000


def test_get_audio_duration_exception_fallback(tmp_path: Path) -> None:
    f = tmp_path / "a.wav"
    f.write_bytes(b"0" * 96000)
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        assert _get_audio_duration(f) == 2000


# ── Chapter synthesis flow (DB + Redis + Port mocked) ───────────────────────

def _fake_db_session(project: Any = None, chapter: Any = None):
    sess = AsyncMock()

    async def _execute(*a, **k):
        class _R:
            def scalar_one_or_none(self):
                # First call -> project, second -> chapter (positional heuristic)
                return project if _fake_db_session._call == 0 else chapter
        _fake_db_session._call += 1
        return _R()

    _fake_db_session._call = 0
    sess.execute = _execute
    return sess


async def _run_chapter(task: TTSChapterTask, paragraphs, *, project=None, chapter=None):
    with patch.object(tts_mod, "AsyncSessionLocal") as ASL, \
         patch.object(tts_mod, "SynthesizePipeline") as SP, \
         patch.object(tts_mod, "_get_redis", return_value=_FakeRedis(evalsha_result=1, set_result=True)):
        ASL.return_value.__aenter__.return_value = _fake_db_session(project, chapter)
        pipe = MagicMock()
        pipe._crossfade_stitch.return_value = Path("/tmp/chapter.wav")
        pipe.segments = []
        SP.return_value = pipe
        with patch.object(task, "_get_port") as gp:
            port = MagicMock()
            port.submit = AsyncMock(return_value=True)

            class _Status:
                status = TTSStatus.DONE
                progress = 1.0
                error_message = None

            class _Result:
                audio_path = str(_SEG_SRC)
                duration_ms = 100
                metadata = {"engine": "kokoro"}

            st = _Status()
            port.get_status = AsyncMock(return_value=st)
            port.get_result = AsyncMock(return_value=_Result())
            gp.return_value = port
            return await tts_mod._run_synthesize_chapter_async(
                task, 1, 2, 3, paragraphs
            )


def test_run_chapter_success(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    task = _make_task()
    para = [{"paragraph_id": "p1", "paragraph_index": 0, "text": "hello", "voice_id": "v1", "prosody": {}}]

    class _Proj:
        id = 1
    class _Chap:
        id = 2

    _SEG_SRC.write_bytes(b"RIFFDATA")
    try:
        result = asyncio.run(_run_chapter(task, para, project=_Proj(), chapter=_Chap()))
    finally:
        if _SEG_SRC.exists():
            _SEG_SRC.unlink()
    assert result["status"] == "completed"
    assert len(result["segments"]) == 1


def test_run_chapter_project_not_found() -> None:
    task = _make_task()
    para = [{"paragraph_id": "p1", "paragraph_index": 0, "text": "hello", "voice_id": "v1", "prosody": {}}]
    result = asyncio.run(_run_chapter(task, para, project=None, chapter=None))
    assert result["status"] == "failed"
    assert "not found" in result["error"]


def test_run_chapter_semaphore_limit() -> None:
    task = _make_task()
    para = [{"paragraph_id": "p1", "paragraph_index": 0, "text": "hello", "voice_id": "v1", "prosody": {}}]
    with patch.object(tts_mod, "AsyncSessionLocal") as ASL, \
         patch.object(tts_mod, "_get_redis", return_value=_FakeRedis(evalsha_result=0)):
        ASL.return_value.__aenter__.return_value = _fake_db_session(None, None)
        # semaphore limit reached -> immediate failure before DB
        result = asyncio.run(
            tts_mod._run_synthesize_chapter_async(task, 1, 2, 3, para)
        )
    assert result["status"] == "failed"
    assert "concurrency limit" in result["error"]


# ── resume_chapter_task (Celery entry) ───────────────────────────────────────

class _Chap:
    id = 2


class _Para:
    id = 1
    index = 0
    text = "hello"
    suggested_voice_id = "v1"
    prosody_overrides = {}


def test_resume_chapter_not_found() -> None:
    task = _make_task()
    db = _SeqDB([{"scalar": None}])
    with patch.object(tts_mod, "AsyncSessionLocal") as ASL, \
         patch.object(tts_mod, "_run_synthesize_chapter_async") as run:
        ASL.return_value.__aenter__.return_value = db
        res = resume_chapter_task(task, 1, 2, 3)
    assert res["status"] == "failed"
    assert "not found" in res["error"]
    run.assert_not_called()


def test_resume_chapter_no_paragraphs() -> None:
    task = _make_task()
    db = _SeqDB([{"scalar": _Chap()}, {"scalars": []}])
    with patch.object(tts_mod, "AsyncSessionLocal") as ASL, \
         patch.object(tts_mod, "_run_synthesize_chapter_async") as run:
        ASL.return_value.__aenter__.return_value = db
        res = resume_chapter_task(task, 1, 2, 3)
    assert res["status"] == "failed"
    assert "No paragraphs" in res["error"]
    run.assert_not_called()


def test_resume_chapter_delegates() -> None:
    task = _make_task()
    db = _SeqDB([{"scalar": _Chap()}, {"scalars": [_Para()]}])
    with patch.object(tts_mod, "AsyncSessionLocal") as ASL, \
         patch.object(tts_mod, "_run_synthesize_chapter_async") as run:
        ASL.return_value.__aenter__.return_value = db
        run.return_value = {"status": "completed"}
        res = resume_chapter_task(task, 1, 2, 3)
    assert res["status"] == "completed"
    run.assert_called_once()


# ── synthesize_paragraph_task / _run_synthesize_paragraph_async ──────────────

class _Proj:
    id = 1


class _ParaRow:
    id = 3
    index = 0
    edited_text = None
    text = "hello"
    routing_voice_id = "v1"
    routing_prosody_overrides = {}


class _ExistingSeg:
    id = 99
    segment_id = "seg-99"
    file_path = "r2://existing.wav"
    duration_ms = 500
    engine = "kokoro"
    voice_id = "v1"


async def _run_paragraph(task, *, project=None, chapter=None, paragraph=None,
                         existing=None, chapters=None, force: bool = True,
                         run_impl=None, redis=None, use_wrapper: bool = False):
    items = [
        {"scalar": project},
        {"scalar": chapter},
        {"scalar": paragraph},
        {"scalar": existing},
        {"scalars": chapters or []},
    ]
    db = _SeqDB(items)
    if redis is None:
        redis = _FakeRedis(evalsha_result=1, set_result=True)
    with patch.object(tts_mod, "AsyncSessionLocal") as ASL, \
         patch.object(tts_mod, "_get_redis", return_value=redis), \
         patch.object(tts_mod, "_synthesize_via_port", new=run_impl or AsyncMock(return_value=(100, "kokoro"))):
        ASL.return_value.__aenter__.return_value = db
        with patch.object(task, "_get_port") as gp:
            gp.return_value = MagicMock()
            if use_wrapper:
                return synthesize_paragraph_task(task, 1, 2, 3, force_regenerate=force)
            return await _run_synthesize_paragraph_async(task, 1, 2, 3, force_regenerate=force)


def test_synthesize_paragraph_semaphore_limit() -> None:
    task = _make_task()
    res = asyncio.run(_run_paragraph(task, redis=_FakeRedis(evalsha_result=0)))
    assert res["status"] == "failed"
    assert "concurrency limit" in res["error"]


def test_synthesize_paragraph_project_not_found() -> None:
    task = _make_task()
    res = asyncio.run(_run_paragraph(task, project=None))
    assert res["status"] == "failed"
    assert "Project" in res["error"]


def test_synthesize_paragraph_chapter_not_found() -> None:
    task = _make_task()
    res = asyncio.run(_run_paragraph(task, project=_Proj(), chapter=None))
    assert res["status"] == "failed"
    assert "Chapter" in res["error"]


def test_synthesize_paragraph_not_found() -> None:
    task = _make_task()
    res = asyncio.run(_run_paragraph(task, project=_Proj(), chapter=_Chap(), paragraph=None))
    assert res["status"] == "failed"
    assert "Paragraph" in res["error"]


def test_synthesize_paragraph_success(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    task = _make_task()
    called = {"n": 0}

    async def _impl(port, text, voice, prosody, out, seg):
        called["n"] += 1
        return 120, "kokoro"

    res = asyncio.run(_run_paragraph(task, project=_Proj(), chapter=_Chap(),
                                     paragraph=_ParaRow(), force=True, run_impl=_impl))
    assert res["status"] == "completed"
    assert called["n"] == 1


def test_synthesize_paragraph_skip_when_exists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    task = _make_task()
    res = asyncio.run(_run_paragraph(task, project=_Proj(), chapter=_Chap(),
                                     paragraph=_ParaRow(), existing=_ExistingSeg(),
                                     force=False,
                                     run_impl=AsyncMock(return_value=(100, "kokoro"))))
    assert res["status"] == "skipped"
    assert res["file_path"] == "r2://existing.wav"


def test_synthesize_paragraph_task_wrapper(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    task = _make_task()
    db = _SeqDB([
        {"scalar": _Proj()},
        {"scalar": _Chap()},
        {"scalar": _ParaRow()},
        {"scalar": None},
        {"scalars": []},
    ])
    with patch.object(tts_mod, "AsyncSessionLocal") as ASL, \
         patch.object(tts_mod, "_get_redis", return_value=_FakeRedis(evalsha_result=1, set_result=True)), \
         patch.object(tts_mod, "_synthesize_via_port", new=AsyncMock(return_value=(100, "kokoro"))):
        ASL.return_value.__aenter__.return_value = db
        with patch.object(task, "_get_port") as gp:
            gp.return_value = MagicMock()
            res = synthesize_paragraph_task(task, 1, 2, 3, force_regenerate=True)
    assert res["status"] == "completed"


# ── get_tts_status ───────────────────────────────────────────────────────────

def _fake_async_result(state: str, info):
    r = MagicMock()
    r.state = state
    r.info = info
    return r


def test_get_tts_status_completed() -> None:
    with patch.object(tts_mod.celery_app, "AsyncResult",
                      return_value=_fake_async_result("SUCCESS", {"current": 5, "total": 5,
                                                                   "paragraph_id": 3, "paragraph_index": 0})):
        res = tts_mod.get_tts_status("abc")
    assert res["state"] == "SUCCESS"
    assert res["progress"] == "completed"
    assert res["current"] == 5


def test_get_tts_status_failure() -> None:
    with patch.object(tts_mod.celery_app, "AsyncResult",
                      return_value=_fake_async_result("FAILURE", {"error": "boom"})):
        res = tts_mod.get_tts_status("abc")
    assert res["progress"] == "failed"
    assert res["error"] == "boom"


def test_get_tts_status_processing() -> None:
    with patch.object(tts_mod.celery_app, "AsyncResult",
                      return_value=_fake_async_result("PROGRESS", "raw-info")):
        res = tts_mod.get_tts_status("abc")
    assert res["progress"] == "processing"
    assert "current" not in res  # info not a dict


# ── verify_checkpoint_recovery ───────────────────────────────────────────────

def test_verify_checkpoint_none() -> None:
    task = _make_task()
    with patch.object(tts_mod, "_get_redis", return_value=None):
        res = tts_mod.verify_checkpoint_recovery(task, 1, 2)
    assert res["verified"] is False
    assert "No checkpoint" in res["error"]


def test_verify_checkpoint_recovery_with_missing_segment() -> None:
    task = _make_task()
    data = json.dumps({
        "completed_paragraphs": [1],
        "failed_paragraphs": [],
        "segments": [{"segment_id": "s1", "file_path": "/tmp/does_not_exist.wav"}],
        "chapter_audio_path": None,
    })
    fake = _FakeRedis(get_result=data)
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        res = tts_mod.verify_checkpoint_recovery(task, 1, 2)
    assert res["verified"] is False
    assert "s1" in res["missing_segments"]


def test_verify_checkpoint_recovery_valid(tmp_path: Path) -> None:
    seg = tmp_path / "ok.wav"
    seg.write_bytes(b"data")
    data = json.dumps({
        "completed_paragraphs": [1],
        "failed_paragraphs": [],
        "segments": [{"segment_id": "s1", "file_path": str(seg)}],
        "chapter_audio_path": None,
    })
    fake = _FakeRedis(get_result=data)
    with patch.object(tts_mod, "_get_redis", return_value=fake):
        res = tts_mod.verify_checkpoint_recovery(task := _make_task(), 1, 2)
    assert res["verified"] is True


# ── stress_test_concurrent_synthesis ─────────────────────────────────────────

def test_stress_test_concurrent_synthesis() -> None:
    task = _make_task()
    submitted = MagicMock()
    submitted.id = "sub-1"

    async_res = MagicMock()
    async_res.get.return_value = {
        "status": "completed", "succeeded": 1, "failed": 0, "segments": []
    }

    def _delay(**kwargs):
        return submitted

    with patch.object(tts_mod.synthesize_chapter_task, "delay", side_effect=_delay), \
         patch.object(tts_mod.celery_app, "AsyncResult", return_value=async_res), \
         patch.object(tts_mod, "_run_synthesize_chapter_async", return_value={"status": "completed"}) as run:
        res = tts_mod.stress_test_concurrent_synthesis(task, chapter_count=2, paragraphs_per_chapter=1)
    assert res["total_chapters"] == 2
    assert len(res["results"]) == 2
    assert run.call_count == 0  # stress test only submits, does not run inline
