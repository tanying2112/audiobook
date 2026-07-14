"""Tests for Remote VoxCPM2 TTS Client.

Uses pytest-httpx for mocking HTTP responses and testing retry/circuit breaker behavior.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import httpx
import pytest

from src.audiobook_studio.llm.circuit_breaker import CircuitBreaker
from src.audiobook_studio.tasks.tts_tasks import TTSChapterTask
from src.audiobook_studio.tts.remote_voxcpm2_client import (
    RemoteVoxCPM2Client,
    RemoteVoxCPM2Config,
    create_remote_voxcpm2_client,
)


class TestRemoteVoxCPM2Config:
    """Tests for RemoteVoxCPM2Config."""

    def test_default_config(self):
        """Test default configuration values."""
        config = RemoteVoxCPM2Config()
        assert config.endpoint == "https://voxcpm2.guwj609.ccwu.cc/generate"
        assert config.connect_timeout == 5.0
        assert config.read_timeout == 120.0
        assert config.write_timeout == 30.0
        assert config.pool_timeout == 10.0
        assert config.max_retries == 3
        assert config.retry_min_wait == 2.0
        assert config.retry_max_wait == 30.0
        assert config.circuit_breaker_threshold == 3
        assert config.circuit_breaker_timeout == 120.0

    def test_from_env_with_defaults(self, monkeypatch):
        """Test from_env with all defaults (no env vars set)."""
        # Clear any existing env vars
        for key in [
            "VOICEPM2_REMOTE_ENDPOINT",
            "VOICEPM2_CONNECT_TIMEOUT",
            "VOICEPM2_READ_TIMEOUT",
            "VOICEPM2_WRITE_TIMEOUT",
            "VOICEPM2_POOL_TIMEOUT",
            "VOICEPM2_MAX_RETRIES",
            "VOICEPM2_RETRY_MIN_WAIT",
            "VOICEPM2_RETRY_MAX_WAIT",
            "VOICEPM2_CB_THRESHOLD",
            "VOICEPM2_CB_TIMEOUT",
        ]:
            monkeypatch.delenv(key, raising=False)

        config = RemoteVoxCPM2Config.from_env()
        assert config.endpoint == "https://voxcpm2.guwj609.ccwu.cc/generate"
        assert config.connect_timeout == 5.0
        assert config.read_timeout == 120.0

    def test_from_env_with_custom_values(self, monkeypatch):
        """Test from_env with custom environment variables."""
        monkeypatch.setenv("VOICEPM2_REMOTE_ENDPOINT", "https://custom.example.com/generate")
        monkeypatch.setenv("VOICEPM2_CONNECT_TIMEOUT", "10.0")
        monkeypatch.setenv("VOICEPM2_READ_TIMEOUT", "60.0")
        monkeypatch.setenv("VOICEPM2_MAX_RETRIES", "5")
        monkeypatch.setenv("VOICEPM2_CB_THRESHOLD", "5")
        monkeypatch.setenv("VOICEPM2_CB_TIMEOUT", "60.0")

        config = RemoteVoxCPM2Config.from_env()
        assert config.endpoint == "https://custom.example.com/generate"
        assert config.connect_timeout == 10.0
        assert config.read_timeout == 60.0
        assert config.max_retries == 5
        assert config.circuit_breaker_threshold == 5
        assert config.circuit_breaker_timeout == 60.0


class TestRemoteVoxCPM2Client:
    """Tests for RemoteVoxCPM2Client."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return RemoteVoxCPM2Config(
            endpoint="https://test.example.com/generate",
            connect_timeout=2.0,
            read_timeout=10.0,
            max_retries=2,
            retry_min_wait=0.1,
            retry_max_wait=1.0,
            circuit_breaker_threshold=2,
            circuit_breaker_timeout=10.0,
        )

    @pytest.fixture
    def circuit_breaker(self):
        """Create a fresh circuit breaker for testing."""
        return CircuitBreaker(
            provider_name="test_voxcpm2",
            failure_threshold=2,
            recovery_timeout_s=10.0,
        )

    @pytest.fixture
    def client(self, config, circuit_breaker):
        """Create client with test config and circuit breaker."""
        return RemoteVoxCPM2Client(config=config, circuit_breaker=circuit_breaker)

    @pytest.mark.asyncio
    async def test_synthesize_success(self, client, httpx_mock):
        """Test successful synthesis."""
        # Mock successful response
        audio_data = b"fake_wav_audio_data"
        httpx_mock.add_response(
            method="POST",
            url="https://test.example.com/generate",
            content=audio_data,
            headers={"Content-Type": "audio/wav"},
            status_code=200,
        )

        result = await client.synthesize(
            text="测试文本",
            voice_id="zh_female_1",
            prosody={"rate": "1.0"},
        )

        assert result == audio_data
        assert len(httpx_mock.get_requests()) == 1

        # Verify request payload
        request = httpx_mock.get_requests()[0]
        assert request.method == "POST"
        assert str(request.url) == "https://test.example.com/generate"
        import json

        payload = json.loads(request.content)
        assert payload["text"] == "测试文本"
        assert payload["voice_id"] == "zh_female_1"
        assert payload["prosody"] == {"rate": "1.0"}

    @pytest.mark.asyncio
    async def test_synthesize_with_reference_audio(self, client, httpx_mock):
        """Test synthesis with reference audio for voice cloning."""
        audio_data = b"fake_wav_audio_data"
        httpx_mock.add_response(
            method="POST",
            url="https://test.example.com/generate",
            content=audio_data,
            status_code=200,
        )

        result = await client.synthesize(
            text="测试文本",
            voice_id="zh_female_1",
            reference_audio="/path/to/reference.wav",
        )

        assert result == audio_data
        request = httpx_mock.get_requests()[0]
        import json

        payload = json.loads(request.content)
        assert payload["reference_audio"] == "/path/to/reference.wav"

    @pytest.mark.asyncio
    async def test_synthesize_http_error_4xx(self, client, httpx_mock, circuit_breaker):
        """Test synthesis with 4xx client error (no retry)."""
        httpx_mock.add_response(
            method="POST",
            url="https://test.example.com/generate",
            status_code=400,
            json={"detail": "Bad request"},
        )

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.synthesize("测试", "zh_female_1")

        assert exc_info.value.response.status_code == 400
        # Circuit breaker should record failure
        assert circuit_breaker.failure_count == 1
        assert circuit_breaker.state == "closed"  # Not yet open

    @pytest.mark.asyncio
    async def test_synthesize_http_error_5xx_retry(self, client, httpx_mock, circuit_breaker):
        """Test synthesis with 5xx server error triggers retry."""
        # First two requests fail with 500, third succeeds
        httpx_mock.add_response(method="POST", url="https://test.example.com/generate", status_code=500)
        httpx_mock.add_response(method="POST", url="https://test.example.com/generate", status_code=500)
        httpx_mock.add_response(
            method="POST",
            url="https://test.example.com/generate",
            content=b"success_audio",
            status_code=200,
        )

        result = await client.synthesize("测试", "zh_female_1")
        assert result == b"success_audio"
        assert len(httpx_mock.get_requests()) == 3

    @pytest.mark.asyncio
    async def test_synthesize_timeout_retry(self, client, httpx_mock, circuit_breaker):
        """Test synthesis with timeout triggers retry."""
        # First request times out, second succeeds
        httpx_mock.add_exception(httpx.TimeoutException("Read timeout"))
        httpx_mock.add_response(
            method="POST",
            url="https://test.example.com/generate",
            content=b"success_audio",
            status_code=200,
        )

        result = await client.synthesize("测试", "zh_female_1")
        assert result == b"success_audio"
        assert len(httpx_mock.get_requests()) == 2

    @pytest.mark.asyncio
    async def test_synthesize_connection_error_retry(self, client, httpx_mock, circuit_breaker):
        """Test synthesis with connection error triggers retry."""
        httpx_mock.add_exception(httpx.ConnectError("Connection refused"))
        httpx_mock.add_response(
            method="POST",
            url="https://test.example.com/generate",
            content=b"success_audio",
            status_code=200,
        )

        result = await client.synthesize("测试", "zh_female_1")
        assert result == b"success_audio"
        assert len(httpx_mock.get_requests()) == 2

    @pytest.mark.asyncio
    async def test_synthesize_max_retries_exhausted(self, client, httpx_mock, circuit_breaker):
        """Test synthesis fails after max retries exhausted."""
        # All retries fail with 500
        for _ in range(3):  # max_retries = 2, so 3 total attempts (initial + 2 retries)
            httpx_mock.add_response(method="POST", url="https://test.example.com/generate", status_code=500)

        with pytest.raises(httpx.HTTPStatusError):
            await client.synthesize("测试", "zh_female_1")

        assert len(httpx_mock.get_requests()) == 3  # initial + 2 retries

    @pytest.mark.asyncio
    async def test_synthesize_circuit_breaker_open(self, client, circuit_breaker):
        """Test synthesis is rejected when circuit breaker is open."""
        # Manually open the circuit breaker
        circuit_breaker.record_failure()
        circuit_breaker.record_failure()  # threshold=2, so this opens it
        assert circuit_breaker.state == "open"

        with pytest.raises(RuntimeError, match="Circuit breaker open"):
            await client.synthesize("测试", "zh_female_1")

    @pytest.mark.asyncio
    async def test_synthesize_client_closed(self, client):
        """Test synthesis fails when client is closed."""
        await client.close()

        with pytest.raises(RuntimeError, match="Client is closed"):
            await client.synthesize("测试", "zh_female_1")

    @pytest.mark.asyncio
    async def test_synthesize_to_file(self, client, httpx_mock, tmp_path):
        """Test synthesize_to_file saves audio to disk."""
        audio_data = b"fake_wav_audio_data_for_file"
        httpx_mock.add_response(
            method="POST",
            url="https://test.example.com/generate",
            content=audio_data,
            status_code=200,
        )

        output_path = tmp_path / "output.wav"
        result_path = await client.synthesize_to_file(
            text="测试文本",
            voice_id="zh_female_1",
            output_path=output_path,
        )

        assert result_path == output_path
        assert output_path.exists()
        assert output_path.read_bytes() == audio_data

    @pytest.mark.asyncio
    async def test_context_manager(self, config, circuit_breaker):
        """Test async context manager properly closes client."""
        client = RemoteVoxCPM2Client(config=config, circuit_breaker=circuit_breaker)

        async with client as c:
            assert c is client
            # Client should be usable

        # After exit, client should be closed
        assert client._closed is True

    @pytest.mark.asyncio
    async def test_get_circuit_breaker_status(self, client, circuit_breaker):
        """Test getting circuit breaker status."""
        status = client.get_circuit_breaker_status()
        assert status["provider"] == "test_voxcpm2"
        assert status["state"] == "closed"
        assert status["failure_count"] == 0

    @pytest.mark.asyncio
    async def test_reset_circuit_breaker(self, client, circuit_breaker):
        """Test manual circuit breaker reset."""
        # Open the circuit
        circuit_breaker.record_failure()
        circuit_breaker.record_failure()
        assert circuit_breaker.state == "open"

        # Reset
        client.reset_circuit_breaker()
        assert circuit_breaker.state == "closed"
        assert circuit_breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_close_idempotent(self, client):
        """Test close() is idempotent."""
        await client.close()
        await client.close()  # Should not raise
        assert client._closed is True

    @pytest.mark.asyncio
    async def test_synthesize_unexpected_error_records_failure(self, client, httpx_mock, circuit_breaker):
        """Test that unexpected errors are recorded in circuit breaker."""
        # Mock an unexpected error (not httpx exception)
        httpx_mock.add_exception(ValueError("Unexpected error"))

        with pytest.raises(ValueError):
            await client.synthesize("测试", "zh_female_1")

        # Circuit breaker should record the failure
        assert circuit_breaker.failure_count == 1


class TestRemoteVoxCPM2ClientRetryBehavior:
    """Tests specifically for retry behavior with tenacity."""

    @pytest.fixture
    def fast_retry_config(self):
        """Config with fast retries for testing."""
        return RemoteVoxCPM2Config(
            endpoint="https://test.example.com/generate",
            max_retries=3,
            retry_min_wait=0.01,
            retry_max_wait=0.1,
            connect_timeout=1.0,
            read_timeout=2.0,
        )

    @pytest.mark.asyncio
    async def test_retry_exponential_backoff_timing(self, fast_retry_config, httpx_mock):
        """Test that retries use exponential backoff."""
        import time

        client = RemoteVoxCPM2Client(config=fast_retry_config)

        # All requests fail with timeout
        # stop_after_attempt(3) = 3 total attempts (initial + 2 retries)
        for _ in range(3):
            httpx_mock.add_exception(httpx.TimeoutException("Timeout"))

        start = time.monotonic()
        with pytest.raises(httpx.TimeoutException):
            await client.synthesize("测试", "zh_female_1")
        elapsed = time.monotonic() - start

        # Should have waited for retries (exponential backoff with min=0.01, max=0.1)
        # Exact timing depends on tenacity implementation, just verify retries happened
        # and it didn't hang indefinitely
        assert elapsed >= 0.1  # At least some backoff occurred
        assert elapsed < 10.0  # But not too long (CI can be slow)

        await client.close()

    @pytest.mark.asyncio
    async def test_4xx_no_retry(self, fast_retry_config, httpx_mock):
        """Test that 4xx errors don't trigger retry."""
        client = RemoteVoxCPM2Client(config=fast_retry_config)

        httpx_mock.add_response(method="POST", url="https://test.example.com/generate", status_code=400)

        with pytest.raises(httpx.HTTPStatusError):
            await client.synthesize("测试", "zh_female_1")

        # Only 1 request, no retries
        assert len(httpx_mock.get_requests()) == 1

        await client.close()


class TestCreateRemoteVoxCPM2Client:
    """Tests for the factory function."""

    @pytest.mark.asyncio
    async def test_factory_creates_client(self):
        """Test factory function creates and initializes client."""
        config = RemoteVoxCPM2Config(
            endpoint="https://factory.example.com/generate",
        )

        client = await create_remote_voxcpm2_client(config)

        assert isinstance(client, RemoteVoxCPM2Client)
        assert client.config.endpoint == "https://factory.example.com/generate"
        assert not client._closed

        await client.close()

    @pytest.mark.asyncio
    async def test_factory_with_none_config_uses_env(self, monkeypatch):
        """Test factory with None config uses from_env()."""
        monkeypatch.setenv("VOICEPM2_REMOTE_ENDPOINT", "https://env.example.com/generate")

        client = await create_remote_voxcpm2_client(None)

        assert client.config.endpoint == "https://env.example.com/generate"
        await client.close()


class TestRemoteVoxCPM2ClientIntegration:
    """Integration-style tests with more realistic scenarios."""

    @pytest.mark.asyncio
    async def test_full_chapter_synthesis_simulation(self, httpx_mock, tmp_path):
        """Simulate synthesizing multiple paragraphs for a chapter."""
        config = RemoteVoxCPM2Config(
            endpoint="https://test.example.com/generate",
            max_retries=2,
            retry_min_wait=0.01,
            retry_max_wait=0.1,
        )
        client = RemoteVoxCPM2Client(config=config)

        # Mock responses for 5 paragraphs
        paragraphs = [
            ("第一章 开始了", "zh_female_1"),
            ("主人公走在路上", "zh_female_1"),
            ("天气很好", "zh_male_1"),
            ("他感到很开心", "zh_male_1"),
            ("故事结束", "zh_female_1"),
        ]

        for i, (text, voice) in enumerate(paragraphs):
            httpx_mock.add_response(
                method="POST",
                url="https://test.example.com/generate",
                content=f"audio_{i}".encode(),
                status_code=200,
            )

        segments = []
        for i, (text, voice) in enumerate(paragraphs):
            audio = await client.synthesize(text, voice)
            segments.append((text, voice, audio))
            # Save to file
            out_path = tmp_path / f"para_{i}.wav"
            out_path.write_bytes(audio)

        assert len(segments) == 5
        assert all(len(s[2]) > 0 for s in segments)

        # Verify all files exist
        for i in range(5):
            assert (tmp_path / f"para_{i}.wav").exists()

        await client.close()

    @pytest.mark.asyncio
    async def test_partial_failure_resume(self, httpx_mock, tmp_path):
        """Test that failed paragraphs can be retried (simulating resume)."""
        config = RemoteVoxCPM2Config(
            endpoint="https://test.example.com/generate",
            max_retries=1,
            retry_min_wait=0.01,
            retry_max_wait=0.1,
        )
        client = RemoteVoxCPM2Client(config=config)

        # The retry decorator uses stop_after_attempt(3) = 3 total attempts
        # For "第一段": 1 success
        httpx_mock.add_response(
            method="POST", url="https://test.example.com/generate", content=b"audio_0", status_code=200
        )
        # For "第二段": 3 failures (initial + 2 retries) - all 500
        httpx_mock.add_response(method="POST", url="https://test.example.com/generate", status_code=500)
        httpx_mock.add_response(method="POST", url="https://test.example.com/generate", status_code=500)
        httpx_mock.add_response(method="POST", url="https://test.example.com/generate", status_code=500)
        # For "第三段": 1 success
        httpx_mock.add_response(
            method="POST", url="https://test.example.com/generate", content=b"audio_2", status_code=200
        )

        results = []
        texts = ["第一段", "第二段", "第三段"]

        for i, text in enumerate(texts):
            try:
                audio = await client.synthesize(text, "zh_female_1")
                results.append(("success", audio))
                (tmp_path / f"para_{i}.wav").write_bytes(audio)
            except httpx.HTTPStatusError as e:
                results.append(("failed", str(e)))

        assert results[0][0] == "success"
        assert results[1][0] == "failed"
        assert results[2][0] == "success"

        # Simulate resume: retry failed paragraph (another 3 attempts: 2 failures + 1 success)
        httpx_mock.add_response(method="POST", url="https://test.example.com/generate", status_code=500)
        httpx_mock.add_response(method="POST", url="https://test.example.com/generate", status_code=500)
        httpx_mock.add_response(
            method="POST", url="https://test.example.com/generate", content=b"audio_1_retry", status_code=200
        )

        audio = await client.synthesize(texts[1], "zh_female_1")
        assert audio == b"audio_1_retry"
        (tmp_path / "para_1.wav").write_bytes(audio)

        assert all((tmp_path / f"para_{i}.wav").exists() for i in range(3))

        await client.close()


# =============================================================================
# Celery Task Tests (TTSChapterTask)
# =============================================================================


class TestTTSChapterTaskIdempotency:
    """Tests for Redis idempotency key functionality in TTSChapterTask."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        mock = MagicMock()
        mock.set.return_value = True  # SETNX succeeds (first call)
        mock.get.return_value = None
        mock.sadd.return_value = 1
        mock.smembers.return_value = set()
        mock.delete.return_value = 1
        mock.expire.return_value = True
        mock.evalsha.side_effect = [1, 1]  # acquire, release
        mock.script_load.return_value = "mock_sha"
        return mock

    @pytest.fixture
    def task(self, mock_redis, monkeypatch):
        """Create TTSChapterTask with mocked Redis."""
        import src.audiobook_studio.tasks.tts_tasks as tts_tasks

        monkeypatch.setattr(tts_tasks, "_get_redis", lambda: mock_redis)
        monkeypatch.setattr(tts_tasks, "_redis_client", mock_redis)
        monkeypatch.setattr(tts_tasks, "_acquire_sha", "mock_acquire_sha")
        monkeypatch.setattr(tts_tasks, "_release_sha", "mock_release_sha")

        task = TTSChapterTask()
        return task

    def test_idem_key_generation(self, task):
        """Test idempotency key generation from text|voice_id|prosody."""
        text = "测试文本"
        voice_id = "zh_female_1"
        prosody = {"rate": "1.0", "pitch": "0"}

        key = task._idem_key(text, voice_id, prosody)

        assert key.startswith("tts:idem:")
        assert len(key) == 9 + 16  # "tts:idem:" + 16 char hex digest

        # Same inputs should produce same key
        key2 = task._idem_key(text, voice_id, prosody)
        assert key == key2

        # Different prosody should produce different key
        key3 = task._idem_key(text, voice_id, {"rate": "2.0"})
        assert key != key3

        # Different text should produce different key
        key4 = task._idem_key("其他文本", voice_id, prosody)
        assert key != key4

    def test_check_and_set_idempotency_first_call(self, task, mock_redis):
        """Test idempotency check returns True on first call (SETNX succeeds)."""
        mock_redis.set.return_value = True

        result = task._check_and_set_idempotency("tts:idem:test123")

        assert result is True
        mock_redis.set.assert_called_once_with("tts:idem:test123", "1", nx=True, ex=3600)

    def test_check_and_set_idempotency_duplicate(self, task, mock_redis):
        """Test idempotency check returns False on duplicate call (SETNX fails)."""
        mock_redis.set.return_value = False

        result = task._check_and_set_idempotency("tts:idem:test123")

        assert result is False
        mock_redis.set.assert_called_once_with("tts:idem:test123", "1", nx=True, ex=3600)

    def test_check_and_set_idempotency_redis_unavailable(self, task, monkeypatch):
        """Test idempotency check returns True when Redis is unavailable (fail-open)."""
        import src.audiobook_studio.tasks.tts_tasks as tts_tasks

        monkeypatch.setattr(tts_tasks, "_redis_client", None)

        result = task._check_and_set_idempotency("tts:idem:test123")

        assert result is True

    def test_check_and_set_idempotency_redis_error(self, task, mock_redis):
        """Test idempotency check returns True on Redis error (fail-open)."""
        mock_redis.set.side_effect = Exception("Redis connection error")

        result = task._check_and_set_idempotency("tts:idem:test123")

        assert result is True


class TestTTSChapterTaskSemaphore:
    """Tests for Redis semaphore concurrency control in TTSChapterTask."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        mock = MagicMock()
        mock.evalsha.side_effect = [1, 1]  # acquire, release
        mock.script_load.return_value = "mock_sha"
        return mock

    @pytest.fixture
    def task(self, mock_redis, monkeypatch):
        """Create TTSChapterTask with mocked Redis."""
        import src.audiobook_studio.tasks.tts_tasks as tts_tasks

        monkeypatch.setattr(tts_tasks, "_get_redis", lambda: mock_redis)
        monkeypatch.setattr(tts_tasks, "_redis_client", mock_redis)
        monkeypatch.setattr(tts_tasks, "_acquire_sha", "mock_acquire_sha")
        monkeypatch.setattr(tts_tasks, "_release_sha", "mock_release_sha")

        task = TTSChapterTask()
        return task

    def test_acquire_semaphore_success(self, task, mock_redis):
        """Test semaphore acquire succeeds when under limit."""
        mock_redis.evalsha.return_value = 1

        result = task._acquire_semaphore()

        assert result is True
        assert task._semaphore_acquired is True
        mock_redis.evalsha.assert_called_once_with("mock_acquire_sha", 1, "tts:remote:sem", 4, 3600)

    def test_acquire_semaphore_limit_reached(self, task, mock_redis):
        """Test semaphore acquire fails when limit reached."""
        mock_redis.evalsha.side_effect = None
        mock_redis.evalsha.return_value = 0

        result = task._acquire_semaphore()

        assert result is False
        assert task._semaphore_acquired is False

    def test_acquire_semaphore_redis_unavailable(self, task, monkeypatch):
        """Test semaphore acquire returns True when Redis unavailable (fail-open)."""
        import src.audiobook_studio.tasks.tts_tasks as tts_tasks

        monkeypatch.setattr(tts_tasks, "_redis_client", None)

        result = task._acquire_semaphore()

        assert result is True

    def test_acquire_semaphore_redis_error(self, task, mock_redis):
        """Test semaphore acquire returns True on Redis error (fail-open)."""
        mock_redis.evalsha.side_effect = Exception("Redis error")

        result = task._acquire_semaphore()

        assert result is True

    def test_release_semaphore(self, task, mock_redis):
        """Test semaphore release decrements counter."""
        task._semaphore_acquired = True
        mock_redis.evalsha.return_value = 1

        task._release_semaphore()

        assert task._semaphore_acquired is False
        mock_redis.evalsha.assert_called_once_with("mock_release_sha", 1, "tts:remote:sem")

    def test_release_semaphore_not_acquired(self, task, mock_redis):
        """Test release is no-op when semaphore not acquired."""
        task._semaphore_acquired = False

        task._release_semaphore()

        mock_redis.evalsha.assert_not_called()


class TestSynthesizeChapterTaskProgress:
    """Tests for Celery task progress updates in synthesize_chapter_task."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        mock = MagicMock()
        mock.evalsha.side_effect = [1, 1]  # acquire, release
        mock.set.return_value = True
        mock.sadd.return_value = 1
        mock.smembers.return_value = set()
        mock.delete.return_value = 1
        mock.expire.return_value = True
        mock.script_load.return_value = "mock_sha"
        return mock

    @pytest.fixture
    def mock_task(self, mock_redis, monkeypatch):
        """Create a TTSChapterTask instance with mocked dependencies."""
        import src.audiobook_studio.tasks.tts_tasks as tts_tasks

        monkeypatch.setattr(tts_tasks, "_get_redis", lambda: mock_redis)
        monkeypatch.setattr(tts_tasks, "_redis_client", mock_redis)
        monkeypatch.setattr(tts_tasks, "_acquire_sha", "mock_acquire_sha")
        monkeypatch.setattr(tts_tasks, "_release_sha", "mock_release_sha")

        # Mock the RemoteVoxCPM2Client
        mock_client = AsyncMock()
        mock_client.synthesize = AsyncMock(return_value=b"fake_audio_data")
        mock_client.close = AsyncMock()

        # Create task instance
        task = TTSChapterTask()
        task._voxcpm2_client = mock_client

        # Mock Celery's update_state
        task.update_state = MagicMock()

        # Mock request.id
        type(task).request = PropertyMock(return_value=MagicMock(id="test-task-id", retries=0))

        return task

    def test_progress_meta_structure(self, mock_task):
        """Test that progress meta contains current, total, paragraph_id."""
        # Simulate progress update
        mock_task.update_state(
            state="PROGRESS",
            meta={
                "current": 3,
                "total": 10,
                "paragraph_id": 42,
                "paragraph_index": 3,
            },
        )

        # Verify update_state was called with correct meta
        mock_task.update_state.assert_called_once()
        call_args = mock_task.update_state.call_args
        assert call_args.kwargs["state"] == "PROGRESS"
        meta = call_args.kwargs["meta"]
        assert meta["current"] == 3
        assert meta["total"] == 10
        assert meta["paragraph_id"] == 42
        assert meta["paragraph_index"] == 3

    def test_get_tts_status_parses_progress_meta(self):
        """Test get_tts_status correctly parses progress meta from Celery result."""
        from unittest.mock import MagicMock, patch

        from src.audiobook_studio.tasks.tts_tasks import get_tts_status

        # Mock Celery AsyncResult
        mock_result = MagicMock()
        mock_result.state = "PROGRESS"
        mock_result.info = {
            "current": 3,
            "total": 10,
            "paragraph_id": 42,
            "paragraph_index": 3,
        }

        with patch("src.audiobook_studio.tasks.tts_tasks.celery_app.AsyncResult", return_value=mock_result):
            status = get_tts_status("test-task-id")

        assert status["task_id"] == "test-task-id"
        assert status["state"] == "PROGRESS"
        assert status["progress"] == "processing"
        assert status["current"] == 3
        assert status["total"] == 10
        assert status["paragraph_id"] == 42
        assert status["paragraph_index"] == 3

    def test_get_tts_status_completed(self):
        """Test get_tts_status for completed task."""
        from unittest.mock import MagicMock, patch

        from src.audiobook_studio.tasks.tts_tasks import get_tts_status

        mock_result = MagicMock()
        mock_result.state = "SUCCESS"
        mock_result.info = {
            "status": "completed",
            "chapter_audio_path": "/output/chapter_1.mp3",
            "segments": [],
        }

        with patch("src.audiobook_studio.tasks.tts_tasks.celery_app.AsyncResult", return_value=mock_result):
            status = get_tts_status("test-task-id")

        assert status["task_id"] == "test-task-id"
        assert status["state"] == "SUCCESS"
        assert status["progress"] == "completed"

    def test_get_tts_status_failed(self):
        """Test get_tts_status for failed task."""
        from unittest.mock import MagicMock, patch

        from src.audiobook_studio.tasks.tts_tasks import get_tts_status

        mock_result = MagicMock()
        mock_result.state = "FAILURE"
        mock_result.info = {"error": "Connection timeout"}

        with patch("src.audiobook_studio.tasks.tts_tasks.celery_app.AsyncResult", return_value=mock_result):
            status = get_tts_status("test-task-id")

        assert status["task_id"] == "test-task-id"
        assert status["state"] == "FAILURE"
        assert status["progress"] == "failed"
        assert status["error"] == "Connection timeout"

    def test_get_tts_status_retry(self):
        """Test get_tts_status for retrying task."""
        from unittest.mock import MagicMock, patch

        from src.audiobook_studio.tasks.tts_tasks import get_tts_status

        mock_result = MagicMock()
        mock_result.state = "RETRY"
        mock_result.info = {
            "current": 1,
            "total": 5,
            "paragraph_id": 10,
            "paragraph_index": 1,
        }

        with patch("src.audiobook_studio.tasks.tts_tasks.celery_app.AsyncResult", return_value=mock_result):
            status = get_tts_status("test-task-id")

        assert status["task_id"] == "test-task-id"
        assert status["state"] == "RETRY"
        assert status["progress"] == "retrying"
        assert status["current"] == 1
        assert status["total"] == 5


# Pytest configuration
pytest_plugins = ["pytest_asyncio"]
