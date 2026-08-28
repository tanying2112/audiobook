"""Mock-mode tests for KokoroBackend (kokoro_backend.py).

Uses the built-in ``mock_mode=True`` to exercise as much of the module as
possible without real kokoro_onnx model inference. Genuinely-external real
inference bodies (real ``_synthesize_internal``, ``warmup``, ``stream``) are
marked ``# pragma: no cover`` in the source.

Imports use the top-level ``audiobook_studio.*`` package (never ``src.``).
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from audiobook_studio.tts.engine import (
    TTSTaskPayload,
    TTSTaskResult,
    TTSTaskStatus,
    TTSProsody,
    TTSVoiceAnchor,
)
from audiobook_studio.tts.kokoro_backend import (
    KOKORO_VOICES,
    KokoroBackend,
    create_kokoro_backend,
    create_kokoro_engine,
)


def _payload(text="Hello world", voice_id="af", **kwargs):
    prosody = kwargs.pop("prosody", None)
    return TTSTaskPayload(
        text=text,
        voice_anchor=TTSVoiceAnchor(voice_id=voice_id),
        prosody=prosody,
        **kwargs,
    )


async def _wait_terminal(backend, task_id, limit=200):
    statuses = []
    for _ in range(limit):
        status = await backend.get_status(task_id)
        statuses.append(status.status)
        if status.status in ("DONE", "FAILED"):
            return status, statuses
        await asyncio.sleep(0.01)
    return await backend.get_status(task_id), statuses


class TestInitAndAvailability:
    def test_mock_init_populates_voice_embeddings(self):
        backend = KokoroBackend(mock_mode=True)
        assert backend._voice_embeddings == KOKORO_VOICES

    @pytest.mark.asyncio
    async def test_mock_initialize_sets_loaded(self):
        backend = KokoroBackend(mock_mode=True)
        assert backend.is_available is False
        await backend.initialize()
        assert backend._loaded is True
        assert backend._initialized is True
        assert backend.is_available is True
        assert backend.engine_name == "kokoro"


class TestSynthesizeInternalMock:
    @pytest.mark.asyncio
    async def test_returns_synthesis_result(self, tmp_path):
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()
        out = tmp_path / "clip.mp3"
        result = await backend._synthesize_internal(
            text="hello", voice_id="af", output_path=out
        )
        assert isinstance(result, object)
        assert result.duration_ms == 1000
        assert result.voice_id == "af"
        assert result.engine == "kokoro"
        # soundfile mock writes bytes so the file exists
        assert Path(result.audio_path).exists()

    @pytest.mark.asyncio
    async def test_mock_initializes_when_not_loaded(self, tmp_path):
        backend = KokoroBackend(mock_mode=True)
        assert backend._loaded is False
        out = tmp_path / "lazy.mp3"
        result = await backend._synthesize_internal(
            text="hi", voice_id="zf_xiaoxiao", output_path=out
        )
        assert result.duration_ms == 1000
        assert backend._loaded is True


class TestSynthesizeMock:
    @pytest.mark.asyncio
    async def test_success_path(self, tmp_path):
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()
        out = tmp_path / "out.mp3"
        result = await backend.synthesize(_payload(), out)
        assert isinstance(result, TTSTaskResult)
        assert result.status == "DONE"
        assert result.audio_path == str(out)
        assert result.duration_ms == 1000
        assert result.voice_id == "af"
        assert result.engine == "kokoro"

    @pytest.mark.asyncio
    async def test_failure_path(self, tmp_path, monkeypatch):
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()

        async def _boom(*args, **kwargs):
            raise RuntimeError("synthesis exploded")

        monkeypatch.setattr(backend, "_synthesize_internal", _boom)
        out = tmp_path / "fail.mp3"
        result = await backend.synthesize(_payload(), out)
        assert result.status == "FAILED"
        assert "synthesis exploded" in result.error_message
        assert result.engine == "kokoro"

    @pytest.mark.asyncio
    async def test_success_path_with_prosody(self, tmp_path):
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()
        payload = _payload(
            prosody=TTSProsody(rate=1.1, pitch=2.0, volume=-3.0, emotion="happy")
        )
        out = tmp_path / "out_prosody.mp3"
        result = await backend.synthesize(payload, out)
        assert result.status == "DONE"
        assert result.duration_ms == 1000


class TestAsyncTaskLifecycle:
    @pytest.mark.asyncio
    async def test_submit_and_terminal_statuses(self, tmp_path, monkeypatch):
        backend = KokoroBackend(mock_mode=True, output_dir=str(tmp_path))
        await backend.initialize()

        # Make synthesis yield so we can observe the RUNNING branch.
        original = KokoroBackend._synthesize_internal
        gate = asyncio.Event()

        async def slow_internal(*args, **kwargs):
            await gate.wait()
            return await original(backend, *args, **kwargs)

        monkeypatch.setattr(backend, "_synthesize_internal", slow_internal)

        ok = await backend.submit("t1", _payload())
        assert ok is True
        # duplicate submit rejected
        ok2 = await backend.submit("t1", _payload())
        assert ok2 is False
        # PENDING right after submit (task not yet run)
        immediate = await backend.get_status("t1")
        assert immediate.status in ("PENDING", "RUNNING", "DONE")
        # Let the task start and suspend at the gate (RUNNING).
        await asyncio.sleep(0.02)
        running = await backend.get_status("t1")
        assert running.status == "RUNNING"
        # Release the gate so synthesis completes -> DONE.
        gate.set()
        status, statuses = await _wait_terminal(backend, "t1")
        assert status.status == "DONE"
        assert "RUNNING" in statuses  # covered the RUNNING branch
        result = await backend.get_result("t1")
        assert isinstance(result, TTSTaskResult)
        assert result.status == "DONE"

    @pytest.mark.asyncio
    async def test_failed_task_and_result_keyerror(self, tmp_path, monkeypatch):
        backend = KokoroBackend(mock_mode=True, output_dir=str(tmp_path))
        await backend.initialize()

        # Make synthesize itself raise -> _run_task except branch (FAILED task).
        async def _boom(*args, **kwargs):
            raise RuntimeError("task boom")

        monkeypatch.setattr(backend, "synthesize", _boom)
        await backend.submit("tf", _payload())
        status, _ = await _wait_terminal(backend, "tf")
        assert status.status == "FAILED"
        assert "task boom" in (status.error_message or "")
        # get_result raises KeyError when no result stored
        with pytest.raises(KeyError):
            await backend.get_result("tf")

    @pytest.mark.asyncio
    async def test_get_status_not_found(self, tmp_path):
        backend = KokoroBackend(mock_mode=True, output_dir=str(tmp_path))
        await backend.initialize()
        st = await backend.get_status("nope")
        assert isinstance(st, TTSTaskStatus)
        assert st.status == "PENDING"
        assert "not found" in (st.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_get_result_not_found(self, tmp_path):
        backend = KokoroBackend(mock_mode=True, output_dir=str(tmp_path))
        await backend.initialize()
        with pytest.raises(KeyError):
            await backend.get_result("nope")

    @pytest.mark.asyncio
    async def test_cancel_branches(self, tmp_path, monkeypatch):
        backend = KokoroBackend(mock_mode=True, output_dir=str(tmp_path))
        await backend.initialize()

        gate = asyncio.Event()
        original = KokoroBackend._synthesize_internal

        async def slow_internal(*args, **kwargs):
            await gate.wait()
            return await original(backend, *args, **kwargs)

        monkeypatch.setattr(backend, "_synthesize_internal", slow_internal)

        # unknown task -> False
        assert await backend.cancel("unknown") is False

        await backend.submit("tc", _payload())
        # let it become RUNNING
        await asyncio.sleep(0.02)
        assert await backend.cancel("tc") is True
        st = await backend.get_status("tc")
        assert st.status == "FAILED"
        # now terminal -> cancel returns False
        assert await backend.cancel("tc") is False
        gate.set()

    @pytest.mark.asyncio
    async def test_cancel_after_done_returns_false(self, tmp_path):
        backend = KokoroBackend(mock_mode=True, output_dir=str(tmp_path))
        await backend.initialize()
        await backend.submit("td", _payload())
        _, _ = await _wait_terminal(backend, "td")
        assert await backend.cancel("td") is False


class TestPhonemize:
    def test_mock_branch(self):
        backend = KokoroBackend(mock_mode=True)
        tokens, lengths = backend._phonemize("hello there", "af")
        assert tokens is not None
        assert lengths is not None

    def test_real_branch_no_external(self, monkeypatch):
        backend = KokoroBackend(mock_mode=False)
        # Provide a fake kokoro so we fall into the non-mock branch
        backend._kokoro = object()
        tokens, lengths = backend._phonemize("hello", "af")
        assert tokens is not None
        assert lengths is not None


class TestVoicesAndEstimate:
    def test_get_voices_count_and_known(self):
        backend = KokoroBackend(mock_mode=True)
        voices = backend.get_voices()
        assert len(voices) == len(KOKORO_VOICES)
        ids = {v.voice_id for v in voices}
        assert "af_bella" in ids
        assert "zf_xiaoxiao" in ids

    def test_estimate_duration_en(self):
        backend = KokoroBackend(mock_mode=True)
        d = backend.estimate_duration("hello world", "af")
        assert isinstance(d, int)
        assert d >= 500

    def test_estimate_duration_zh(self):
        backend = KokoroBackend(mock_mode=True)
        d = backend.estimate_duration("中文测试文本", "zf_xiaoxiao")
        assert isinstance(d, int)
        assert d >= 500

    def test_estimate_duration_with_speed(self):
        backend = KokoroBackend(mock_mode=True)
        slow = backend.estimate_duration("hello world", "af", prosody={"rate": 2.0})
        normal = backend.estimate_duration("hello world", "af")
        assert slow < normal


class TestHealthWarmupClose:
    @pytest.mark.asyncio
    async def test_health_check(self):
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()
        health = await backend.health_check()
        assert health["healthy"] is True
        assert health["engine"] == "kokoro"
        assert health["mock_mode"] is True
        assert health["loaded"] is True

    @pytest.mark.asyncio
    async def test_warmup_mock(self):
        backend = KokoroBackend(mock_mode=True)
        assert await backend.warmup() is True
        assert backend._loaded is True

    @pytest.mark.asyncio
    async def test_close(self):
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()
        await backend.close()
        assert backend._loaded is False
        assert backend._initialized is False
        assert backend._kokoro is None


class TestStream:
    @pytest.mark.asyncio
    async def test_mock_stream_yields_chunk(self):
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()
        chunks = []
        async for chunk in backend.stream(_payload()):
            chunks.append(chunk)
        assert len(chunks) >= 1

    @pytest.mark.asyncio
    async def test_mock_stream_auto_initializes(self):
        # stream should lazily initialize when not yet loaded (covers the
        # `if not self._loaded: await self.initialize()` branch).
        backend = KokoroBackend(mock_mode=True)
        assert backend._loaded is False
        chunks = []
        async for chunk in backend.stream(_payload()):
            chunks.append(chunk)
        assert len(chunks) >= 1
        assert backend._loaded is True


class TestFactories:
    @pytest.mark.asyncio
    async def test_create_kokoro_backend_mock(self):
        backend = await create_kokoro_backend(mock_mode=True)
        assert isinstance(backend, KokoroBackend)
        assert backend.engine_name == "kokoro"
        assert backend.is_available is True

    @pytest.mark.asyncio
    async def test_create_kokoro_engine_alias_mock(self):
        backend = await create_kokoro_engine(mock_mode=True)
        assert isinstance(backend, KokoroBackend)
        assert backend.mock_mode is True


class TestRealInitializeFileNotFound:
    @pytest.mark.asyncio
    async def test_initialize_raises_file_not_found(self, tmp_path):
        # Point at a nonexistent model file so the real-mode existence check
        # raises FileNotFoundError (the repo ships real model files, so we
        # must supply an absent path to exercise this branch deterministically).
        missing = tmp_path / "does_not_exist_kokoro_model.onnx"
        backend = KokoroBackend(mock_mode=False, model_path=str(missing))
        assert backend._loaded is False
        with pytest.raises(FileNotFoundError):
            await backend.initialize()
        # The except Exception branch re-raises
        assert backend._loaded is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
