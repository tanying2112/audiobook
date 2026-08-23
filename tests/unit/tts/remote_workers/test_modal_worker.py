"""Tests for ModalWorker (tests/unit/tts/remote_workers/test_modal_worker.py).

Target: 70%+ coverage of modal_worker.py (~245 lines).
Tests: worker initialization, engine loading, smoke test, synthesis, GPU metrics, Modal app config.
Mocks: modal, torch, torchaudio, soundfile, huggingface_hub, voxcpm model.
"""

import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, ANY

import pytest


def _identity_decorator(*args, **kwargs):
    """Decorator factory that returns the wrapped function unchanged.

    Used so that ``@torch.inference_mode()`` / ``@app.function(...)`` /
    ``@app.local_entrypoint()`` do not swallow the real function body when
    the underlying objects are mocked.
    """
    def decorator(func):
        return func
    return decorator


# Mock heavy dependencies before importing
mock_torch = Mock()
mock_torch.cuda.is_available.return_value = True
mock_torch.cuda.get_device_name.return_value = "T4"
mock_torch.cuda.get_device_properties.return_value = Mock(total_memory=16 * 1024 * 1024 * 1024)
mock_torch.cuda.memory_allocated.return_value = 2 * 1024 * 1024 * 1024
mock_torch.inference_mode = _identity_decorator
mock_torch.load = Mock()
mock_torch.cat = Mock(return_value=Mock(cpu=Mock(return_value=Mock(numpy=Mock(return_value=Mock(T=Mock()))))))
mock_torch.nn = Mock()

mock_soundfile = Mock()
mock_soundfile.write = Mock()

mock_voxcpm_model = Mock()
mock_voxcpm_model.generate.return_value = iter([Mock()])
mock_voxcpm_model.sample_rate = 24000
mock_voxcpm_model.from_local = Mock(return_value=mock_voxcpm_model)

mock_llama_tokenizer = Mock()
mock_llama_tokenizer.from_pretrained = Mock(return_value=Mock())

mock_hf_hub = Mock()
mock_hf_hub.snapshot_download = Mock()

mock_modal = Mock()
mock_modal.Image = Mock()
mock_modal.Image.debian_slim = Mock(return_value=Mock(
    apt_install=Mock(return_value=Mock()),
    pip_install=Mock(return_value=Mock()),
    add_local_dir=Mock(return_value=Mock()),
))
mock_modal.Volume = Mock()
mock_modal.Volume.from_name = Mock(return_value=Mock())
mock_modal.App = Mock()
mock_modal.App.return_value.function = _identity_decorator
mock_modal.App.return_value.local_entrypoint = _identity_decorator
mock_modal.Secret = Mock()
mock_modal.Secret.from_name = Mock(return_value=Mock())
mock_modal.function = Mock()
mock_modal.local_entrypoint = Mock()

# Only `modal` (unconditional import in modal_worker) and `torch` (cached via
# `try: import torch` at module top) need to be mocked for the worker import to
# succeed. We restore them immediately after import so we don't pollute other
# test files; the imported worker module keeps its cached mock references.
sys.modules["modal"] = mock_modal
sys.modules["torch"] = mock_torch

from src.audiobook_studio.tts.remote_workers.modal_worker import (
    ModalWorker,
    VoxCPM2Engine,
    worker_image,
    model_vol,
    app,
    run_modal_consumer,
    main,
)
import src.audiobook_studio.tts.remote_workers.modal_worker as _modal_worker_mod

# Restore module-level sys.modules entries touched for import (avoid polluting
# other test files in the same pytest session).
sys.modules.pop("modal", None)
sys.modules.pop("torch", None)

# `transformers` is required by the worker's lazy runtime import in
# VoxCPM2Engine._load_model(); expose it so the fixture below can wire it.
mock_transformers = Mock(LlamaTokenizerFast=mock_llama_tokenizer)

_MISSING = object()


def _rebind_worker_globals():
    """Rebind the names imported at module level to the *reloaded* worker module.

    The package ``__init__`` imports every worker at once, so the first worker
    test file to run binds all workers' module-level ``import torch`` /
    ``from transformers import ...`` to ITS mocks. Those bindings are cached in
    ``sys.modules`` and leak into later files. Reloading the targeted worker
    module re-binds its globals to this file's mocks, and we re-point the test's
    references so engine/helper calls use the correct mock objects.
    """
    global ModalWorker, VoxCPM2Engine, worker_image, model_vol, app, run_modal_consumer, main
    ModalWorker = _modal_worker_mod.ModalWorker
    VoxCPM2Engine = _modal_worker_mod.VoxCPM2Engine
    worker_image = _modal_worker_mod.worker_image
    model_vol = _modal_worker_mod.model_vol
    app = _modal_worker_mod.app
    run_modal_consumer = _modal_worker_mod.run_modal_consumer
    main = _modal_worker_mod.main


@pytest.fixture(autouse=True)
def _mock_runtime_deps():
    """Mock the heavy deps the worker imports lazily at runtime.

    These must be present in sys.modules *during each test* (the worker does
    runtime `import`/`from ... import` inside _load_model / __init__), but are
    restored afterwards so other test files (e.g. test_edge_tts_engine,
    test_voxcpm2_backend) see clean sys.modules instead of global MagicMocks.
    """
    runtime_mocks = {
        "modal": mock_modal,
        "torch": mock_torch,
        "torch.nn": MagicMock(),
        "transformers": mock_transformers,
        "huggingface_hub": mock_hf_hub,
        "voxcpm": MagicMock(),
        "voxcpm.model": MagicMock(),
        "voxcpm.model.voxcpm2": MagicMock(VoxCPM2Model=mock_voxcpm_model),
        "soundfile": mock_soundfile,
    }
    saved = {}
    for _name, _mock in runtime_mocks.items():
        saved[_name] = sys.modules.get(_name, _MISSING)
        sys.modules[_name] = _mock
    import importlib
    importlib.reload(_modal_worker_mod)
    _rebind_worker_globals()
    try:
        yield
    finally:
        for _name, _orig in saved.items():
            if _orig is _MISSING:
                sys.modules.pop(_name, None)
            else:
                sys.modules[_name] = _orig


class TestModalAppConfig:
    """Tests for Modal app configuration."""

    def test_worker_image_defined(self):
        """Test worker image is defined."""
        assert worker_image is not None

    def test_model_volume_defined(self):
        """Test model volume is defined."""
        assert model_vol is not None
        mock_modal.Volume.from_name.assert_called_with("voxcpm2-model-vol", create_if_missing=True)

    def test_app_defined(self):
        """Test Modal app is defined."""
        assert app is not None
        mock_modal.App.assert_called_with("dark-night-audio-factory-worker")


class TestVoxCPM2Engine:
    """Tests for VoxCPM2Engine class."""

    @pytest.fixture
    def mock_hf_hub_clean(self):
        mock_hf_hub.snapshot_download.reset_mock()
        yield
        mock_hf_hub.snapshot_download.reset_mock()

    def test_init_loads_model_from_volume(self, mock_hf_hub_clean):
        """Test engine initialization loads model from Modal volume."""
        with patch("os.makedirs"):
            with patch("pathlib.Path.exists", return_value=True):
                engine = VoxCPM2Engine(model_path="/models/voxcpm2-cache")

        assert engine.model is not None
        mock_voxcpm_model.from_local.assert_called()
        mock_llama_tokenizer.from_pretrained.assert_called()

    def test_init_downloads_model_when_not_cached(self, mock_hf_hub_clean):
        """Test engine downloads model when not in volume."""
        with patch("os.makedirs"):
            with patch("pathlib.Path.exists", return_value=False):
                engine = VoxCPM2Engine(model_path="/models/voxcpm2-cache")

        mock_hf_hub.snapshot_download.assert_called_once()
        assert engine.model is not None

    def test_synthesize_returns_audio_bytes(self):
        """Test synthesize returns WAV bytes."""
        engine = VoxCPM2Engine.__new__(VoxCPM2Engine)
        engine.model = mock_voxcpm_model
        engine.tokenizer = Mock()

        mock_audio_chunk = Mock()
        mock_audio_chunk.cpu.return_value.numpy.return_value.T = Mock()
        mock_voxcpm_model.generate.return_value = iter([mock_audio_chunk])

        mock_buffer = Mock()
        with patch("io.BytesIO", return_value=mock_buffer):
            with patch.object(mock_soundfile, "write") as mock_write:
                audio_bytes = engine.synthesize("测试", "zh_female_1", {"inference_timesteps": 10}, None)

        assert audio_bytes is not None
        mock_voxcpm_model.generate.assert_called()
        mock_write.assert_called()

    def test_synthesize_with_reference_audio(self):
        """Test synthesize with reference audio path."""
        engine = VoxCPM2Engine.__new__(VoxCPM2Engine)
        engine.model = mock_voxcpm_model
        engine.tokenizer = Mock()

        mock_audio_chunk = Mock()
        mock_voxcpm_model.generate.return_value = iter([mock_audio_chunk])

        mock_buffer = Mock()
        with patch("io.BytesIO", return_value=mock_buffer):
            with patch.object(mock_soundfile, "write"):
                with patch("pathlib.Path.exists", return_value=True):
                    audio_bytes = engine.synthesize("测试", "zh_female_1", {}, "/path/to/ref.wav")

        assert audio_bytes is not None

    def test_synthesize_empty_chunks_raises(self):
        """Test synthesize raises when no audio chunks generated."""
        engine = VoxCPM2Engine.__new__(VoxCPM2Engine)
        engine.model = mock_voxcpm_model
        engine.tokenizer = Mock()

        mock_voxcpm_model.generate.return_value = iter([])

        with pytest.raises(ValueError, match="No audio generated"):
            engine.synthesize("测试", "zh_female_1", {}, None)


class TestModalWorker:
    """Tests for ModalWorker class."""

    @pytest.fixture
    def worker(self):
        """Create a worker with mocked dependencies."""
        with patch.object(ModalWorker.__mro__[1], "__init__", return_value=None):
            mock_engine = Mock()
            # Patch VoxCPM2Engine in the exact globals dict that ModalWorker._init_engine
            # reads. Using sys.modules-targeted patch is unreliable because the module can
            # be imported as two distinct objects (src.audiobook_studio... vs audiobook_studio...).
            engine_globals = ModalWorker._init_engine.__globals__
            saved_engine = engine_globals.get("VoxCPM2Engine")
            engine_globals["VoxCPM2Engine"] = Mock(return_value=mock_engine)
            try:
                worker = ModalWorker()
                worker.worker_id = "modal-test-worker"
                worker.engine = mock_engine
                yield worker
            finally:
                engine_globals["VoxCPM2Engine"] = saved_engine

    def test_init_calls_parent_init(self):
        """Test worker init calls parent init with modal prefix."""
        with patch.object(ModalWorker.__mro__[1], "__init__", return_value=None) as mock_super:
            worker = ModalWorker()
            mock_super.assert_called_once_with(platform_prefix="modal")

    def test_init_engine_returns_voxcpm2_engine(self, worker):
        """Test _init_engine returns VoxCPM2Engine instance."""
        engine = worker._init_engine()
        assert engine is worker.engine

    def test_execute_smoke_test(self, worker):
        """Test smoke test runs synthesis."""
        worker.engine.synthesize.return_value = b"test_audio"

        worker._execute_smoke_test()

        worker.engine.synthesize.assert_called_once_with("测试", "zh_female_1", {})

    def test_synthesize_delegates_to_engine(self, worker):
        """Test _synthesize delegates to engine."""
        worker.engine.synthesize.return_value = b"audio_output"

        result = worker._synthesize("Test text", "zh_female_1", {"cfg_value": 2.0}, "/ref.wav")

        assert result == b"audio_output"
        worker.engine.synthesize.assert_called_once_with("Test text", "zh_female_1", {"cfg_value": 2.0}, "/ref.wav")

    def test_get_platform_gpu_metrics(self, worker):
        """Test GPU metrics includes device info."""
        metrics = worker._get_platform_gpu_metrics()

        assert "gpu_mem_used_mb" in metrics
        assert "gpu_mem_total_mb" in metrics
        assert "device_name" in metrics
        assert metrics["device_name"] == "T4"


class TestRunModalConsumer:
    """Tests for run_modal_consumer function."""

    def test_run_modal_consumer_sets_env_and_runs(self):
        """Test run_modal_consumer sets env vars and runs worker."""
        mock_worker = Mock()
        mock_worker_class = Mock(return_value=mock_worker)
        consumer_globals = run_modal_consumer.__globals__
        with patch.dict(os.environ, {}, clear=True):
            # Patch the exact ModalWorker name that run_modal_consumer resolves at
            # call time (sys.modules-targeted patch is unreliable due to module
            # being importable under two distinct objects).
            with patch.dict(consumer_globals, {"ModalWorker": mock_worker_class}):
                run_modal_consumer()

                # Check env vars are set
                assert "WORKER_ID" in os.environ
                assert os.environ["IDLE_TIMEOUT_SECONDS"] == "900"
                assert os.environ["MAX_EMPTY_POLLS"] == "2"
                assert os.environ["VOXCPM2_MODEL_PATH"] == "/models"

        mock_worker_class.assert_called_once()
        mock_worker.run.assert_called_once()


class TestModalMain:
    """Tests for main() local entrypoint."""

    def test_main_calls_remote(self):
        """Test main calls remote function."""
        mock_remote = Mock()
        main_globals = main.__globals__
        # Patch the exact run_modal_consumer name that main resolves at call time.
        with patch.dict(main_globals, {"run_modal_consumer": mock_remote}):
            main()
        mock_remote.remote.assert_called_once()


@pytest.fixture(autouse=True)
def reset_mocks():
    mock_torch.cuda.is_available.return_value = True
    mock_hf_hub.snapshot_download.reset_mock()
    mock_voxcpm_model.from_local.reset_mock()
    mock_llama_tokenizer.from_pretrained.reset_mock()
    mock_soundfile.write.reset_mock()
    yield
    mock_torch.cuda.is_available.return_value = True