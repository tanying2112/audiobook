#!/usr/bin/env python3
"""
Direct API submission for AI Studio Pipeline (bypassing broken baidubce)
"""
import json
import os
import time
import uuid
from pathlib import Path

import requests

# Load .env
env_path = Path("/Users/guwj/Desktop/AI_Lab/audiobook/voxcpm2-pool/paddle/.env")
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

AISTUDIO_TOKEN = os.getenv("AISTUDIO_TOKEN", "")
if not AISTUDIO_TOKEN:
    print("ERROR: AISTUDIO_TOKEN not set in environment or .env")
    print("Get your token from: https://aistudio.baidu.com/account/accessToken")
    exit(1)

# API Config
API_BASE = "https://aistudio.baidu.com"
CREATE_URL = f"{API_BASE}/paddlex/v3/pipelines/sdk/create"
QUERY_URL = f"{API_BASE}/paddlex/v3/pipelines/sdk/list"
STOP_URL = f"{API_BASE}/paddlex/v3/pipelines/sdk/stop"

HEADERS = {"Content-Type": "application/json", "Authorization": f"token {AISTUDIO_TOKEN}"}


def submit_job():
    """Submit the pipeline job"""
    code_path = "/Users/guwj/Desktop/AI_Lab/audiobook/voxcpm2-pool/paddle/job_package"

    # Use unique name with timestamp
    unique_name = f"voxcpm2-worker-v15-{int(time.time())}-{uuid.uuid4().hex[:6]}"

    payload = {
        "name": unique_name,
        "cmd": "bash entry.sh",
        "env": "paddle2.6_py3.10",
        "device": "v100",
        "gpus": 1,
        "payment": "coupon",
        "dataset": [],
    }

    print(f"Submitting job to {CREATE_URL}...")
    print(f"Name: {unique_name}")

    resp = requests.post(CREATE_URL, headers=HEADERS, json=payload, timeout=60)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text}")

    if resp.status_code == 200:
        data = resp.json()
        if data.get("errorCode") == 0:
            pipeline_id = data.get("result", {}).get("pipelineId")
            print(f"✅ Job submitted! Pipeline ID: {pipeline_id}")
            return pipeline_id
        else:
            print(f"❌ API Error: {data.get('errorMsg')}")
    else:
        print(f"❌ HTTP Error: {resp.status_code}")
    return None


def query_job(pipeline_id):
    """Query job status"""
    payload = {"pipelineId": pipeline_id, "pipelineName": "", "stage": ""}
    resp = requests.post(QUERY_URL, headers=HEADERS, json=payload, timeout=30)
    if resp.status_code == 200:
        return resp.json()
    return None


def monitor_job(pipeline_id):
    """Monitor job until completion"""
    print(f"Monitoring {pipeline_id}...")
    for i in range(480):  # 2 hours max
        result = query_job(pipeline_id)
        if result and result.get("errorCode") == 0:
            pipelines = result.get("result", {}).get("pipelines", [])
            for p in pipelines:
                if p.get("pipelineId") == pipeline_id:
                    status = p.get("stage", "Unknown")
                    print(f"[{time.strftime('%H:%M:%S')}] Status: {status}")
                    if status in ["Succeeded", "Failed", "Stopped"]:
                        print(f"Final status: {status}")
                        return status
                    break
        time.sleep(15)
    return "Timeout"


if __name__ == "__main__":
    pid = submit_job()
    if pid:
        monitor_job(pid)
