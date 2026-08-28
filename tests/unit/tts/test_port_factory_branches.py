"""Tests for tts/port_factory.py - covering missing branches.

Targets uncovered branches from branch-coverage report:
- StreamingTTSConfig / ZeroShotCloneConfig properties (43, 47, 51, 67, 71)
- create_engine: MOCK_TTS with real engine (102->105), auto+VOXCPM2 (135),
  explicit v0.4 engine types (147-163)
- create_streaming_tts_engine / create_zero_shot_clone_engine (184-199)
- create_configured_registry (219-224)
- _build_config_from_env: streaming/clone endpoint parsing (265-288)
- get_default_engine explicit-registry branches
- EnginePortAdapter: submit/_run_synthesis/get_status/get_result/cancel/
  health_check/close
- register_engine / sregister_engine / get_engine
- cleanup_global_registry / scleanup_global_registry
"""

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.audiobook_studio.di import DIContainer, reset_app_container, set_app_container
from src.audiobook_studio.tts.engine import EngineRegistry, TTSEngine
from src.audiobook_studio.tts.port import (
    TTSStatus,
    TTSTaskPayload,
    TTSTaskResult,
    TTSVoiceAnchor,
)
from src.audiobook_studio.tts.port_factory import (
    StreamingTTSConfig,
    ZeroShotCloneConfig,
    _build_config_from_env,
    create_configured_registry,
    create_engine,
    create_streaming_tts_engine,
    create_zero_shot_clone_engine,
    get_default_engine,
    get_port,
)
from src.audiobook_studio.di import get_app_container
from src.audiobook_studio.tts.engine import EngineRegistry


@pytest.fixture
def di_registry():
    """Install a fresh DI container holding a real EngineRegistry."""
    container = DIContainer()
    registry = EngineRegistry()
    container.register_singleton(EngineRegistry, registry)
    set_app_container(container)
    yield registry
    reset_app_container()


class TestStreamingTTSConfig:
    """Cover StreamingTTSConfig property branches (43, 47, 51)."""

    def test_base_url(self):
        cfg = StreamingTTSConfig(engine="cosyvoice_stream", host="h", port=1234)
        assert cfg.base_url == "http://h:1234"

    def test_mock_mode_true(self):
        with patch.dict(os.environ, {"MOCK_TTS": "true"}):
            cfg = StreamingTTSConfig(engine="x")
            assert cfg.mock_mode is True

    def test_mock_mode_false(self):
        with patch.dict(os.environ, {"MOCK_TTS": "false"}):
            cfg = StreamingTTSConfig(engine="x")
            assert cfg.mock_mode is False

    def test_chunk_samples(self):
        cfg = StreamingTTSConfig(engine="x", sample_rate=24000, chunk_size_ms=100)
        assert cfg.chunk_samples == 2400


class TestZeroShotCloneConfig:
    """Cover ZeroShotCloneConfig property branches (67, 71)."""

    def test_base_url(self):
        cfg = ZeroShotCloneConfig(engine="xtts_v2", host="h", port=5010)
        assert cfg.base_url == "http://h:5010"

    def test_mock_mode_true(self):
        with patch.dict(os.environ, {"MOCK_TTS": "true"}):
            cfg = ZeroShotCloneConfig(engine="x")
            assert cfg.mock_mode is True

    def test_mock_mode_false(self):
        with patch.dict(os.environ, {"MOCK_TTS": "false"}):
            cfg = ZeroShotCloneConfig(engine="x")
            assert cfg.mock_mode is False


class TestCreateEngineBranches:
    """Cover create_engine missing branches."""

    def test_mock_tts_env_with_real_engine(self):
        """MOCK_TTS=true sets mock_mode kwarg for non-fake engines (102->105)."""
        with patch.dict(os.environ, {"MOCK_TTS": "true"}):
            with patch("src.audiobook_studio.tts.port_factory.create_kokoro_port") as mock_create:
                mock_create.return_value = Mock(spec=TTSEngine)
                create_engine("kokoro")
                _, kwargs = mock_create.call_args
                assert kwargs.get("mock_mode") is True

    def test_auto_with_voxcpm2_endpoint(self):
        """auto + VOXCPM2_ENDPOINT selects remote voxcpm2 port (135)."""
        with patch.dict(os.environ, {
            "VOXCPM2_ENDPOINT": "http://vox:8080",
            "MOCK_LLM": "false",
            "TEST_MODE": "false",
            "MOCK_TTS": "false",
        }):
            with patch("src.audiobook_studio.tts.remote_voxcpm2_port.create_remote_voxcpm2_port") as mock_create:
                mock_create.return_value = Mock()
                engine = create_engine("auto")
                assert engine is mock_create.return_value
                mock_create.assert_called_once()

    @pytest.mark.parametrize("engine_type", [
        "cosyvoice_stream", "seed_tts_stream", "melotts_stream",
    ])
    def test_explicit_streaming_engines(self, engine_type):
        """Explicit v0.4 streaming engine types (147-154)."""
        with patch("src.audiobook_studio.tts.streaming.create_streaming_tts_engine") as mock_inner:
            mock_inner.return_value = Mock(spec=TTSEngine)
            engine = create_engine(engine_type)
            assert engine is mock_inner.return_value
            cfg = mock_inner.call_args[0][0]
            assert cfg.engine == engine_type

    @pytest.mark.parametrize("engine_type", [
        "xtts_v2", "openvoice_v2", "cosyvoice_clone",
    ])
    def test_explicit_clone_engines(self, engine_type):
        """Explicit v0.4 zero-shot clone engine types (155-163)."""
        with patch("src.audiobook_studio.tts.zero_shot_clone.create_zero_shot_clone_engine") as mock_inner:
            mock_inner.return_value = Mock(spec=TTSEngine)
            engine = create_engine(engine_type)
            assert engine is mock_inner.return_value
            cfg = mock_inner.call_args[0][0]
            assert cfg.engine == engine_type


class TestEngineBuilderFunctions:
    """Cover create_streaming_tts_engine / create_zero_shot_clone_engine (184-199)."""

    def test_create_streaming_tts_engine_builds_config(self):
        mock_engine = Mock(spec=TTSEngine)
        with patch("src.audiobook_studio.tts.streaming.create_streaming_tts_engine", return_value=mock_engine) as mock_inner:
            result = create_streaming_tts_engine(
                engine="cosyvoice_stream", host="h", port=5000, mock_mode=True,
            )
            assert result is mock_engine
            cfg = mock_inner.call_args[0][0]
            assert cfg.engine == "cosyvoice_stream"
            assert cfg.host == "h"
            assert cfg.port == 5000

    def test_create_zero_shot_clone_engine_builds_config(self):
        mock_engine = Mock(spec=TTSEngine)
        with patch("src.audiobook_studio.tts.zero_shot_clone.create_zero_shot_clone_engine", return_value=mock_engine) as mock_inner:
            result = create_zero_shot_clone_engine(
                engine="xtts_v2", host="h", port=5010, mock_mode=True,
            )
            assert result is mock_engine
            cfg = mock_inner.call_args[0][0]
            assert cfg.engine == "xtts_v2"
            assert cfg.host == "h"
            assert cfg.port == 5010


class TestCreateConfiguredRegistry:
    """Cover create_configured_registry (219-224)."""

    @pytest.mark.asyncio
    async def test_with_explicit_config(self):
        # Import locally: port_factory may have been reloaded by an earlier test,
        # leaving a stale module-level reference to create_kokoro_backend.
        from src.audiobook_studio.tts.port_factory import create_configured_registry

        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "kokoro"
        mock_engine.initialize = AsyncMock()
        # engine.py lazily imports create_kokoro_backend inside initialize(), and the
        # real KokoroBackend constructor probes the model file. Patch both so the mock
        # is used even if port_factory/kokoro_backend were reloaded by an earlier test
        # (which would otherwise leave a stale module-level reference).
        with patch(
            "src.audiobook_studio.tts.kokoro_backend.create_kokoro_backend",
            return_value=mock_engine,
        ), patch(
            "src.audiobook_studio.tts.kokoro_backend.KokoroBackend",
            return_value=mock_engine,
        ):
            registry = await create_configured_registry({"kokoro": {"output_dir": "./output"}})
        assert isinstance(registry, EngineRegistry)
        assert registry.config == {"kokoro": {"output_dir": "./output"}}

    @pytest.mark.asyncio
    async def test_with_none_config_reads_env(self):
        with patch.dict(os.environ, {"ENABLE_LOCAL_TTS": "false", "EDGE_TTS_ENABLED": "true"}, clear=False):
            registry = await create_configured_registry(None)
            assert isinstance(registry, EngineRegistry)
            assert "edge" in registry.config


class TestBuildConfigFromEnvBranches:
    """Cover _build_config_from_env endpoint-parsing branches (265-288)."""

    def test_streaming_endpoints_with_port(self):
        with patch.dict(os.environ, {
            "ENABLE_LOCAL_TTS": "false",
            "EDGE_TTS_ENABLED": "false",
            "COSYVOICE_STREAM_ENDPOINT": "http://cosy:5000",
            "SEED_TTS_STREAM_ENDPOINT": "http://seed:5001",
            "MELOTTS_STREAM_ENDPOINT": "http://melo:5002",
        }):
            config = _build_config_from_env()
            assert config["cosyvoice_stream"]["host"] == "cosy"
            assert config["cosyvoice_stream"]["port"] == 5000
            assert config["seed_tts_stream"]["host"] == "seed"
            assert config["melotts_stream"]["port"] == 5002

    def test_streaming_endpoint_no_port_uses_default(self):
        """Schemeless endpoint without port -> default port branch."""
        with patch.dict(os.environ, {
            "ENABLE_LOCAL_TTS": "false",
            "EDGE_TTS_ENABLED": "false",
            "COSYVOICE_STREAM_ENDPOINT": "cosy.example.com",
        }):
            config = _build_config_from_env()
            assert config["cosyvoice_stream"]["host"] == "cosy.example.com"
            assert config["cosyvoice_stream"]["port"] == 5000  # default

    def test_clone_endpoints_with_port(self):
        with patch.dict(os.environ, {
            "ENABLE_LOCAL_TTS": "false",
            "EDGE_TTS_ENABLED": "false",
            "XTTS_V2_ENDPOINT": "http://xtts:5010",
            "OPENVOICE_V2_ENDPOINT": "http://ov:5011",
            "COSYVOICE_CLONE_ENDPOINT": "http://cv:5012",
        }):
            config = _build_config_from_env()
            assert config["xtts_v2"]["host"] == "xtts"
            assert config["xtts_v2"]["port"] == 5010
            assert config["openvoice_v2"]["port"] == 5011
            assert config["cosyvoice_clone"]["host"] == "cv"

    def test_clone_endpoint_no_port_uses_default(self):
        with patch.dict(os.environ, {
            "ENABLE_LOCAL_TTS": "false",
            "EDGE_TTS_ENABLED": "false",
            "XTTS_V2_ENDPOINT": "xtts-host",
        }):
            config = _build_config_from_env()
            assert config["xtts_v2"]["host"] == "xtts-host"
            assert config["xtts_v2"]["port"] == 5010  # default

    def test_kokoro_without_model_path(self):
        """KOKORO_MODEL_PATH unset -> skip model_path branch (237->241)."""
        env = {"ENABLE_LOCAL_TTS": "true", "EDGE_TTS_ENABLED": "false"}
        with patch.dict(os.environ, env):
            os.environ.pop("KOKORO_MODEL_PATH", None)
            config = _build_config_from_env()
            assert "kokoro" in config
            assert "model_path" not in config["kokoro"]


class TestGetDefaultEngineBranches:
    """Cover get_default_engine explicit-registry branches."""

    @pytest.mark.asyncio
    async def test_explicit_registry_with_default(self):
        mock_engine = Mock(spec=TTSEngine)
        mock_registry = Mock(spec=EngineRegistry)
        mock_registry.get_default = Mock(return_value=mock_engine)

        result = await get_default_engine(registry=mock_registry)
        assert result is mock_engine

    @pytest.mark.asyncio
    async def test_explicit_registry_initializes_when_no_default(self):
        mock_engine = Mock(spec=TTSEngine)
        mock_registry = Mock(spec=EngineRegistry)
        mock_registry.get_default = Mock(side_effect=[None, mock_engine])
        mock_registry.initialize = AsyncMock()

        result = await get_default_engine(registry=mock_registry)
        assert result is mock_engine
        mock_registry.initialize.assert_called_once()


def _make_engine(**overrides):
    """Build a mock TTSEngine with async methods."""
    engine = Mock(spec=TTSEngine)
    engine.engine_name = overrides.get("engine_name", "test")
    engine.output_dir = overrides.get("output_dir", "./output")
    engine.synthesize = overrides.get("synthesize", AsyncMock())
    engine.health_check = overrides.get("health_check", AsyncMock(return_value={"status": "ok"}))
    engine.close = overrides.get("close", AsyncMock())
    return engine


def _payload():
    return TTSTaskPayload(
        text="hello world",
        voice_anchor=TTSVoiceAnchor(voice_id="v1"),
    )


class TestEnginePortAdapter:
    """Cover EnginePortAdapter branches via get_port()."""

    async def _make_port(self, engine):
        container = DIContainer()
        mock_registry = Mock(spec=EngineRegistry)
        mock_registry.get_default = Mock(return_value=engine)
        mock_registry.initialize = AsyncMock()
        container.register_singleton(EngineRegistry, mock_registry)
        set_app_container(container)
        return await get_port()

    async def _wait_terminal(self, port, task_id):
        for _ in range(200):
            status = await port.get_status(task_id)
            if status.status in (TTSStatus.DONE, TTSStatus.FAILED):
                return status
            await asyncio.sleep(0.02)
        return await port.get_status(task_id)

    @pytest.mark.asyncio
    async def test_submit_and_success_flow(self, tmp_path):
        """submit + _run_synthesis success path."""
        audio_file = tmp_path / "task1.wav"
        audio_file.write_bytes(b"RIFF fake audio")

        engine = _make_engine(
            output_dir=str(tmp_path),
            synthesize=AsyncMock(return_value=TTSTaskResult(
                task_id="task1",
                status=TTSStatus.DONE,
                audio_path=str(audio_file),
                duration_ms=100,
            )),
        )

        try:
            port = await self._make_port(engine)
            ok = await port.submit("task1", _payload())
            assert ok is True
            # duplicate submit returns False
            ok2 = await port.submit("task1", _payload())
            assert ok2 is False

            status = await self._wait_terminal(port, "task1")
            assert status.status == TTSStatus.DONE

            result = await port.get_result("task1")
            assert result.status == TTSStatus.DONE
            assert result.audio_path == str(audio_file)
        finally:
            reset_app_container()

    @pytest.mark.asyncio
    async def test_engine_failed_status(self, tmp_path):
        """_run_synthesis engine FAILED status branch."""
        engine = _make_engine(
            output_dir=str(tmp_path),
            synthesize=AsyncMock(return_value=TTSTaskResult(
                task_id="task_fail",
                status=TTSStatus.FAILED,
                error_message="boom",
            )),
        )

        try:
            port = await self._make_port(engine)
            await port.submit("task_fail", _payload())
            status = await self._wait_terminal(port, "task_fail")
            assert status.status == TTSStatus.FAILED
            assert "boom" in (status.error_message or "")
        finally:
            reset_app_container()

    @pytest.mark.asyncio
    async def test_engine_success_but_missing_file(self, tmp_path):
        """_run_synthesis DONE but file missing branch."""
        engine = _make_engine(
            output_dir=str(tmp_path),
            synthesize=AsyncMock(return_value=TTSTaskResult(
                task_id="task_missing",
                status=TTSStatus.DONE,
                audio_path=str(tmp_path / "nonexistent.wav"),
                duration_ms=10,
            )),
        )

        try:
            port = await self._make_port(engine)
            await port.submit("task_missing", _payload())
            status = await self._wait_terminal(port, "task_missing")
            assert status.status == TTSStatus.FAILED
            assert "not found" in (status.error_message or "").lower()
        finally:
            reset_app_container()

    @pytest.mark.asyncio
    async def test_engine_raises_exception(self, tmp_path):
        """_run_synthesis exception branch."""
        engine = _make_engine(
            output_dir=str(tmp_path),
            synthesize=AsyncMock(side_effect=RuntimeError("synth crash")),
        )

        try:
            port = await self._make_port(engine)
            await port.submit("task_exc", _payload())
            status = await self._wait_terminal(port, "task_exc")
            assert status.status == TTSStatus.FAILED
            assert "synth crash" in (status.error_message or "")
        finally:
            reset_app_container()

    @pytest.mark.asyncio
    async def test_get_status_unknown_task(self, tmp_path):
        """get_status not-found branch."""
        engine = _make_engine(output_dir=str(tmp_path))

        try:
            port = await self._make_port(engine)
            status = await port.get_status("nope")
            assert status.status == TTSStatus.PENDING
            assert status.error_message == "Not found"
        finally:
            reset_app_container()

    @pytest.mark.asyncio
    async def test_get_result_not_ready(self, tmp_path):
        """get_result raises KeyError when result missing."""
        engine = _make_engine(output_dir=str(tmp_path))

        try:
            port = await self._make_port(engine)
            with pytest.raises(KeyError):
                await port.get_result("nope")
        finally:
            reset_app_container()

    @pytest.mark.asyncio
    async def test_cancel_branches(self, tmp_path):
        """cancel: unknown task, running cancel, terminal cancel."""
        gate = asyncio.Event()

        async def slow_synth(payload, output_path):
            await gate.wait()
            Path(output_path).write_bytes(b"RIFF")
            return TTSTaskResult(
                task_id="x", status=TTSStatus.DONE,
                audio_path=str(output_path), duration_ms=1,
            )

        engine = _make_engine(output_dir=str(tmp_path), synthesize=slow_synth)

        try:
            port = await self._make_port(engine)

            # unknown task -> False
            assert await port.cancel("unknown") is False

            # running task -> True
            await port.submit("task_cancel", _payload())
            assert await port.cancel("task_cancel") is True
            status = await port.get_status("task_cancel")
            assert status.status == TTSStatus.FAILED

            # terminal task -> False
            assert await port.cancel("task_cancel") is False

            gate.set()
        finally:
            reset_app_container()

    @pytest.mark.asyncio
    async def test_health_check_and_close(self, tmp_path):
        """health_check and close adapter branches."""
        engine = _make_engine(output_dir=str(tmp_path))

        try:
            port = await self._make_port(engine)
            health = await port.health_check()
            assert health == {"status": "ok"}
            await port.close()
            engine.close.assert_called_once()
        finally:
            reset_app_container()


class TestGlobalRegistryHelpers:
    """Cover register/get/cleanup helpers via DI container."""

    @pytest.mark.asyncio
    async def test_register_engine_async(self, di_registry):
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "reg_async"

        registry = get_app_container().get(EngineRegistry)
        await registry.register(mock_engine)
        assert registry.get("reg_async") is mock_engine

    def test_sregister_engine_sync(self, di_registry):
        import asyncio
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "reg_sync"

        registry = get_app_container().get(EngineRegistry)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(registry.register(mock_engine))
        assert registry.get("reg_sync") is mock_engine

    def test_get_engine_not_found(self, di_registry):
        registry = get_app_container().get(EngineRegistry)
        assert registry.get("does_not_exist") is None

    @pytest.mark.asyncio
    async def test_cleanup_global_registry(self, di_registry):
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "to_cleanup"
        mock_engine.close = AsyncMock()

        registry = get_app_container().get(EngineRegistry)
        await registry.register(mock_engine)
        await registry.close_all()
        mock_engine.close.assert_called_once()

    def test_scleanup_global_registry(self, di_registry):
        import asyncio
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "to_scleanup"
        mock_engine.close = AsyncMock()

        registry = get_app_container().get(EngineRegistry)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(registry.register(mock_engine))
        loop.run_until_complete(registry.close_all())
        mock_engine.close.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
