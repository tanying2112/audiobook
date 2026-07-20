#!/usr/bin/env python3
"""
Kaggle VoxCPM2 Worker (Terminal Hardcore Deployment).

Hermes-AgentMesh Core Architecture Integration:
- Inherits BaseWorker contract (heartbeat, graceful shutdown, retry, R2 upload)
- Polls Upstash Redis queue "tts:tasks" -> synthesizes on T4 x2 -> pushes audio to Cloudflare R2
- Model parallel via device_map="auto" across T4 x2
- Real forward-pass smoke test to verify GPU compute pipeline
- Uses hf-mirror.com to bypass Cloudflare blocks
"""

import os
import sys
import torch
import torchaudio
from transformers import AutoModelForCausalLM, AutoTokenizer
from huggingface_hub import snapshot_download

from .base_worker import BaseWorker


# ==========================================
# SSL VERIFICATION BYPASS
# ==========================================
os.environ["HF_HUB_DISABLE_SSL_VERIFY"] = "1"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# ==========================================
# PyTorch 2.6+ weights_only=True COMPAT FIX
# ==========================================
# Force torch.load default to weights_only=False for legacy model files
_REAL_ORIGINAL_TORCH_LOAD = torch.load

def _patched_torch_load(*args, **kwargs):
    if 'weights_only' not in kwargs:
        kwargs['weights_only'] = False
    return _REAL_ORIGINAL_TORCH_LOAD(*args, **kwargs)
_patched_torch_load._patched_weights_only = True

torch.load = _patched_torch_load
sys.modules['torch'].load = _patched_torch_load

# ==========================================
# BlockMask TYPE HINT FIX (transformers compat)
# ==========================================
try:
    if not hasattr(torch.nn, 'attention'):
        torch.nn.attention = types.ModuleType('attention')
        sys.modules['torch.nn.attention'] = torch.nn.attention

    try:
        import torch.nn.attention.flex_attention as flex_module
    except ImportError:
        flex_module = types.ModuleType('flex_attention')
        torch.nn.attention.flex_attention = flex_module
        sys.modules['torch.nn.attention.flex_attention'] = flex_module

    if not hasattr(flex_module, 'BlockMask') or not isinstance(getattr(flex_module, 'BlockMask', None), type):
        class DummyBlockMask:
            pass
        flex_module.BlockMask = DummyBlockMask
        sys.modules['torch.nn.attention.flex_attention.BlockMask'] = DummyBlockMask
except Exception:
    pass


# ==========================================
# GPU Helpers
# ==========================================
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


# ==========================================
# Engine Class
# ==========================================
class T4VoxCPM2Engine:
    """
    PyTorch VoxCPM2 inference engine for Kaggle T4 x2.
    Downloads model from hf-mirror.com at runtime.
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
            print(f"📡 Model not found, downloading from HF Mirror: {self.HF_REPO_ID} -> {self.CACHE_DIR}...")
            snapshot_download(
                repo_id=self.HF_REPO_ID,
                local_dir=self.CACHE_DIR,
                local_dir_use_symlinks=False,
                resume_download=True,
            )
            print("✅ Model download complete!")
        else:
            print(f"📦 Using local cached model: {self.CACHE_DIR}")

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


# ==========================================
# KAGGLE WORKER IMPLEMENTATION
# ==========================================
class KaggleWorker(BaseWorker):
    """Kaggle worker with T4 x2."""

    def __init__(self):
        super().__init__(platform_prefix="kaggle")

    def _init_engine(self):
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
        print("ERROR: CUDA not available. This worker requires GPU (T4 x2 on Kaggle).", file=sys.stderr)
        sys.exit(1)

    worker = KaggleWorker()
    worker.run()


if __name__ == "__main__":
    main()