"""
Kaggle Worker for VoxCPM2 TTS
===================================
Kaggle 免费 T4 x2 GPU 节点实现
复用 worker/kaggle_worker.py 的完整实现
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from worker_base import BaseWorker


class KaggleWorker(BaseWorker):
    """Kaggle 免费 T4 x2 GPU Worker"""

    def __init__(self):
        super().__init__(platform_prefix="kaggle")

    def _init_engine(self) -> Any:
        """初始化 VoxCPM2 引擎 (Kaggle 环境优化)"""
        import torch

        _log(f"🔧 [{self.worker_id}] 初始化 Kaggle VoxCPM2 引擎...")

        # Kaggle 环境变量 (SSL 修复 + 镜像)
        os.environ.setdefault("HF_HUB_DISABLE_SSL_VERIFY", "1")
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

        model_path = os.getenv("VOXCPM2_MODEL_PATH", "/mnt/workspace/VoxCPM2")

        # 确保依赖
        self._ensure_kaggle_deps()

        # 烟雾测试会在 _execute_smoke_test 中验证
        # 加载模型
        return self._load_model()

    def _ensure_kaggle_deps(self):
        """确保 Kaggle 环境依赖"""
        import importlib.util
        import subprocess

        deps = {
            "modelscope": "modelscope",
            "huggingface_hub": "huggingface_hub",
            "soundfile": "soundfile",
            "requests": "requests",
            "numpy": "numpy",
            "boto3": "boto3",
            "redis": "redis",
        }
        missing = [
            pkg
            for mod, pkg in {
                "modelscope": "modelscope",
                "huggingface_hub": "huggingface_hub",
                "soundfile": "soundfile",
                "requests": "requests",
                "numpy": "numpy",
                "boto3": "boto3",
                "redis": "redis",
            }.items()
            if importlib.util.find_spec(mod) is None
        ]
        if missing:
            import subprocess

            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-cache-dir", *missing], check=False)

        if importlib.util.find_spec("voxcpm") is None:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "--no-cache-dir", "voxcpm==2.0.3"], check=False
            )

        # Kaggle 特有 patch: torch.load weights_only + BlockMask
        self._apply_kaggle_patches()

    def _apply_kaggle_patches(self):
        """Kaggle 特有补丁 (PyTorch 2.5+/2.6+ 兼容)"""
        import types
        import torch

        _REAL_TORCH_LOAD = torch.load

        def _patched_load(*a, **kw):
            if "weights_only" not in kw:
                kw["weights_only"] = False
            return _REAL_TORCH_LOAD(*a, **kw)

        _patched_load._patched_weights_only = True
        torch.load = _patched_load
        sys.modules["torch"].load = _patched_load

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

            class _BlockMask:
                pass

            f.BlockMask = _BlockMask
            sys.modules["torch.nn.attention.flex_attention.BlockMask"] = _BlockMask

    def _load_model(self) -> Any:
        """加载模型 (复用 voxcpm 库)"""
        import torch

        model_path = os.getenv("VOXCPM2_MODEL_PATH", "/mnt/workspace/VoxCPM2")
        _log(f"加载 VoxCPM2 from {model_path} ...")

        try:
            from voxcpm import VoxCPM

            t0 = time.time()
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            model = VoxCPM.from_pretrained(
                model_path,
                load_denoiser=False,
                optimize=False,
                device=dev,
            )
            sr = getattr(model.tts_model, "sample_rate", 48000)
            _log(f"✅ 官方库加载完成 {time.time()-t0:.1f}s, sr={sr}")
            if torch.cuda.is_available():
                mem = torch.cuda.memory_allocated() // 1024 // 1024
                tot = torch.cuda.get_device_properties(0).total_memory // 1024 // 1024
                _log(f"显存: {mem}/{tot} MB")
            return model
        except Exception as e:
            _log(f"官方库加载失败 ({e})，回退项目源码...")
            from voxcpm.model.voxcpm2 import VoxCPM2Model

            m = VoxCPM2Model.from_local(
                os.getenv("VOXCPM2_MODEL_PATH", "/mnt/workspace/VoxCPM2"),
                optimize=False,
            )
            m.eval()
            return m

    def _execute_smoke_test(self) -> None:
        """Kaggle 烟雾测试"""
        import numpy as np

        _log("🧪 烟雾测试...")
        try:
            wav = self.engine.generate(
                text="测试。",
                cfg_value=2.0,
                inference_timesteps=5,
            )
            wav = np.asarray(wav).astype("float32").reshape(-1)
            _log(f"✅ 烟雾测试通过: {len(wav)} 采样点")
        except Exception as e:
            raise RuntimeError(f"烟雾测试失败: {e}")

    def _synthesize(
        self,
        text: str,
        voice_id: str,
        prosody: Dict[str, Any],
        reference_audio: Optional[str],
    ) -> bytes:
        """Kaggle 推理 -> 返回 WAV bytes"""
        import numpy as np
        import soundfile as sf

        steps = prosody.get("steps", int(os.getenv("VOXCPM2_INFERENCE_TIMESTEPS", "10")))
        cfg = prosody.get("cfg", 2.0)

        _log(f"🎵 合成: {len(text)} 字符, steps={steps}")

        wav = self.engine.generate(
            text=text,
            cfg_value=cfg,
            inference_timesteps=prosody.get("inference_timesteps", steps),
        )

        wav = np.asarray(wav).astype("float32").reshape(-1)

        buffer = io.BytesIO()
        sr = getattr(self.engine.tts_model, "sample_rate", 48000)
        sf.write(buffer, wav, sr, format="WAV")
        return buffer.getvalue()

    def _get_platform_gpu_metrics(self) -> Dict[str, int]:
        """Kaggle GPU 指标"""
        import torch

        if torch.cuda.is_available():
            alloc = torch.cuda.memory_allocated() // 1024 // 1024
            total = torch.cuda.get_device_properties(0).total_memory // 1024 // 1024
            return {
                "vram_used_mb": alloc,
                "vram_total_mb": total,
                "vram_usage_percent": int(alloc * 100 / total) if total > 0 else 0,
                "gpu_name": torch.cuda.get_device_name(0),
                "gpu_count": torch.cuda.device_count(),
            }
        return {"error": "no_cuda"}


def _log(msg: str, also_print: bool = True):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    if also_print:
        print(line, flush=True)


# Kaggle Notebook 专用运行入口
def run_kaggle_notebook_cell():
    """
    在 Kaggle Notebook 的一个 cell 中运行此函数即可启动 Worker
    使用方式：
        exec(open("worker/kaggle_worker.py").read())
        run_kaggle_notebook_cell()
    """
    # 设置环境变量
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HUB_DISABLE_SSL_VERIFY", "1")
    os.environ.setdefault("VOXCPM2_MODEL_PATH", "/mnt/workspace/VoxCPM2")
    os.environ.setdefault("WORKER_ID", "kaggle-01")

    worker = KaggleWorker()
    worker.run()


if __name__ == "__main__":
    # 设置默认环境
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HUB_DISABLE_SSL_VERIFY", "1")
    os.environ.setdefault("VOXCPM2_MODEL_PATH", "/mnt/workspace/VoxCPM2")
    os.environ.setdefault("WORKER_ID", "kaggle-01")

    worker = KaggleWorker()
    worker.run()
