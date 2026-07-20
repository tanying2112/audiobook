"""Unit tests for RemoteTTSPort contract and Fake implementation.

Tests cover:
- State machine transitions (PENDING -> RUNNING -> DONE/FAILED)
- Payload validation and contract enforcement
- Error capture and propagation
- Concurrency safety
- Cancellation behavior
- Health check reporting
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.audiobook_studio.tts.fake_port import FakeRemoteTTSPort, MockRemoteTTSPort
from src.audiobook_studio.tts.port import (
    RemoteTTSPort,
    TTSProsody,
    TTSStatus,
    TTSTaskPayload,
    TTSTaskResult,
    TTSTaskStatus,
    TTSVoiceAnchor,
)


# Module-level fixtures available to all test classes
@pytest.fixture
def payload() -> TTSTaskPayload:
    """Standard test payload."""
    return TTSTaskPayload(
        text="Test synthesis text",
        voice_anchor=TTSVoiceAnchor(voice_id="voice_001", speaker_name="Test Speaker"),
        prosody=TTSProsody(rate=1.0, emotion="neutral"),
    )


@pytest.fixture
def payload_v2() -> TTSTaskPayload:
    """Second test payload for isolation tests."""
    return TTSTaskPayload(
        text="Test synthesis text 2",
        voice_anchor=TTSVoiceAnchor(voice_id="voice_002", speaker_name="Test Speaker 2"),
        prosody=TTSProsody(rate=1.2, emotion="happy"),
    )


class TestTTSVoiceAnchor:
    """Tests for TTSVoiceAnchor dataclass."""

    def test_valid_voice_anchor(self):
        anchor = TTSVoiceAnchor(voice_id="voice_001", speaker_name="Alice", language="zh-CN")
        assert anchor.voice_id == "voice_001"
        assert anchor.speaker_name == "Alice"
        assert anchor.language == "zh-CN"

    def test_voice_anchor_defaults(self):
        anchor = TTSVoiceAnchor(voice_id="voice_001")
        assert anchor.speaker_name is None
        assert anchor.language == "zh-CN"
        assert anchor.reference_audio_path is None

    def test_empty_voice_id_raises(self):
        with pytest.raises(ValueError, match="voice_id must be non-empty"):
            TTSVoiceAnchor(voice_id="")
        with pytest.raises(ValueError, match="voice_id must be non-empty"):
            TTSVoiceAnchor(voice_id="   ")


class TestTTSProsody:
    """Tests for TTSProsody dataclass."""

    def test_default_prosody(self):
        prosody = TTSProsody()
        assert prosody.rate == 1.0
        assert prosody.pitch == 0.0
        assert prosody.volume == 0.0
        assert prosody.emotion is None

    def test_custom_prosody(self):
        prosody = TTSProsody(rate=1.5, pitch=2.0, volume=-3.0, emotion="happy")
        assert prosody.rate == 1.5
        assert prosody.pitch == 2.0
        assert prosody.volume == -3.0
        assert prosody.emotion == "happy"


class TestTTSTaskPayload:
    """Tests for TTSTaskPayload dataclass."""

    def test_valid_payload(self):
        anchor = TTSVoiceAnchor(voice_id="voice_001")
        prosody = TTSProsody(rate=1.2, emotion="neutral")
        payload = TTSTaskPayload(text="Hello world", voice_anchor=anchor, prosody=prosody)
        assert payload.text == "Hello world"
        assert payload.voice_anchor == anchor
        assert payload.prosody == prosody

    def test_empty_text_raises(self):
        anchor = TTSVoiceAnchor(voice_id="voice_001")
        with pytest.raises(ValueError, match="text must be non-empty"):
            TTSTaskPayload(text="", voice_anchor=anchor)
        with pytest.raises(ValueError, match="text must be non-empty"):
            TTSTaskPayload(text="   ", voice_anchor=anchor)

    def test_invalid_voice_anchor_raises(self):
        with pytest.raises(TypeError, match="voice_anchor must be TTSVoiceAnchor instance"):
            TTSTaskPayload(text="Hello", voice_anchor="not-an-anchor")

    def test_metadata_default_factory(self):
        anchor = TTSVoiceAnchor(voice_id="voice_001")
        payload1 = TTSTaskPayload(text="Hello", voice_anchor=anchor)
        payload2 = TTSTaskPayload(text="Hello", voice_anchor=anchor)
        # Each should get a fresh dict
        payload1.metadata["key"] = "value"
        assert "key" not in payload2.metadata


class TestTTSTaskStatus:
    """Tests for TTSTaskStatus dataclass."""

    def test_status_creation(self):
        status = TTSTaskStatus(task_id="task-1", status=TTSStatus.RUNNING, progress=0.5)
        assert status.task_id == "task-1"
        assert status.status == TTSStatus.RUNNING
        assert status.progress == 0.5
        assert status.error_message is None
        assert status.dnsmos_score is None

    def test_status_with_optional_fields(self):
        status = TTSTaskStatus(
            task_id="task-1",
            status=TTSStatus.FAILED,
            error_message="Connection timeout",
            dnsmos_score=3.8,
        )
        assert status.error_message == "Connection timeout"
        assert status.dnsmos_score == 3.8


class TestTTSTaskResult:
    """Tests for TTSTaskResult dataclass."""

    def test_result_done(self):
        result = TTSTaskResult(
            task_id="task-1",
            status=TTSStatus.DONE,
            audio_path="r2://bucket/audio.wav",
            duration_ms=5000,
            dnsmos_score=4.2,
            asr_wer=0.02,
            speaker_similarity=0.96,
            started_at="2024-01-01T00:00:00Z",
            completed_at="2024-01-01T00:00:05Z",
        )
        assert result.status == TTSStatus.DONE
        assert result.audio_path == "r2://bucket/audio.wav"
        assert result.duration_ms == 5000
        assert result.dnsmos_score == 4.2
        assert result.asr_wer == 0.02
        assert result.speaker_similarity == 0.96

    def test_result_failed(self):
        result = TTSTaskResult(
            task_id="task-1",
            status=TTSStatus.FAILED,
            error_message="GPU OOM",
            started_at="2024-01-01T00:00:00Z",
            completed_at="2024-01-01T00:00:01Z",
        )
        assert result.status == TTSStatus.FAILED
        assert result.error_message == "GPU OOM"
        assert result.audio_path is None
        assert result.dnsmos_score is None


class TestFakeRemoteTTSPort:
    """Tests for FakeRemoteTTSPort implementation."""

    @pytest.fixture
    def port(self):
        return FakeRemoteTTSPort(synthesis_delay=0.05, simulate_progress=False)

    @pytest.mark.asyncio
    async def test_submit_returns_true_for_new_task(self, port, payload):
        result = await port.submit("task-1", payload)
        assert result is True

    @pytest.mark.asyncio
    async def test_submit_returns_false_for_duplicate_task_id(self, port, payload):
        await port.submit("task-1", payload)
        result = await port.submit("task-1", payload)
        assert result is False

    @pytest.mark.asyncio
    async def test_submit_validates_payload(self, port):
        with pytest.raises(ValueError, match="text must be non-empty"):
            await port.submit("task-1", TTSTaskPayload(text="", voice_anchor=TTSVoiceAnchor(voice_id="v1")))

    @pytest.mark.asyncio
    async def test_status_pending_immediately_after_submit(self, port, payload):
        await port.submit("task-1", payload)
        status = await port.get_status("task-1")
        assert status.status == TTSStatus.PENDING
        assert status.task_id == "task-1"

    @pytest.mark.asyncio
    async def test_state_transition_pending_to_running_to_done(self, port, payload):
        await port.submit("task-1", payload)

        # Wait for processing
        await asyncio.sleep(0.1)

        status = await port.get_status("task-1")
        assert status.status in (TTSStatus.RUNNING, TTSStatus.DONE)

        if status.status == TTSStatus.DONE:
            result = await port.get_result("task-1")
            assert result.status == TTSStatus.DONE

    @pytest.mark.asyncio
    async def test_get_result_after_done(self, port, payload):
        await port.submit("task-1", payload)
        await asyncio.sleep(0.1)

        result = await port.get_result("task-1")
        assert result.status == TTSStatus.DONE
        assert result.task_id == "task-1"
        assert result.audio_path is not None
        assert result.duration_ms is not None

    @pytest.mark.asyncio
    async def test_get_result_raises_for_non_terminal(self, port, payload):
        await port.submit("task-1", payload)
        with pytest.raises(KeyError, match="not yet terminal"):
            await port.get_result("task-1")

    @pytest.mark.asyncio
    async def test_get_result_raises_for_unknown_task(self, port):
        with pytest.raises(KeyError, match="not found"):
            await port.get_result("unknown-task")

    @pytest.mark.asyncio
    async def test_cancel_pending_task(self, port, payload):
        await port.submit("task-1", payload)
        # Cancel before processing starts
        result = await port.cancel("task-1")
        assert result is True

        # Task should eventually show as cancelled
        await asyncio.sleep(0.05)
        status = await port.get_status("task-1")
        assert status.status == TTSStatus.FAILED
        assert "Cancelled" in (status.error_message or "")

    @pytest.mark.asyncio
    async def test_cancel_running_task(self, port, payload):
        port = FakeRemoteTTSPort(synthesis_delay=0.5, simulate_progress=True)
        await port.submit("task-1", payload)
        await asyncio.sleep(0.05)  # Let it start running

        result = await port.cancel("task-1")
        assert result is True

        await asyncio.sleep(0.05)
        status = await port.get_status("task-1")
        assert status.status == TTSStatus.FAILED
        assert "Cancelled" in (status.error_message or "")

    @pytest.mark.asyncio
    async def test_cancel_done_task_returns_false(self, port, payload):
        await port.submit("task-1", payload)
        await asyncio.sleep(0.15)  # Wait for completion

        result = await port.cancel("task-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_unknown_task_returns_false(self, port):
        result = await port.cancel("unknown-task")
        assert result is False

    @pytest.mark.asyncio
    async def test_failure_rate_injection(self, payload):
        port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=1.0)
        await port.submit("task-1", payload)
        await asyncio.sleep(0.05)

        status = await port.get_status("task-1")
        assert status.status == TTSStatus.FAILED

    @pytest.mark.asyncio
    async def test_custom_failure_mode(self, payload):
        def fail_on_long_text(p: TTSTaskPayload) -> bool:
            return len(p.text) > 10

        port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_mode=fail_on_long_text)
        await port.submit("task-1", payload)
        await asyncio.sleep(0.05)

        status = await port.get_status("task-1")
        assert status.status == TTSStatus.FAILED

    @pytest.mark.asyncio
    async def test_success_with_custom_failure_mode(self, payload_v2):
        """Short text should succeed even with failure mode."""

        def fail_on_long_text(p: TTSTaskPayload) -> bool:
            return len(p.text) > 10

        port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_mode=fail_on_long_text)
        short_payload = TTSTaskPayload(
            text="Hi",  # Short text
            voice_anchor=TTSVoiceAnchor(voice_id="v1"),
        )
        await port.submit("task-1", short_payload)
        await asyncio.sleep(0.05)

        status = await port.get_status("task-1")
        assert status.status == TTSStatus.DONE

    @pytest.mark.asyncio
    async def test_quality_scores_in_result(self, payload):
        custom_scores = {"dnsmos": 4.5, "wer": 0.01, "speaker_sim": 0.99}
        port = FakeRemoteTTSPort(synthesis_delay=0.01, quality_scores=custom_scores)
        await port.submit("task-1", payload)
        await asyncio.sleep(0.05)

        result = await port.get_result("task-1")
        assert result.dnsmos_score == 4.5
        assert result.asr_wer == 0.01
        assert result.speaker_similarity == 0.99

    @pytest.mark.asyncio
    async def test_health_check_returns_queue_stats(self, port, payload):
        await port.submit("task-1", payload)
        await port.submit("task-2", payload)

        health = await port.health_check()
        assert health["healthy"] is True
        assert "pending_count" in health
        assert "running_count" in health
        assert "done_count" in health
        assert "failed_count" in health
        assert health["total_count"] == 2

    @pytest.mark.asyncio
    async def test_concurrent_submits(self):
        port = FakeRemoteTTSPort(synthesis_delay=0.01)
        payload = TTSTaskPayload(text="Test", voice_anchor=TTSVoiceAnchor(voice_id="v1"))

        tasks = [port.submit(f"task-{i}", payload) for i in range(10)]
        results = await asyncio.gather(*tasks)
        assert all(results)
        assert len(port._tasks) == 10

    @pytest.mark.asyncio
    async def test_concurrent_status_polls(self, port, payload):
        await port.submit("task-1", payload)

        async def poll():
            return await port.get_status("task-1")

        results = await asyncio.gather(*[poll() for _ in range(20)])
        assert all(r.task_id == "task-1" for r in results)

    @pytest.mark.asyncio
    async def test_close_cancels_background_tasks(self):
        port = FakeRemoteTTSPort(synthesis_delay=10.0)  # Very long delay
        payload = TTSTaskPayload(text="Test", voice_anchor=TTSVoiceAnchor(voice_id="v1"))
        await port.submit("task-1", payload)
        await asyncio.sleep(0.01)

        await port.close()
        # Background tasks should be cancelled
        assert len(port._background_tasks) == 0

    @pytest.mark.asyncio
    async def test_reset_clears_all_tasks(self, port, payload):
        await port.submit("task-1", payload)
        await port.submit("task-2", payload)
        assert len(port._tasks) == 2

        port.reset()
        assert len(port._tasks) == 0


class TestMockRemoteTTSPort:
    """Tests for MockRemoteTTSPort implementation."""

    @pytest.fixture
    def mock_port(self):
        return MockRemoteTTSPort()

    @pytest.fixture
    def payload(self):
        return TTSTaskPayload(text="Test", voice_anchor=TTSVoiceAnchor(voice_id="v1"))

    @pytest.mark.asyncio
    async def test_submit_returns_configured_value(self, mock_port, payload):
        mock_port.set_submit_return(True)
        assert await mock_port.submit("task-1", payload) is True

        mock_port.set_submit_return(False)
        assert await mock_port.submit("task-1", payload) is False

    @pytest.mark.asyncio
    async def test_submit_raises_configured_exception(self, mock_port, payload):
        mock_port.set_submit_side_effect(RuntimeError("Service unavailable"))
        with pytest.raises(RuntimeError, match="Service unavailable"):
            await mock_port.submit("task-1", payload)

    @pytest.mark.asyncio
    async def test_get_status_returns_configured_status(self, mock_port):
        custom_status = TTSTaskStatus(task_id="task-1", status=TTSStatus.RUNNING, progress=0.5)
        mock_port.set_status_return(custom_status)

        status = await mock_port.get_status("task-1")
        assert status == custom_status

    @pytest.mark.asyncio
    async def test_get_result_returns_configured_result(self, mock_port):
        custom_result = TTSTaskResult(task_id="task-1", status=TTSStatus.DONE, audio_path="r2://test.wav")
        mock_port.set_result_return(custom_result)

        result = await mock_port.get_result("task-1")
        assert result == custom_result

    @pytest.mark.asyncio
    async def test_get_result_raises_configured_exception(self, mock_port):
        mock_port.set_result_side_effect(KeyError("Not found"))
        with pytest.raises(KeyError, match="Not found"):
            await mock_port.get_result("task-1")

    @pytest.mark.asyncio
    async def test_cancel_returns_configured_value(self, mock_port):
        mock_port.set_cancel_return(True)
        assert await mock_port.cancel("task-1") is True
        mock_port.set_cancel_return(False)
        assert await mock_port.cancel("task-1") is False

    @pytest.mark.asyncio
    async def test_health_check_returns_configured_value(self, mock_port):
        mock_port.set_health_return({"healthy": False, "latency_ms": 999})
        health = await mock_port.health_check()
        assert health["healthy"] is False
        assert health["latency_ms"] == 999

    @pytest.mark.asyncio
    async def test_call_log_tracks_invocations(self, mock_port, payload):
        mock_port.set_result_return(TTSTaskResult(task_id="task-1", status=TTSStatus.DONE))
        await mock_port.submit("task-1", payload)
        await mock_port.get_status("task-1")
        await mock_port.get_result("task-1")
        await mock_port.cancel("task-1")
        await mock_port.health_check()
        await mock_port.close()

        log = mock_port.get_call_log()
        assert len(log) == 6
        assert log[0][0] == "submit"
        assert log[1][0] == "get_status"
        assert log[2][0] == "get_result"
        assert log[3][0] == "cancel"
        assert log[4][0] == "health_check"
        assert log[5][0] == "close"

    @pytest.mark.asyncio
    async def test_call_log_can_be_reset(self, mock_port, payload):
        await mock_port.submit("task-1", payload)
        mock_port.reset_call_log()
        assert mock_port.get_call_log() == []


class TestTTSStatusEnum:
    """Tests for TTSStatus enum."""

    def test_status_values(self):
        assert TTSStatus.PENDING.value == "PENDING"
        assert TTSStatus.RUNNING.value == "RUNNING"
        assert TTSStatus.DONE.value == "DONE"
        assert TTSStatus.FAILED.value == "FAILED"

    def test_status_is_string_enum(self):
        assert isinstance(TTSStatus.PENDING, str)
        assert TTSStatus.PENDING == "PENDING"


class TestPortContractCompliance:
    """Tests ensuring Fake and Mock ports comply with RemoteTTSPort ABC."""

    def test_fake_port_is_subclass(self):
        assert issubclass(FakeRemoteTTSPort, RemoteTTSPort)

    def test_mock_port_is_subclass(self):
        assert issubclass(MockRemoteTTSPort, RemoteTTSPort)

    @pytest.mark.asyncio
    async def test_fake_port_implements_all_abstract_methods(self):
        port = FakeRemoteTTSPort(synthesis_delay=0.01)
        payload = TTSTaskPayload(text="Test", voice_anchor=TTSVoiceAnchor(voice_id="v1"))

        # All methods should be callable without NotImplementedError
        await port.submit("task-1", payload)
        await port.get_status("task-1")
        await asyncio.sleep(0.02)
        await port.get_result("task-1")
        await port.cancel("task-1")
        await port.health_check()
        await port.close()

    @pytest.mark.asyncio
    async def test_mock_port_implements_all_abstract_methods(self):
        port = MockRemoteTTSPort()
        payload = TTSTaskPayload(text="Test", voice_anchor=TTSVoiceAnchor(voice_id="v1"))

        port.set_result_return(TTSTaskResult(task_id="task-1", status=TTSStatus.DONE))

        await port.submit("task-1", payload)
        await port.get_status("task-1")
        await port.get_result("task-1")
        await port.cancel("task-1")
        await port.health_check()
        await port.close()


class TestStateMachineInvariants:
    """Tests for state machine invariants in FakeRemoteTTSPort."""

    @pytest.mark.asyncio
    async def test_no_backward_transitions(self, payload):
        port = FakeRemoteTTSPort(synthesis_delay=0.05)
        await port.submit("task-1", payload)

        seen_states = []
        for _ in range(20):
            status = await port.get_status("task-1")
            seen_states.append(status.status)
            await asyncio.sleep(0.01)

        # Verify no backward transitions
        state_order = [TTSStatus.PENDING, TTSStatus.RUNNING, TTSStatus.DONE]
        for i in range(1, len(seen_states)):
            if seen_states[i] != seen_states[i - 1]:
                prev_idx = state_order.index(seen_states[i - 1])
                curr_idx = state_order.index(seen_states[i])
                assert curr_idx >= prev_idx, f"Backward transition: {seen_states[i-1]} -> {seen_states[i]}"

    @pytest.mark.asyncio
    async def test_failed_can_only_go_to_pending_via_manual_retry(self, payload):
        port = FakeRemoteTTSPort(synthesis_delay=0.05, failure_rate=1.0)
        await port.submit("task-1", payload)
        await asyncio.sleep(0.1)

        status = await port.get_status("task-1")
        assert status.status == TTSStatus.FAILED

        # No automatic retry - stays FAILED
        await asyncio.sleep(0.05)
        status = await port.get_status("task-1")
        assert status.status == TTSStatus.FAILED

    @pytest.mark.asyncio
    async def test_done_is_terminal(self, payload):
        port = FakeRemoteTTSPort(synthesis_delay=0.05)
        await port.submit("task-1", payload)
        await asyncio.sleep(0.15)

        result1 = await port.get_result("task-1")
        await asyncio.sleep(0.05)
        result2 = await port.get_result("task-1")

        # Result should be stable
        assert result1.audio_path == result2.audio_path
        assert result1.dnsmos_score == result2.dnsmos_score


class TestPayloadContractEnforcement:
    """Tests for payload validation and contract enforcement."""

    @pytest.mark.asyncio
    async def test_text_whitespace_rejected(self):
        port = FakeRemoteTTSPort(synthesis_delay=0.01)
        anchor = TTSVoiceAnchor(voice_id="v1")

        with pytest.raises(ValueError, match="text must be non-empty"):
            await port.submit("task-1", TTSTaskPayload(text="  \n\t  ", voice_anchor=anchor))

    @pytest.mark.asyncio
    async def test_voice_anchor_immutability(self):
        anchor = TTSVoiceAnchor(voice_id="v1", speaker_name="Original")
        payload = TTSTaskPayload(text="Test", voice_anchor=anchor)

        # Original anchor should not be affected by any processing
        assert anchor.speaker_name == "Original"
        assert payload.voice_anchor.speaker_name == "Original"

    @pytest.mark.asyncio
    async def test_metadata_isolation_between_tasks(self, payload, payload_v2):
        port = FakeRemoteTTSPort(synthesis_delay=0.01)
        payload1 = TTSTaskPayload(text="Test 1", voice_anchor=TTSVoiceAnchor(voice_id="v1"))
        payload2 = TTSTaskPayload(text="Test 2", voice_anchor=TTSVoiceAnchor(voice_id="v2"))
        payload1.metadata["custom"] = "value1"
        payload2.metadata["custom"] = "value2"

        await port.submit("task-1", payload1)
        await port.submit("task-2", payload2)

        # Each payload keeps its own metadata
        assert port.get_task_state("task-1").payload.metadata["custom"] == "value1"
        assert port.get_task_state("task-2").payload.metadata["custom"] == "value2"


class TestProgressSimulation:
    """Tests for progress simulation during RUNNING state."""

    @pytest.mark.asyncio
    async def test_progress_increases_monotonically(self, payload):
        port = FakeRemoteTTSPort(synthesis_delay=0.2, simulate_progress=True)
        await port.submit("task-1", payload)

        progress_values = []
        for _ in range(10):
            status = await port.get_status("task-1")
            if status.progress is not None:
                progress_values.append(status.progress)
            await asyncio.sleep(0.02)

        # Progress should be monotonic (or None before RUNNING)
        filtered = [p for p in progress_values if p is not None]
        for i in range(1, len(filtered)):
            assert filtered[i] >= filtered[i - 1], "Progress should not decrease"

    @pytest.mark.asyncio
    async def test_progress_reaches_one_on_completion(self, payload):
        port = FakeRemoteTTSPort(synthesis_delay=0.1, simulate_progress=True)
        await port.submit("task-1", payload)
        await asyncio.sleep(0.2)

        status = await port.get_status("task-1")
        assert status.status == TTSStatus.DONE
        assert status.progress == 1.0

    @pytest.mark.asyncio
    async def test_no_progress_when_simulate_progress_false(self, payload):
        port = FakeRemoteTTSPort(synthesis_delay=0.1, simulate_progress=False)
        await port.submit("task-1", payload)
        await asyncio.sleep(0.05)

        status = await port.get_status("task-1")
        # Progress stays at 0 or jumps to 1
        if status.status == TTSStatus.RUNNING:
            assert status.progress == 0.0


class TestCancellationEdgeCases:
    """Tests for cancellation edge cases."""

    @pytest.mark.asyncio
    async def test_cancel_before_submit_returns_false(self):
        port = FakeRemoteTTSPort()
        result = await port.cancel("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_after_done_returns_false(self, payload):
        port = FakeRemoteTTSPort(synthesis_delay=0.01)
        await port.submit("task-1", payload)
        await asyncio.sleep(0.05)

        result = await port.cancel("task-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_after_failed_returns_false(self, payload):
        port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=1.0)
        await port.submit("task-1", payload)
        await asyncio.sleep(0.05)

        result = await port.cancel("task-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancelled_task_result_shows_failure(self, payload):
        port = FakeRemoteTTSPort(synthesis_delay=0.5, simulate_progress=True)
        await port.submit("task-1", payload)
        await asyncio.sleep(0.05)

        await port.cancel("task-1")
        await asyncio.sleep(0.05)

        result = await port.get_result("task-1")
        assert result.status == TTSStatus.FAILED
        assert "Cancelled" in result.error_message
