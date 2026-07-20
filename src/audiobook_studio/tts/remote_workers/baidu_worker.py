#!/usr/bin/env python3
"""
Baidu AI Studio Worker for VoxCPM2 TTS (Daily Burst - 12h/day V100).

Hermes-AgentMesh Core Architecture Integration:
- Inherits BaseWorker contract (heartbeat, graceful shutdown, retry, R2 upload)
- Polls Upstash Redis queue "tts:tasks" -> synthesizes on V100 -> pushes audio to Cloudflare R2
- Dual backend: PaddlePaddle (preferred) + PyTorch fallback
- Downloads model from Hugging Face Hub at runtime, caches to /tmp/voxcpm2-model
- Requires Baidu Secrets: REDIS_HOST, REDIS_PORT, REDIS_AUTH, R2_*, WORKER_ID, PREFER_PADDLE, VOXCPM2_HF_REPO (optional)
"""

import os
import sys
import uuid
from typing import Any, Dict, Optional

from .base_worker import BaseWorker


# ==========================================
# Helper Functions
# ==========================================
def is_gpu_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        pass
    try:
        import paddle
        return paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0
    except Exception:
        pass
    return False


def get_device_name() -> str:
    try:
        import paddle
        return paddle.device.cuda.get_device_name(0)
    except Exception:
        pass
    try:
        import torch
        return torch.cuda.get_device_name(0)
    except Exception:
        pass
    return "CPU"


def get_gpu_memory_used_mb() -> int:
    try:
        import paddle
        return paddle.device.cuda.memory_allocated() // (1024 * 1024)
    except Exception:
        pass
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.memory_allocated() // (1024 * 1024)
    except Exception:
        pass
    return 0


def get_gpu_memory_total_mb() -> int:
    try:
        import paddle
        return paddle.device.cuda.get_device_properties(0).total_memory // (1024 * 1024)
    except Exception:
        pass
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
    except Exception:
        pass
    return 0


# ==========================================
# Engine Classes
# ==========================================
# We lazily import heavy deps only when needed
_TORCH_ENGINE = None
_PADDLE_ENGINE = None


def get_torch_engine():
    """Lazy import and instantiate PyTorch engine."""
    global _TORCH_ENGINE
    if _TORCH_ENGINE is not None:
        return _TORCH_ENGINE

    import torch
    import torchaudio
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from huggingface_hub import snapshot_download

    class T4VoxCPM2Engine:
        HF_REPO_ID = os.getenv("VOXCPM2_HF_REPO", "openbmb/VoxCPM2")
        CACHE_DIR = "/tmp/voxcpm2-model"

        def __init__(self, model_path: str = None):
            self.model_path = model_path or self.CACHE_DIR
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            print(f"[BOOTSTRAP] [PyTorch] Detected GPU: {get_device_name()}")
            self.model = None
            self.tokenizer = None
            self._load_model()

        def _load_model(self) -> None:
            import os
            if not os.path.exists(os.path.join(self.CACHE_DIR, "config.json")):
                print(f"📡 [PyTorch] 模型未找到，正在从 Hugging Face 下载: {self.HF_REPO_ID} -> {self.CACHE_DIR}...")
                snapshot_download(
                    repo_id=self.HF_REPO_ID,
                    local_dir=self.CACHE_DIR,
                    local_dir_use_symlinks=False,
                    resume_download=True,
                )
                print("✅ 模型下载完成！")
            else:
                print(f"📦 [PyTorch] 使用本地缓存模型: {self.CACHE_DIR}")

            self.model_path = self.CACHE_DIR
            print(f"Loading VoxCPM2 from {self.model_path} on {self.device}...")

            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_path,
                trust_remote_code=True,
                use_fast=False,
            )

            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                torch_dtype=torch.float16,
                device_map="auto",
                trust_remote_code=True,
                low_cpu_mem_usage=True,
            )
            self.model.eval()
            print(f"Model loaded. GPU memory: {get_gpu_memory_used_mb()} MB / {get_gpu_memory_total_mb()} MB")

        @torch.inference_mode()
        def synthesize(
            self,
            text: str,
            voice_id: str,
            prosody: dict,
            reference_audio: str = None,
        ) -> bytes:
            speaker_prompt = self._get_speaker_prompt(voice_id, reference_audio)

            inputs = self.tokenizer(text, return_tensors="pt")
            first_device = next(self.model.parameters()).device
            inputs = {k: v.to(first_device) for k, v in inputs.items()}

            audio_tokens = self.model.generate(
                **inputs,
                max_new_tokens=1024,
                do_sample=True,
                temperature=prosody.get("temperature", 0.7),
                top_p=prosody.get("top_p", 0.9),
                speaker_prompt=speaker_prompt,
            )

            waveform = self.model.decode_audio(audio_tokens)

            import io
            buffer = io.BytesIO()
            torchaudio.save(buffer, waveform.cpu(), sample_rate=24000, format="wav")
            return buffer.getvalue()

        def _get_speaker_prompt(self, voice_id: str, reference_audio: str = None):
            import os
            if reference_audio and os.path.exists(reference_audio):
                waveform, sr = torchaudio.load(reference_audio)
                if sr != 24000:
                    waveform = torchaudio.functional.resample(waveform, sr, 24000)
                first_device = next(self.model.parameters()).device
                return self.model.encode_speaker(waveform.to(first_device))

            speaker_map = {
                "zh_female_1": 0,
                "zh_male_1": 1,
                "en_female_1": 2,
                "en_male_1": 3,
            }
            speaker_idx = speaker_map.get(voice_id, 0)
            return self.model.get_speaker_embedding(speaker_idx)

    _TORCH_ENGINE = T4VoxCPM2Engine
    return _TORCH_ENGINE


def get_paddle_engine():
    """Lazy import and instantiate PaddlePaddle engine."""
    global _PADDLE_ENGINE
    if _PADDLE_ENGINE is not None:
        return _PADDLE_ENGINE

    import paddle
    from paddlenlp.transformers import AutoModelForCausalLM as PaddleAutoModelForCausalLM
    from paddlenlp.transformers import AutoTokenizer as PaddleAutoTokenizer
    from huggingface_hub import snapshot_download
    import soundfile as sf
    import io

    class PaddleVoxCPM2Engine:
        HF_REPO_ID = os.getenv("VOXCPM2_HF_REPO", "openbmb/VoxCPM2")
        CACHE_DIR = "/tmp/voxcpm2-model"

        def __init__(self, model_path: str = None):
            self.model_path = model_path or self.CACHE_DIR
            print(f"[BOOTSTRAP] [PaddlePaddle] Detected GPU: {get_device_name()}")
            self.model = None
            self.tokenizer = None
            self._load_model()

        def _load_model(self) -> None:
            import os
            if not os.path.exists(os.path.join(self.CACHE_DIR, "config.json")):
                print(f"📡 [Paddle] 模型未找到，正在从 Hugging Face 下载: {self.HF_REPO_ID} -> {self.CACHE_DIR}...")
                snapshot_download(
                    repo_id=self.HF_REPO_ID,
                    local_dir=self.CACHE_DIR,
                    local_dir_use_symlinks=False,
                    resume_download=True,
                )
                print("✅ 模型下载完成！")
            else:
                print(f"📦 [Paddle] 使用本地缓存模型: {self.CACHE_DIR}")

            self.model_path = self.CACHE_DIR
            print(f"Loading VoxCPM2 (Paddle) from {self.model_path}...")

            self.tokenizer = PaddleAutoTokenizer.from_pretrained(self.model_path, trust_remote_code=True)
            self.model = PaddleAutoModelForCausalLM.from_pretrained(
                self.model_path,
                dtype="float16",
                device_map="auto",
                trust_remote_code=True,
            )
            self.model.eval()
            print(f"Model loaded. GPU memory: {get_gpu_memory_used_mb()} MB / {get_gpu_memory_total_mb()} MB")

        @paddle.no_grad()
        def synthesize(
            self,
            text: str,
            voice_id: str,
            prosody: dict,
            reference_audio: str = None,
        ) -> bytes:
            speaker_prompt = self._get_speaker_prompt(voice_id, reference_audio)

            inputs = self.tokenizer(text, return_tensors="pd").to("gpu")

            audio_tokens = self.model.generate(
                **inputs,
                max_new_tokens=1024,
                do_sample=True,
                temperature=prosody.get("temperature", 0.7),
                top_p=prosody.get("top_p", 0.9),
                speaker_prompt=speaker_prompt,
            )

            waveform = self.model.decode_audio(audio_tokens)

            buffer = io.BytesIO()
            sf.write(buffer, waveform.numpy().T, samplerate=24000, format="WAV")
            return buffer.getvalue()

        def _get_speaker_prompt(self, voice_id: str, reference_audio: str = None):
            import paddle
            from pathlib import Path

            if reference_audio and Path(reference_audio).exists():
                waveform, sr = sf.read(reference_audio)
                waveform_tensor = paddle.to_tensor(waveform.T, dtype="float32").unsqueeze(0).to("gpu")
                if sr != 24000:
                    import paddlaudio.functional as F
                    waveform_tensor = F.resample(waveform_tensor, sr, 24000)
                return self.model.encode_speaker(waveform_tensor)

            speaker_map = {
                "zh_female_1": 0,
                "zh_male_1": 1,
                "en_female_1": 2,
                "en_male_1": 3,
            }
            speaker_idx = speaker_map.get(voice_id, 0)
            return self.model.get_speaker_embedding(speaker_idx)

    _PADDLE_ENGINE = PaddleVoxCPM2Engine
    return _PADDLE_ENGINE


# ==========================================
# BAIDU WORKER IMPLEMENTATION
# ==========================================
class BaiduWorker(BaseWorker):
    """Baidu AI Studio worker with dual backend (Paddle preferred, PyTorch fallback)."""

    def __init__(self):
        self.prefer_paddle = os.getenv("PREFER_PADDLE", "true").lower() == "true"
        self.backend = None
        super().__init__(platform_prefix="baidu")

    def _init_engine(self):
        # Engine downloads from HF Hub automatically
        if self.prefer_paddle:
            try:
                import paddle
                # Check if paddle is available and can use GPU
                if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
                    PaddleEngine = get_paddle_engine()
                    engine = PaddleEngine()
                    self.backend = "paddle"
                    print("Using PaddlePaddle backend (preferred on Baidu)")
                    return engine
            except Exception as e:
                print(f"PaddlePaddle backend failed: {e}")
                print("Falling back to PyTorch...")

        try:
            import torch
            if torch.cuda.is_available():
                TorchEngine = get_torch_engine()
                engine = TorchEngine()
                self.backend = "torch"
                print("Using PyTorch backend (fallback)")
                return engine
        except Exception as e:
            print(f"PyTorch backend failed: {e}")
            raise

        raise RuntimeError("No inference backend available (need PaddlePaddle or PyTorch)")

    def _execute_smoke_test(self) -> None:
        print(f"🧪 [{self.worker_id}] Running smoke test ({self.backend})...")
        test_audio = self.engine.synthesize("测试语音合成。", "zh_female_1", {})
        print(f"✅ Smoke test passed: {len(test_audio)} bytes generated")

    def _synthesize(
        self,
        text: str,
        voice_id: str,
        prosody: dict,
        reference_audio: str = None,
    ) -> bytes:
        return self.engine.synthesize(text, voice_id, prosody, reference_audio)

    def _get_platform_gpu_metrics(self) -> dict:
        return {
            "gpu_mem_used_mb": get_gpu_memory_used_mb(),
            "gpu_mem_total_mb": get_gpu_memory_total_mb(),
            "device_name": get_device_name(),
            "backend": self.backend,
        }


def main():
    if not getattr(sys, '_baidu_worker_test_mode', False):
        if not is_gpu_available():
            print("ERROR: GPU not available. This worker requires V100 GPU on Baidu AI Studio.", file=sys.stderr)
            sys.exit(1)

    worker = BaiduWorker()
    worker.run()


if __name__ == "__main__":
    main()