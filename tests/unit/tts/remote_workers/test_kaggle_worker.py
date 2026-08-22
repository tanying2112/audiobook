"""Tests for KaggleWorker (tests/unit/tts/remote_workers/test_kaggle_worker.py).

Target: 70%+ coverage of kaggle_worker.py.
Tests: worker initialization, engine loading, smoke test, synthesis, GPU metrics, SSL/patches.
Mocks: torch, torchaudio, transformers, huggingface_hub.
"""

import os
import sys
from unittest.mock import Mock, patch, MagicMock

import pytest


# Mock heavy dependencies before importing
mock_torch = Mock()
mock_torch.cuda.is_available.return_value = True
mock_torch.cuda.get_device_name.return_value = "T4"
mock_torch.cuda.get_device_properties.return_value = Mock(total_memory=16 * 1024 * 1024 * 1024)
mock_torch.cuda.memory_allocated.return_value = 2 * 1024 * 1024 * 1024
mock_torch.inference_mode = lambda: MagicMock(__enter__=Mock(return_value=None), __exit__=Mock(return_value=None))
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

sys.modules["torch"] = mock_torch
sys.modules["torch.nn"] = mock_torch.nn
sys.modules["torch.nn.attention"] = mock_torch.nn.attention
sys.modules["torch.nn.attention.flex_attention"] = mock_torch.nn.attention.flex_attention
sys.modules["torchaudio"] = mock_torchaudio
sys.modules["transformers"] = mock_transformers
sys.modules["huggingface_hub"] = mock_hf_hub


from src.audiobook_studio.tts.remote_workers.kaggle_worker import (
    KaggleWorker,
    T4VoxCPM2Engine,
    get_device_name,
    get_gpu_memory_used_mb,
    get_gpu_memory_total_mb,
    main,
)


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
        model.parameters.return_value = iter([Mock(device="cuda")])
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

        with patch("os.path.exists", return_value=True):
            engine = T4VoxCPM2Engine(model_path="/tmp/model")

        mock_waveform = Mock()
        mock_waveform.to = Mock(return_value=mock_waveform)
        mock_torchaudio.load.return_value = (mock_waveform, 24000)

        import io
        mock_buffer = Mock()
        mock_buffer.getvalue.return_value = b"wav_audio_data"
        with patch("io.BytesIO", return_value=mock_buffer):
            audio = engine.synthesize("测试", "zh_female_1", {}, "/path/to/ref.wav")

        assert audio == b"wav_audio_data"
        mock_torchaudio.load.assert_called_with("/path/to/ref.wav")
        mock_model.encode_speaker.assert_called()

    def test_synthesize_resamples_reference_audio(self, mock_model, mock_tokenizer):
        mock_auto_model.from_pretrained.return_value = mock_model
        mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer

        with patch("os.path.exists", return_value=True):
            engine = T4VoxCPM2Engine(model_path="/tmp/model")

        mock_waveform = Mock()
        mock_torchaudio.load.return_value = (mock_waveform, 16000)  # Different sample rate

        import io
        mock_buffer = Mock()
        mock_buffer.getvalue.return_value = b"wav_audio_data"
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
            with patch("src.audiobook_studio.tts.remote_workers.kaggle_worker.BaseWorker.__init__", return_value=None):
                mock_auto_model.from_pretrained.return_value = mock_model
                mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer
                with patch("os.path.exists", return_value=True):

                    worker = KaggleWorker()
                    worker.worker_id = "test-worker"
                    worker.engine = worker._init_engine()
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
        mock_torch.cuda.is_available.return_value = False

        with patch("sys.exit") as mock_exit:
            with patch("sys.stderr.write") as mock_stderr:
                main()
                mock_exit.assert_called_with(1)

    def test_main_creates_worker_and_runs(self, mock_model, mock_tokenizer):
        mock_torch.cuda.is_available.return_value = True
        mock_auto_model.from_pretrained.return_value = mock_model
        mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer

        with patch("os.path.exists", return_value=True):
            with patch("src.audiobook_studio.tts.remote_workers.kaggle_worker.KaggleWorker") as mock_worker_class:
                mock_worker = Mock()
                mock_worker_class.return_value = mock_worker

                main()

                mock_worker_class.assert_called_once()
                mock_worker.run.assert_called_once()


@pytest.fixture
def mock_model():
    model = Mock()
    model.parameters.return_value = iter([Mock(device="cuda")])
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