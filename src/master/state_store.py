"""
Hermes State Store — Distributed State Machine for TTS Task Lifecycle.

Provides:
1. Distributed locking (SET NX + Lua TTL refresh) for idempotent task claiming
2. TTS Task State Machine: PENDING → CLAIMED → SYNTHESIZING → UPLOADING → COMPLETED | FAILED
3. Idempotency key support for idempotent re-submission
4. TTL-aware state TTL (auto-cleanup after completion)

Redis Key Schema:
- tts:task:{task_id}           (hash) → task state machine
- tts:lock:{task_id}           (string) → distributed lock with TTL
- tts:idempotency:{idempotency_key} → task_id mapping (TTL 24h)
"""

import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Optional

import redis


class TaskState(str, Enum):
    """TTS Task lifecycle states."""

    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    SYNTHESIZING = "SYNTHESIZING"
    UPLOADING = "UPLOADING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# Valid state transitions (from -> allowed next states)
VALID_TRANSITIONS = {
    TaskState.PENDING: {TaskState.CLAIMED, TaskState.FAILED},
    TaskState.CLAIMED: {TaskState.SYNTHESIZING, TaskState.FAILED},
    TaskState.SYNTHESIZING: {TaskState.UPLOADING, TaskState.FAILED},
    TaskState.UPLOADING: {TaskState.COMPLETED, TaskState.FAILED},
    TaskState.COMPLETED: set(),  # Terminal
    TaskState.FAILED: {TaskState.CLAIMED},  # Allow retry
}

# Terminal states
TERMINAL_STATES = {TaskState.COMPLETED, TaskState.FAILED}

# TTL configuration (seconds)
TASK_TTL_PENDING = 3600  # 1h for pending tasks
TASK_TTL_ACTIVE = 7200  # 2h for in-flight tasks
TASK_TTL_COMPLETED = 86400  # 24h for completed/failed
IDEMPOTENCY_TTL = 86400  # 24h idempotency key TTL
LOCK_TTL = 300  # 5min lock TTL (renewable)
LOCK_RENEWAL_INTERVAL = 30  # Renew lock every 30s


# Lua script for atomic lock acquisition (SET NX + TTL)
LOCK_ACQUIRE_SCRIPT = """
if redis.call('set', KEYS[1], ARGV[1], 'nx', 'ex', ARGV[2]) then
    return 1
else
    return 0
end
"""

# Lua script for atomic lock renewal (only if we own it)
LOCK_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
else
    return 0
end
"""

# Lua script for atomic lock release (only if we own it)
LOCK_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

# Lua script for atomic state transition with validation
STATE_TRANSITION_SCRIPT = """
local task_key = KEYS[1]
local lock_key = KEYS[2]
local new_state = ARGV[1]
local worker_id = ARGV[2]
local timestamp = ARGV[3]
local ttl = ARGV[4]

-- Verify lock ownership
if redis.call('get', lock_key) ~= worker_id then
    return {0, "LOCK_NOT_OWNED"}
end

-- Get current state
local current_state = redis.call('hget', task_key, 'state')
if not current_state then
    return {0, "TASK_NOT_FOUND"}
end

-- Validate transition
local valid = false
local transitions = {
    PENDING = {CLAIMED=1, FAILED=1},
    CLAIMED = {SYNTHESIZING=1, FAILED=1},
    SYNTHESIZING = {UPLOADING=1, FAILED=1},
    UPLOADING = {COMPLETED=1, FAILED=1},
    COMPLETED = {},
    FAILED = {CLAIMED=1}
}
if transitions[current_state] and transitions[current_state][new_state] then
    valid = true
end

if not valid then
    return {0, "INVALID_TRANSITION:" .. current_state .. "->" .. new_state}
end

-- Perform atomic transition
redis.call('hset', task_key, 'state', new_state, 'updated_at', timestamp, 'worker_id', worker_id)
redis.call('expire', task_key, ttl)
return {1, "OK"}
"""


@dataclass
class TTSTask:
    """TTS Task state machine record."""

    task_id: str
    state: TaskState
    text: str
    voice_id: str
    prosody: Dict[str, Any]
    reference_audio: Optional[str]
    worker_id: Optional[str] = None
    result_url: Optional[str] = None
    error: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0
    idempotency_key: Optional[str] = None

    @classmethod
    def from_hash(cls, data: Dict[str, str]) -> "TTSTask":
        """Reconstruct from Redis hash."""
        return cls(
            task_id=data["task_id"],
            state=TaskState(data["state"]),
            text=data["text"],
            voice_id=data["voice_id"],
            prosody=json.loads(data.get("prosody", "{}")),
            reference_audio=data.get("reference_audio") or None,
            worker_id=data.get("worker_id") or None,
            result_url=data.get("result_url") or None,
            error=data.get("error") or None,
            created_at=float(data.get("created_at", 0)),
            updated_at=float(data.get("updated_at", 0)),
            idempotency_key=data.get("idempotency_key") or None,
        )

    def to_hash(self) -> Dict[str, str]:
        """Serialize to Redis hash."""
        return {
            "task_id": self.task_id,
            "state": self.state.value,
            "text": self.text,
            "voice_id": self.voice_id,
            "prosody": json.dumps(self.prosody),
            "reference_audio": self.reference_audio or "",
            "worker_id": self.worker_id or "",
            "result_url": self.result_url or "",
            "error": self.error or "",
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
            "idempotency_key": self.idempotency_key or "",
        }


class DistributedLock:
    """Distributed lock with automatic TTL renewal."""

    def __init__(self, redis_client: redis.Redis, lock_key: str, owner_id: str, ttl: int = LOCK_TTL):
        self.redis = redis_client
        self.lock_key = lock_key
        self.owner_id = owner_id
        self.ttl = ttl
        self._acquired = False
        self._renew_task = None

    def acquire(self, blocking: bool = True, timeout: float = 10.0) -> bool:
        """Acquire lock with optional blocking wait."""
        start = time.time()
        while True:
            result = self.redis.eval(LOCK_ACQUIRE_SCRIPT, 1, self.lock_key, self.owner_id, self.ttl)
            if result:
                self._acquired = True
                return True

            if not blocking or (time.time() - start) >= timeout:
                return False

            time.sleep(0.1)

    def renew(self) -> bool:
        """Renew lock TTL if we still own it."""
        if not self._acquired:
            return False
        result = self.redis.eval(LOCK_RENEW_SCRIPT, 1, self.lock_key, self.owner_id, self.ttl)
        return bool(result)

    def release(self) -> bool:
        """Release lock if we own it."""
        if not self._acquired:
            return False
        result = self.redis.eval(LOCK_RELEASE_SCRIPT, 1, self.lock_key, self.owner_id)
        self._acquired = False
        return bool(result)

    def __enter__(self):
        self.acquire(blocking=True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class HermesStateStore:
    """
    Centralized TTS Task State Machine with Distributed Locking.

    Guarantees:
    - At-least-once delivery via CLAIMED state + lock ownership
    - Idempotent task submission via idempotency keys
    - Atomic state transitions validated by Lua script
    - Automatic TTL cleanup of completed/failed tasks
    """

    def __init__(
        self,
        redis_host: str,
        redis_port: int,
        redis_auth: str,
    ):
        self.redis = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_auth,
            decode_responses=True,
            socket_timeout=30,  # Must exceed blpop timeout (5s) + buffer
            socket_connect_timeout=10,
            ssl=True,  # Upstash requires TLS
        )
        # Register Lua scripts
        self._lock_acquire = self.redis.register_script(LOCK_ACQUIRE_SCRIPT)
        self._lock_renew = self.redis.register_script(LOCK_RENEW_SCRIPT)
        self._lock_release = self.redis.register_script(LOCK_RELEASE_SCRIPT)
        self._state_transition = self.redis.register_script(STATE_TRANSITION_SCRIPT)

    # --- Idempotency Key Support ---

    def check_idempotency(self, idempotency_key: str) -> Optional[str]:
        """
        Check if idempotency key exists.

        Returns existing task_id if found, None otherwise.
        """
        key = f"tts:idempotency:{idempotency_key}"
        return self.redis.get(key)

    def reserve_idempotency(self, idempotency_key: str, task_id: str) -> bool:
        """
        Atomically reserve idempotency key.

        Returns True if reserved, False if already exists.
        """
        key = f"tts:idempotency:{idempotency_key}"
        return bool(self.redis.set(key, task_id, nx=True, ex=IDEMPOTENCY_TTL))

    def release_idempotency(self, idempotency_key: str) -> bool:
        """Release idempotency reservation (on task failure/retry)."""
        key = f"tts:idempotency:{idempotency_key}"
        return bool(self.redis.delete(key))

    # --- Task CRUD ---

    def create_task(
        self,
        text: str,
        voice_id: str,
        prosody: Dict[str, Any],
        reference_audio: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> TTSTask:
        """
        Create new PENDING task.

        If idempotency_key provided and exists, returns existing task.
        """
        # Check idempotency
        if idempotency_key:
            existing_id = self.check_idempotency(idempotency_key)
            if existing_id:
                task = self.get_task(existing_id)
                if task and task.state != TaskState.FAILED:
                    return task
                # If failed, allow retry by releasing idempotency key
                self.release_idempotency(idempotency_key)

        task_id = f"tts-{uuid.uuid4().hex[:12]}"
        now = time.time()

        task = TTSTask(
            task_id=task_id,
            state=TaskState.PENDING,
            text=text,
            voice_id=voice_id,
            prosody=prosody,
            reference_audio=reference_audio,
            created_at=now,
            updated_at=now,
            idempotency_key=idempotency_key,
        )

        # Store task
        task_key = f"tts:task:{task_id}"
        self.redis.hset(task_key, mapping=task.to_hash())
        self.redis.expire(task_key, TASK_TTL_PENDING)

        # Reserve idempotency key
        if idempotency_key:
            self.reserve_idempotency(idempotency_key, task_id)

        # Push to pending queue with full task data for worker consumption
        queue_payload = {
            "id": task_id,
            "text": text,
            "voice_id": voice_id,
            "prosody": prosody,
            "reference_audio": reference_audio,
        }
        self.redis.rpush("tts:tasks", json.dumps(queue_payload))

        return task

    def get_task(self, task_id: str) -> Optional[TTSTask]:
        """Retrieve task by ID."""
        task_key = f"tts:task:{task_id}"
        data = self.redis.hgetall(task_key)
        if not data:
            return None
        return TTSTask.from_hash(data)

    def get_tasks_by_state(self, state: TaskState, limit: int = 100) -> list:
        """Scan tasks by state (for debugging/recovery)."""
        tasks = []
        cursor = 0
        while len(tasks) < limit:
            cursor, keys = self.redis.scan(cursor, match="tts:task:*", count=100)
            if keys:
                pipe = self.redis.mget(keys)
                for raw in pipe:
                    if raw:
                        try:
                            task = TTSTask.from_hash(json.loads(raw))
                            if task.state == state:
                                tasks.append(task)
                        except Exception:
                            pass
            if cursor == 0:
                break
        return tasks

    # --- State Machine ---

    @contextmanager
    def claim_task(self, worker_id: str) -> Optional[TTSTask]:
        """
        Atomically claim next PENDING task for this worker.

        Uses BLPOP + Lua transition to ensure at-least-once.
        Yields the claimed task (or None if queue empty).
        """
        # Try to pop a task
        task_data = self.redis.blpop("tts:tasks", timeout=5)
        if not task_data:
            yield None
            return

        _, payload = task_data
        task_id = json.loads(payload)["id"]
        task = self.get_task(task_id)

        if not task or task.state != TaskState.PENDING:
            # Task already claimed or invalid - skip
            yield None
            return

        # Try to transition PENDING -> CLAIMED with lock
        lock_key = f"tts:lock:{task_id}"
        lock = DistributedLock(self.redis, lock_key, worker_id, LOCK_TTL)
        acquired = lock.acquire(blocking=False)

        if not acquired:
            # Another worker got it - requeue for them
            self.redis.rpush("tts:tasks", payload)
            yield None
            return

        try:
            # Validate and transition
            result = self._state_transition(
                keys=[f"tts:task:{task_id}", lock_key],
                args=[TaskState.CLAIMED.value, worker_id, str(time.time()), str(TASK_TTL_ACTIVE)],
            )

            if result[0]:
                task.state = TaskState.CLAIMED
                task.worker_id = worker_id
                task.updated_at = time.time()
                yield task
            else:
                print(f"⚠️ Claim failed: {result[1]}", file=sys.stderr)
                yield None
        finally:
            lock.release()

    def transition_state(self, task_id: str, new_state: TaskState, worker_id: str, **extra_fields) -> bool:
        """
        Atomically transition task state with lock ownership validation.

        Returns True on success, False on invalid transition or lock loss.
        """
        lock_key = f"tts:lock:{task_id}"

        # Determine TTL based on new state
        if new_state in TERMINAL_STATES:
            ttl = TASK_TTL_COMPLETED
        elif new_state in (TaskState.SYNTHESIZING, TaskState.UPLOADING):
            ttl = TASK_TTL_ACTIVE
        else:
            ttl = TASK_TTL_ACTIVE

        result = self._state_transition(
            keys=[f"tts:task:{task_id}", lock_key],
            args=[new_state.value, worker_id, str(time.time()), str(ttl)],
        )

        return bool(result[0])

    def complete_task(self, task_id: str, worker_id: str, result_url: str) -> bool:
        """Mark task COMPLETED with result URL."""
        return self.transition_state(
            task_id,
            TaskState.COMPLETED,
            worker_id,
            result_url=result_url,
        )

    def fail_task(self, task_id: str, worker_id: str, error: str, requeue: bool = True) -> bool:
        """Mark task FAILED with error. Optionally re-queue for retry."""
        success = self.transition_state(task_id, TaskState.FAILED, worker_id, error=error)

        if success and requeue:
            # Re-queue for retry (at-least-once)
            task = self.get_task(task_id)
            if task:
                self.redis.rpush("tts:tasks", json.dumps({"id": task_id}))

        return success

    def update_task_fields(self, task_id: str, fields: Dict[str, Any]) -> bool:
        """Update arbitrary task fields (e.g., result_url, error)."""
        task_key = f"tts:task:{task_id}"
        serialized = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in fields.items()}
        return bool(self.redis.hset(task_key, mapping=serialized))

    # --- Lock Management ---

    @contextmanager
    def task_lock(self, task_id: str, worker_id: str, ttl: int = LOCK_TTL):
        """Context manager for task-level distributed lock."""
        lock_key = f"tts:lock:{task_id}"
        lock = DistributedLock(self.redis, lock_key, worker_id, ttl)
        acquired = lock.acquire(blocking=True, timeout=10.0)
        if not acquired:
            raise RuntimeError(f"Could not acquire lock for task {task_id}")
        try:
            yield lock
        finally:
            lock.release()

    # --- Health / Debug ---

    def get_task_summary(self) -> Dict[str, int]:
        """Count tasks by state."""
        counts = {s.value: 0 for s in TaskState}
        cursor = 0
        while True:
            cursor, keys = self.redis.scan(cursor, match="tts:task:*", count=200)
            if keys:
                pipe = self.redis.mget(keys)
                for raw in pipe:
                    if raw:
                        try:
                            task = TTSTask.from_hash(json.loads(raw))
                            counts[task.state.value] += 1
                        except Exception:
                            pass
            if cursor == 0:
                break
        return counts


def main():
    """Demo / health check entry point."""
    redis_host = os.getenv("REDIS_HOST")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    redis_auth = os.getenv("REDIS_AUTH")

    if not all([redis_host, redis_auth]):
        print("ERROR: REDIS_HOST and REDIS_AUTH required", file=sys.stderr)
        sys.exit(1)

    store = HermesStateStore(redis_host, redis_port, redis_auth)

    # Quick health check
    try:
        summary = store.get_task_summary()
        print(f"✅ State store connected. Task summary: {summary}")
    except Exception as e:
        print(f"❌ Connection failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
