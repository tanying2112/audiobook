# Hermes Master Module & Dashboard

The central nervous system for the **VoxCPM2 Multi-Cloud TTS Fleet** (Kaggle, Lightning, Baidu, Modal).

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        HERMES MASTER                             │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │   Scheduler  │  │ State Store  │  │   Orchestrator       │   │
│  │ (scheduler.py)│  │(state_store.py)│  │(orchestrator.py)    │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬────────────┘   │
│         │                 │                     │                │
│         ▼                 ▼                     ▼                │
│  ┌──────────────────────────────────────────────────────┐       │
│  │              REDIS (Upstash)                          │       │
│  │  • worker:heartbeat:*  (telemetry, TTL=960s)         │       │
│  │  • tts:tasks           (pending queue)               │       │
│  │  • tts:results         (completed queue)             │       │
│  │  • tts:task:{id}       (state machine hash)          │       │
│  │  • tts:lock:{id}       (distributed lock)            │       │
│  │  • tts:idempotency:{key} (24h dedup)                 │       │
│  └──────────────────────────────────────────────────────┘       │
│                           │                                      │
│                           ▼                                      │
│  ┌──────────────────────────────────────────────────────┐       │
│  │           CLOUDFLARE R2 (Audio Storage)              │       │
│  │  • tts/{task_id}.wav       (chunk audio)             │       │
│  │  • audiobooks/{book_id}/final.wav (final output)     │       │
│  └──────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    HERMES DASHBOARD (Streamlit)                 │
│  • Real-time fleet health per platform                          │
│  • GPU utilization heatmap                                      │
│  • Task state distribution                                      │
│  • Alert banner: queue > 50 with 0 active workers              │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. HermesScheduler (`src/master/scheduler.py`)
**Dynamic load balancer & fleet monitor**

- **SCAN-based heartbeat collection** — Production-safe, non-blocking
- **Platform routing priority**: Modal (urgent) → Baidu (throughput) → Lightning (core) → Kaggle (batch)
- **Stale worker detection** — Auto-alerts when workers miss heartbeats
- **Maintenance loop** — Runs every 30s, logs fleet status, detects anomalies

```python
from master import HermesScheduler

scheduler = HermesScheduler(
    redis_host="your-upstash-host",
    redis_port=6379,
    redis_auth="your-token",
    stale_threshold=120,  # seconds
)

# Run maintenance loop (blocking)
scheduler.run_maintenance_loop(interval=30)

# Or get fleet snapshot for dashboard
status = scheduler.get_fleet_status()
```

### 2. HermesStateStore (`src/master/state_store.py`)
**Distributed state machine with atomic operations**

- **Task states**: PENDING → CLAIMED → SYNTHESIZING → UPLOADING → COMPLETED | FAILED
- **Distributed locking** — Lua scripts for atomic SET NX + TTL + renewal
- **Idempotency keys** — 24h deduplication for safe retries
- **At-least-once delivery** — Failed tasks auto-requeued

```python
from master import HermesStateStore, TaskState

store = HermesStateStore(redis_host, redis_port, redis_auth)

# Submit task with idempotency
task = store.create_task(
    text="Hello world",
    voice_id="zh_female_1",
    prosody={"temperature": 0.7},
    idempotency_key="my-unique-key",  # Prevents duplicate submission
)

# Worker claims and processes
with store.claim_task(worker_id) as task:
    if task:
        store.transition_state(task.task_id, TaskState.SYNTHESIZING, worker_id)
        # ... synthesize ...
        store.complete_task(task.task_id, worker_id, r2_url)

# On failure with auto-requeue
store.fail_task(task_id, worker_id, "GPU OOM", requeue=True)
```

### 3. AudiobookOrchestrator (`src/master/orchestrator.py`)
**Semantic chunking + async pipeline + result reassembly**

- **Semantic chunking** — Splits at `。！？\n` clauses, max 200 chars
- **Async pipeline** — Submits all chunks to queue with idempotency keys
- **Result listener** — Redis pub/sub on `tts:results` channel
- **Auto-reassembly** — Downloads chunks, concatenates, uploads final audiobook

```python
from master import AudiobookOrchestrator, ChunkStrategy

orchestrator = AudiobookOrchestrator(
    redis_host=redis_host,
    redis_port=redis_port,
    redis_auth=redis_auth,
    r2_endpoint=r2_endpoint,
    r2_access_key=r2_access_key,
    r2_secret_key=r2_secret_key,
    r2_bucket=r2_bucket,
    r2_public_url=r2_public_url,
)

# Submit full book
chapters = [
    {"title": "Chapter 1", "text": "很久很久以前..."},
    {"title": "Chapter 2", "text": "故事继续..."},
]

orchestrator.submit_audiobook(
    book_id="my-book-001",
    title="My Audiobook",
    author="Author Name",
    chapters=chapters,
    voice_id="zh_female_1",
    prosody={"temperature": 0.7, "top_p": 0.9},
    chunk_strategy=ChunkStrategy.SEMANTIC,
    max_chunk_chars=200,
)

# Start listener (blocking)
orchestrator.run()

# Or check progress programmatically
progress = orchestrator.get_progress("my-book-001")
print(f"Completed: {progress.completed_chunks}/{progress.total_chunks}")
```

## Quick Start

### 1. Environment Variables
```bash
# Redis (Upstash)
export REDIS_HOST="your-host.upstash.io"
export REDIS_PORT=6379
export REDIS_AUTH="your-token"

# Cloudflare R2
export R2_ENDPOINT="https://<account-id>.r2.cloudflarestorage.com"
export R2_ACCESS_KEY_ID="your-access-key"
export R2_SECRET_ACCESS_KEY="your-secret-key"
export R2_BUCKET="your-bucket"
export R2_PUBLIC_URL="https://pub-xxx.r2.dev"  # Optional public domain
```

### 2. Install Dependencies
```bash
pip install -r src/master/requirements.txt
```

### 3. Run Scheduler (Daemon)
```bash
python -m src.master.scheduler
```

### 4. Run Orchestrator (For Audiobook Generation)
```bash
python -m src.master.orchestrator
```

### 5. Launch Dashboard
```bash
streamlit run src/dashboard/app.py
```

## Redis Key Schema

| Key Pattern | Type | TTL | Description |
|-------------|------|-----|-------------|
| `worker:heartbeat:{worker_id}` | String (JSON) | idle_timeout+60s | Worker telemetry |
| `tts:tasks` | List | — | Pending task queue (BLPOP) |
| `tts:results` | List | — | Completed results (LPUSH) |
| `tts:task:{task_id}` | Hash | 1h-24h | Task state machine |
| `tts:lock:{task_id}` | String | 5min (renewable) | Distributed lock |
| `tts:idempotency:{key}` | String | 24h | Deduplication mapping |

## Task State Machine

```
PENDING ──claim──► CLAIMED ──synthesize──► SYNTHESIZING ──upload──► UPLOADING ──done──► COMPLETED
    │                    │                      │                    │
    └─────────fail───────┴──────────fail────────┴────────fail────────┘
                              │
                              ▼
                           FAILED ──retry──► CLAIMED
```

## Platform Routing Matrix

| Priority | Platform | Use Case | GPU | Quota |
|----------|----------|----------|-----|-------|
| 1 | Modal | Urgent/Interactive | T4 | 40h/mo |
| 2 | Baidu | Throughput burst | V100 | 12h/day |
| 3 | Lightning | Core persistent | T4 | 80h/mo |
| 4 | Kaggle | Primary batch | P100/T4 | 30h/wk |

## Alerting Rules

The scheduler and dashboard enforce:
- **Critical**: Queue depth > 50 with 0 active workers
- **Warning**: All workers stale (no heartbeat > TTL)
- **Warning**: No workers online

## Testing

```bash
# Unit tests for state machine
python -m pytest tests/test_state_store.py -v

# Integration test with mock Redis
python -m pytest tests/test_orchestrator.py -v
```

## License

Part of the VoxCPM2 Multi-Cloud TTS project.