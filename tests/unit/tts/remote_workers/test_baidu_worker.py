"""Tests for BaiduWorker (tests/unit/tts/remote_workers/test_baidu_worker.py).

Target: 70%+ coverage of baidu_worker.py (~375 lines).
Tests: worker initialization, dual backend selection (Paddle preferred, PyTorch fallback),
engine loading, smoke test, synthesis, GPU metrics.
Mocks: torch, paddle, transformers, huggingface_hub, torchaudio, soundfile.
"""

import os
import sys
from unittest.mock import ANY, MagicMock, Mock, patch

import pytest


def _identity_decorator(*args, **kwargs):
    """Decorator factory returning the wrapped function unchanged."""
    def decorator(func):
        return func
    return decorator


# Mock heavy dependencies before importing
mock_torch = Mock()
mock_torch.cuda.is_available.return_value = True
mock_torch.cuda.get_device_name.return_value = "V100"
mock_torch.cuda.memory_allocated.return_value = 2048 * 1024 * 1024
mock_torch.cuda.get_device_properties.return_value = Mock(total_memory=32 * 1024 * 1024 * 1024)
mock_torch.float16 = "float16"
mock_torch.inference_mode = _identity_decorator
mock_torch.load = Mock()
mock_torch.nn = Mock()
mock_torch.nn.attention = Mock()
mock_torch.nn.attention.flex_attention = Mock()

mock_paddle = Mock()
mock_paddle.device.is_compiled_with_cuda.return_value = True
mock_paddle.device.cuda.device_count.return_value = 1
mock_paddle.device.cuda.get_device_name.return_value = "V100"
mock_paddle.device.cuda.memory_allocated.return_value = 2048 * 1024 * 1024
mock_paddle.device.cuda.get_device_properties.return_value = Mock(total_memory=32 * 1024 * 1024 * 1024)
mock_paddle.no_grad = lambda *args, **kwargs: (lambda f: f)
mock_paddle.to_tensor = Mock(return_value=Mock())
mock_paddle = MagicMock()
# Reset after the MagicMock() reassignment above (line 42's no_grad was lost).
mock_paddle.no_grad = _identity_decorator
mock_paddle.device.is_compiled_with_cuda.return_value = True
mock_paddle.device.cuda.device_count.return_value = 1

mock_transformers = Mock()
mock_auto_model = Mock()
mock_auto_tokenizer = Mock()
mock_transformers.AutoModelForCausalLM = mock_auto_model
mock_transformers.AutoTokenizer = mock_auto_tokenizer

mock_paddle_transformers = Mock()
mock_paddle_auto_model = Mock()
mock_paddle_auto_tokenizer = Mock()
mock_paddle_transformers.AutoModelForCausalLM = mock_paddle_auto_model
mock_paddle_transformers.AutoTokenizer = mock_paddle_auto_tokenizer

mock_hf_hub = Mock()
mock_snapshot_download = Mock()
mock_hf_hub.snapshot_download = mock_snapshot_download

mock_torchaudio = Mock()
mock_torchaudio.load = Mock(return_value=(Mock(), 24000))
mock_torchaudio.save = Mock()
mock_torchaudio.functional = Mock()
mock_torchaudio.functional.resample = Mock(return_value=Mock())

mock_soundfile = Mock()
mock_soundfile.read = Mock(return_value=(Mock(), 24000))
mock_soundfile.write = Mock()

mock_paddlaudio = Mock()
mock_paddlaudio.functional = Mock()
mock_paddlaudio.functional.resample = Mock(return_value=Mock())

# Mocks required for the WORKER IMPORT to succeed. Temporarily placed in
# sys.modules, then removed right after import so we do not pollute other test
# files in the same pytest session. Runtime imports inside the worker are served
# by the _mock_runtime_deps autouse fixture below.
_IMPORT_MODULES = {
    "torch": mock_torch,
    "torch.nn": mock_torch.nn,
    "torch.nn.attention": mock_torch.nn.attention,
    "torch.nn.attention.flex_attention": mock_torch.nn.attention.flex_attention,
    "transformers": mock_transformers,
    "paddlenlp.transformers": mock_paddle_transformers,
    "huggingface_hub": mock_hf_hub,
    "torchaudio": mock_torchaudio,
    "soundfile": mock_soundfile,
    "paddlaudio": mock_paddlaudio,
    "paddle": mock_paddle,
}
for _name, _mock in _IMPORT_MODULES.items():
    sys.modules[_name] = _mock

# Now import the module
from src.audiobook_studio.tts.remote_workers.baidu_worker import (
    BaiduWorker,
    get_device_name,
    get_gpu_memory_total_mb,
    get_gpu_memory_used_mb,
    get_paddle_engine,
    get_torch_engine,
    is_gpu_available,
    main,
)
import src.audiobook_studio.tts.remote_workers.baidu_worker as _baidu_worker_mod

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
    global BaiduWorker, get_device_name, get_gpu_memory_total_mb, get_gpu_memory_used_mb, get_paddle_engine, get_torch_engine, is_gpu_available, main
    BaiduWorker = _baidu_worker_mod.BaiduWorker
    get_device_name = _baidu_worker_mod.get_device_name
    get_gpu_memory_total_mb = _baidu_worker_mod.get_gpu_memory_total_mb
    get_gpu_memory_used_mb = _baidu_worker_mod.get_gpu_memory_used_mb
    get_paddle_engine = _baidu_worker_mod.get_paddle_engine
    get_torch_engine = _baidu_worker_mod.get_torch_engine
    is_gpu_available = _baidu_worker_mod.is_gpu_available
    main = _baidu_worker_mod.main


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
    importlib.reload(_baidu_worker_mod)
    _rebind_worker_globals()
    try:
        yield
    finally:
        for _name, _orig in saved.items():
            if _orig is _MISSING:
                sys.modules.pop(_name, None)
            else:
                sys.modules[_name] = _orig


def _apply_defaults():
    """Re-apply canonical default return values for shared module-level mocks.

    Called by the autouse reset fixture before every test so that any state a
    previous test leaked (return_value / side_effect) is cleared and the helpers
    behave deterministically: the source tries paddle *first* for GPU helpers, so
    by default paddle must succeed, and torch must also succeed.
    """
    # torch
    mock_torch.cuda.is_available.return_value = True
    mock_torch.cuda.get_device_name.return_value = "V100"
    mock_torch.cuda.memory_allocated.return_value = 2048 * 1024 * 1024
    mock_torch.cuda.get_device_properties.return_value = Mock(total_memory=32 * 1024 * 1024 * 1024)
    mock_torch.inference_mode = _identity_decorator
    mock_torch.load = Mock()
    mock_torch.float16 = "float16"
    # paddle (tried first by the helper functions -> must succeed by default)
    mock_paddle.no_grad = _identity_decorator
    mock_paddle.device.is_compiled_with_cuda.return_value = True
    mock_paddle.device.cuda.device_count.return_value = 1
    mock_paddle.device.cuda.get_device_name.return_value = "V100"
    mock_paddle.device.cuda.memory_allocated.return_value = 2048 * 1024 * 1024
    mock_paddle.device.cuda.get_device_properties.return_value = Mock(total_memory=32 * 1024 * 1024 * 1024)
    mock_paddle.to_tensor = Mock(return_value=Mock())
    # transformers
    mock_transformers.AutoModelForCausalLM = mock_auto_model
    mock_transformers.AutoTokenizer = mock_auto_tokenizer
    mock_paddle_transformers.AutoModelForCausalLM = mock_paddle_auto_model
    mock_paddle_transformers.AutoTokenizer = mock_paddle_auto_tokenizer
    # huggingface_hub
    mock_hf_hub.snapshot_download = mock_snapshot_download
    # torchaudio
    mock_torchaudio.load.return_value = (Mock(), 24000)
    mock_torchaudio.save = Mock()
    mock_torchaudio.functional.resample.return_value = Mock()
    # soundfile
    mock_soundfile.read.return_value = (Mock(), 24000)
    mock_soundfile.write = Mock()
    # paddlaudio
    mock_paddlaudio.functional.resample.return_value = Mock()


@pytest.fixture(autouse=True)
def _reset_mocks():
    """Reset shared module-level mocks before each test to avoid state leakage."""
    for _m in (mock_torch, mock_paddle, mock_transformers, mock_paddle_transformers,
               mock_hf_hub, mock_torchaudio, mock_soundfile, mock_paddlaudio):
        _m.reset_mock(return_value=True, side_effect=True)
    _apply_defaults()
    yield


class TestGPUHelpers:
    """Tests for GPU helper functions."""

    def test_is_gpu_available_torch(self):
        """Test GPU detection via PyTorch."""
        mock_torch.cuda.is_available.return_value = True
        assert is_gpu_available() is True

    def test_is_gpu_available_paddle(self):
        """Test GPU detection via PaddlePaddle when torch unavailable."""
        # is_gpu_available() returns torch.cuda.is_available() directly, so to
        # reach the paddle fallback path torch must actually raise.
        mock_torch.cuda.is_available.side_effect = Exception("torch unavailable")
        mock_paddle.device.is_compiled_with_cuda.return_value = True
        mock_paddle.device.cuda.device_count.return_value = 1
        assert is_gpu_available() is True

    def test_is_gpu_available_none(self):
        """Test GPU detection returns False when no GPU."""
        mock_torch.cuda.is_available.return_value = False
        mock_paddle.device.is_compiled_with_cuda.return_value = False
        assert is_gpu_available() is False

    def test_get_device_name_torch(self):
        """Test device name from PyTorch."""
        # get_device_name() tries paddle first; make it raise so torch is used.
        mock_paddle.device.cuda.get_device_name.side_effect = Exception("no paddle")
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.get_device_name.return_value = "V100-SXM2-32GB"
        assert get_device_name() == "V100-SXM2-32GB"

    def test_get_device_name_paddle_fallback(self):
        """Test device name falls back to Paddle."""
        mock_torch.cuda.is_available.return_value = False
        mock_paddle.device.cuda.get_device_name.return_value = "V100"
        assert get_device_name() == "V100"

    def test_get_device_name_cpu_fallback(self):
        """Test device name returns CPU when no GPU."""
        # Both paddle and torch must fail to reach the CPU fallback.
        mock_paddle.device.cuda.get_device_name.side_effect = Exception("no paddle")
        mock_torch.cuda.get_device_name.side_effect = Exception("no torch")
        assert get_device_name() == "CPU"

    def test_get_gpu_memory_used_mb_torch(self):
        """Test GPU memory used via PyTorch."""
        # get_gpu_memory_used_mb() tries paddle first; make it raise.
        mock_paddle.device.cuda.memory_allocated.side_effect = Exception("no paddle")
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.memory_allocated.return_value = 4 * 1024 * 1024 * 1024  # 4GB
        assert get_gpu_memory_used_mb() == 4096

    def test_get_gpu_memory_used_mb_paddle(self):
        """Test GPU memory used via Paddle."""
        mock_torch.cuda.is_available.return_value = False
        mock_paddle.device.cuda.memory_allocated.return_value = 2 * 1024 * 1024 * 1024  # 2GB
        assert get_gpu_memory_used_mb() == 2048

    def test_get_gpu_memory_total_mb_torch(self):
        """Test total GPU memory via PyTorch."""
        # get_gpu_memory_total_mb() tries paddle first; make it raise.
        mock_paddle.device.cuda.get_device_properties.side_effect = Exception("no paddle")
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.get_device_properties.return_value = Mock(total_memory=16 * 1024 * 1024 * 1024)
        assert get_gpu_memory_total_mb() == 16384

    def test_get_gpu_memory_total_mb_paddle(self):
        """Test total GPU memory via Paddle."""
        mock_torch.cuda.is_available.return_value = False
        mock_paddle.device.cuda.get_device_properties.return_value = Mock(total_memory=32 * 1024 * 1024 * 1024)
        assert get_gpu_memory_total_mb() == 32768


class TestTorchEngine:
    """Tests for PyTorch engine."""

    @pytest.fixture(autouse=True)
    def reset_modules(self):
        """Reset global engine cache between tests."""
        import src.audiobook_studio.tts.remote_workers.baidu_worker as bw
        bw._TORCH_ENGINE = None
        bw._PADDLE_ENGINE = None
        yield
        bw._TORCH_ENGINE = None
        bw._PADDLE_ENGINE = None

    def test_get_torch_engine_creates_class(self):
        """Test get_torch_engine returns engine class."""
        engine_class = get_torch_engine()
        assert engine_class is not None
        assert hasattr(engine_class, "synthesize")

    def test_get_torch_engine_caches(self):
        """Test get_torch_engine caches the class."""
        engine_class1 = get_torch_engine()
        engine_class2 = get_torch_engine()
        assert engine_class1 is engine_class2

    def test_torch_engine_init_loads_model(self, tmp_path):
        """Test Torch engine initialization loads model."""
        mock_auto_tokenizer.from_pretrained.return_value = Mock()
        mock_auto_model.from_pretrained.return_value = Mock()
        mock_snapshot_download.reset_mock()

        engine_class = get_torch_engine()
        engine = engine_class(model_path=str(tmp_path))

        mock_auto_tokenizer.from_pretrained.assert_called()
        mock_auto_model.from_pretrained.assert_called()

    def test_torch_engine_synthesize(self):
        """Test Torch engine synthesis."""
        mock_model = Mock()
        mock_model.generate.return_value = Mock()
        mock_model.decode_audio.return_value = Mock()
        mock_model.get_speaker_embedding.return_value = Mock()
        mock_model.encode_speaker.return_value = Mock()
        mock_model.parameters.return_value = iter([Mock(device="cuda")])

        mock_auto_model.from_pretrained.return_value = mock_model
        mock_auto_tokenizer.from_pretrained.return_value = Mock(
            return_value={"input_ids": Mock(to=Mock(return_value=Mock()))}
        )

        engine_class = get_torch_engine()
        engine = engine_class(model_path="/tmp/model")

        # Mock torchaudio.save
        mock_buffer = Mock()
        mock_buffer.getvalue = Mock(return_value=b"wav_data")
        mock_torchaudio.save = Mock()

        import io
        with patch("io.BytesIO", return_value=mock_buffer):
            audio_bytes = engine.synthesize("测试", "zh_female_1", {"temperature": 0.7}, None)

        assert audio_bytes == b"wav_data"
        mock_model.generate.assert_called()
        mock_model.decode_audio.assert_called()

    def test_torch_engine_synthesize_with_reference_audio(self):
        """Test Torch engine synthesis with reference audio."""
        mock_model = Mock()
        mock_model.generate.return_value = Mock()
        mock_model.decode_audio.return_value = Mock()
        mock_model.encode_speaker.return_value = Mock()
        mock_model.parameters.side_effect = lambda: iter([Mock(device="cuda")])

        mock_auto_model.from_pretrained.return_value = mock_model
        mock_auto_tokenizer.from_pretrained.return_value = Mock(
            return_value={"input_ids": Mock(to=Mock(return_value=Mock()))}
        )

        engine_class = get_torch_engine()
        engine = engine_class(model_path="/tmp/model")

        mock_waveform = Mock()
        mock_waveform.to = Mock(return_value=mock_waveform)
        mock_torchaudio.load.return_value = (mock_waveform, 24000)

        import io
        mock_buffer = Mock()
        mock_buffer.getvalue = Mock(return_value=b"wav_data")
        with patch("os.path.exists", return_value=True):
            with patch("io.BytesIO", return_value=mock_buffer):
                audio_bytes = engine.synthesize("测试", "zh_female_1", {}, "/path/to/ref.wav")

        assert audio_bytes == b"wav_data"
        mock_torchaudio.load.assert_called_with("/path/to/ref.wav")
        mock_model.encode_speaker.assert_called()


class TestPaddleEngine:
    """Tests for PaddlePaddle engine."""

    @pytest.fixture(autouse=True)
    def reset_modules(self):
        import src.audiobook_studio.tts.remote_workers.baidu_worker as bw
        bw._TORCH_ENGINE = None
        bw._PADDLE_ENGINE = None
        yield
        bw._TORCH_ENGINE = None
        bw._PADDLE_ENGINE = None

    def test_get_paddle_engine_creates_class(self):
        """Test get_paddle_engine returns engine class."""
        engine_class = get_paddle_engine()
        assert engine_class is not None
        assert hasattr(engine_class, "synthesize")

    def test_get_paddle_engine_caches(self):
        """Test get_paddle_engine caches the class."""
        engine_class1 = get_paddle_engine()
        engine_class2 = get_paddle_engine()
        assert engine_class1 is engine_class2

    def test_paddle_engine_init_loads_model(self):
        """Test Paddle engine initialization loads model."""
        mock_paddle_auto_tokenizer.from_pretrained.return_value = Mock()
        mock_paddle_auto_model.from_pretrained.return_value = Mock()
        mock_snapshot_download.reset_mock()

        engine_class = get_paddle_engine()
        engine = engine_class(model_path="/tmp/model")

        mock_paddle_auto_tokenizer.from_pretrained.assert_called()
        mock_paddle_auto_model.from_pretrained.assert_called()

    def test_paddle_engine_synthesize(self):
        """Test Paddle engine synthesis."""
        mock_model = Mock()
        mock_model.generate.return_value = Mock()
        mock_model.decode_audio.return_value = Mock()
        mock_model.get_speaker_embedding.return_value = Mock()
        mock_model.encode_speaker.return_value = Mock()

        mock_paddle_auto_model.from_pretrained.return_value = mock_model
        # Paddle source: tokenizer(...) returns obj with .to("gpu") -> dict
        mock_paddle_auto_tokenizer.from_pretrained.return_value = Mock(
            return_value=Mock(to=Mock(return_value={"input_ids": Mock()}))
        )

        engine_class = get_paddle_engine()
        engine = engine_class(model_path="/tmp/model")

        mock_buffer = Mock()
        import io
        with patch("io.BytesIO", return_value=mock_buffer):
            mock_buffer.getvalue = Mock(return_value=b"wav_data")
            audio_bytes = engine.synthesize("测试", "zh_female_1", {"temperature": 0.7}, None)

        assert audio_bytes == b"wav_data"
        mock_model.generate.assert_called()

    def test_paddle_engine_synthesize_with_reference_audio(self):
        """Test Paddle engine synthesis with reference audio."""
        mock_model = Mock()
        mock_model.generate.return_value = Mock()
        mock_model.decode_audio.return_value = Mock()
        mock_model.encode_speaker.return_value = Mock()

        mock_paddle_auto_model.from_pretrained.return_value = mock_model
        mock_paddle_auto_tokenizer.from_pretrained.return_value = Mock(
            return_value=Mock(to=Mock(return_value={"input_ids": Mock()}))
        )

        engine_class = get_paddle_engine()
        engine = engine_class(model_path="/tmp/model")

        mock_soundfile.read.return_value = (Mock(), 24000)

        mock_buffer = Mock()
        mock_buffer.getvalue = Mock(return_value=b"wav_data")
        with patch("pathlib.Path.exists", return_value=True):
            with patch("io.BytesIO", return_value=mock_buffer):
                audio_bytes = engine.synthesize("测试", "zh_female_1", {}, "/path/to/ref.wav")

        assert audio_bytes == b"wav_data"
        mock_soundfile.read.assert_called_with("/path/to/ref.wav")
        mock_model.encode_speaker.assert_called()


class TestBaiduWorkerInitialization:
    """Tests for BaiduWorker initialization and backend selection."""

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
            "WORKER_ID": "baidu-worker-123",
            "BAIDU_STUDIO_ID": "studio-123",
            "PREFER_PADDLE": "true",
        }

    @pytest.fixture(autouse=True)
    def reset_modules(self):
        import src.audiobook_studio.tts.remote_workers.baidu_worker as bw
        bw._TORCH_ENGINE = None
        bw._PADDLE_ENGINE = None
        yield
        bw._TORCH_ENGINE = None
        bw._PADDLE_ENGINE = None

    def test_init_prefers_paddle_when_available(self, mock_env):
        """Test worker initializes with PaddlePaddle when preferred and available."""
        with patch.dict(os.environ, mock_env, clear=True):
            with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.BaseWorker.__init__", return_value=None) as mock_super:
                with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.get_paddle_engine") as mock_get_paddle:
                    mock_engine = Mock()
                    mock_get_paddle.return_value = mock_engine

                    worker = BaiduWorker()
                    worker._init_engine()

                    assert worker.backend == "paddle"
                    assert worker.prefer_paddle is True
                    mock_get_paddle.assert_called()

    def test_init_falls_back_to_torch_when_paddle_fails(self, mock_env):
        """Test worker falls back to PyTorch when PaddlePaddle fails."""
        with patch.dict(os.environ, mock_env, clear=True):
            with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.BaseWorker.__init__", return_value=None):
                with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.get_paddle_engine", side_effect=Exception("Paddle failed")):
                    with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.get_torch_engine") as mock_get_torch:
                        mock_engine = Mock()
                        mock_get_torch.return_value = mock_engine

                        worker = BaiduWorker()
                        worker._init_engine()

                        assert worker.backend == "torch"
                        mock_get_torch.assert_called()

    def test_init_uses_torch_when_prefer_paddle_false(self, mock_env):
        """Test worker uses PyTorch when PREFER_PADDLE=false."""
        mock_env["PREFER_PADDLE"] = "false"

        with patch.dict(os.environ, mock_env, clear=True):
            with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.BaseWorker.__init__", return_value=None):
                with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.get_torch_engine") as mock_get_torch:
                    mock_engine = Mock()
                    mock_get_torch.return_value = mock_engine

                    worker = BaiduWorker()
                    worker._init_engine()

                    assert worker.backend == "torch"

    def test_init_raises_when_no_backend_available(self, mock_env):
        """Test worker raises RuntimeError when both backends fail."""
        with patch.dict(os.environ, mock_env, clear=True):
            with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.BaseWorker.__init__", return_value=None):
                with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.get_paddle_engine", side_effect=RuntimeError("Paddle failed")):
                    with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.get_torch_engine", side_effect=RuntimeError("Torch failed")):
                        with pytest.raises(RuntimeError):
                            worker = BaiduWorker()
                            worker._init_engine()


class TestBaiduWorkerMethods:
    """Tests for BaiduWorker abstract method implementations."""

    @pytest.fixture
    def worker(self, mock_env):
        with patch.dict(os.environ, mock_env, clear=True):
            with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.BaseWorker.__init__", return_value=None):
                with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.get_paddle_engine"):
                    worker = BaiduWorker()
                    worker.worker_id = "test-worker"
                    worker.engine = Mock()
                    worker.backend = "paddle"
                    return worker

    def test_execute_smoke_test(self, worker):
        """Test smoke test runs synthesis."""
        worker.engine.synthesize.return_value = b"test_audio"

        worker._execute_smoke_test()

        worker.engine.synthesize.assert_called_once_with("测试语音合成。", "zh_female_1", {})

    def test_synthesize_delegates_to_engine(self, worker):
        """Test _synthesize delegates to engine."""
        worker.engine.synthesize.return_value = b"audio_bytes"

        result = worker._synthesize("Hello", "zh_male_1", {"temperature": 0.8}, "/ref.wav")

        assert result == b"audio_bytes"
        worker.engine.synthesize.assert_called_once_with("Hello", "zh_male_1", {"temperature": 0.8}, "/ref.wav")

    def test_get_platform_gpu_metrics(self, worker):
        """Test GPU metrics includes backend info."""
        with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.get_gpu_memory_used_mb", return_value=1024):
            with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.get_gpu_memory_total_mb", return_value=16384):
                with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.get_device_name", return_value="V100"):
                    metrics = worker._get_platform_gpu_metrics()

        assert metrics["gpu_mem_used_mb"] == 1024
        assert metrics["gpu_mem_total_mb"] == 16384
        assert metrics["device_name"] == "V100"
        assert metrics["backend"] == "paddle"

    def test_get_platform_gpu_metrics_torch_backend(self, worker):
        """Test GPU metrics with torch backend."""
        worker.backend = "torch"

        with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.get_gpu_memory_used_mb", return_value=2048):
            with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.get_gpu_memory_total_mb", return_value=32768):
                with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.get_device_name", return_value="T4"):
                    metrics = worker._get_platform_gpu_metrics()

        assert metrics["backend"] == "torch"


class TestBaiduWorkerMain:
    """Tests for main() entry point."""

    def test_main_exits_when_no_gpu(self):
        """Test main exits with error when GPU not available."""
        with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.is_gpu_available", return_value=False):
            with pytest.raises(SystemExit):
                main()

    def test_main_creates_worker_and_runs(self):
        """Test main creates worker and calls run when GPU available."""
        with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.is_gpu_available", return_value=True):
            with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.BaiduWorker") as mock_worker_class:
                mock_worker = Mock()
                mock_worker_class.return_value = mock_worker

                main()

                mock_worker_class.assert_called_once()
                mock_worker.run.assert_called_once()

    def test_main_test_mode_skips_gpu_check(self):
        """Test main skips GPU check in test mode."""
        with patch("src.audiobook_studio.tts.remote_workers.baidu_worker.BaiduWorker") as mock_worker_class:
            mock_worker = Mock()
            mock_worker_class.return_value = mock_worker

            import sys as _sys
            _sys._baidu_worker_test_mode = True
            try:
                main()
            finally:
                _sys._baidu_worker_test_mode = False

            mock_worker_class.assert_called_once()
            mock_worker.run.assert_called_once()


class TestBaiduWorkerSpeakerMap:
    """Tests for speaker ID mapping."""

    def test_speaker_map_defaults(self):
        """Test default speaker mappings."""
        from src.audiobook_studio.tts.remote_workers.baidu_worker import get_torch_engine
        import src.audiobook_studio.tts.remote_workers.baidu_worker as bw

        bw._TORCH_ENGINE = None
        mock_model = Mock()
        mock_model.get_speaker_embedding.return_value = Mock()
        mock_model.parameters.side_effect = lambda: iter([Mock(device="cuda")])
        # The engine lazily does `from transformers import AutoModelForCausalLM`,
        # which resolves to the mocked transformers module (mock_transformers);
        # its AutoModelForCausalLM is the module-level mock_auto_model. Configure
        # the model returned by from_pretrained directly.
        mock_auto_model.from_pretrained.return_value = mock_model
        mock_auto_tokenizer.from_pretrained.return_value = Mock()

        engine_class = get_torch_engine()
        engine = engine_class(model_path="/tmp")

        # Test default speaker mapping
        embedding = engine._get_speaker_prompt("zh_female_1", None)
        mock_model.get_speaker_embedding.assert_called_with(0)

        embedding = engine._get_speaker_prompt("zh_male_1", None)
        mock_model.get_speaker_embedding.assert_called_with(1)

        embedding = engine._get_speaker_prompt("en_female_1", None)
        mock_model.get_speaker_embedding.assert_called_with(2)

        embedding = engine._get_speaker_prompt("en_male_1", None)
        mock_model.get_speaker_embedding.assert_called_with(3)

        # Unknown voice_id defaults to 0
        embedding = engine._get_speaker_prompt("unknown", None)
        mock_model.get_speaker_embedding.assert_called_with(0)

        bw._TORCH_ENGINE = None


@pytest.fixture
def mock_env():
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
        "WORKER_ID": "baidu-worker-123",
        "BAIDU_STUDIO_ID": "studio-123",
        "PREFER_PADDLE": "true",
    }