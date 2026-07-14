# Multi-Cloud GPU Worker Deployment Guide (v2.1.0-PRO)

## Architecture Overview

**Goal: Write code once, run on four clouds zero-config.** Each worker is now a **single-file, self-contained executable** that:

1. **Bootstraps dependencies** at runtime (pip install inside container)
2. **Downloads model from Hugging Face Hub** on first run → caches to `/tmp/voxcpm2-model`
3. **Loads VoxCPM2** with `device_map="auto"` (model parallel across all GPUs)
4. **Consumes** `tts:tasks` from Upstash Redis
5. **Synthesizes** audio on GPU
6. **Uploads** WAV to Cloudflare R2
7. **Pushes** result to `tts:results`
8. **Heartbeats** to `worker:heartbeat:{id}` with TTL
9. **Auto-exits** after 15 min idle (quota preservation)

**No local model files needed. No dataset uploads. No volume pre-warming.**

### Worker Comparison (All Free Tier)

| Worker | Platform | Free Quota | GPUs | Role |
|--------|----------|------------|------|------|
| `kaggle_worker.py` | **Kaggle Kernels (Primary)** | 30h/week | 2× T4 (16GB each) | **Main production** — highest quota, batch mode |
| `lightning_worker.py` | **Lightning AI Studios** | 80h/month | 1× T4 | **Backup/overflow** — monthly quota |
| `baidu_paddle_worker.py` | **Baidu AI Studio (飞桨)** | 12h/day | 1× V100 | **Daily burst** — V100 for heavy chapters |
| `modal_worker.py` | **Modal Serverless** | 40h/month | 1× T4 | **Spiky demand** — instant cold start |

**Shared Architecture:**
- Queue: Upstash Redis `tts:tasks` / `tts:results` (free tier: 10k req/day, 256 MB)
- Storage: Cloudflare R2 `audiobook-tts-output` (free egress)
- Telemetry: `worker:heartbeat:{worker_id}` (TTL 15min → Telegram alert)
- At-least-once: Failed tasks re-queued automatically
- Idle exit: 3 empty polls × 5 min = 15 min → auto shutdown

---

## Core Architecture (v2.1 — Inlined BaseWorker)

**Each worker file is now a single, self-contained executable** (~200-300 lines). No external `src/worker_base.py` dependency at runtime — the base class is **inlined** into every worker. This eliminates path/import issues on remote platforms.

### Inlined Components (per worker file)

1. **Bootstrap** — `_install_missing_deps()` auto-installs: `torch`, `transformers`, `accelerate`, `huggingface_hub`, `redis`, `boto3`, etc.
2. **R2Uploader** — S3-compatible upload to Cloudflare R2 with retry
3. **BaseWorker (abstract)** — Redis consumer loop, heartbeat, graceful shutdown, at-least-once semantics
4. **Engine Classes** — HF Hub download → cache → `device_map="auto"` load
   - `DualT4VoxCPM2Engine` (Kaggle: 2× T4 model parallel)
   - `T4VoxCPM2Engine` (Lightning/Modal/Baidu PyTorch fallback: single GPU)
   - `PaddleVoxCPM2Engine` (Baidu preferred: PaddlePaddle backend)
5. **Platform Worker** — Concrete implementation + `main()` entry point

### Unified Runtime Dependencies

```text
torch>=2.3.0
torchaudio>=2.3.0
transformers>=4.40.0
accelerate>=0.30.0
sentencepiece>=0.2.0
protobuf>=4.25.0
redis>=5.0.0
boto3>=1.34.0
tiktoken>=0.7.0
huggingface_hub>=0.20.0
soundfile>=0.12.0      # Baidu/Paddle audio I/O
```

| Platform | Install Method |
|----------|----------------|
| Kaggle / Lightning / Baidu | Bootstrap auto-installs at runtime (see `_install_missing_deps()` in each worker) |
| Modal | Pre-baked in `worker_image` definition (`.pip_install(...)`) |

---

## Platform-Specific Deep Optimizations (v2.1)

### Kaggle Kernels (Primary)

| Setting | Value | Reason |
|---------|-------|--------|
| **Internet Access** | **ON** (Settings → Internet) | Required for HF Hub download + Upstash Redis TLS |
| **GPU** | **ON** (2× T4) | Model parallel via `device_map="auto"` |
| **Keep-alive** | Print log every 10 min | Prevent idle recycle (10 min Kaggle limit) |
| **Config** | `kernel-metadata.json` in same dir | `enable_gpu: true`, `enable_internet: true`, `dataset_sources: []` |

**Deploy:**
```bash
cd worker
kaggle kernels push -p .
kaggle kernels start guwj/voxcpm2-kaggle-worker
```

### Lightning AI Studios (Backup)

- **Persistent Storage** — Model cached at `/tmp/voxcpm2-model` (survives Studio restart within session)
- **Studio Secrets** — All credentials via UI (never hardcode)
- **Auto-start** — Add `python lightning_worker.py` to `~/.bashrc` or Studio startup script

**Deploy:**
```bash
# In Lightning Studio terminal
python lightning_worker.py
```

### Baidu AI Studio (飞桨) — Daily Burst

```bash
# Create isolated env to avoid system Paddle conflicts
conda create -n voxcpm python=3.10
conda activate voxcpm
# Worker bootstraps its own deps at runtime (including paddlepaddle-gpu if PREFER_PADDLE=true)
python baidu_paddle_worker.py
```

- Set `PREFER_PADDLE=true` in secrets (enables PaddlePaddle backend, falls back to PyTorch)
- Use **Scheduled Task** (定时任务) in UI for daily auto-start at quota reset
- **Dual Backend Architecture**:
  - Primary: `PaddleVoxCPM2Engine` — native PaddlePaddle via `paddlenlp` (optimal on Baidu)
  - Fallback: `T4VoxCPM2Engine` — PyTorch via `transformers` (if Paddle unavailable)

### Modal Serverless — Spiky Demand

```python
# modal_worker.py optimizations
@app.function(
    gpu="T4",
    concurrency_limit=2,
    volumes={"/models": model_vol},  # Persistent HF cache across cold starts
    timeout=32400,
    secrets=[modal.Secret.from_name("audiobook-config")],
)
def run_modal_consumer():
    ...
```

**Deploy:**
```bash
modal deploy modal_worker.py
modal run modal_worker.py::run_modal_consumer
```

---

## Prerequisites (One-time Setup)

### 1. Upstash Redis (Free Tier)
```
1. https://console.upstash.com/redis → Create database → Free tier (10k req/day, 256 MB)
2. Copy: UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN
   Or Redis-compatible endpoint: host, port, password
```

### 2. Cloudflare R2 (Free Tier)
```
1. https://dash.cloudflare.com/r2 → Create bucket: `audiobook-tts-output`
2. Create API token: R2 → Object Read & Write
3. Copy: R2_ENDPOINT (e.g., https://<account-id>.r2.cloudflarestorage.com),
            R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
4. Optional: Custom domain for public URLs (e.g., pub-xxx.r2.dev)
5. Lifecycle Rule: Delete objects after 30 days (prevent bucket fill)
```

### 3. Hugging Face (Model Source)
```
Model: openbmb/VoxCPM2 (public, no token required)
Or: your-org/voxcpm2-finetuned (private → create HF token, add as Secret)
```

### 4. Platform Secrets (Per Worker)

| Platform | Required Secrets |
|----------|------------------|
| **Kaggle** | `REDIS_HOST`, `REDIS_PORT`, `REDIS_AUTH`, `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_URL` (optional), `WORKER_ID`, `VOXCPM2_HF_REPO` (optional) |
| **Lightning** | Same as Kaggle |
| **Baidu** | Same as Kaggle + `PREFER_PADDLE` (optional, default `true`) |
| **Modal** | Single secret `audiobook-config` containing all above keys |

---

## Quick Deploy Commands

| Platform | Command |
|----------|---------|
| **Kaggle** | `kaggle kernels push -p worker && kaggle kernels start guwj/voxcpm2-kaggle-worker` |
| **Lightning** | Studio UI → Terminal → `python lightning_worker.py` (add to `~/.bashrc` for auto-start) |
| **Baidu** | AI Studio → Terminal → `conda activate voxcpm && python baidu_paddle_worker.py` (Scheduled Task for daily) |
| **Modal** | `modal deploy modal_worker.py && modal run modal_worker.py::run_modal_consumer` |

---

## Task Submission & Result Retrieval

### Method 1: Celery (Recommended)
```python
from src.audiobook_studio.tasks.tts_tasks import synthesize_chapter_task, get_tts_status

task = synthesize_chapter_task.delay(
    project_id=123, chapter_id=456, chapter_index=1,
    paragraphs=[{"paragraph_id": 1, "paragraph_index": 0, "text": "第一章...", "voice_id": "zh_female_1"}]
)
status = get_tts_status(task.id)
```

### Method 2: Direct Redis (Bypass Celery)
```python
import redis, json, hashlib, os
r = redis.Redis(host=os.getenv("REDIS_HOST"), port=6379, password=os.getenv("REDIS_AUTH"), decode_responses=True)

def submit_tts(text: str, voice_id: str, prosody: dict = None) -> str:
    task_id = f"tts-{hashlib.md5(text.encode()).hexdigest()[:8]}"
    idem_key = f"tts:idem:{hashlib.sha256(f'{text}|{voice_id}|{json.dumps(prosody or {})}'.encode()).hexdigest()[:16]}"
    if r.set(idem_key, "1", nx=True, ex=3600):
        r.rpush("tts:tasks", json.dumps({"id": task_id, "text": text, "voice_id": voice_id, "prosody": prosody or {}}))
    return task_id

# Blocking wait for result
_, payload = r.blpop("tts:results", timeout=300)
result = json.loads(payload)
```

---

## Operational Toolbox (Production-Grade)

### A. Worker Health Check (CLI)
```bash
# ops/check_workers.sh
for worker in "kaggle-t4-dual-01" "lightning-t4-01" "baidu-v100-01" "modal-t4-01"; do
    ttl=$(redis-cli -h $REDIS_HOST -a $REDIS_AUTH TTL "worker:heartbeat:$worker" 2>/dev/null)
    if [[ $ttl -gt 0 ]]; then
        echo "✅ $worker online (TTL: ${ttl}s)"
    else
        echo "❌ $worker offline"
    fi
done
```

### B. Stuck Task Recovery
```python
# ops/clean_stuck_tasks.py
import os, redis, json
r = redis.Redis(host=os.getenv("REDIS_HOST"), password=os.getenv("REDIS_AUTH"), decode_responses=True)

stuck = r.lrange("tts:results", 0, -1)
requeued = 0
for item in stuck:
    data = json.loads(item)
    if data.get("status") in ("processing", "started", "pending"):
        r.rpush("tts:tasks", json.dumps({"id": data["id"], "text": data.get("text", ""), "voice_id": data.get("voice_id", "zh_female_1")}))
        requeued += 1

r.delete("tts:results")
print(f"Requeued {requeued} stuck tasks. Queue reset.")
```

### C. Telegram Alert Bot (cron every 5 min)
```python
# ops/alert_bot.py
import os, redis, requests, json, time
r = redis.Redis(host=os.getenv("REDIS_HOST"), password=os.getenv("REDIS_AUTH"), decode_responses=True)
BOT = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT = os.getenv("TELEGRAM_CHAT_ID")

for key in r.scan_iter("worker:heartbeat:*"):
    raw = r.get(key)
    if raw:
        hb = json.loads(raw)
        if time.time() - hb["ts"] > 900:
            msg = f"🚨 Worker {hb['worker_id']} offline >15min. Last heartbeat: {hb['ts']:.0f}, Queue: {r.llen('tts:tasks')}"
            requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage", json={"chat_id": CHAT, "text": msg})
```

---

## Cost & Load Balancing Strategy (Advanced)

**Don't run all four workers 24/7.** Use tiered scheduling:

| Tier | Platform | Trigger | Quota Burn |
|------|----------|---------|------------|
| **T1** | Modal | Always 1 cold node, burst scale on demand | ~40h/mo |
| **T2** | Kaggle + Lightning | Queue > 50 tasks → batch wake | ~110h/mo |
| **T3** | Baidu | T1+T2 quota exhausted or offline | ~360h/mo (12h/day) |

**Controller Logic (integrated in Celery App):**
```python
# src/audiobook_studio/tasks/queue_controller.py
def auto_scale_workers():
    r = get_redis()
    qlen = r.llen("tts:tasks")
    
    if qlen > 100:
        wake_up("lightning"); wake_up("baidu")
    elif qlen > 50:
        wake_up("lightning")
    # qlen == 0 → workers auto-exit after 15min idle, no action needed

def wake_up(platform: str):
    if platform == "kaggle":
        kaggle_api.kernels_start("yourusername/audiobook-tts-worker")
    elif platform == "lightning":
        lightning_api.studio_start("audiobook-tts-worker")
    elif platform == "baidu":
        baidu_api.project_run("audiobook-tts-worker")
    # Modal scales via concurrency_limit automatically
```

---

## Troubleshooting Quick Reference

| Symptom | Fix |
|---------|-----|
| `CUDA not available` | Enable GPU on platform (Kaggle: toggle; Lightning: GPU instance; Baidu: select V100; Modal: gpu="T4") |
| `Model not found` | First run downloads from HF Hub (~5-10 min); verify internet access |
| `Redis connection failed` | Check Upstash host/port/auth; Kaggle needs Internet ON |
| `R2 upload failed` | `R2_ENDPOINT` must include `https://`; verify creds & bucket name |
| `Worker exits instantly` | Check logs for import errors; bootstrap installs deps at runtime |
| `OOM` | Reduce `max_new_tokens`; `device_map="auto"` splits across GPUs |
| `Kaggle kernel recycled` | Enable Internet; 10-min keep-alive `print()` built-in |

---

## Final Production-Ready Checklist

- [ ] **Security**: All `.env` in `.gitignore`; secrets only in platform Secret Stores
- [ ] **Model Integrity**: Single source of truth (HF Hub `openbmb/VoxCPM2`)
- [ ] **Monitoring**: Telegram Bot receives "Worker offline" alerts
- [ ] **Cold Start**: Workers gracefully sleep when queue empty (no error spam)
- [ ] **Data Hygiene**: R2 lifecycle rule → delete after 30 days
- [ ] **Pinned Deps**: Bootstrap spec locked; all 4 platforms install same versions
- [ ] **Base Class Inlined**: Each worker self-contained, zero external dependency at runtime
- [ ] **Auto-scale**: Controller logic integrated in Celery App
- [ ] **Ops Scripts**: `check_workers.sh`, `clean_stuck_tasks.py`, `alert_bot.py` deployed + cron'd

---

## Architecture Diagram

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Main App   │────▶│  Upstash     │◀───▶│  Worker Fleet   │
│  (Celery)   │     │  Redis Queue │     │  (4 platforms)  │
└─────────────┘     │  tts:tasks   │     └────────┬────────┘
                    └──────┬───────┘              │
                           │                      │
                    ┌──────▼───────┐     ┌────────▼────────┐
                    │  tts:results │     │  Cloudflare R2  │
                    │  (results)   │     │  (audio files)  │
                    └──────────────┘     └─────────────────┘
                           │
                    ┌──────▼───────┐
                    │  Heartbeat   │
                    │  Monitor     │
                    │  (Telegram)  │
                    └──────────────┘
                           │
                    ┌──────▼───────┐
                    │  Controller  │
                    │ (auto-scale) │
                    └──────────────┘
```

---

*Version 2.1.0-PRO — Four clouds, one codebase, zero local models, fully ops-ready.*