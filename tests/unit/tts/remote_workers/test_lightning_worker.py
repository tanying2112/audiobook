"""Tests for LightningWorker (tests/unit/tts/remote_workers/test_lightning_worker.py).

Target: 70%+ coverage of lightning_worker.py (~190 lines).
Tests: worker initialization, engine loading, smoke test, synthesis, GPU metrics.
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
sys.modules["torchaudio"] = mock_torchaudio
sys.modules["transformers"] = mock_transformers
sys.modules["huggingface_hub"] = mock_hf_hub


from src.audiobook_studio.tts.remote_workers.lightning_worker import (
    LightningWorker,
    T4VoxCPM2Engine,
    get_device_name,
    get_gpu_memory_used_mb,
    get_gpu_memory_total_mb,
    main,
)


class TestGPUHelpers:
    """Tests for GPU helper functions."""

    def test_get_gpu_memory_used_mb(self):
        """Test GPU memory used in MB."""
        result = get_gpu_memory_used_mb()
        assert result == 2048  # 2GB in MB

    def test_get_gpu_memory_used_mb_no_cuda(self):
        """Test GPU memory when CUDA not available."""
        mock_torch.cuda.is_available.return_value = False
        result = get_gpu_memory_used_mb()
        assert result == 0

    def test_get_gpu_memory_total_mb(self):
        """Test total GPU memory in MB."""
        result = get_gpu_memory_total_mb()
        assert result == 16384  # 16GB in MB

    def test_get_gpu_memory_total_mb_no_cuda(self):
        """Test total GPU memory when CUDA not available."""
        mock_torch.cuda.is_available.return_value = False
        result = get_gpu_memory_total_mb()
        assert result == 0

    def test_get_device_name(self):
        """Test GPU device name retrieval."""
        result = get_device_name()
        assert result == "T4"

    def test_get_device_name_no_cuda(self):
        """Test device name when CUDA not available."""
        mock_torch.cuda.is_available.return_value = False
        result = get_device_name()
        assert result == "CPU"


class TestT4VoxCPM2Engine:
    """Tests for T4VoxCPM2Engine class."""

    @pytest.fixture
    def mock_model(self):
        """Create a mock model."""
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
        """Create a mock tokenizer."""
        tokenizer = Mock()
        tokenizer.return_value = {"input_ids": Mock(to=Mock(return_value=Mock()))}
        return tokenizer

    def test_init_loads_model_from_cache(self, mock_model, mock_tokenizer):
        """Test engine initialization loads model from cache."""
        mock_auto_model.from_pretrained.return_value = mock_model
        mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer

        with patch("os.path.exists", return_value=True):
            engine = T4VoxCPM2Engine(model_path="/tmp/cached-model")

        assert engine.model is mock_model
        assert engine.tokenizer is mock_tokenizer
        mock_auto_model.from_pretrained.assert_called()
        mock_auto_tokenizer.from_pretrained.assert_called()

    def test_init_downloads_model_when_not_cached(self, mock_model, mock_tokenizer):
        """Test engine downloads model when not cached."""
        mock_auto_model.from_pretrained.return_value = mock_model
        mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer

        with patch("os.path.exists", return_value=False):
            engine = T4VoxCPM2Engine(model_path="/tmp/model")

        mock_hf_hub.snapshot_download.assert_called_once_with(
            repo_id="openbmb/VoxCPM2",
            local_dir="/tmp/voxcpm2-model",
            local_dir_use_symlinks=False,
            resume_download=True,
        )
        assert engine.model is mock_model

    def test_synthesize_returns_audio_bytes(self, mock_model, mock_tokenizer):
        """Test synthesize returns WAV bytes."""
        mock_auto_model.from_pretrained.return_value = mock_model
        mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer

        with patch("os.path.exists", return_value=True):
            engine = T4VoxCPM2Engine(model_path="/tmp/model")

        mock_waveform = Mock()
        mock_model.decode_audio.return_value = mock_waveform

        mock_buffer = Mock()
        mock_buffer.getvalue.return_value = b"fake_wav_data"
        with patch("io.BytesIO", return_value=mock_buffer):
            with patch("torchaudio.save"):
                audio_bytes = engine.synthesize("Hello world", "zh_female_1", {"temperature": 0.7}, None)

        assert audio_bytes == b"fake_wav_data"
        mock_model.generate.assert_called()
        mock_model.decode_audio.assert_called()

    def test_synthesize_with_reference_audio(self, mock_model, mock_tokenizer):
        """Test synthesize with reference audio path."""
        mock_auto_model.from_pretrained.return_value = mock_model
        mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer

        with patch("os.path.exists", return_value=True):
            engine = T4VoxCPM2Engine(model_path="/tmp/model")

        mock_waveform = Mock()
        mock_model.decode_audio.return_value = mock_waveform
        mock_model.encode_speaker.return_value = Mock()

        mock_buffer = Mock()
        mock_buffer.getvalue.return_value = b"fake_wav_data"
        with patch("io.BytesIO", return_value=mock_buffer):
            with patch("torchaudio.save"):
                with patch("torchaudio.load", return_value=(Mock(), 24000)):
                    with patch("torchaudio.functional.resample"):
                        audio_bytes = engine.synthesize(
                            "Hello", "zh_female_1", {}, "/path/to/reference.wav"
                        )

        assert audio_bytes == b"fake_wav_data"
        mock_torchaudio.load.assert_called()
        mock_model.encode_speaker.assert_called()

    def test_synthesize_reference_audio_resamples(self, mock_model, mock_tokenizer):
        """Test reference audio resampling when sample rate differs."""
        mock_auto_model.from_pretrained.return_value = mock_model
        mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer

        with patch("os.path.exists", return_value=True):
            engine = T4VoxCPM2Engine(model_path="/tmp/model")

        mock_waveform = Mock()
        mock_model.decode_audio.return_value = mock_waveform
        mock_model.encode_speaker.return_value = Mock()

        mock_buffer = Mock()
        mock_buffer.getvalue.return_value = b"fake_wav_data"
        with patch("io.BytesIO", return_value=mock_buffer):
            with patch("torchaudio.save"):
                with patch("torchaudio.load", return_value=(Mock(), 16000)):  # Different sample rate
                    with patch("torchaudio.functional.resample") as mock_resample:
                        audio_bytes = engine.synthesize(
                            "Hello", "zh_female_1", {}, "/path/to/reference.wav"
                        )

        mock_resample.assert_called()


class TestLightningWorker:
    """Tests for LightningWorker class."""

    @pytest.fixture
    def worker(self):
        """Create a worker with mocked dependencies."""
        with patch("src.audiobook_studio.tts.remote_workers.lightning_worker.BaseWorker.__init__", return_value=None):
            with patch("src.audiobook_studio.tts.remote_workers.lightning_worker.T4VoxCPM2Engine") as mock_engine_class:
                mock_engine = Mock()
                mock_engine_class.return_value = mock_engine
                worker = LightningWorker()
                worker.worker_id = "lightning-test-worker"
                worker.engine = mock_engine
                return worker

    def test_init_calls_parent_init(self):
        """Test worker init calls parent init with lightning prefix."""
        with patch("src.audiobook_studio.tts.remote_workers.lightning_worker.BaseWorker.__init__", return_value=None) as mock_super:
            with patch("src.audiobook_studio.tts.remote_workers.lightning_worker.T4VoxCPM2Engine"):
                worker = LightningWorker()
                mock_super.assert_called_once_with("lightning")

    def test_init_engine_returns_t4_engine(self, worker):
        """Test _init_engine returns T4VoxCPM2Engine instance."""
        engine = worker._init_engine()
        assert engine is worker.engine

    def test_execute_smoke_test(self, worker):
        """Test smoke test runs synthesis."""
        worker.engine.synthesize.return_value = b"test_audio_bytes"

        worker._execute_smoke_test()

        worker.engine.synthesize.assert_called_once_with("测试语音合成。", "zh_female_1", {})

    def test_synthesize_delegates_to_engine(self, worker):
        """Test _synthesize delegates to engine."""
        worker.engine.synthesize.return_value = b"audio_output"

        result = worker._synthesize("Test text", "zh_male_1", {"temperature": 0.8}, "/ref.wav")

        assert result == b"audio_output"
        worker.engine.synthesize.assert_called_once_with("Test text", "zh_male_1", {"temperature": 0.8}, "/ref.wav")

    def test_get_platform_gpu_metrics(self, worker):
        """Test GPU metrics includes device info."""
        metrics = worker._get_platform_gpu_metrics()

        assert metrics["gpu_mem_used_mb"] == 2048
        assert metrics["gpu_mem_total_mb"] == 16384
        assert metrics["device_name"] == "T4"


class TestLightningWorkerMain:
    """Tests for main() entry point."""

    def test_main_exits_when_no_cuda(self):
        """Test main exits with error when CUDA not available."""
        mock_torch.cuda.is_available.return_value = False

        with patch("sys.exit") as mock_exit:
            with patch("sys.stderr.write") as mock_stderr:
                main()
                mock_exit.assert_called_with(1)

    def test_main_creates_worker_and_runs(self, mock_model, mock_tokenizer):
        """Test main creates worker and calls run when GPU available."""
        mock_torch.cuda.is_available.return_value = True
        mock_auto_model.from_pretrained.return_value = mock_model
        mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer

        with patch("os.path.exists", return_value=True):
            with patch("src.audiobook_studio.tts.remote_workers.lightning_worker.LightningWorker") as mock_worker_class:
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