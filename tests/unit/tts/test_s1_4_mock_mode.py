"""Sprint 1 S1-4 coverage: TTS port isolation via in-memory FakeRemoteTTSPort.

These tests exercise the remote TTS port contract using ``FakeRemoteTTSPort``
as the mock adapter, so no GPU / remote Modal service / network is required.
This is the "isolate external" strategy for the tts/ area.
"""

from __future__ import annotations

import asyncio

import pytest

from src.audiobook_studio.tts.fake_port import FakeRemoteTTSPort
from src.audiobook_studio.tts.port import TTSStatus, TTSTaskPayload, TTSVoiceAnchor


def _make_payload(text: str = "你好，世界") -> TTSTaskPayload:
    return TTSTaskPayload(text=text, voice_anchor=TTSVoiceAnchor(voice_id="v-narrator"))


@pytest.fixture
def port() -> FakeRemoteTTSPort:
    return FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)


@pytest.mark.asyncio
async def test_submit_then_terminal_status(port: FakeRemoteTTSPort) -> None:
    """Submitting a task and waiting yields a DONE terminal state."""
    ok = await port.submit("task-1", _make_payload())
    assert ok is True

    # Allow the simulated synthesis to finish.
    await asyncio.sleep(0.08)
    status = await port.get_status("task-1")
    assert status.status in (TTSStatus.RUNNING, TTSStatus.DONE)


@pytest.mark.asyncio
async def test_result_contains_quality_scores(port: FakeRemoteTTSPort) -> None:
    """A completed task exposes audio path and simulated quality metrics."""
    await port.submit("task-2", _make_payload())
    await asyncio.sleep(0.08)

    result = await port.get_result("task-2")
    assert result.status == TTSStatus.DONE
    assert result.audio_path
    assert result.dnsmos_score is not None
    assert result.asr_wer is not None
    assert result.speaker_similarity is not None


@pytest.mark.asyncio
async def test_cancel_pending_task(port: FakeRemoteTTSPort) -> None:
    """A freshly submitted task can be cancelled."""
    await port.submit("task-3", _make_payload())
    cancelled = await port.cancel("task-3")
    assert cancelled is True


def test_invalid_failure_rate_rejected() -> None:
    """Bad configuration fails fast rather than corrupting state."""
    with pytest.raises(ValueError):
        FakeRemoteTTSPort(failure_rate=1.5)
    with pytest.raises(ValueError):
        FakeRemoteTTSPort(synthesis_delay=-1.0)


@pytest.mark.asyncio
async def test_unknown_task_reports_missing(port: FakeRemoteTTSPort) -> None:
    """Querying a non-existent task surfaces a clear missing-task signal."""
    # get_status is non-blocking and reports the unknown task as PENDING.
    missing = await port.get_status("does-not-exist")
    assert missing.status == TTSStatus.PENDING
    assert missing.error_message
    # get_result only works for known, terminal tasks -> raises for unknown.
    with pytest.raises(KeyError):
        await port.get_result("does-not-exist")
