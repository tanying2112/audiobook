"""Tests for KaggleWorker (tests/unit/tts/remote_workers/test_kaggle_worker.py).

Target: 70%+ coverage of kaggle_worker.py.
Tests: worker initialization, engine loading, smoke test, synthesis, GPU metrics, SSL/patches.
Mocks: torch, torchaudio, transformers, huggingface_hub.
"""

import os
import sys
from unittest.mock import Mock, patch, MagicMock

import pytest


def _identity_decorator(*args, **kwargs):
    """Decorator factory returning the wrapped function unchanged."""
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
mock_torch.nn = Mock()
mock_torch.nn.attention = Mock()
mock_torch.nn.attention.flex_attention = Mock()
mock_torch.nn.attention.flex_attention.BlockMask = type("BlockMask", (), {})

mock_torchaudio = Mock()
mock_torchaudio.load = Mock(return_value=(Mock(), 24000))
mock_torchaudio.save = Mock()
mock_torchaudio.functional = Mock()
mock_torchaudio.functional.resample = Mock(return_value=Mock())

mock_transformers = Mock()
mock_auto_model = Mock()
mock_auto_tokenizer = Mock()
mock_transformers.AutoModelForCausalLM = mock_auto_model
mock_transformers.AutoTokenizer = mock_auto_tokenizer

mock_hf_hub = Mock()
mock_hf_hub.snapshot_download = Mock()

# Mocks required for the WORKER IMPORT to succeed. These are temporarily placed
# in sys.modules, then removed right after import so we do not pollute other test
# files in the same pytest session. Runtime imports inside the worker are served
# by the _mock_runtime_deps autouse fixture below.
_IMPORT_MODULES = {
    "torch": mock_torch,
    "torch.nn": mock_torch.nn,
    "torch.nn.attention": mock_torch.nn.attention,
    "torch.nn.attention.flex_attention": mock_torch.nn.attention.flex_attention,
    "torchaudio": mock_torchaudio,
    "transformers": mock_transformers,
    "huggingface_hub": mock_hf_hub,
}
for _name, _mock in _IMPORT_MODULES.items():
    sys.modules[_name] = _mock

from src.audiobook_studio.tts.remote_workers.kaggle_worker import (
    KaggleWorker,
    T4VoxCPM2Engine,
    get_device_name,
    get_gpu_memory_used_mb,
    get_gpu_memory_total_mb,
    main,
)
import src.audiobook_studio.tts.remote_workers.kaggle_worker as _kaggle_worker_mod

for _name in _IMPORT_MODULES:
    sys.modules.pop(_name, None)


_RUNTIME_MODULES = dict(_IMPORT_MODULES)
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
    global KaggleWorker, T4VoxCPM2Engine, get_device_name, get_gpu_memory_used_mb, get_gpu_memory_total_mb, main
    KaggleWorker = _kaggle_worker_mod.KaggleWorker
    T4VoxCPM2Engine = _kaggle_worker_mod.T4VoxCPM2Engine
    get_device_name = _kaggle_worker_mod.get_device_name
    get_gpu_memory_used_mb = _kaggle_worker_mod.get_gpu_memory_used_mb
    get_gpu_memory_total_mb = _kaggle_worker_mod.get_gpu_memory_total_mb
    main = _kaggle_worker_mod.main


@pytest.fixture(autouse=True)
def _mock_runtime_deps():
    """Mock heavy deps the worker imports lazily at runtime.

    Restored after each test so other files (e.g. test_edge_tts_engine) see clean
    sys.modules instead of global MagicMocks.
    """
    saved = {}
    for _name, _mock in _RUNTIME_MODULES.items():
        saved[_name] = sys.modules.get(_name, _MISSING)
        sys.modules[_name] = _mock
    import importlib
    importlib.reload(_kaggle_worker_mod)
    _rebind_worker_globals()
    try:
        yield
    finally:
        for _name, _orig in saved.items():
            if _orig is _MISSING:
                sys.modules.pop(_name, None)
            else:
                sys.modules[_name] = _orig


class TestGPUHelpers:
    """Tests for GPU helper functions."""

    def test_get_gpu_memory_used_mb(self):
        result = get_gpu_memory_used_mb()
        assert result == 2048

    def test_get_gpu_memory_used_mb_no_cuda(self):
        mock_torch.cuda.is_available.return_value = False
        result = get_gpu_memory_used_mb()
        assert result == 0

    def test_get_gpu_memory_total_mb(self):
        result = get_gpu_memory_total_mb()
        assert result == 16384

    def test_get_gpu_memory_total_mb_no_cuda(self):
        mock_torch.cuda.is_available.return_value = False
        result = get_gpu_memory_total_mb()
        assert result == 0

    def test_get_device_name(self):
        result = get_device_name()
        assert result == "T4"

    def test_get_device_name_no_cuda(self):
        mock_torch.cuda.is_available.return_value = False
        result = get_device_name()
        assert result == "CPU"


class TestT4VoxCPM2Engine:
    """Tests for T4VoxCPM2Engine class."""

    @pytest.fixture
    def mock_model(self):
        model = Mock()
        model.parameters.side_effect = lambda: iter([Mock(device="cuda")])
        model.generate.return_value = Mock()
        model.decode_audio.return_value = Mock()
        model.encode_speaker.return_value = Mock()
        model.get_speaker_embedding.return_value = Mock()
        model.eval = Mock()
        return model

    @pytest.fixture
    def mock_tokenizer(self):
        tokenizer = Mock()
        tokenizer.return_value = {"input_ids": Mock(to=Mock(return_value=Mock()))}
        return tokenizer

    def test_init_loads_model_from_cache(self, mock_model, mock_tokenizer):
        mock_auto_model.from_pretrained.return_value = mock_model
        mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer

        with patch("os.path.exists", return_value=True):
            engine = T4VoxCPM2Engine(model_path="/tmp/cached-model")

        assert engine.model is mock_model
        assert engine.tokenizer is mock_tokenizer
        mock_auto_model.from_pretrained.assert_called()
        mock_auto_tokenizer.from_pretrained.assert_called()
        mock_hf_hub.snapshot_download.assert_not_called()

    def test_init_downloads_model_when_not_cached(self, mock_model, mock_tokenizer):
        mock_auto_model.from_pretrained.return_value = mock_model
        mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer

        with patch("os.path.exists", return_value=False):
            engine = T4VoxCPM2Engine(model_path="/tmp/model")

        mock_hf_hub.snapshot_download.assert_called_once()

    def test_synthesize(self, mock_model, mock_tokenizer):
        mock_auto_model.from_pretrained.return_value = mock_model
        mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer

        with patch("os.path.exists", return_value=True):
            engine = T4VoxCPM2Engine(model_path="/tmp/model")

        import io
        mock_buffer = Mock()
        mock_buffer.getvalue.return_value = b"wav_audio_data"
        with patch("io.BytesIO", return_value=mock_buffer):
            audio = engine.synthesize("测试文本", "zh_female_1", {"temperature": 0.7})

        assert audio == b"wav_audio_data"
        mock_model.generate.assert_called()
        mock_model.decode_audio.assert_called()
        mock_torchaudio.save.assert_called()

    def test_synthesize_with_reference_audio(self, mock_model, mock_tokenizer):
        mock_auto_model.from_pretrained.return_value = mock_model
        mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer

        mock_waveform = Mock()
        mock_waveform.to = Mock(return_value=mock_waveform)
        mock_torchaudio.load.return_value = (mock_waveform, 24000)

        import io
        mock_buffer = Mock()
        mock_buffer.getvalue.return_value = b"wav_audio_data"
        with patch("os.path.exists", return_value=True):
            engine = T4VoxCPM2Engine(model_path="/tmp/model")
            with patch("io.BytesIO", return_value=mock_buffer):
                audio = engine.synthesize("测试", "zh_female_1", {}, "/path/to/ref.wav")

        assert audio == b"wav_audio_data"
        mock_torchaudio.load.assert_called_with("/path/to/ref.wav")
        mock_model.encode_speaker.assert_called()

    def test_synthesize_resamples_reference_audio(self, mock_model, mock_tokenizer):
        mock_auto_model.from_pretrained.return_value = mock_model
        mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer

        mock_waveform = Mock()
        mock_torchaudio.load.return_value = (mock_waveform, 16000)  # Different sample rate

        import io
        mock_buffer = Mock()
        mock_buffer.getvalue.return_value = b"wav_audio_data"
        with patch("os.path.exists", return_value=True):
            engine = T4VoxCPM2Engine(model_path="/tmp/model")
            with patch("io.BytesIO", return_value=mock_buffer):
                audio = engine.synthesize("测试", "zh_female_1", {}, "/path/to/ref.wav")

        mock_torchaudio.functional.resample.assert_called()


class TestKaggleWorker:
    """Tests for KaggleWorker class."""

    @pytest.fixture
    def mock_env(self):
        return {
            "REDIS_HOST": "localhost",
            "REDIS_PORT": "6379",
            "REDIS_AUTH": "test_password",
            "R2_ENDPOINT": "https://test.r2.cloudflarestorage.com",
            "R2_ACCESS_KEY_ID": "test_key",
            "R2_SECRET_ACCESS_KEY": "test_secret",
            "R2_BUCKET": "test-bucket",
            "R2_PUBLIC_URL": "https://test-bucket.r2.cloudflarestorage.com",
            "VOXCPM2_MODEL_PATH": "/tmp/model",
            "WORKER_ID": "kaggle-worker-123",
            "VOXCPM2_HF_REPO": "openbmb/VoxCPM2",
        }

    @pytest.fixture
    def worker(self, mock_env, mock_model, mock_tokenizer):
        with patch.dict(os.environ, mock_env, clear=True):
            with patch.object(KaggleWorker.__mro__[1], "__init__", return_value=None):
                mock_auto_model.from_pretrained.return_value = mock_model
                mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer
                with patch("os.path.exists", return_value=True):
                    worker = KaggleWorker()
                    worker.worker_id = "test-worker"
                    worker.engine = Mock()
                    return worker

    def test_init_engine_returns_engine(self, worker):
        engine = worker._init_engine()
        assert isinstance(engine, T4VoxCPM2Engine)

    def test_execute_smoke_test(self, worker):
        worker.engine.synthesize.return_value = b"test_audio"

        worker._execute_smoke_test()

        worker.engine.synthesize.assert_called_once_with("测试语音合成。", "zh_female_1", {})

    def test_synthesize_delegates_to_engine(self, worker):
        worker.engine.synthesize.return_value = b"audio_data"

        result = worker._synthesize("Hello world", "en_female_1", {"top_p": 0.9}, "/ref.wav")

        assert result == b"audio_data"
        worker.engine.synthesize.assert_called_once_with("Hello world", "en_female_1", {"top_p": 0.9}, "/ref.wav")

    def test_get_platform_gpu_metrics(self, worker):
        metrics = worker._get_platform_gpu_metrics()

        assert metrics["gpu_mem_used_mb"] == 2048
        assert metrics["gpu_mem_total_mb"] == 16384
        assert metrics["device_name"] == "T4"


class TestKaggleWorkerMain:
    """Tests for main() entry point."""

    def test_main_exits_when_no_cuda(self):
        main_globals = main.__globals__
        with patch.dict(main_globals, {
            "inject_kaggle_secrets": Mock(),
            "verify_kaggle_env": Mock(return_value=True),
        }):
            # Patch CUDA availability on the torch object main() actually uses
            # (avoids the double-module trap where the test's mock_torch differs).
            with patch.object(main_globals["torch"].cuda, "is_available", return_value=False):
                # main() calls the real sys.exit(1) -> SystemExit when no CUDA.
                with pytest.raises(SystemExit):
                    main()

    def test_main_creates_worker_and_runs(self, mock_model, mock_tokenizer):
        main_globals = main.__globals__
        mock_auto_model.from_pretrained.return_value = mock_model
        mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer

        mock_worker = Mock()
        mock_worker_class = Mock(return_value=mock_worker)
        with patch.dict(main_globals, {
            "inject_kaggle_secrets": Mock(),
            "verify_kaggle_env": Mock(return_value=True),
            "KaggleWorker": mock_worker_class,
        }):
            with patch.object(main_globals["torch"].cuda, "is_available", return_value=True):
                with patch("os.path.exists", return_value=True):
                    main()

        mock_worker_class.assert_called_once()
        mock_worker.run.assert_called_once()


@pytest.fixture
def mock_model():
    model = Mock()
    model.parameters.side_effect = lambda: iter([Mock(device="cuda")])
    model.generate.return_value = Mock()
    model.decode_audio.return_value = Mock()
    model.encode_speaker.return_value = Mock()
    model.get_speaker_embedding.return_value = Mock()
    model.eval = Mock()
    return model


@pytest.fixture
def mock_tokenizer():
    tokenizer = Mock()
    tokenizer.return_value = {"input_ids": Mock(to=Mock(return_value=Mock()))}
    return tokenizer


@pytest.fixture(autouse=True)
def reset_mocks():
    mock_torch.cuda.is_available.return_value = True
    mock_auto_model.from_pretrained.reset_mock()
    mock_auto_tokenizer.from_pretrained.reset_mock()
    mock_hf_hub.snapshot_download.reset_mock()
    mock_torchaudio.load.reset_mock()
    mock_torchaudio.save.reset_mock()
    mock_torchaudio.functional.resample.reset_mock()
    yield
    mock_torch.cuda.is_available.return_value = True