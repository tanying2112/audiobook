"""Tests for BaseWorker and R2Uploader (tests/unit/tts/remote_workers/test_base_worker.py).

Target: 70%+ coverage of base_worker.py (~300 lines).
Tests: worker initialization, job processing, error handling, status reporting, heartbeat, graceful shutdown.
Mocks: redis, boto3, signal handlers.
"""

import abc
import json
import os
import signal
import sys
import time
from unittest.mock import ANY, AsyncMock, MagicMock, Mock, patch

import pytest

# Mock boto3 and redis before importing base_worker
with patch.dict(sys.modules, {"boto3": Mock(), "redis": Mock()}):
    from src.audiobook_studio.tts.remote_workers.base_worker import BaseWorker, R2Uploader


class TestR2Uploader:
    """Tests for R2Uploader class."""

    def test_init_requires_boto3(self):
        """Test R2Uploader raises RuntimeError when boto3 unavailable."""
        with patch.dict(sys.modules, {"boto3": None}):
            with pytest.raises(RuntimeError, match="boto3 unavailable"):
                R2Uploader(
                    endpoint_url="https://test.r2.cloudflarestorage.com",
                    access_key_id="test_key",
                    secret_access_key="test_secret",
                    bucket="test-bucket",
                )

    def test_init_success(self):
        """Test successful R2Uploader initialization."""
        mock_boto3 = Mock()
        mock_s3 = Mock()
        mock_boto3.client.return_value = mock_s3

        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            uploader = R2Uploader(
                endpoint_url="https://test.r2.cloudflarestorage.com",
                access_key_id="test_key",
                secret_access_key="test_secret",
                bucket="test-bucket",
                public_url_base="https://custom.domain.com",
                verify_ssl=True,
            )

            assert uploader.bucket == "test-bucket"
            assert uploader.public_url_base == "https://custom.domain.com"
            mock_boto3.client.assert_called_once_with(
                "s3",
                endpoint_url="https://test.r2.cloudflarestorage.com",
                aws_access_key_id="test_key",
                aws_secret_access_key="test_secret",
                region_name="auto",
                verify=True,
            )

    def test_init_default_public_url(self):
        """Test default public URL construction."""
        mock_boto3 = Mock()
        mock_s3 = Mock()
        mock_boto3.client.return_value = mock_s3

        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            uploader = R2Uploader(
                endpoint_url="https://test.r2.cloudflarestorage.com",
                access_key_id="test_key",
                secret_access_key="test_secret",
                bucket="my-bucket",
            )

            assert uploader.public_url_base == "https://my-bucket.r2.cloudflarestorage.com"

    def test_upload_success(self):
        """Test successful audio upload to R2."""
        mock_boto3 = Mock()
        mock_s3 = Mock()
        mock_boto3.client.return_value = mock_s3

        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            uploader = R2Uploader(
                endpoint_url="https://test.r2.cloudflarestorage.com",
                access_key_id="test_key",
                secret_access_key="test_secret",
                bucket="test-bucket",
            )

            audio_bytes = b"fake_wav_data"
            object_key = "tts/task-123.wav"

            url = uploader.upload(audio_bytes, object_key)

            mock_s3.put_object.assert_called_once_with(
                Bucket="test-bucket",
                Key=object_key,
                Body=audio_bytes,
                ContentType="audio/wav",
            )
            assert url == f"https://test-bucket.r2.cloudflarestorage.com/{object_key}"

    def test_upload_custom_public_url(self):
        """Test upload with custom public URL base."""
        mock_boto3 = Mock()
        mock_s3 = Mock()
        mock_boto3.client.return_value = mock_s3

        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            uploader = R2Uploader(
                endpoint_url="https://test.r2.cloudflarestorage.com",
                access_key_id="test_key",
                secret_access_key="test_secret",
                bucket="test-bucket",
                public_url_base="https://cdn.example.com",
            )

            url = uploader.upload(b"audio", "tts/task.wav")
            assert url == "https://cdn.example.com/tts/task.wav"


class ConcreteWorker(BaseWorker):
    """Concrete implementation for testing BaseWorker abstract methods."""

    def _init_engine(self):
        return Mock()

    def _execute_smoke_test(self):
        pass

    def _synthesize(self, text, voice_id, prosody, reference_audio):
        return b"fake_audio_data"

    def _get_platform_gpu_metrics(self):
        return {"gpu_mem_used_mb": 1024, "gpu_mem_total_mb": 16384, "device_name": "T4"}


class TestBaseWorkerInitialization:
    """Tests for BaseWorker initialization and configuration."""

    @pytest.fixture
    def mock_env(self):
        """Mock all required environment variables."""
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
            "WORKER_ID": "test-worker-123",
            "LIGHTNING_STUDIO_ID": "studio-123",
            "IDLE_TIMEOUT_SECONDS": "900",
            "MAX_EMPTY_POLLS": "3",
        }

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        mock = Mock()
        mock.blpop = Mock(return_value=None)
        mock.llen = Mock(return_value=0)
        mock.rpush = Mock(return_value=1)
        mock.setex = Mock(return_value=True)
        return mock

    @pytest.fixture
    def mock_boto3(self):
        """Mock boto3 client."""
        mock = Mock()
        mock_client = Mock()
        mock.client.return_value = mock_client
        return mock

    def test_init_validates_required_env_vars(self, mock_env):
        """Test initialization validates all required environment variables."""
        with patch.dict(os.environ, mock_env, clear=True):
            with patch("src.audiobook_studio.tts.remote_workers.base_worker.redis") as mock_redis_module:
                mock_redis_module.Redis.return_value = Mock()
                with patch("src.audiobook_studio.tts.remote_workers.base_worker.boto3") as mock_boto3:
                    mock_boto3.client.return_value = Mock()

                    worker = ConcreteWorker("test")
                    assert worker.worker_id == "test-worker-123"
                    assert worker.idle_timeout == 900
                    assert worker.max_empty_polls == 3

    def test_init_raises_on_missing_env_vars(self):
        """Test initialization raises ValueError for missing env vars."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="Missing env vars"):
                ConcreteWorker("test")

    def test_init_partial_missing_env_vars(self, mock_env):
        """Test initialization raises for partial missing env vars."""
        # Remove one required var
        del mock_env["REDIS_HOST"]

        with patch.dict(os.environ, mock_env, clear=True):
            with pytest.raises(ValueError, match="Missing env vars.*REDIS_HOST"):
                ConcreteWorker("test")

    def test_init_sets_signal_handlers(self, mock_env):
        """Test signal handlers are registered."""
        with patch.dict(os.environ, mock_env, clear=True):
            with patch("signal.signal") as mock_signal:
                with patch("src.audiobook_studio.tts.remote_workers.base_worker.redis") as mock_redis_module:
                    mock_redis_module.Redis.return_value = Mock()
                    with patch("src.audiobook_studio.tts.remote_workers.base_worker.boto3") as mock_boto3:
                        mock_boto3.client.return_value = Mock()

                        worker = ConcreteWorker("test")
                        assert mock_signal.call_count == 2
                        mock_signal.assert_any_call(signal.SIGTERM, worker._handle_shutdown)
                        mock_signal.assert_any_call(signal.SIGINT, worker._handle_shutdown)

    def test_init_creates_r2_uploader(self, mock_env):
        """Test R2Uploader is created during initialization."""
        with patch.dict(os.environ, mock_env, clear=True):
            with patch("src.audiobook_studio.tts.remote_workers.base_worker.redis") as mock_redis_module:
                mock_redis_module.Redis.return_value = Mock()
                with patch("src.audiobook_studio.tts.remote_workers.base_worker.R2Uploader") as mock_r2:
                    worker = ConcreteWorker("test")
                    mock_r2.assert_called_once()

    def test_init_calls_init_engine_and_smoke_test(self, mock_env):
        """Test _init_engine and _execute_smoke_test are called during init."""
        with patch.dict(os.environ, mock_env, clear=True):
            with patch("src.audiobook_studio.tts.remote_workers.base_worker.redis") as mock_redis_module:
                mock_redis_module.Redis.return_value = Mock()
                with patch("src.audiobook_studio.tts.remote_workers.base_worker.R2Uploader"):
                    with patch.object(ConcreteWorker, "_init_engine", return_value=Mock()) as mock_init:
                        with patch.object(ConcreteWorker, "_execute_smoke_test") as mock_smoke:
                            worker = ConcreteWorker("test")
                            mock_init.assert_called_once()
                            mock_smoke.assert_called_once()


class TestBaseWorkerHeartbeat:
    """Tests for heartbeat functionality."""

    @pytest.fixture
    def worker(self, mock_env):
        """Create a worker with mocked dependencies."""
        with patch.dict(os.environ, mock_env, clear=True):
            with patch("src.audiobook_studio.tts.remote_workers.base_worker.redis") as mock_redis_module:
                mock_redis = Mock()
                mock_redis_module.Redis.return_value = mock_redis
                with patch("src.audiobook_studio.tts.remote_workers.base_worker.R2Uploader"):
                    worker = ConcreteWorker("test")
                    worker.redis = mock_redis
                    return worker

    def test_send_heartbeat_idle(self, worker):
        """Test heartbeat sent with idle status."""
        worker._send_heartbeat("idle", queue_depth=0)

        worker.redis.setex.assert_called_once()
        args, kwargs = worker.redis.setex.call_args
        assert args[0] == f"worker:heartbeat:{worker.worker_id}"
        assert args[1] == worker.idle_timeout + 60
        payload = json.loads(args[2])
        assert payload["status"] == "idle"
        assert payload["worker_id"] == worker.worker_id
        assert payload["queue_depth"] == 0

    def test_send_heartbeat_processing(self, worker):
        """Test heartbeat sent with processing status."""
        worker._send_heartbeat("processing", queue_depth=5)

        args, _ = worker.redis.setex.call_args
        payload = json.loads(args[2])
        assert payload["status"] == "processing"
        assert payload["queue_depth"] == 5

    def test_send_heartbeat_includes_gpu_metrics(self, worker):
        """Test heartbeat includes GPU metrics."""
        worker._send_heartbeat("idle", 0)

        args, _ = worker.redis.setex.call_args
        payload = json.loads(args[2])
        assert "gpu_metrics" in payload
        assert payload["gpu_metrics"]["gpu_mem_used_mb"] == 1024
        assert payload["gpu_metrics"]["device_name"] == "T4"

    def test_send_heartbeat_handles_redis_error(self, worker):
        """Test heartbeat handles Redis errors gracefully."""
        worker.redis.setex.side_effect = Exception("Redis connection failed")

        # Should not raise
        worker._send_heartbeat("idle", 0)


class TestBaseWorkerNetworkCallRetry:
    """Tests for _execute_network_call_with_retry."""

    @pytest.fixture
    def worker(self, mock_env):
        with patch.dict(os.environ, mock_env, clear=True):
            with patch("src.audiobook_studio.tts.remote_workers.base_worker.redis") as mock_redis_module:
                mock_redis_module.Redis.return_value = Mock()
                with patch("src.audiobook_studio.tts.remote_workers.base_worker.R2Uploader"):
                    return ConcreteWorker("test")

    def test_retry_success_on_first_attempt(self, worker):
        """Test successful call on first attempt."""
        mock_func = Mock(return_value="success")

        result = worker._execute_network_call_with_retry(mock_func, "arg1", key="value", max_retries=3)

        assert result == "success"
        mock_func.assert_called_once_with("arg1", key="value")

    def test_retry_on_redis_error(self, worker):
        """Test retry on Redis error."""
        mock_redis = Mock()
        mock_redis.RedisError = Exception

        with patch("src.audiobook_studio.tts.remote_workers.base_worker.redis", mock_redis):
            mock_func = Mock(side_effect=[mock_redis.RedisError("fail"), "success"])

            with patch("time.sleep") as mock_sleep:
                result = worker._execute_network_call_with_retry(mock_func, max_retries=3)

            assert result == "success"
            assert mock_func.call_count == 2
            assert mock_sleep.call_count == 1
            mock_sleep.assert_called_with(1.0)

    def test_retry_on_boto3_error(self, worker):
        """Test retry on boto3 error."""
        mock_boto3 = Mock()
        mock_boto3.exceptions.Boto3Error = Exception

        with patch("src.audiobook_studio.tts.remote_workers.base_worker.boto3", mock_boto3):
            mock_func = Mock(side_effect=[mock_boto3.exceptions.Boto3Error("fail"), "success"])

            with patch("time.sleep") as mock_sleep:
                result = worker._execute_network_call_with_retry(mock_func, max_retries=3)

            assert result == "success"
            assert mock_sleep.call_count == 1

    def test_retry_exhausted_raises(self, worker):
        """Test exception raised after max retries exhausted."""
        mock_redis = Mock()
        mock_redis.RedisError = Exception

        with patch("src.audiobook_studio.tts.remote_workers.base_worker.redis", mock_redis):
            mock_func = Mock(side_effect=mock_redis.RedisError("persistent failure"))

            with patch("time.sleep"):
                with pytest.raises(Exception, match="persistent failure"):
                    worker._execute_network_call_with_retry(mock_func, max_retries=2)

            assert mock_func.call_count == 2

    def test_exponential_backoff(self, worker):
        """Test exponential backoff timing."""
        mock_redis = Mock()
        mock_redis.RedisError = Exception

        with patch("src.audiobook_studio.tts.remote_workers.base_worker.redis", mock_redis):
            mock_func = Mock(side_effect=mock_redis.RedisError("fail"))

            with patch("time.sleep") as mock_sleep:
                with pytest.raises(Exception):
                    worker._execute_network_call_with_retry(mock_func, max_retries=3)

            # Check exponential backoff: 1.0, 2.0
            mock_sleep.assert_any_call(1.0)
            mock_sleep.assert_any_call(2.0)


class TestBaseWorkerTaskProcessing:
    """Tests for _process_single_task method."""

    @pytest.fixture
    def worker(self, mock_env):
        with patch.dict(os.environ, mock_env, clear=True):
            with patch("src.audiobook_studio.tts.remote_workers.base_worker.redis") as mock_redis_module:
                mock_redis_component = Mock()
                mock_redis_module.Redis.return_value = mock_redis_component
                with patch("src.audiobook_studio.tts.remote_workers.base_worker.R2Uploader") as mock_r2_class:
                    mock_r2 = Mock()
                    mock_r2.upload.return_value = "https://r2.example.com/tts/task123.wav"
                    mock_r2_class.return_value = mock_r2

                    worker = ConcreteWorker("test")
                    worker.r2 = mock_r2
                    worker._execute_network_call_with_retry = Mock(side_effect=lambda f, *a, **k: f(*a, **k))
                    return worker

    def test_process_task_success(self, worker):
        """Test successful task processing."""
        task = {
            "id": "task-123",
            "text": "Hello world",
            "voice_id": "zh_female_1",
            "prosody": {"temperature": 0.7},
            "reference_audio": None,
        }

        result = worker._process_single_task(task)

        assert result["id"] == "task-123"
        assert result["status"] == "success"
        assert result["url"] == "https://r2.example.com/tts/task123.wav"
        assert result["worker"] == worker.worker_id
        assert "duration_ms" in result

    def test_process_task_with_reference_audio(self, worker):
        """Test task processing with reference audio."""
        task = {
            "id": "task-456",
            "text": "Test with ref",
            "voice_id": "zh_male_1",
            "prosody": {},
            "reference_audio": "/path/to/ref.wav",
        }

        result = worker._process_single_task(task)

        # Should pass reference_audio to _synthesize
        assert result["status"] == "success"

    def test_process_task_synthesis_failure(self, worker):
        """Test handling of synthesis failure."""
        worker.engine.synthesize.side_effect = RuntimeError("GPU OOM")

        task = {"id": "task-fail", "text": "Fail", "voice_id": "zh_female_1", "prosody": {}}

        result = worker._process_single_task(task)

        assert result["status"] == "failed"
        assert "GPU OOM" in result["error"]
        assert result["worker"] == worker.worker_id

    def test_process_task_r2_upload_failure(self, worker):
        """Test handling of R2 upload failure."""
        worker._execute_network_call_with_retry.side_effect = Exception("R2 upload failed")

        task = {"id": "task-r2fail", "text": "Fail", "voice_id": "zh_female_1", "prosody": {}}

        result = worker._process_single_task(task)

        assert result["status"] == "failed"
        assert "R2 upload failed" in result["error"]


class TestBaseWorkerRunLoop:
    """Tests for main run() consumer loop."""

    @pytest.fixture
    def worker(self, mock_env):
        with patch.dict(os.environ, mock_env, clear=True):
            with patch("src.audiobook_studio.tts.remote_workers.base_worker.redis") as mock_redis_module:
                mock_redis = Mock()
                mock_redis_module.Redis.return_value = mock_redis
                with patch("src.audiobook_studio.tts.remote_workers.base_worker.R2Uploader"):
                    worker = ConcreteWorker("test")
                    worker.redis = mock_redis
                    worker._send_heartbeat = Mock()
                    worker._process_single_task = Mock(return_value={"id": "task-1", "status": "success"})
                    worker._execute_network_call_with_retry = Mock(side_effect=lambda f, *a, **k: f(*a, **k))
                    return worker

    def test_run_processes_task_from_queue(self, worker):
        """Test run loop processes task from queue."""
        task_payload = json.dumps({"id": "task-1", "text": "test", "voice_id": "zh_female_1", "prosody": {}})
        worker.redis.blpop.side_effect = [
            ("tts:tasks", task_payload),  # First call returns task
            None,  # Second call returns None (empty)
        ]
        worker.running = True
        worker.max_empty_polls = 1

        # Run will exit after empty_polls >= max_empty_polls
        worker.run()

        assert worker.redis.blpop.call_count >= 1
        worker._process_single_task.assert_called()

    def test_run_requeues_failed_task(self, worker):
        """Test failed task is re-queued."""
        task_payload = json.dumps({"id": "task-fail", "text": "test", "voice_id": "zh_female_1", "prosody": {}})
        worker.redis.blpop.side_effect = [
            ("tts:tasks", task_payload),
            None,
        ]
        worker._process_single_task.return_value = {"id": "task-fail", "status": "failed", "error": "OOM"}
        worker.running = True
        worker.max_empty_polls = 1

        worker.run()

        worker.redis.rpush.assert_any_call("tts:tasks", task_payload)

    def test_run_discards_corrupted_payload(self, worker):
        """Test corrupted JSON payload is discarded."""
        worker.redis.blpop.side_effect = [
            ("tts:tasks", "not valid json"),
            None,
        ]
        worker.running = True
        worker.max_empty_polls = 1

        worker.run()

        # Should not process corrupted payload
        worker._process_single_task.assert_not_called()

    def test_run_idle_timeout_exits(self, worker):
        """Test idle timeout triggers exit."""
        worker.redis.blpop.side_effect = [None, None, None]  # 3 empty polls
        worker.redis.llen.return_value = 0
        worker.running = True
        worker.max_empty_polls = 3

        worker.run()

        # Should send exiting heartbeat
        calls = [call[0][0] for call in worker._send_heartbeat.call_args_list]
        assert "exiting" in calls

    def test_run_shutdown_signal_stops_loop(self, worker):
        """Test SIGTERM/SIGINT sets running=False and exits."""
        worker.redis.blpop.side_effect = [None]
        worker.running = True

        # Simulate shutdown signal
        worker._handle_shutdown(signal.SIGTERM, None)

        assert worker.running is False

    def test_run_redis_connection_error_handled(self, worker):
        """Test Redis connection error during blpop is handled."""
        worker.redis.blpop.side_effect = [
            Exception("Connection lost"),
            None,
        ]
        worker.running = True
        worker.max_empty_polls = 1

        with patch("time.sleep") as mock_sleep:
            worker.run()

        mock_sleep.assert_called_with(5)


class TestBaseWorkerShutdown:
    """Tests for graceful shutdown handling."""

    @pytest.fixture
    def worker(self, mock_env):
        with patch.dict(os.environ, mock_env, clear=True):
            with patch("src.audiobook_studio.tts.remote_workers.base_worker.redis") as mock_redis_module:
                mock_redis_module.Redis.return_value = Mock()
                with patch("src.audiobook_studio.tts.remote_workers.base_worker.R2Uploader"):
                    return ConcreteWorker("test")

    def test_handle_shutdown_sets_running_false(self, worker):
        """Test _handle_shutdown sets running to False."""
        worker.running = True
        worker._handle_shutdown(signal.SIGTERM, None)
        assert worker.running is False

    def test_handle_shutdown_sigint(self, worker):
        """Test SIGINT also triggers shutdown."""
        worker.running = True
        worker._handle_shutdown(signal.SIGINT, None)
        assert worker.running is False


class TestBaseWorkerAbstractMethods:
    """Tests that abstract methods must be implemented."""

    def test_base_worker_is_abstract(self):
        """Test BaseWorker cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseWorker("test")

    def test_all_abstract_methods_required(self):
        """Test all four abstract methods are required."""

        class IncompleteWorker(BaseWorker):
            def _init_engine(self):
                pass
            # Missing _execute_smoke_test, _synthesize, _get_platform_gpu_metrics

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteWorker("test")


class TestBaseWorkerIdleTimeout:
    """Tests for idle timeout logic."""

    @pytest.fixture
    def worker(self, mock_env):
        with patch.dict(os.environ, mock_env, clear=True):
            with patch("src.audiobook_studio.tts.remote_workers.base_worker.redis") as mock_redis_module:
                mock_redis = Mock()
                mock_redis_module.Redis.return_value = mock_redis
                with patch("src.audiobook_studio.tts.remote_workers.base_worker.R2Uploader"):
                    worker = ConcreteWorker("test")
                    worker.redis = mock_redis
                    worker._send_heartbeat = Mock()
                    worker._process_single_task = Mock(return_value={"status": "success"})
                    worker._execute_network_call_with_retry = Mock(side_effect=lambda f, *a, **k: f(*a, **k))
                    return worker

    def test_max_empty_polls_triggers_idle_check(self, worker):
        """Test max_empty_polls triggers idle timeout check."""
        worker.redis.blpop.return_value = None
        worker.redis.llen.return_value = 0
        worker.running = True
        worker.max_empty_polls = 2

        with patch("time.sleep") as mock_sleep:
            worker.run()

        # Should check queue depth after max_empty_polls
        worker.redis.llen.assert_called_with("tts:tasks")
        worker._send_heartbeat.assert_any_call("exiting", 0)

    def test_idle_timeout_not_triggered_if_queue_not_empty(self, worker):
        """Test idle timeout doesn't trigger if queue has items."""
        worker.redis.blpop.return_value = None
        worker.redis.llen.return_value = 5  # Queue not empty
        worker.running = True
        worker.max_empty_polls = 2

        with patch("time.sleep"):
            worker.run()

        # Should not send exiting heartbeat
        calls = [call[0][0] for call in worker._send_heartbeat.call_args_list]
        assert "exiting" not in calls


# Fixtures for all tests
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
        "WORKER_ID": "test-worker-123",
        "LIGHTNING_STUDIO_ID": "studio-123",
        "IDLE_TIMEOUT_SECONDS": "900",
        "MAX_EMPTY_POLLS": "3",
    }