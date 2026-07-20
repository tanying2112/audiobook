#!/usr/bin/env python3
"""
Lightning AI Studio Worker for VoxCPM2 TTS (Backup - 80h/month T4).

Hermes-AgentMesh Core Architecture Integration:
- Inherits BaseWorker contract (heartbeat, graceful shutdown, retry, R2 upload)
- Polls Upstash Redis queue "tts:tasks" -> synthesizes on T4 -> pushes audio to Cloudflare R2
- Downloads model from Hugging Face Hub at runtime, caches to /tmp/voxcpm2-model
- Requires Lightning Secrets: REDIS_HOST, REDIS_PORT, REDIS_AUTH, R2_*, WORKER_ID, VOXCPM2_HF_REPO (optional)
"""

import os
import sys
import torch
import torchaudio
from transformers import AutoModelForCausalLM, AutoTokenizer
from huggingface_hub import snapshot_download

from .base_worker import BaseWorker


def get_gpu_memory_used_mb() -> int:
    try:
        if torch.cuda.is_available():
            return torch.cuda.memory_allocated() // (1024 * 1024)
    except Exception:
        pass
    return 0


def get_gpu_memory_total_mb() -> int:
    try:
        if torch.cuda.is_available():
            return torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
    except Exception:
        pass
    return 0


def get_device_name() -> str:
    try:
        if torch.cuda.is_available():
            return torch.cuda.get_device_name(0)
    except Exception:
        pass
    return "CPU"


class T4VoxCPM2Engine:
    """
    PyTorch VoxCPM2 inference engine for single T4 (Lightning/Modal).
    Downloads model from Hugging Face Hub at runtime if not cached locally.
    """

    HF_REPO_ID = os.getenv("VOXCPM2_HF_REPO", "openbmb/VoxCPM2")
    CACHE_DIR = "/tmp/voxcpm2-model"

    def __init__(self, model_path: str = None):
        self.model_path = model_path or self.CACHE_DIR
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[BOOTSTRAP] Detected GPU: {get_device_name()}")
        self.model = None
        self.tokenizer = None
        self._load_model()

    def _load_model(self) -> None:
        import os

        if not os.path.exists(os.path.join(self.CACHE_DIR, "config.json")):
            print(f"📡 模型未找到，正在从 Hugging Face 下载: {self.HF_REPO_ID} -> {self.CACHE_DIR}...")
            snapshot_download(
                repo_id=self.HF_REPO_ID,
                local_dir=self.CACHE_DIR,
                local_dir_use_symlinks=False,
                resume_download=True,
            )
            print("✅ 模型下载完成！")
        else:
            print(f"📦 使用本地缓存模型: {self.CACHE_DIR}")

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


class LightningWorker(BaseWorker):
    """Lightning AI Studio worker with T4 + R2 upload."""

    def __init__(self):
        super().__init__(platform_prefix="lightning")

    def _init_engine(self) -> T4VoxCPM2Engine:
        return T4VoxCPM2Engine()

    def _execute_smoke_test(self) -> None:
        print(f"🧪 [{self.worker_id}] Running smoke test...")
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
        }


def main():
    if not torch.cuda.is_available():
        print("ERROR: CUDA not available. This worker requires GPU (T4 on Lightning AI Studio).", file=sys.stderr)
        sys.exit(1)

    worker = LightningWorker()
    worker.run()


if __name__ == "__main__":
    main()