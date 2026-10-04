"""Manual Review Gate orchestration tests — 审核门的编排层行为.

Covers (与 test_review_gate_api.py 的 HTTP 层互补，本文件测编排逻辑):
- _enter_review_gate: 全 approved 跳过门（恢复路径关键）、进门置 pending_review、
  轮询放行、审核中取消（project 状态回写 cancelled）
- POST /start: mode=review 重置审核纪元（仅此处重置）、awaiting_review 冲突检查
- _run_auto_pipeline: mode=review 在 audio_postprocess 后进门；mode=auto 不进
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks

from src.audiobook_studio.api.auto_run import (
    AutoRunConfig,
    AutoRunStartRequest,
    _active_runs,
    _enter_review_gate,
    _run_auto_pipeline,
    start_auto_run,
)
from src.audiobook_studio.exceptions import DomainError

MODULE = "src.audiobook_studio.api.auto_run"


@pytest.fixture(autouse=True)
def clean_active_runs():
    _active_runs.clear()
    yield
    _active_runs.clear()


def _chapter(idx, review_status=None, cid=None):
    return SimpleNamespace(id=cid or idx, index=idx, review_status=review_status)


def _fake_session(chapters, committed=None):
    """Minimal async-session stand-in: execute() → chapters, commit/close tracked."""
    session = MagicMock()

    async def execute(*a, **k):
        r = MagicMock()
        r.scalars.return_value.all.return_value = chapters
        return r

    session.execute = execute

    async def commit():
        if committed is not None:
            committed.append(True)

    session.commit = commit
    session.close = AsyncMock()
    return session


def _session_factory(chapters, committed=None):
    return lambda: _fake_session(chapters, committed)


def _events():
    """Patch emit_pipeline_event, return the list of emitted event types."""
    calls = []

    async def emit(project_id, event_type, **kwargs):
        calls.append(event_type)

    return calls, emit


# ─────────────────────────────────────────────────────────────────────────────
# _enter_review_gate
# ─────────────────────────────────────────────────────────────────────────────


class TestEnterReviewGate:
    @pytest.mark.asyncio
    async def test_all_approved_skips_gate(self):
        """全部章节已 approved → 门被跳过（重启恢复路径的关键），不发 AWAITING_REVIEW。"""
        chapters = [_chapter(1, "approved"), _chapter(2, "approved")]
        with (
            patch(f"{MODULE}.create_async_session", _session_factory(chapters)),
            patch(f"{MODULE}._sync_project_progress", new=AsyncMock()) as sync_mock,
        ):
            calls, emit = _events()
            with patch(f"{MODULE}.emit_pipeline_event", emit):
                released = await _enter_review_gate(1, "run_1")

        assert released is True
        assert calls == []  # no gate events at all
        sync_mock.assert_not_called()
        # approved flags untouched
        assert all(ch.review_status == "approved" for ch in chapters)

    @pytest.mark.asyncio
    async def test_entry_marks_pending_then_release(self):
        """进门：NULL → pending_review（绝不清 approved）；轮询发现全 approved → 放行。"""
        chapters = [_chapter(1, None), _chapter(2, "approved"), _chapter(3, None)]
        committed: list = []
        _active_runs[1] = {"run_id": "run_1", "status": "running"}
        calls, emit = _events()

        original_sleep = asyncio.sleep

        async def flip_and_sleep(_seconds):
            # After the gate entry tick, approve the remaining chapters
            for ch in chapters:
                ch.review_status = "approved"

        with (
            patch(f"{MODULE}.create_async_session", _session_factory(chapters, committed)),
            patch(f"{MODULE}._sync_project_progress", new=AsyncMock()) as sync_mock,
            patch(f"{MODULE}.emit_pipeline_event", emit),
            patch(f"{MODULE}.asyncio.sleep", flip_and_sleep),
        ):
            released = await _enter_review_gate(1, "run_1")

        assert released is True
        assert committed  # entry commit happened
        # 只填 NULL，绝不清 approved —— approved 标记在 entry 前已存在且存活
        assert "awaiting_review" in calls
        assert "review_released" in calls
        assert _active_runs[1]["status"] == "running"  # released back to running
        # project row synced: awaiting_review then processing
        statuses = [c.args[2] for c in sync_mock.call_args_list]
        assert "awaiting_review" in statuses and "processing" in statuses

    @pytest.mark.asyncio
    async def test_cancel_during_gate(self):
        """审核中取消 → 门退出(False)、发 CANCELLED、project 状态回写 cancelled（防幽灵门）。"""
        chapters = [_chapter(1, None)]
        _active_runs[1] = {"run_id": "run_1", "status": "running"}
        calls, emit = _events()

        async def cancel_and_sleep(_seconds):
            _active_runs[1]["status"] = "cancelled"

        with (
            patch(f"{MODULE}.create_async_session", _session_factory(chapters)),
            patch(f"{MODULE}._sync_project_progress", new=AsyncMock()) as sync_mock,
            patch(f"{MODULE}.emit_pipeline_event", emit),
            patch(f"{MODULE}.asyncio.sleep", cancel_and_sleep),
        ):
            released = await _enter_review_gate(1, "run_1")

        assert released is False
        assert "cancelled" in calls
        # 既有 /cancel 不回写 project 状态是坑，门路径必须回写
        statuses = [c.args[2] for c in sync_mock.call_args_list]
        assert "cancelled" in statuses
        assert 1 not in _active_runs  # entry popped


# ─────────────────────────────────────────────────────────────────────────────
# POST /start: epoch reset + conflict checks
# ─────────────────────────────────────────────────────────────────────────────


class TestStartReviewMode:
    def _db(self, project, chapters):
        db = AsyncMock()
        results = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=project)),  # project lookup
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=chapters)))),
        ]

        async def execute(*a, **k):
            return results.pop(0) if results else MagicMock()

        db.execute = execute
        db.commit = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_review_mode_resets_epoch(self):
        """mode=review → 所有章节 review_status 重置 NULL（新审核纪元，仅 /start 重置）。"""
        project = SimpleNamespace(id=1)
        chapters = [_chapter(1, "approved"), _chapter(2, "pending_review"), _chapter(3, None)]
        req = AutoRunStartRequest(mode="review")
        resp = await start_auto_run(1, req, BackgroundTasks(), self._db(project, chapters))
        assert resp.status == "running"
        assert all(ch.review_status is None for ch in chapters)

    @pytest.mark.asyncio
    async def test_auto_mode_keeps_review_status(self):
        """mode=auto（默认，向后兼容）→ 不动 review_status。"""
        project = SimpleNamespace(id=1)
        chapters = [_chapter(1, "approved")]
        req = AutoRunStartRequest(mode="auto")
        resp = await start_auto_run(1, req, BackgroundTasks(), self._db(project, chapters))
        assert resp.status == "running"
        assert chapters[0].review_status == "approved"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("blocking_status", ["running", "paused", "awaiting_review"])
    async def test_conflict_when_run_active(self, blocking_status):
        """running/paused/awaiting_review 都阻止新 start（防孤儿审核门）。"""
        _active_runs[1] = {"run_id": "old", "status": blocking_status}
        project = SimpleNamespace(id=1)
        db = self._db(project, [])
        with pytest.raises(DomainError) as ei:
            await start_auto_run(1, AutoRunStartRequest(), BackgroundTasks(), db)
        assert ei.value.error_code == "CONFLICT"


# ─────────────────────────────────────────────────────────────────────────────
# _run_auto_pipeline: gate placement
# ─────────────────────────────────────────────────────────────────────────────


class TestPipelineGatePlacement:
    async def _run(self, mode):
        with (
            patch(f"{MODULE}._run_single_stage", new=AsyncMock()),
            patch(f"{MODULE}._sync_project_progress", new=AsyncMock()),
            patch(f"{MODULE}.emit_pipeline_event", new=AsyncMock()),
            patch(f"{MODULE}._get_checkpoint_manager", MagicMock()),
            patch(f"{MODULE}._enter_review_gate", new=AsyncMock(return_value=True)) as gate_mock,
        ):
            await _run_auto_pipeline(1, "run_1", AutoRunConfig(), pause_points=None, mode=mode)
            return gate_mock

    @pytest.mark.asyncio
    async def test_review_mode_enters_gate_after_audio_postprocess(self):
        gate_mock = await self._run("review")
        gate_mock.assert_awaited_once_with(1, "run_1")
        assert _active_runs[1]["status"] == "completed"
        # 门在 audio_postprocess 之后 → 合成/质检照常完成
        assert "synthesize" in _active_runs[1]["completed_stages"]

    @pytest.mark.asyncio
    async def test_auto_mode_never_enters_gate(self):
        gate_mock = await self._run("auto")
        gate_mock.assert_not_called()
        assert _active_runs[1]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_gate_cancel_stops_pipeline(self):
        """门返回 False（审核中取消）→ 流水线立即返回，不进 synthesize。"""
        with (
            patch(f"{MODULE}._run_single_stage", new=AsyncMock()),
            patch(f"{MODULE}._sync_project_progress", new=AsyncMock()),
            patch(f"{MODULE}.emit_pipeline_event", new=AsyncMock()),
            patch(f"{MODULE}._get_checkpoint_manager", MagicMock()),
            patch(f"{MODULE}._enter_review_gate", new=AsyncMock(return_value=False)),
        ):
            await _run_auto_pipeline(1, "run_1", AutoRunConfig(), pause_points=None, mode="review")
        # 门返回 False → 流水线立即返回，不进 synthesize/quality
        # (真实门的取消路径会自行弹出 run 条目；此处门被 mock，不断言条目)
        assert "synthesize" not in _active_runs[1]["completed_stages"]
        assert "quality" not in _active_runs[1]["completed_stages"]
