"""Phase 3 isolated coverage tests for ``pipeline/orchestrator.py``.

Exercises the hook registry, hook emitters, telemetry integration, the
``_sanitize_kwargs`` helper, and the async ``run_stage`` / ``run_pipeline``
coordinators. DB resolution is faked with lightweight sync/async session
stand-ins and ``StageRegistry`` / web-socket emitters are monkeypatched so
no real database or socket is touched.
"""

import asyncio
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.audiobook_studio.exceptions import AudiobookError, StageExecutionError
from src.audiobook_studio.pipeline import orchestrator as orch


# ── autouse: keep module-level hook registries & telemetry isolated ──────────

@pytest.fixture(autouse=True)
def _restore_state():
    saved = {
        "_stage_hooks": list(orch._stage_hooks),
        "_pipeline_hooks": list(orch._pipeline_hooks),
        "_async_stage_hooks": list(orch._async_stage_hooks),
        "_async_pipeline_hooks": list(orch._async_pipeline_hooks),
        "_telemetry_collector": orch._telemetry_collector,
    }
    yield
    # 原位写回（保持 list 对象同一性）：其他模块可能通过
    # ``from orchestrator import _stage_hooks`` 持有同一列表的引用，
    # 重新赋值会令其指向过期对象，造成跨文件顺序污染。
    orch._stage_hooks[:] = saved["_stage_hooks"]
    orch._pipeline_hooks[:] = saved["_pipeline_hooks"]
    orch._async_stage_hooks[:] = saved["_async_stage_hooks"]
    orch._async_pipeline_hooks[:] = saved["_async_pipeline_hooks"]
    orch._telemetry_collector = saved["_telemetry_collector"]


# ── Fake DB sessions ──────────────────────────────────────────────────────────

class FakeRow:
    id = 5
    raw_text = "chapter text"
    index = 1
    chapter_id = 5
    project_id = 1


class _AsyncResult:
    def __init__(self, obj):
        self.obj = obj

    def scalar_one_or_none(self):
        return self.obj


class FakeAsyncSession:
    def __init__(self, obj=None):
        self._obj = obj or FakeRow()

    async def execute(self, *a, **k):
        return _AsyncResult(self._obj)


class _SyncQuery:
    def filter(self, *a, **k):
        return self

    def first(self):
        return FakeRow()


class FakeSyncSession:
    def query(self, *a, **k):
        return _SyncQuery()


# ── Fake stage handler / registry ─────────────────────────────────────────────

class FakeHandler:
    def __init__(self, result=None, raise_exc=None):
        self._result = result if result is not None else {"ok": True}
        self._raise = raise_exc
        self.apersist_called = False
        self.snapshot = None

    async def run(self, **ctx):
        if self._raise:
            raise self._raise
        return self._result

    async def apersist(self, db, project_id, chapter, para, result, ci, pi):
        self.apersist_called = True

    def get_result_snapshot(self, result):
        self.snapshot = result
        return {"snap": result}


class FakeHandlerNoApersist:
    def __init__(self, result=None, raise_exc=None):
        self._result = result if result is not None else {"ok": True}
        self._raise = raise_exc
        self.snapshot = None

    async def run(self, **ctx):
        if self._raise:
            raise self._raise
        return self._result

    def get_result_snapshot(self, result):
        self.snapshot = result
        return {"snap": result}


class FakeRegistry:
    def __init__(self, handler):
        self._handler = handler

    def get(self, stage):
        return self._handler


class FakeCollector:
    def capture_stage(self, **kw):
        self.last = FakeCapture()
        return self.last


class FakeCapture:
    def set_llm_output(self, o):
        self.out = o

    def set_source(self, s):
        self.source = s


# ── Hook registration ────────────────────────────────────────────────────────

def test_register_stage_hook_dedup():
    def h(*a, **k):
        pass

    orch.register_stage_hook(h)
    n1 = len(orch._stage_hooks)
    orch.register_stage_hook(h)  # duplicate → no-op
    assert len(orch._stage_hooks) == n1


def test_register_async_stage_hook():
    async def h(*a, **k):
        pass
    orch.register_async_stage_hook(h)
    assert h in orch._async_stage_hooks


def test_register_pipeline_hook():
    def h(*a, **k):
        pass
    orch.register_pipeline_hook(h)
    assert h in orch._pipeline_hooks


def test_register_async_pipeline_hook():
    async def h(*a, **k):
        pass
    orch.register_async_pipeline_hook(h)
    assert h in orch._async_pipeline_hooks


# ── Sync emitters ─────────────────────────────────────────────────────────────

def test_emit_stage_enter():
    calls = []
    orch._stage_hooks.clear()
    orch._stage_hooks.append(lambda *a, **k: calls.append(a))
    orch._emit_stage_enter("extract", {"project_id": 1})
    assert calls and calls[0][0] == "stage_enter"


def test_emit_stage_enter_hook_error():
    def boom(*a, **k):
        raise RuntimeError("x")
    orch._stage_hooks.clear()
    orch._stage_hooks.append(boom)
    orch._emit_stage_enter("extract", {})  # must not raise


def test_emit_stage_exit():
    calls = []
    orch._stage_hooks.clear()
    orch._stage_hooks.append(lambda *a, **k: calls.append(a))
    orch._emit_stage_exit("extract", {}, result="r", error=None)
    assert calls[0][0] == "stage_exit"


def test_emit_stage_exit_with_error():
    calls = []
    orch._stage_hooks.clear()
    orch._stage_hooks.append(lambda *a, **k: calls.append(a))
    orch._emit_stage_exit("extract", {}, result=None, error=ValueError("e"))
    assert calls[0][4] is not None


def test_emit_pipeline_start():
    calls = []
    orch._pipeline_hooks.clear()
    orch._pipeline_hooks.append(lambda *a, **k: calls.append(a))
    orch._emit_pipeline_start({"project_id": 1})
    assert calls[0][0] == "pipeline_start"


def test_emit_pipeline_start_error():
    def boom(*a, **k):
        raise RuntimeError("x")
    orch._pipeline_hooks.clear()
    orch._pipeline_hooks.append(boom)
    orch._emit_pipeline_start({})


def test_emit_pipeline_end():
    calls = []
    orch._pipeline_hooks.clear()
    orch._pipeline_hooks.append(lambda *a, **k: calls.append(a))
    orch._emit_pipeline_end({}, result=[1], error=None)
    assert calls[0][0] == "pipeline_end"


def test_emit_pipeline_end_error():
    calls = []
    orch._pipeline_hooks.clear()
    orch._pipeline_hooks.append(lambda *a, **k: calls.append(a))
    orch._emit_pipeline_end({}, result=None, error=ValueError("e"))
    assert calls[0][3] is not None


# ── Async emitters ───────────────────────────────────────────────────────────

def test_async_stage_emitters():
    async def good(event, stage, ctx, result=None, error=None):
        pass

    orch._async_stage_hooks.clear()
    orch._async_stage_hooks.append(good)
    asyncio.run(orch._emit_async_stage_enter("extract", {}))
    asyncio.run(orch._emit_async_stage_exit("extract", {}, result="r", error=None))


def test_async_pipeline_emitters():
    async def good(event, ctx, result=None, error=None):
        pass

    orch._async_pipeline_hooks.clear()
    orch._async_pipeline_hooks.append(good)
    asyncio.run(orch._emit_async_pipeline_start({}))
    asyncio.run(orch._emit_async_pipeline_end({}, result=[1], error=None))


def test_async_emitters_error_branch():
    async def bad(*a, **k):
        raise RuntimeError("x")
    orch._async_stage_hooks.clear()
    orch._async_stage_hooks.append(bad)
    orch._async_pipeline_hooks.clear()
    orch._async_pipeline_hooks.append(bad)
    asyncio.run(orch._emit_async_stage_enter("extract", {}))
    asyncio.run(orch._emit_async_pipeline_start({}))


# ── Default + websocket hooks ─────────────────────────────────────────────────

def test_default_stage_hook_logs():
    orch._default_stage_hook("stage_enter", "extract", {"project_id": 1}, None, None)
    orch._default_stage_hook("stage_exit", "extract", {}, "r", ValueError("e"))


def test_websocket_hook_no_project():
    asyncio.run(orch._websocket_stage_hook("stage_enter", "extract", {}, None, None))


def test_websocket_hook_enter(monkeypatch):
    emit = AsyncMock()
    monkeypatch.setattr(orch, "emit_stage_enter", emit)
    ctx = {"project_id": 1, "chapter_index": 1, "chapter_id": 5,
           "paragraph_index": 2, "paragraph_id": 7, "kwargs": {"total_items": 3}}
    asyncio.run(orch._websocket_stage_hook("stage_enter", "extract", ctx))
    assert emit.await_count == 1


def test_websocket_hook_exit(monkeypatch):
    emit = AsyncMock()
    monkeypatch.setattr(orch, "emit_stage_exit", emit)
    ctx = {"project_id": 1, "chapter_index": 1, "chapter_id": 5,
           "paragraph_index": 2, "paragraph_id": 7}
    asyncio.run(orch._websocket_stage_hook("stage_exit", "extract", ctx, error=None))
    assert emit.await_count == 1


def test_websocket_hook_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(orch, "emit_stage_enter", boom)
    ctx = {"project_id": 1}
    asyncio.run(orch._websocket_stage_hook("stage_enter", "extract", ctx))


# ── Telemetry ─────────────────────────────────────────────────────────────────

class FakeTelemetry:
    def __init__(self, **kw):
        self.calls = []

    def on_pipeline_start(self, event, ctx, result=None, error=None):
        self.calls.append(event)

    def on_pipeline_end(self, event, ctx, result=None, error=None):
        self.calls.append(event)

    def on_stage_enter(self, event, stage, ctx, result=None, error=None):
        pass

    def on_stage_exit(self, event, stage, ctx, result=None, error=None):
        pass

    def get_summary(self):
        return {"summary": True}


def test_get_telemetry_none():
    assert orch.get_telemetry() is None


def test_shutdown_telemetry_none():
    assert orch.shutdown_telemetry() is None


def test_init_telemetry_unavailable(monkeypatch):
    monkeypatch.setattr(orch, "_TELEMETRY_AVAILABLE", False)
    assert orch.init_telemetry("p1") is None


def test_init_telemetry_and_shutdown(monkeypatch):
    monkeypatch.setattr(orch, "_TELEMETRY_AVAILABLE", True)
    monkeypatch.setattr(orch, "TelemetryCollector", FakeTelemetry)
    collector = orch.init_telemetry("p1")
    assert collector is not None
    assert orch.get_telemetry() is collector
    # hooks registered
    assert any(collector.on_pipeline_start == h for h in orch._pipeline_hooks)
    summary = orch.shutdown_telemetry()
    assert summary == {"summary": True}
    assert orch.get_telemetry() is None


# ── _sanitize_kwargs ──────────────────────────────────────────────────────────

def test_sanitize_kwargs_pydantic():
    class M:
        def model_dump(self):
            return {"a": 1}
    assert orch._sanitize_kwargs({"m": M()}) == {"m": {"a": 1}}


def test_sanitize_kwargs_object():
    class O:
        pass
    o = O()
    assert orch._sanitize_kwargs({"o": o}) == {"o": str(o)}


def test_sanitize_kwargs_plain():
    assert orch._sanitize_kwargs({"x": 5}) == {"x": 5}


# ── run_stage ─────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_registry(monkeypatch):
    handler = FakeHandler()
    monkeypatch.setattr(orch.StageRegistry, "get", lambda stage: handler)
    monkeypatch.setattr(orch, "pause_check", AsyncMock(return_value=False))
    monkeypatch.setattr(orch, "emit_stage_enter", AsyncMock())
    monkeypatch.setattr(orch, "emit_stage_exit", AsyncMock())
    return handler


@pytest.mark.asyncio
async def test_run_stage_basic(fake_registry, monkeypatch):
    monkeypatch.setattr(orch, "AsyncSession", FakeAsyncSession)
    result = await orch.run_stage("extract", FakeAsyncSession(), project_id=None)
    assert result == {"ok": True}
    assert fake_registry.apersist_called is True


@pytest.mark.asyncio
async def test_run_stage_no_apersist(fake_registry, monkeypatch):
    handler = FakeHandlerNoApersist()
    monkeypatch.setattr(orch.StageRegistry, "get", lambda stage: handler)
    monkeypatch.setattr(orch, "AsyncSession", FakeAsyncSession)
    result = await orch.run_stage("extract", FakeAsyncSession(), project_id=None)
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_run_stage_with_feedback(fake_registry, monkeypatch):
    monkeypatch.setattr(orch, "AsyncSession", FakeAsyncSession)
    collector = FakeCollector()
    result = await orch.run_stage("extract", FakeAsyncSession(), project_id=1, feedback_collector=collector)
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_run_stage_quality_feedback(fake_registry, monkeypatch):
    monkeypatch.setattr(orch, "AsyncSession", FakeAsyncSession)
    collector = FakeCollector()
    await orch.run_stage("quality", FakeAsyncSession(), project_id=1, feedback_collector=collector)
    # capture source set to "quality_judge"
    assert collector.last.source == "quality_judge"


@pytest.mark.asyncio
async def test_run_stage_chapter_by_id(fake_registry, monkeypatch):
    monkeypatch.setattr(orch, "AsyncSession", FakeAsyncSession)
    result = await orch.run_stage("extract", FakeAsyncSession(), project_id=1, chapter_id=5)
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_run_stage_chapter_by_index(fake_registry, monkeypatch):
    monkeypatch.setattr(orch, "AsyncSession", FakeAsyncSession)
    result = await orch.run_stage("extract", FakeAsyncSession(), project_id=1, chapter_index=2)
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_run_stage_para_by_id(fake_registry, monkeypatch):
    monkeypatch.setattr(orch, "AsyncSession", FakeAsyncSession)
    result = await orch.run_stage("annotate", FakeAsyncSession(), project_id=1, chapter_id=5, paragraph_id=7)
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_run_stage_para_by_index(fake_registry, monkeypatch):
    monkeypatch.setattr(orch, "AsyncSession", FakeAsyncSession)
    result = await orch.run_stage("annotate", FakeAsyncSession(), project_id=1, chapter_id=5, paragraph_index=3)
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_run_stage_analyze_injects_raw_text(fake_registry, monkeypatch):
    monkeypatch.setattr(orch, "AsyncSession", FakeAsyncSession)
    captured = {}

    async def run(**ctx):
        captured.update(ctx)
        return {"ok": True}
    handler = FakeHandler()
    handler.run = run
    monkeypatch.setattr(orch.StageRegistry, "get", lambda stage: handler)
    await orch.run_stage("analyze", FakeAsyncSession(), project_id=1, chapter_id=5)
    assert captured.get("raw_text") == "chapter text"


@pytest.mark.asyncio
async def test_run_stage_analyze_raw_text_present(fake_registry, monkeypatch):
    monkeypatch.setattr(orch, "AsyncSession", FakeAsyncSession)
    captured = {}

    async def run(**ctx):
        captured.update(ctx)
        return {"ok": True}
    handler = FakeHandler()
    handler.run = run
    monkeypatch.setattr(orch.StageRegistry, "get", lambda stage: handler)
    await orch.run_stage("analyze", FakeAsyncSession(), project_id=1, chapter_id=5, raw_text="preset")
    assert captured.get("raw_text") == "preset"


@pytest.mark.asyncio
async def test_run_stage_paused(fake_registry, monkeypatch):
    monkeypatch.setattr(orch, "AsyncSession", FakeAsyncSession)
    monkeypatch.setattr(orch, "pause_check", AsyncMock(return_value=True))
    result = await orch.run_stage("extract", FakeAsyncSession(), project_id=1)
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_run_stage_sync_chapter_by_id(fake_registry, monkeypatch):
    monkeypatch.setattr(orch, "Session", FakeSyncSession)
    result = await orch.run_stage("extract", FakeSyncSession(), project_id=1, chapter_id=5)
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_run_stage_sync_chapter_by_index(fake_registry, monkeypatch):
    monkeypatch.setattr(orch, "Session", FakeSyncSession)
    result = await orch.run_stage("extract", FakeSyncSession(), project_id=1, chapter_index=2)
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_run_stage_sync_para_by_index(fake_registry, monkeypatch):
    monkeypatch.setattr(orch, "Session", FakeSyncSession)
    result = await orch.run_stage("annotate", FakeSyncSession(), project_id=1, chapter_id=5, paragraph_index=3)
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_run_stage_value_error(monkeypatch):
    monkeypatch.setattr(orch.StageRegistry, "get", lambda stage: (_ for _ in ()).throw(ValueError("unknown")))
    monkeypatch.setattr(orch, "pause_check", AsyncMock(return_value=False))
    monkeypatch.setattr(orch, "emit_stage_enter", AsyncMock())
    monkeypatch.setattr(orch, "emit_stage_exit", AsyncMock())
    with pytest.raises(StageExecutionError):
        await orch.run_stage("bogus", FakeAsyncSession(), project_id=None)


@pytest.mark.asyncio
async def test_run_stage_audiobook_error(monkeypatch):
    handler = FakeHandler(raise_exc=AudiobookError(message="boom", error_code="E_TEST", stage="extract"))
    monkeypatch.setattr(orch.StageRegistry, "get", lambda stage: handler)
    monkeypatch.setattr(orch, "pause_check", AsyncMock(return_value=False))
    monkeypatch.setattr(orch, "emit_stage_enter", AsyncMock())
    monkeypatch.setattr(orch, "emit_stage_exit", AsyncMock())
    with pytest.raises(AudiobookError):
        await orch.run_stage("extract", FakeAsyncSession(), project_id=None)


@pytest.mark.asyncio
async def test_run_stage_generic_error(monkeypatch):
    handler = FakeHandler(raise_exc=RuntimeError("boom"))
    monkeypatch.setattr(orch.StageRegistry, "get", lambda stage: handler)
    monkeypatch.setattr(orch, "pause_check", AsyncMock(return_value=False))
    monkeypatch.setattr(orch, "emit_stage_enter", AsyncMock())
    monkeypatch.setattr(orch, "emit_stage_exit", AsyncMock())
    with pytest.raises(StageExecutionError):
        await orch.run_stage("extract", FakeAsyncSession(), project_id=None)


# ── run_pipeline ──────────────────────────────────────────────────────────────

@pytest.fixture
def fake_pipeline(monkeypatch):
    mock = AsyncMock(side_effect=lambda stage, db, **kw: f"result:{stage}")
    monkeypatch.setattr(orch, "run_stage", mock)
    monkeypatch.setattr(orch, "is_paused", lambda pid: False)
    monkeypatch.setattr(orch, "pause_check", AsyncMock(return_value=None))
    monkeypatch.setattr(orch, "emit_chapter_complete", AsyncMock())
    monkeypatch.setattr(orch, "emit_pipeline_completed", AsyncMock())
    monkeypatch.setattr(orch, "emit_error", AsyncMock())
    return mock


class FakeCheckpoint:
    def __init__(self, done_map=None):
        self.done_map = done_map or {}
        self.started = []
        self.done = []

    def is_stage_done(self, stage, ci, pi):
        return self.done_map.get(stage, False)

    def mark_stage_started(self, stage, ci, pi):
        self.started.append(stage)

    def mark_stage_done(self, stage, ci, pi):
        self.done.append(stage)


@pytest.mark.asyncio
async def test_run_pipeline_basic(fake_pipeline):
    results = await orch.run_pipeline(["a", "b"], FakeAsyncSession(), project_id=1, chapter_index=1)
    assert results == ["result:a", "result:b"]
    assert orch.emit_chapter_complete.call_count >= 1


@pytest.mark.asyncio
async def test_run_pipeline_paused(fake_pipeline):
    orch.is_paused = lambda pid: True
    results = await orch.run_pipeline(["a"], FakeAsyncSession(), project_id=1, chapter_index=1)
    assert results == ["result:a"]


@pytest.mark.asyncio
async def test_run_pipeline_checkpoint_skip(fake_pipeline):
    cp = FakeCheckpoint(done_map={"a": True})
    results = await orch.run_pipeline(["a", "b"], FakeAsyncSession(), project_id=1, chapter_index=1,
                                      checkpoint_manager=cp)
    assert results == [None, "result:b"]
    assert "b" in cp.started and "b" in cp.done


@pytest.mark.asyncio
async def test_run_pipeline_checkpoint_all_done(fake_pipeline):
    cp = FakeCheckpoint(done_map={"a": True, "b": True})
    results = await orch.run_pipeline(["a", "b"], FakeAsyncSession(), project_id=1, chapter_index=1,
                                      checkpoint_manager=cp)
    assert results == []


@pytest.mark.asyncio
async def test_run_pipeline_error(fake_pipeline):
    orch.run_stage = AsyncMock(side_effect=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        await orch.run_pipeline(["a"], FakeAsyncSession(), project_id=1, chapter_index=1)
    assert orch.emit_error.call_count >= 1
