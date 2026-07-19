#!/usr/bin/env python3
"""
VoxCPM2 Baidu Worker - PyTorch Only（无 PaddlePaddle，避免 CUDA 库冲突）
用法：python3 pytorch_worker_only.py
"""
import io
import json
import os
import signal
import sys
import time
import types
import uuid
from pathlib import Path

import torch

# ========== 补丁 ==========
_REAL = torch.load


def _patched(*a, **kw):
    if "weights_only" not in kw:
        kw["weights_only"] = False
    return _REAL(*a, **kw)


_patched._patched_weights_only = True
torch.load = _patched
sys.modules["torch"].load = _patched

if not hasattr(torch.nn, "attention"):
    torch.nn.attention = types.ModuleType("attention")
    sys.modules["torch.nn.attention"] = torch.nn.attention
try:
    import torch.nn.attention.flex_attention as f
except ImportError:
    f = types.ModuleType("flex_attention")
    torch.nn.attention.flex_attention = f
    sys.modules["torch.nn.attention.flex_attention"] = f
if not hasattr(f, "BlockMask") or not isinstance(getattr(f, "BlockMask", None), type):

    class D:
        pass

    f.BlockMask = D
    sys.modules["torch.nn.attention.flex_attention.BlockMask"] = D

os.environ["HF_HUB_DISABLE_SSL_VERIFY"] = "1"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# ========== 加载 .env ==========
env_path = Path(__file__).resolve().parent.parent / "voxcpm2-pool" / "paddle" / ".env"
if not env_path.exists():
    env_path = Path("/home/aistudio/audiobook/voxcpm2-pool/paddle/.env")
if env_path.exists():
    for l in env_path.read_text().splitlines():
        l = l.strip()
        if l and not l.startswith("#") and "=" in l:
            k, v = l.split("=", 1)
            os.environ[k.strip()] = v.strip()

import boto3

# ========== 导入 ==========
import redis
import torchaudio
from botocore.config import Config
from transformers import AutoModelForCausalLM, AutoTokenizer

# ========== 配置 ==========
MP = os.getenv("MODEL_PATH", "/tmp/voxcpm2-model")
RH = os.getenv("REDIS_HOST")
RP = int(os.getenv("REDIS_PORT", "6379"))
RA = os.getenv("REDIS_AUTH")
R2E = os.getenv("R2_ENDPOINT")
R2A = os.getenv("R2_ACCESS_KEY_ID")
R2S = os.getenv("R2_SECRET_ACCESS_KEY")
R2B = os.getenv("R2_BUCKET")
WID = os.getenv("WORKER_ID", "baidu-v100-01")

missing = [
    k
    for k, v in [
        ("REDIS_HOST", RH),
        ("REDIS_AUTH", RA),
        ("R2_ENDPOINT", R2E),
        ("R2_ACCESS_KEY_ID", R2A),
        ("R2_SECRET_ACCESS_KEY", R2S),
        ("R2_BUCKET", R2B),
    ]
    if not v
]
if missing:
    print("❌ 缺少环境变量:", missing)
    sys.exit(1)

# ========== 连接 ==========
r = redis.Redis(host=RH, port=RP, password=RA, decode_responses=True, socket_timeout=10)
s3 = boto3.client(
    "s3",
    endpoint_url=R2E,
    aws_access_key_id=R2A,
    aws_secret_access_key=R2S,
    config=Config(signature_version="s3v4"),
    verify=False,
)

# ========== 加载模型 ==========
print("⚙️ 加载模型:", MP)
print("📊 GPU:", torch.cuda.get_device_name(0))
tok = AutoTokenizer.from_pretrained(MP, trust_remote_code=True, use_fast=False)
m = AutoModelForCausalLM.from_pretrained(
    MP, torch_dtype=torch.float16, device_map="auto", trust_remote_code=True, low_cpu_mem_usage=True
)
m.eval()
mem = torch.cuda.memory_allocated() // 1024 // 1024
tot = torch.cuda.get_device_properties(0).total_memory // 1024 // 1024
print("✅ 显存:", mem, "/", tot, "MB")

# ========== 烟雾测试 ==========
print("🧪 烟雾测试...")
inp = tok("测试。", return_tensors="pt")
inp = {k: v.to("cuda") for k, v in inp.items()}
with torch.inference_mode():
    at = m.generate(**inp, max_new_tokens=128, do_sample=True, temperature=0.7, top_p=0.9)
    wf = m.decode_audio(at)
print("✅ 通过！输出:", wf.shape)

# ========== 主循环 ==========
running = True


def shutdown(s, f):
    global running
    print("\n⚠️ 退出...")
    running = False


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)
print(f"\n⚡ [{WID}] 就绪！等待任务...\n")

while running:
    try:
        td = r.blpop("tts:tasks", timeout=120)
    except Exception as e:
        print("🔌 Redis 错误:", e)
        time.sleep(5)
        continue
    if not td:
        continue
    _, pl = td
    try:
        task = json.loads(pl)
    except json.JSONDecodeError:
        print("🚨 损坏的任务数据")
        continue

    tid = task.get("id", str(uuid.uuid4()))
    txt = task.get("text", "")
    pros = task.get("prosody", {})
    print(f"🚀 [{tid}] 合成 ({len(txt)} 字)")

    try:
        inp = tok(txt, return_tensors="pt")
        inp = {k: v.to("cuda") for k, v in inp.items()}
        with torch.inference_mode():
            at = m.generate(
                **inp,
                max_new_tokens=1024,
                do_sample=True,
                temperature=pros.get("temperature", 0.7),
                top_p=pros.get("top_p", 0.9),
            )
            wf = m.decode_audio(at)

        buf = io.BytesIO()
        torchaudio.save(buf, wf.cpu(), sample_rate=24000, format="wav")
        key = f"tts/{tid}.wav"
        s3.put_object(Bucket=R2B, Key=key, Body=buf.getvalue(), ContentType="audio/wav")
        url = f"https://{R2B}.r2.cloudflarestorage.com/{key}"
        r.rpush("tts:results", json.dumps({"id": tid, "status": "success", "url": url, "worker": WID}))
        print(f"✅ 完成:", url)

    except Exception as e:
        print(f"💥 失败:", e)
        r.rpush("tts:results", json.dumps({"id": tid, "status": "failed", "error": str(e), "worker": WID}))
