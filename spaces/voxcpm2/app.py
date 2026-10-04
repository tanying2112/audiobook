#!/usr/bin/env python3
"""
ModelScope 创空间 Gradio Demo —— VoxCPM2 TTS
==========================================
部署到魔搭创空间享受免费 xGPU 自动冷启动/自动回收。

本地开发调试（在已配置好模型的 DSW/本机）：
  pip install gradio==4.44.1
  python app.py   # http://localhost:7860

推送到创空间：
  1) 魔搭网页 -> 创空间 -> 新建空间 -> 选择 "Gradio" / "Python" / GPU: xGPU(免费)
  2) 克隆空间仓库，把下列文件推上去：
     - app.py            (本文件)
     - requirements.txt  (见下方)
     - README.md         (可选，自动生成模型卡片)
  3) 创空间自动构建、分配免费 xGPU、给出固定 HTTPS 域名

持久化模型权重（关键，避免每次冷启动重新下载 4.58GB）：
  - 创空间支持挂载 数据集/模型 到 /mnt/data，建议在魔搭先上传 VoxCPM2 模型为私有数据集/模型，
    然后在空间设置里「挂载数据集/模型」到 /mnt/data/VoxCPM2
  - 或在代码里用 modelscope.snapshot_download 下载到 /tmp（冷启动会重下，较慢）

环境变量（在空间设置 -> 环境变量 里配置，不落代码）：
  VOXCPM2_INFERENCE_TIMESTEPS=10   # 推理步数，8~12，默认10
  HF_ENDPOINT=https://hf-mirror.com
"""
import os
import sys
import time
import types
import warnings
import tempfile
import base64

os.environ.setdefault("HF_HUB_DISABLE_SSL_VERIFY", "1")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass
warnings.filterwarnings("ignore", category=FutureWarning)

import numpy as np
import torch
import gradio as gr

# ---- 兼容补丁 ----
_real = torch.load
def _pl(*a, **k):
    k.setdefault("weights_only", False)
    return _real(*a, **k)
_pl._patched_weights_only = True
torch.load = _pl
if not hasattr(torch.nn, "attention"):
    torch.nn.attention = types.ModuleType("attention")
    sys.modules["torch.nn.attention"] = torch.nn.attention
try:
    import torch.nn.attention.flex_attention as _f
except Exception:
    _f = types.ModuleType("flex_attention")
    torch.nn.attention.flex_attention = _f
    sys.modules["torch.nn.attention.flex_attention"] = _f
if not hasattr(_f, "BlockMask") or not isinstance(getattr(_f, "BlockMask"), type):
    class _BM: pass
    _f.BlockMask = _BM

# ---- 全局模型单例 ----
MODEL_DIR = os.environ.get("MODEL_CACHE", "/mnt/data/VoxCPM2")  # 创空间挂载点
VOXCPM_MODEL = None
SAMPLE_RATE = 48000
MODEL_LOADED = False


def load_model_once():
    global VOXCPM_MODEL, SAMPLE_RATE, MODEL_LOADED
    if MODEL_LOADED:
        return VOXCPM_MODEL, SAMPLE_RATE
    # 兜底：若挂载点无模型，从 HF/魔搭下载到缓存（首次冷启动较慢）
    if not (os.path.exists(os.path.join(MODEL_DIR, "config.json")) and
            os.path.exists(os.path.join(MODEL_DIR, "model.safetensors"))):
        print(f"[Space] 模型未在 {MODEL_DIR} 发现，尝试自动下载 ...")
        try:
            from modelscope import snapshot_download
            snapshot_download("OpenBMB/VoxCPM2", local_dir=MODEL_DIR)
        except Exception:
            # 进一步兜底到 HF 镜像
            import subprocess, sys
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "huggingface_hub"], check=False)
            from huggingface_hub import snapshot_download
            snapshot_download("openbmb/VoxCPM2", local_dir=MODEL_DIR, endpoint=os.environ.get("HF_ENDPOINT"))
    from voxcpm import VoxCPM
    print(f"[Space] Loading VoxCPM2 from {MODEL_DIR} ...", flush=True)
    t0 = time.time()
    VOXCPM_MODEL = VoxCPM.from_pretrained(
        MODEL_DIR, load_denoiser=False, optimize=False, device="cuda" if torch.cuda.is_available() else "cpu"
    )
    SAMPLE_RATE = getattr(VOXCPM_MODEL.tts_model, "sample_rate", 48000)
    MODEL_LOADED = True
    print(f"[Space] Loaded in {time.time()-t0:.1f}s, sr={SAMPLE_RATE}", flush=True)
    return VOXCPM_MODEL, SAMPLE_RATE


def generate_tts(text: str, steps: int, cfg: float):
    """Gradio 回调：返回 (sample_rate, numpy_audio)"""
    if not text or not text.strip():
        raise gr.Error("请输入要合成的文本")
    model, sr = load_model_once()
    t0 = time.time()
    wav = model.generate(text=text, cfg_value=cfg, inference_timesteps=steps)
    synth = time.time() - t0
    wav = np.asarray(wav).astype("float32").reshape(-1)
    dur = len(wav) / sr
    # 返回 Gradio 期望的 (sr, np.ndarray)
    return sr, wav


# ---- Gradio UI ----
with gr.Blocks(title="VoxCPM2 TTS Demo (ModelScope Space)", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
# 🎙️ VoxCPM2 文本转语音演示
**ModelScope 创空间 · 免费 xGPU 自动冷启动**  
模型：OpenBMB/VoxCPM2 | 采样率 48kHz | 支持中英混合
""")
    with gr.Row():
        with gr.Column(scale=3):
            txt = gr.Textbox(
                label="输入文本",
                placeholder="你好，这是 VoxCPM2 在魔搭免费 GPU 上生成的语音。",
                lines=3,
            )
            with gr.Row():
                steps = gr.Slider(6, 15, value=int(os.environ.get("VOXCPM2_INFERENCE_TIMESTEPS", "10")), step=1, label="推理步数 (steps)")
                cfg = gr.Slider(1.0, 3.5, value=2.0, step=0.1, label="CFG 引导系数")
            btn = gr.Button("🔊 生成语音", variant="primary", size="lg")
        with gr.Column(scale=2):
            audio_out = gr.Audio(label="生成结果", type="numpy", autoplay=True)
            meta = gr.Markdown("*等待生成...*")
    btn.click(generate_tts, inputs=[txt, steps, cfg], outputs=[audio_out]).then(
        lambda sr, wav: f"✅ 完成 | 采样率 {sr} Hz | 时长 {len(wav)/sr:.2f}s | 合成耗时 {time.time()-_t0:.2f}s" if (_t0:=time.time()) else "",
        inputs=[], outputs=[meta]
    )
    gr.Examples(
        examples=[
            ["你好，这是 VoxCPM2 在魔搭免费 GPU 上生成的中文语音测试。", 10, 2.0],
            ["Hello, this is a test of VoxCPM2 text-to-speech on ModelScope free GPU.", 10, 2.0],
            ["The quick brown fox jumps over the lazy dog. 你好，世界！", 8, 2.0],
        ],
        inputs=[txt, steps, cfg],
    )

if __name__ == "__main__":
    # 预热加载（可选，加快首次请求）
    print("[Space] Pre-warming model...", flush=True)
    load_model_once()
    demo.launch(server_name="0.0.0.0", server_port=7860, show_error=True)
