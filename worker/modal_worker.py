#!/usr/bin/env python3
"""
Modal Serverless Worker for VoxCPM2 TTS (Spiky Demand - 40h/month T4).

Hermes-AgentMesh Core Architecture Integration:
- Inherits BaseWorker contract (heartbeat, graceful shutdown, retry, R2 upload)
- Polls Upstash Redis queue "tts:tasks" → synthesizes on T4 → pushes audio to Cloudflare R2
- Downloads model from Hugging Face Hub at runtime, caches to Modal Volume for fast cold start
- Requires Modal Secret "audiobook-config" with: REDIS_HOST, REDIS_PORT, REDIS_AUTH, R2_*, WORKER_ID, VOXCPM2_HF_REPO (optional)

# ==========================================
# Modal SECRETS (configured via `modal secret create audiobook-config`)
# ==========================================
# ⚠️ 红线#5 合规：本文件密钥已占位化，Modal Secret 在 Dashboard 配置，不回填明文到代码。
# Modal Secret 名称: audiobook-config
# 必需字段:
#   REDIS_HOST=casual-sawfish-86152.upstash.io
#   REDIS_PORT=6379
#   REDIS_AUTH=<REDACTED_UPSTASH_REDIS_PASSWORD>
#   R2_ENDPOINT=https://<REDACTED_R2_ACCOUNT_ID>.r2.cloudflarestorage.com
#   R2_ACCESS_KEY_ID=<REDACTED_R2_ACCESS_KEY_ID>
#   R2_SECRET_ACCESS_KEY=<REDACTED_R2_SECRET_ACCESS_KEY>
#   R2_BUCKET=audiobook-assets
#   R2_PUBLIC_URL=https://pub-xxx.r2.dev
#   WORKER_ID=modal-t4-01
#   VOXCPM2_HF_REPO=openbmb/VoxCPM2
#
# 创建命令:
# modal secret create audiobook-config REDIS_HOST=... REDIS_PORT=... REDIS_AUTH=... ...
"""

import io
import json
import os
import sys
from pathlib import Path

import modal

# Ensure src is on path for BaseWorker import
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

PROJECT_ROOT = Path(__file__).parent.parent

# ==========================================
# Safe torch import for local development
# ==========================================
try:
    import torch
except ImportError:

    class MockTorch:
        def inference_mode(self, *args, **kwargs):
            return lambda func: func

    torch = MockTorch()
    print("⚠️  Local env missing torch, mock active (cloud deployment unaffected).")

from src.worker_base import BaseWorker

# ==========================================
# 1. Modal Image Definition (pre-baked deps)
# ==========================================
worker_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .pip_install(
        "torch",
        "torchaudio",
        "transformers>=4.45.0",
        "sentencepiece",
        "protobuf",
        "tiktoken",
        "accelerate",
        "scipy",
        "soundfile",
        "redis",
        "boto3",
        "einops",
        "librosa",
        "safetensors",
        "pydantic",
        "tqdm",
        "huggingface_hub",  # NEW: for runtime model download
            "speechbrain==1.1.0",
    )
    .add_local_dir(str(PROJECT_ROOT / "src"), remote_path="/src")
)

# Persistent volume for model cache (survives container recycle)
model_vol = modal.Volume.from_name("voxcpm2-model-vol", create_if_missing=True)

app = modal.App("dark-night-audio-factory-worker")


# ==========================================
# 2. Engine & Worker Classes
# ==========================================
class VoxCPM2Engine:
    """
    PyTorch VoxCPM2 inference engine for Modal using custom VoxCPM2 model.
    Downloads from HF Hub on first run, caches to Modal Volume.
    """

    HF_REPO_ID = os.getenv("VOXCPM2_HF_REPO", "openbmb/VoxCPM2")
    # Cache in Modal Volume for persistence across cold starts
    CACHE_DIR = "/models/voxcpm2-cache"

    def __init__(self, model_path: str = None):
        import torch

        self.model_path = model_path or self.CACHE_DIR
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.tokenizer = None
        self._load_model()

    def _load_model(self) -> None:
        import sys

        import torch
        from huggingface_hub import snapshot_download
        from transformers import LlamaTokenizerFast

        sys.path.insert(0, "/src")

        from voxcpm.model.voxcpm2 import VoxCPM2Model

        # Ensure cache directory exists
        os.makedirs(self.CACHE_DIR, exist_ok=True)

        # Download from HF Hub if not cached
        config_path = Path(self.CACHE_DIR) / "config.json"
        if not config_path.exists():
            print(f"📡 Model not found in volume, downloading from HF: {self.HF_REPO_ID} -> {self.CACHE_DIR}...")
            snapshot_download(
                repo_id=self.HF_REPO_ID,
                local_dir=self.CACHE_DIR,
                local_dir_use_symlinks=False,
                resume_download=True,
            )
            print("✅ Model downloaded and cached to Modal Volume!")
        else:
            print(f"📦 Using cached model from Modal Volume: {self.CACHE_DIR}")

        self.model_path = self.CACHE_DIR
        print(f"Loading VoxCPM2 from {self.model_path} on {self.device}...")

        # Load tokenizer
        self.tokenizer = LlamaTokenizerFast.from_pretrained(self.model_path, use_fast=False)
        print(f"✅ Tokenizer loaded: {self.tokenizer.__class__.__name__}")

        # Load VoxCPM2 model using from_local class method
        self.model = VoxCPM2Model.from_local(
            self.model_path,
            device=self.device,
            optimize=False,
        )
        self.model.eval()
        print(f"✅ VoxCPM2 model loaded: {self.model.__class__.__name__}")

    @torch.inference_mode()
    def synthesize(
        self,
        text: str,
        voice_id: str,
        prosody: dict,
        reference_audio: str = None,
    ) -> bytes:
        reference_wav = reference_audio if reference_audio and Path(reference_audio).exists() else ""

        generator = self.model.generate(
            target_text=text,
            reference_wav_path=reference_wav,
            inference_timesteps=prosody.get("inference_timesteps", 10),
            cfg_value=prosody.get("cfg_value", 2.0),
            seed=prosody.get("seed", None),
        )

        audio_chunks = []
        for chunk in generator:
            audio_chunks.append(chunk)

        if not audio_chunks:
            raise ValueError("No audio generated")

        waveform = torch.cat(audio_chunks, dim=-1)

        import numpy as np
        import soundfile as sf

        buffer = io.BytesIO()
        sample_rate = getattr(self.model, "sample_rate", 24000)
        sf.write(buffer, waveform.cpu().numpy().T, sample_rate, format="WAV")
        return buffer.getvalue()


class ModalWorker(BaseWorker):
    """Modal serverless worker implementation."""

    def __init__(self):
        super().__init__(platform_prefix="modal")

    def _init_engine(self):
        return VoxCPM2Engine()

    def _execute_smoke_test(self) -> None:
        print(f"🧪 [{self.worker_id}] Running smoke test...")
        test_audio = self.engine.synthesize("测试", "zh_female_1", {})
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
        import torch

        return {
            "gpu_mem_used_mb": torch.cuda.memory_allocated() // (1024 * 1024) if torch.cuda.is_available() else 0,
            "gpu_mem_total_mb": (
                torch.cuda.get_device_properties(0).total_memory // (1024 * 1024) if torch.cuda.is_available() else 0
            ),
            "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
        }


# ==========================================
# 3. Modal Serverless Function
# ==========================================
@app.function(
    image=worker_image,
    gpu="T4",
    max_containers=2,
    volumes={"/models": model_vol},  # Persistent cache
    timeout=32400,
    secrets=[
        modal.Secret.from_name("audiobook-config"),
    ],
)
def run_modal_consumer() -> None:
    """Modal Serverless entry point running BaseWorker in ephemeral container."""
    import uuid

    os.environ["WORKER_ID"] = os.getenv("WORKER_ID", f"modal-t4-{uuid.uuid4().hex[:8]}")
    os.environ["IDLE_TIMEOUT_SECONDS"] = "900"
    os.environ["MAX_EMPTY_POLLS"] = "2"
    os.environ["VOXCPM2_MODEL_PATH"] = "/models"  # Model path in Modal volume

    worker = ModalWorker()
    worker.run()


# ==========================================
# 4. Local Entrypoint
# ==========================================
@app.local_entrypoint()
def main():
    print("🚀 Deploying to Modal cloud, allocating T4 node...")
    run_modal_consumer.remote()
    print("✅ Dispatched! Check Modal dashboard for logs.")


# ==========================================
# Determinism test entrypoint (runs REMOTE on Modal GPU)
# Usage: modal run worker/modal_worker.py::test_determinism --text "..." --seed 42
# Returns audio bytes hash for byte-level determinism verification
# ==========================================
@app.function(
    image=worker_image,
    volumes={"/models": model_vol},
    gpu="T4",
    timeout=300,
)
def test_determinism(text: str = "确定性测试文本", seed: int = 42, voice_id: str = "zh_female_1") -> str:
    import hashlib
    engine = VoxCPM2Engine()
    audio = engine.synthesize(
        text=text,
        voice_id=voice_id,
        prosody={"seed": seed},
    )
    h = hashlib.sha256(audio).hexdigest()
    print(f"DETERMINISM_HASH:{h}")
    print(f"BYTES:{len(audio)}")
    return h


# ==========================================
# 5. ECAPA Validation Function (runs on Modal T4 GPU)
# ==========================================
@app.function(
    image=worker_image,
    volumes={"/models": model_vol},
    gpu="T4",
    timeout=1800,
    secrets=[modal.Secret.from_name("audiobook-config")],
)
def run_ecapa_validation():
    """Run ECAPA speaker verification on all successful audio samples."""
    import json
    import os
    import redis
    import torch
    import torchaudio
    import tempfile
    import hashlib
    import requests
    from speechbrain.inference import SpeakerRecognition
    from urllib3.util.retry import Retry
    from requests.adapters import HTTPAdapter

    # Redis connection
    r = redis.Redis(
        host=os.getenv("REDIS_HOST", "casual-sawfish-86152.upstash.io"),
        port=6379,
        password=os.getenv("REDIS_AUTH", ""),
        ssl=True,
        decode_responses=True
    )

    print("=== ECAPA Validation Started ===")

    # Get successful results
    results = []
    for raw in redis.Redis(
        host="casual-sawfish-86152.upstash.io",
        port=6379,
        password=os.getenv("REDIS_AUTH", ""),
        ssl=True,
        decode_responses=True
    ).lrange('tts:results', 0, -1):
        try:
            result = json.loads(raw)
            if result.get('status') == 'success' and result.get('url'):
                results.append(result)
        except:
            pass

    print(f"Found {len(results)} successful audio tasks")

    if not results:
        return {"status": "no_results", "message": "No successful tasks found"}

    # Initialize ECAPA
    print("Initializing ECAPA...")
    from speechbrain.inference import SpeakerRecognition
    verification = SpeakerRecognition.from_hparams(
        source='speechbrain/spkrec-ecapa-voxceleb',
        savedir='/tmp/ecapa',
        run_opts={'device': 'cuda'}
    )

    # Download audio files
    import requests
    import tempfile

    session = requests.Session()
    from urllib3.util.retry import Retry
    from requests.adapters import HTTPAdapter
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=3))

    def download_audio(url):
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        tmp.write(resp.content)
        tmp.close()
        return tmp.name

    audio_files = {}
    for r_audio in results:
        url = r_audio['url']
        for attempt in range(3):
            try:
                resp = requests.get(url, timeout=60)
                resp.raise_for_status()
                tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                tmp.write(resp.content)
                tmp.close()
                audio_files[r_audio['id']] = {'path': tmp.name, 'info': r_audio}
                print(f"Downloaded {r_audio['id']}")
                break
            except Exception as e:
                if attempt == 2:
                    print(f"Failed to download {r_audio['id']}: {e}")
                time.sleep(2)

    print(f"Downloaded {len(audio_files)} audio files")

    # Initialize ECAPA
    from speechbrain.inference import SpeakerRecognition
    verification = SpeakerRecognition.from_hparams(
        source='speechbrain/spkrec-ecapa-voxceleb',
        savedir='/tmp/ecapa',
        run_opts={'device': 'cuda'}
    )

    # Pairwise comparison
    audio_items = list(audio_files.items())
    results_detail = []

    for i, (id_a, a) in enumerate(audio_items):
        for id_b, b in list(audio_files.items())[i+1:]:
            try:
                score, prediction = verification.verify_files(a['path'], b['path'])
                same = "同人" if prediction else "异人"
                score_val = float(score)
                result = {
                    "id_a": id_a,
                    "id_b": id_b,
                    "score": float(score),
                    "same_speaker": bool(prediction),
                    "same_label": "同人" if prediction else "异人"
                }
                results_detail.append(result)
                print(f'Pair {id_a[:8]} vs {id_b[:8]}: score={score_val:.4f} ({"同人" if prediction else "异人"})')
            except Exception as e:
                print(f'Pair 对比失败: {e}')

    # Cleanup
    import os
    for _, info in audio_files.items():
        try:
            os.unlink(info['path'])
        except:
            pass

    # Summary
    same_count = sum(1 for r in results_detail if r['same_speaker'])
    diff_count = len(results_detail) - same_count
    avg_score = sum(r['score'] for r in results_detail) / len(results_detail) if results_detail else 0

    summary = {
        "total_pairs": len(results_detail),
        "same_speaker_pairs": same_count,
        "diff_speaker_pairs": diff_count,
        "average_score": avg_score,
        "details": results_detail
    }

    print(f"\n=== ECAPA 验收摘要 ===")
    print(f"总对比对数: {summary['total_pairs']}")
    print(f"同声对数: {summary['same_speaker_pairs']}")
    print(f"跨声对数: {summary['diff_speaker_pairs']}")
    print(f"平均相似度: {summary['average_score']:.4f}")

    return {"status": "success", "summary": summary, "details": results_detail}

# 6. Local Entrypoints
# ==========================================

@app.local_entrypoint()
def deploy_worker():
    """Deploy the T4 worker consumer."""
    print("🚀 Deploying to Modal cloud, allocating T4 node...")
    run_modal_consumer.remote()
    print("✅ Dispatched! Check Modal dashboard for logs.")


@app.local_entrypoint()
def run_ecapa_validation_entrypoint():
    """Run ECAPA validation on Modal GPU."""
    result = run_ecapa_validation.remote()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    print("Usage: modal run worker/modal_worker.py")
    print("Direct python execution won't trigger cloud compute.")
