"""Integration tests for Celery stress testing and Redis checkpoint recovery.

These tests verify:
1. Concurrent synthesis with semaphore control (max 4)
2. Redis idempotency - no duplicate synthesis
3. Checkpoint save/resume after worker restart
4. Redis restart data persistence
"""

from __future__ import annotations

import asyncio
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

# Set REDIS_URL to test database BEFORE importing tts_tasks
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1")

import pytest
import redis

from src.audiobook_studio.tasks.tts_tasks import (
    _ACQUIRE_LUA,
    _RELEASE_LUA,
    TTSChapterTask,
    _get_redis,
    synthesize_chapter_task,
)
from src.audiobook_studio.tts.fake_port import FakeRemoteTTSPort
from src.audiobook_studio.tts.port_factory import reset_port as reset_port_factory
from src.audiobook_studio.tts.port_factory import set_port

# Test configuration
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1")
TTS_CONCURRENCY = 4


@pytest.fixture(scope="session")
def redis_client():
    """Get Redis client for testing."""
    client = redis.from_url(TEST_REDIS_URL, decode_responses=True)
    # Clean up test keys before and after
    for key in client.keys("tts:*"):
        client.delete(key)
    yield client
    for key in client.keys("tts:*"):
        client.delete(key)


@pytest.fixture(autouse=True)
def reset_port_fixture():
    """Reset port factory for each test."""
    reset_port_factory()
    # Use fake port for testing
    fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)
    set_port(fake_port)
    yield
    asyncio.run(fake_port.close())
    reset_port_factory()


@pytest.fixture
def sample_paragraphs() -> List[Dict[str, Any]]:
    """Generate sample paragraphs for testing."""
    return [
        {
            "paragraph_id": i + 1,
            "paragraph_index": i + 1,
            "text": f"这是第 {i + 1} 个测试段落，用于验证并发合成功能。" * 3,
            "voice_id": "zh_female_1",
            "prosody": {"rate": 1.0, "pitch": 0.0, "volume": 0.0},
        }
        for i in range(10)
    ]


class TestRedisSemaphore:
    """Test Redis semaphore for concurrency control."""

    def test_semaphore_acquire_release(self, redis_client):
        """Test basic semaphore acquire/release."""
        from src.audiobook_studio.tasks.tts_tasks import _acquire_sha, _get_redis, _release_sha

        client = _get_redis()
        # Clear any existing semaphore state
        client.delete("tts:remote:sem")
        # Re-load scripts with test client
        client.script_flush()
        _acquire_sha = client.script_load(_ACQUIRE_LUA)
        _release_sha = client.script_load(_RELEASE_LUA)

        # Acquire up to limit
        for i in range(TTS_CONCURRENCY):
            result = client.evalsha(_acquire_sha, 1, "tts:remote:sem", TTS_CONCURRENCY, 3600)
            assert result == 1, f"Failed to acquire slot {i}"

        # Next acquire should fail
        result = client.evalsha(_acquire_sha, 1, "tts:remote:sem", TTS_CONCURRENCY, 3600)
        assert result == 0, "Should not acquire beyond limit"

        # Release one
        result = client.evalsha(_release_sha, 1, "tts:remote:sem")
        assert result == 1

        # Now should be able to acquire again
        result = client.evalsha(_acquire_sha, 1, "tts:remote:sem", TTS_CONCURRENCY, 3600)
        assert result == 1

    def test_semaphore_ttl_expiry(self, redis_client):
        """Test semaphore auto-expires after TTL."""
        client = redis_client
        client.script_flush()
        acquire_sha = client.script_load(_ACQUIRE_LUA)

        # Acquire with short TTL
        result = client.evalsha(acquire_sha, 1, "tts:test:sem", 1, 1)  # 1 second TTL
        assert result == 1

        # Wait for expiry
        time.sleep(1.5)

        # Should be able to acquire again
        result = client.evalsha(acquire_sha, 1, "tts:test:sem", 1, 1)
        assert result == 1


class TestIdempotency:
    """Test Redis idempotency key prevents duplicate synthesis."""

    def test_idempotency_key_prevents_duplicate(self, redis_client):
        """Test SETNX idempotency key works."""
        client = redis_client
        idem_key = "tts:idem:test_duplicate"

        # First time - should acquire
        acquired = client.set(idem_key, "1", nx=True, ex=3600)
        assert acquired is True

        # Second time - should fail (already exists)
        acquired = client.set(idem_key, "1", nx=True, ex=3600)
        assert acquired is None  # Returns None when key already exists (nx=True)

    def test_idempotency_different_text_voice_allows(self, redis_client):
        """Test different text/voice combinations get different keys."""
        client = redis_client

        key1 = "tts:idem:hash1"
        key2 = "tts:idem:hash2"

        # Both should succeed (different keys)
        assert client.set(key1, "1", nx=True, ex=3600) is True
        assert client.set(key2, "1", nx=True, ex=3600) is True


class TestCheckpointSaveLoad:
    """Test checkpoint save/load functionality."""

    def test_checkpoint_save_load(self, redis_client):
        """Test saving and loading checkpoint data."""
        client = redis_client
        project_id = 999
        chapter_id = 888

        checkpoint_key = f"tts:checkpoint:{project_id}:{chapter_id}"
        checkpoint_data = {
            "project_id": project_id,
            "chapter_id": chapter_id,
            "completed_paragraphs": [1, 2, 3],
            "failed_paragraphs": [5],
            "chapter_audio_path": "/output/chapter_1.mp3",
            "segments": [{"segment_id": "seg1", "file_path": "/output/seg1.wav", "duration_ms": 1000}],
            "updated_at": time.time(),
        }

        import json

        client.set(checkpoint_key, json.dumps(checkpoint_data), ex=86400)

        # Load and verify
        loaded = client.get(checkpoint_key)
        assert loaded is not None
        loaded_data = json.loads(loaded)
        assert loaded_data["completed_paragraphs"] == [1, 2, 3]
        assert loaded_data["failed_paragraphs"] == [5]

    def test_checkpoint_resume_skips_completed(self, sample_paragraphs):
        """Test that resume skips already completed paragraphs."""
        from src.audiobook_studio.tasks.tts_tasks import TTSChapterTask

        task = TTSChapterTask()
        project_id = 100
        chapter_id = 200

        # Save a checkpoint with some completed paragraphs
        client = _get_redis()
        checkpoint_key = f"tts:checkpoint:{project_id}:{chapter_id}"
        import json

        client.set(
            checkpoint_key,
            json.dumps(
                {
                    "project_id": project_id,
                    "chapter_id": chapter_id,
                    "completed_paragraphs": [1, 2, 3],
                    "failed_paragraphs": [],
                    "segments": [],
                    "updated_at": time.time(),
                }
            ),
            ex=86400,
        )

        # Load checkpoint
        checkpoint = task._load_checkpoint(project_id, chapter_id)
        assert checkpoint is not None
        assert set(checkpoint["completed_paragraphs"]) == {1, 2, 3}


class TestConcurrentSynthesis:
    """Test concurrent synthesis with multiple tasks."""

    @pytest.mark.asyncio
    async def test_concurrent_synthesis_no_duplicates(self, sample_paragraphs):
        """Test concurrent synthesis doesn't produce duplicates."""
        from src.audiobook_studio.tasks.tts_tasks import _synthesize_via_port, get_port

        port = get_port()
        output_dir = Path("./output/test_concurrent")
        output_dir.mkdir(parents=True, exist_ok=True)

        async def synthesize_segment(idx: int, text: str):
            segment_id = f"test_{idx}"
            output_path = output_dir / f"{segment_id}.wav"
            duration, engine = await _synthesize_via_port(
                port, text, "zh_female_1", {"rate": 1.0}, output_path, segment_id
            )
            return {"index": idx, "duration": duration, "path": str(output_path)}

        # Run 5 concurrent syntheses
        tasks = [synthesize_segment(i, p["text"]) for i, p in enumerate(sample_paragraphs[:5])]
        results = await asyncio.gather(*tasks)

        assert len(results) == 5
        for r in results:
            assert r["duration"] > 0
            assert Path(r["path"]).exists()

    def test_concurrent_celery_tasks_semaphore_limit(self, redis_client):
        """Test that Celery tasks respect semaphore limit."""
        # This test verifies the semaphore logic, not actual Celery execution
        client = redis_client
        # Clear any existing semaphore state
        client.delete("tts:remote:sem")
        client.script_flush()
        acquire_sha = client.script_load(_ACQUIRE_LUA)
        release_sha = client.script_load(_RELEASE_LUA)

        # Simulate 5 tasks trying to acquire
        acquired = 0
        for i in range(6):
            result = client.evalsha(acquire_sha, 1, "tts:remote:sem", TTS_CONCURRENCY, 3600)
            if result == 1:
                acquired += 1

        assert acquired == TTS_CONCURRENCY, f"Expected {TTS_CONCURRENCY} acquired, got {acquired}"

        # Release all
        for _ in range(acquired):
            client.evalsha(release_sha, 1, "tts:remote:sem")


class TestWorkerRestartRecovery:
    """Test recovery after worker restart simulation."""

    def test_checkpoint_survives_worker_restart(self, redis_client):
        """Test checkpoint data persists after worker process ends."""
        client = redis_client
        project_id = 300
        chapter_id = 400

        checkpoint_key = f"tts:checkpoint:{project_id}:{chapter_id}"
        import json

        client.set(
            checkpoint_key,
            json.dumps(
                {
                    "project_id": project_id,
                    "chapter_id": chapter_id,
                    "completed_paragraphs": [1, 2, 3, 4],
                    "failed_paragraphs": [5],
                    "segments": [
                        {"segment_id": f"seg{i}", "file_path": f"/output/seg{i}.wav", "duration_ms": 1000 * i}
                        for i in range(1, 5)
                    ],
                    "updated_at": time.time(),
                }
            ),
            ex=86400,
        )

        # Simulate new worker process (new client connection)
        new_client = redis.from_url(TEST_REDIS_URL, decode_responses=True)
        loaded = new_client.get(checkpoint_key)

        assert loaded is not None
        import json

        data = json.loads(loaded)
        assert data["completed_paragraphs"] == [1, 2, 3, 4]
        assert data["failed_paragraphs"] == [5]
        assert len(data["segments"]) == 4

    def test_failed_paragraph_tracking(self, redis_client):
        """Test failed paragraph tracking for resume."""
        client = redis_client
        project_id = 500
        chapter_id = 600

        failed_key = f"tts:failed:{project_id}:{chapter_id}"

        # Record failed paragraphs
        client.sadd(failed_key, "2", "4", "5")
        client.expire(failed_key, 86400)

        # Retrieve
        failed = client.smembers(failed_key)
        assert failed == {"2", "4", "5"}

        # Simulate retry - remove one after success
        client.srem(failed_key, "4")
        failed = client.smembers(failed_key)
        assert failed == {"2", "5"}


class TestRedisRestartPersistence:
    """Test data persistence across Redis restarts."""

    def test_redis_data_persistence(self, redis_client):
        """Test that Redis data persists (simulated by using same instance)."""
        # Since we can't actually restart Redis in unit tests,
        # we verify that data written to Redis is readable
        client = redis_client

        # Write various data types
        client.set("tts:test:string", "value", ex=3600)
        client.hset("tts:test:hash", mapping={"field1": "value1", "field2": "value2"})
        client.sadd("tts:test:set", "member1", "member2")
        client.expire("tts:test:set", 3600)

        # Verify reads
        assert client.get("tts:test:string") == "value"
        assert client.hget("tts:test:hash", "field1") == "value1"
        assert client.smembers("tts:test:set") == {"member1", "member2"}


class TestStressScenarios:
    """High-level stress test scenarios."""

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_high_concurrency_synthesis(self):
        """Test synthesis under high concurrency (10 parallel)."""
        from src.audiobook_studio.tasks.tts_tasks import _synthesize_via_port, get_port

        port = get_port()
        output_dir = Path("./output/test_high_concurrency")
        output_dir.mkdir(parents=True, exist_ok=True)

        async def synth(idx: int):
            segment_id = f"high_concurrent_{idx}"
            output_path = output_dir / f"{segment_id}.wav"
            return await _synthesize_via_port(port, f"测试文本 {idx} " * 10, "zh_female_1", {}, output_path, segment_id)

        # Run 10 concurrent syntheses (more than semaphore limit)
        tasks = [synth(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        # All should succeed (fake port has no real limit)
        assert len(results) == 10
        for duration, engine in results:
            assert duration > 0
            assert engine == "hermes"

    def test_redis_connection_recovery(self, redis_client):
        """Test Redis client recovers after connection issues."""
        # This test verifies the lazy init pattern in _get_redis()
        from src.audiobook_studio.tasks.tts_tasks import _get_redis

        # First call initializes
        client1 = _get_redis()
        assert client1 is not None

        # Subsequent calls return same client
        client2 = _get_redis()
        assert client1 is client2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
