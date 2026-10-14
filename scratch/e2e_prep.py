#!/usr/bin/env python3
"""E2E 探针前置：起服务 → 注册/登录 → 建项目 → 上传 → 等抽取完成 → 落盘状态。

不做 /start —— 由外部手动触发，便于在挂起时探测 /health 与 SQLite 锁。
"""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PORT = 8123
BASE = f"http://127.0.0.1:{PORT}"
REDIS_PORT = 6380
SERVER_LOG = ROOT / "scratch" / "e2e_probe_server.log"
STATE = ROOT / "scratch" / "e2e_state.json"

BOOK_TEXT = "用于探针的文本。\n\n第一章\n\n清晨的薄雾还未散去。\n李明说：「我出发了。」\n"


def main() -> int:
    log_f = open(SERVER_LOG, "wb")
    redis = subprocess.Popen(
        ["redis-server", "--port", str(REDIS_PORT), "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    db_path = ROOT / "src" / "data" / "audiobook.db"
    env = os.environ.copy()
    env.update({
        "MOCK_LLM": "true", "MOCK_TTS": "true",
        "REDIS_URL": f"redis://127.0.0.1:{REDIS_PORT}/0",
        "AUTH_REGISTRATION_MODE": "open",
        "DATABASE_URL": f"sqlite:///{db_path}",
    })
    server = subprocess.Popen(
        [str(ROOT / ".venv/bin/python"), "-m", "uvicorn",
         "src.audiobook_studio.main:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--log-level", "info"],
        cwd=ROOT, env=env, stdout=log_f, stderr=subprocess.STDOUT)

    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE}/health", timeout=2.0).status_code == 200:
                break
        except Exception:
            time.sleep(1.0)
    else:
        print("server boot timeout", flush=True)
        server.kill()
        return 1
    print("server up", flush=True)

    user = f"probe_{uuid.uuid4().hex[:8]}"
    with httpx.Client(base_url=BASE, timeout=120.0) as c:
        c.post("/api/auth/register", json={
            "username": user, "email": f"{user}@example.com",
            "password": "E2eTest#2026"})
        r = c.post("/api/auth/login", data={"username": user, "password": "E2eTest#2026"})
        r.raise_for_status()
        token = r.json()["access_token"]
        c.headers["Authorization"] = f"Bearer {token}"

        r = c.post("/api/projects/", json={"title": "E2E 探针", "language": "zh"})
        r.raise_for_status()
        pid = r.json()["id"]
        r = c.post(f"/api/projects/{pid}/upload", files={
            "file": ("book.txt", BOOK_TEXT.encode("utf-8"), "text/plain")})
        r.raise_for_status()
        job_id = r.json()["extraction_job_id"]

        deadline = time.time() + 180
        js = None
        while time.time() < deadline:
            r = c.get(f"/api/projects/{pid}/extraction/{job_id}/status")
            r.raise_for_status()
            js = r.json()
            if js["status"] in ("completed", "failed"):
                break
            time.sleep(1.5)
        print(f"extraction: {js['status']}", flush=True)

    STATE.write_text(json.dumps({
        "pid": pid, "token": token, "user": user, "job": job_id,
        "server_port": PORT, "redis_port": REDIS_PORT,
    }))
    print(f"state saved: pid={pid}", flush=True)
    print(f"SERVER_PID={server.pid} REDIS_PID={redis.pid}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
