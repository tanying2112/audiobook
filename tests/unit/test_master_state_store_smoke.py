import json
import os
import sys
from contextlib import contextmanager
from unittest import mock

import pytest

import master.state_store as S
from master.state_store import DistributedLock, HermesStateStore, TaskState, TTSTask


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.hashes = {}
        self.scan_keys = []

    def register_script(self, script):
        def run(keys=None, args=None):
            return [1, ""]

        return run

    def eval(self, script, numkeys, *keys):
        return 1

    def get(self, key):
        return self.store.get(key)

    def set(self, key, val, nx=False, ex=None):
        if nx and key in self.store:
            return 0
        self.store[key] = val
        return 1

    def delete(self, key):
        return 1 if key in self.store and self.store.pop(key) is not None else 0

    def hset(self, key, mapping=None, **kw):
        h = self.hashes.setdefault(key, {})
        if mapping:
            h.update(mapping)
        h.update(kw)
        return 1

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def expire(self, key, ttl):
        return True

    def rpush(self, key, val):
        return 1

    def blpop(self, key, timeout=0):
        return None

    def scan(self, cursor, match=None, count=None):
        keys = [k for k in self.hashes if k.startswith("tts:task:")]
        return (0, keys)

    def mget(self, keys):
        return [json.dumps(self.hashes[k]) for k in keys if k in self.hashes]


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(S.redis, "Redis", lambda *a, **k: FakeRedis())
    return HermesStateStore("h", 6379, "auth")


def test_ttstask_roundtrip():
    t = TTSTask(
        task_id="tts-1",
        state=TaskState.PENDING,
        text="hi",
        voice_id="v1",
        prosody={"speed": 1.0},
        reference_audio=None,
    )
    h = t.to_hash()
    t2 = TTSTask.from_hash(h)
    assert t2.task_id == "tts-1"
    assert t2.state == TaskState.PENDING
    assert t2.prosody == {"speed": 1.0}


def test_distributed_lock():
    fr = FakeRedis()
    lock = DistributedLock(fr, "lk", "owner")
    assert lock.acquire(blocking=False) is True
    assert lock.renew() is True
    assert lock.release() is True
    # not acquired -> renew/release false
    lock2 = DistributedLock(fr, "lk2", "owner")
    assert lock2.renew() is False
    assert lock2.release() is False
    with DistributedLock(fr, "lk3", "owner") as lock:
        assert lock._acquired is True


def test_idempotency(store):
    assert store.check_idempotency("k1") is None
    assert store.reserve_idempotency("k1", "tts-abc") is True
    assert store.check_idempotency("k1") == "tts-abc"
    assert store.release_idempotency("k1") is True


def test_create_and_get_task(store):
    t = store.create_task("text", "v1", {"speed": 1.0}, idempotency_key="idem1")
    assert t.task_id
    got = store.get_task(t.task_id)
    assert got is not None and got.text == "text"
    assert store.get_task("nonexistent") is None


def test_create_task_idempotent_reuse(store):
    t1 = store.create_task("text", "v1", {}, idempotency_key="same")
    t2 = store.create_task("text2", "v1", {}, idempotency_key="same")
    assert t1.task_id == t2.task_id


def test_get_tasks_by_state(store):
    store.create_task("a", "v", {})
    store.create_task("b", "v", {})
    out = store.get_tasks_by_state(TaskState.PENDING)
    assert len(out) == 2


def test_claim_task_none(store):
    with store.claim_task("w1") as task:
        assert task is None


def test_claim_task_success(store):
    t = store.create_task("a", "v", {})
    fr = store.redis
    fr.blpop = lambda key, timeout=0: ("tts:tasks", json.dumps({"id": t.task_id}))
    with store.claim_task("w1") as claimed:
        assert claimed is not None
        assert claimed.state == TaskState.CLAIMED


def test_transition_complete_fail_update(store):
    t = store.create_task("a", "v", {})
    assert store.transition_state(t.task_id, TaskState.CLAIMED, "w1") is True
    assert store.complete_task(t.task_id, "w1", "https://x/y.wav") is True
    assert store.fail_task(t.task_id, "w1", "boom") is True
    assert store.update_task_fields(t.task_id, {"result_url": "z", "extra": {"a": 1}}) is True
    assert store.transition_state("nope", TaskState.CLAIMED, "w1") is True


def test_task_lock(store):
    t = store.create_task("a", "v", {})
    with store.task_lock(t.task_id, "w1") as lock:
        assert lock._acquired is True


def test_task_lock_fail(monkeypatch):
    fr = FakeRedis()
    fr.eval = lambda *a, **k: 0
    monkeypatch.setattr(S.redis, "Redis", lambda *a, **k: fr)
    s = HermesStateStore("h", 6379, "a")
    with pytest.raises(RuntimeError):
        with s.task_lock("tts-x", "w1"):
            pass


def test_get_task_summary(store):
    store.create_task("a", "v", {})
    summary = store.get_task_summary()
    assert summary[TaskState.PENDING.value] == 1


def test_main_missing_env(monkeypatch):
    monkeypatch.delenv("REDIS_HOST", raising=False)
    monkeypatch.delenv("REDIS_AUTH", raising=False)
    with pytest.raises(SystemExit):
        S.main()


def test_main_ok(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "h")
    monkeypatch.setenv("REDIS_AUTH", "a")
    fake = mock.MagicMock()
    fake.get_task_summary.return_value = {s.value: 0 for s in TaskState}
    monkeypatch.setattr(S, "HermesStateStore", lambda *a, **k: fake)
    S.main()
    fake.get_task_summary.assert_called_once()
