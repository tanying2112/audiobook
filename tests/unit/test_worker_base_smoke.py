import json
import os
from unittest import mock

import pytest

import worker_base as W


class FakeRedisW:
    def __init__(self):
        self.store = {}

    def setex(self, key, ttl, val):
        self.store[key] = val
        return True

    def llen(self, key):
        return 0

    def blpop(self, key, timeout=0):
        return None

    def rpush(self, key, val):
        return 1


class ConcreteWorker(W.BaseWorker):
    def _init_engine(self):
        return mock.MagicMock()

    def _execute_smoke_test(self):
        return None

    def _get_platform_gpu_metrics(self):
        return {
            "gpu_mem_used_mb": 1000,
            "gpu_mem_total_mb": 2000,
            "device_name": "GPU",
            "backend": "torch",
        }

    def _synthesize(self, text, voice_id, prosody, reference_audio):
        return b"WAVDATA"


@pytest.fixture
def worker(monkeypatch):
    for v in [
        "REDIS_HOST",
        "REDIS_AUTH",
        "R2_ENDPOINT",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
        "VOXCPM2_MODEL_PATH",
    ]:
        monkeypatch.setenv(v, "x")
    monkeypatch.setenv("R2_PUBLIC_URL", "https://pub")
    monkeypatch.setattr(W.redis, "Redis", lambda *a, **k: FakeRedisW())
    monkeypatch.setattr(W.boto3, "client", lambda *a, **k: mock.MagicMock())
    exc = mock.MagicMock()
    exc.Boto3Error = Exception
    monkeypatch.setattr(W.boto3, "exceptions", exc)
    w = ConcreteWorker("modal")
    return w


def test_r2_uploader(monkeypatch):
    s3 = mock.MagicMock()
    monkeypatch.setattr(W.boto3, "client", lambda *a, **k: s3)
    u = W.R2Uploader("e", "ak", "sk", "bucket", "https://pub")
    assert u.upload(b"data", "k.wav") == "https://pub/k.wav"
    s3.put_object.assert_called_once()


def test_validate_config_and_shutdown(worker):
    worker._handle_shutdown(15, None)
    assert worker.running is False


def test_network_retry_success(worker):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise W.redis.RedisError("x")
        return "ok"

    assert worker._execute_network_call_with_retry(flaky) == "ok"
    assert calls["n"] == 2


def test_network_retry_exhausted(worker):
    def always_fail():
        raise W.redis.RedisError("boom")

    with pytest.raises(W.redis.RedisError):
        worker._execute_network_call_with_retry(always_fail, max_retries=2)


def test_send_heartbeat(worker):
    worker._send_heartbeat("processing", 3)
    assert any("worker:heartbeat" in k for k in worker.redis.store)


def test_process_single_task_success(worker):
    res = worker._process_single_task({"id": "t1", "text": "hi"})
    assert res["status"] == "success"
    assert res["url"] == "https://pub/tts/t1.wav"


def test_process_single_task_failure(worker, monkeypatch):
    def boom(text, voice_id, prosody, reference_audio):
        raise RuntimeError("crash")

    monkeypatch.setattr(worker, "_synthesize", boom)
    res = worker._process_single_task({"id": "t2", "text": "hi"})
    assert res["status"] == "failed"
    assert "crash" in res["error"]


def test_run_process_and_idle_exit(worker):
    fr = worker.redis
    calls = {"n": 0}

    def blpop(key, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            return (b"tts:tasks", json.dumps({"id": "t1", "text": "hi"}))
        return None

    fr.blpop = blpop
    fr.llen = lambda k: 0
    worker.max_empty_polls = 1
    worker.running = True
    worker.run()


def test_run_corrupted_payload(worker):
    fr = worker.redis
    calls = {"n": 0}

    def blpop(key, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            return (b"tts:tasks", "not-json")
        return None

    fr.blpop = blpop
    fr.llen = lambda k: 0
    worker.max_empty_polls = 1
    worker.running = True
    worker.run()


def test_run_redis_error_then_exit(worker):
    fr = worker.redis
    calls = {"n": 0}

    def blpop(key, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise W.redis.RedisError("severed")
        return None

    fr.blpop = blpop
    fr.llen = lambda k: 0
    worker.max_empty_polls = 1
    worker.running = True
    worker.run()
