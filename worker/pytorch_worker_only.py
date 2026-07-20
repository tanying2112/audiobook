#!/usr/bin/env python3
"""
VoxCPM2 Worker - PyTorch Only（无 PaddlePaddle，避免 CUDA 库冲突）

使用项目自带的 VoxCPM2Model.from_local() 加载模型。
generate() 直接返回波形张量，无需 decode_audio()。

用法：
  export PYTHONPATH=/home/aistudio/audiobook/src:$PYTHONPATH
  python3 pytorch_worker_only.py
"""

import io
import json
import os
import signal
import sys
import time
import uuid
from pathlib import Path

# ========== 添加项目源码路径 ==========
_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import types

import torch

# ========== 补丁：weights_only & BlockMask ==========
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
import redis
import torchaudio
from botocore.config import Config

# ========== 导入 VoxCPM2 模型（项目源码） ==========
from voxcpm.model.voxcpm2 import VoxCPM2Model

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

# ========== 连接 Redis & R2 ==========
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

# from_local() 自动加载 tokenizer + AudioVAE + safetensors
# optimize=False 禁用 torch.compile（V100 不支持）
model = VoxCPM2Model.from_local(MP, optimize=False)
model.eval()

mem = torch.cuda.memory_allocated() // 1024 // 1024
tot = torch.cuda.get_device_properties(0).total_memory // 1024 // 1024
print("✅ 显存:", mem, "/", tot, "MB")

# ========== 烟雾测试 ==========
print("🧪 烟雾测试...")
# generate() 直接返回波形张量（48kHz），无需 decode_audio()
wf = model.generate(target_text="测试语音合成。", max_len=256)
print("✅ 通过！输出波形:", wf.shape, "采样率: 48000Hz")

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
        # generate() 直接返回波形 —— 正确 API！
        wf = model.generate(
            target_text=txt,
            max_len=pros.get("max_len", 1024),
            cfg_value=pros.get("cfg", 2.0),
            inference_timesteps=pros.get("steps", 10),
        )

        # 模型输出采样率为 48kHz（audio_vae out_sample_rate）
        buf = io.BytesIO()
        torchaudio.save(buf, wf.cpu(), sample_rate=48000, format="wav")
        key = f"tts/{tid}.wav"
        s3.put_object(Bucket=R2B, Key=key, Body=buf.getvalue(), ContentType="audio/wav")
        url = f"https://{R2B}.r2.cloudflarestorage.com/{key}"
        r.rpush("tts:results", json.dumps({"id": tid, "status": "success", "url": url, "worker": WID}))
        print(f"✅ 完成:", url)

    except Exception as e:
        print(f"💥 失败:", e)
        r.rpush("tts:results", json.dumps({"id": tid, "status": "failed", "error": str(e), "worker": WID}))
