#!/usr/bin/env python3
"""
Baidu AI Studio (飞桨) Worker for VoxCPM2 TTS (Daily Burst - 12h/day V100).

Hermes-AgentMesh Core Architecture Integration:
- Inherits BaseWorker contract (heartbeat, graceful shutdown, retry, R2 upload)
- Polls Upstash Redis queue "tts:tasks" → synthesizes on V100 → pushes audio to Cloudflare R2
- Dual backend: PaddlePaddle (preferred) + PyTorch fallback
- Downloads model from Hugging Face Hub at runtime, caches to /tmp/voxcpm2-model
- Requires Baidu Secrets: REDIS_HOST, REDIS_PORT, REDIS_AUTH, R2_*, WORKER_ID, PREFER_PADDLE, VOXCPM2_HF_REPO (optional)
"""

import abc
import json
import os
import signal
import sys
import time
import uuid
from typing import Any, Dict, Optional

# ==========================================
# 1. RUNTIME DEPENDENCY INJECTION
# ==========================================
_print = print


def _log(msg: str) -> None:
    _print(f"[BOOTSTRAP] {msg}", flush=True)


def _install_missing_deps() -> None:
    """Install missing packages at runtime (Baidu Studio base image is minimal)."""
    required = {
        "torch": "torch",
        "torchaudio": "torchaudio",
        "transformers": "transformers",
        "sentencepiece": "sentencepiece",
        "protobuf": "protobuf",
        "accelerate": "accelerate",
        "redis": "redis",
        "boto3": "boto3",
        "tiktoken": "tiktoken",
        "huggingface_hub": "huggingface_hub",
        "soundfile": "soundfile",
    }
    import importlib
    import subprocess

    for mod, pkg in required.items():
        try:
            importlib.import_module(mod)
        except ImportError:
            _log(f"Installing missing dependency: {pkg}")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-q", pkg],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    # PaddlePaddle is platform-specific - install only if preferred
    if os.getenv("PREFER_PADDLE", "true").lower() == "true":
        try:
            importlib.import_module("paddle")
        except ImportError:
            _log("Installing PaddlePaddle (preferred on Baidu)...")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-q", "paddlepaddle-gpu", "paddlenlp", "paddlaudio"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


_log("📦 Installing production dependencies...")
_install_missing_deps()
_log("✅ Bootstrap complete")

# ==========================================
# 2. HEAVY IMPORTS (after bootstrap)
# ==========================================
import torch
import torchaudio
from transformers import AutoModelForCausalLM, AutoTokenizer

try:
    import boto3
    import redis
except ImportError:
    boto3 = None
    redis = None

# PaddlePaddle - optional
try:
    import paddle
    from paddlenlp.transformers import AutoModelForCausalLM as PaddleAutoModelForCausalLM
    from paddlenlp.transformers import AutoTokenizer as PaddleAutoTokenizer

    PADDLE_AVAILABLE = True
    _log("✓ PaddlePaddle available - using Paddle backend")
except ImportError:
    PADDLE_AVAILABLE = False
    _log("✗ PaddlePaddle not available")

TORCH_AVAILABLE = True  # torch imported above


# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def is_gpu_available() -> bool:
    if PADDLE_AVAILABLE:
        try:
            return paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0
        except Exception:
            pass
    if TORCH_AVAILABLE:
        try:
            return torch.cuda.is_available()
        except Exception:
            pass
    return False


def get_device_name() -> str:
    if PADDLE_AVAILABLE:
        try:
            return paddle.device.cuda.get_device_name(0)
        except Exception:
            pass
    if TORCH_AVAILABLE:
        try:
            return torch.cuda.get_device_name(0)
        except Exception:
            pass
    return "CPU"


def get_gpu_memory_used() -> int:
    if PADDLE_AVAILABLE:
        try:
            return paddle.device.cuda.memory_allocated() // (1024 * 1024)
        except Exception:
            pass
    if TORCH_AVAILABLE:
        try:
            if torch.cuda.is_available():
                return torch.cuda.memory_allocated() // (1024 * 1024)
        except Exception:
            pass
    return 0


def get_gpu_memory_total() -> int:
    if PADDLE_AVAILABLE:
        try:
            return paddle.device.cuda.get_device_properties(0).total_memory // (1024 * 1024)
        except Exception:
            pass
    if TORCH_AVAILABLE:
        try:
            if torch.cuda.is_available():
                return torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
        except Exception:
            pass
    return 0


# ==========================================
# 4. INLINED BaseWorker (single-file contract)
# ==========================================
class R2Uploader:
    """Upload audio bytes directly to Cloudflare R2 (S3-compatible)."""

    def __init__(
        self,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        public_url_base: Optional[str] = None,
        verify_ssl: bool = False,  # Disable SSL verification for R2 custom domains
    ):
        if boto3 is None:
            raise RuntimeError("boto3 unavailable — bootstrap failed")
        self.bucket = bucket
        self.public_url_base = public_url_base or f"https://{bucket}.r2.cloudflarestorage.com"
        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
            verify=verify_ssl,
        )

    def upload(self, audio_bytes: bytes, object_key: str) -> str:
        """Upload raw WAV bytes to R2, return public URL."""
        self.s3.put_object(
            Bucket=self.bucket,
            Key=object_key,
            Body=audio_bytes,
            ContentType="audio/wav",
        )
        return f"{self.public_url_base}/{object_key}"


class BaseWorker(abc.ABC):
    """
    Abstract base worker coordinating distributed TTS task lifecycle.

    Subclasses implement:
    - _init_engine(): Model loading with dual backend support
    - _synthesize(): Inference call returning raw WAV bytes
    - _execute_smoke_test(): Quick validation at startup
    - _get_platform_gpu_metrics(): Hardware telemetry
    """

    def __init__(self, platform_prefix: str):
        self.platform_prefix = platform_prefix
        self.running = True

        self.worker_id = os.getenv("WORKER_ID", f"{platform_prefix}-{uuid.uuid4().hex[:8]}")
        self.studio_id = os.getenv("BAIDU_STUDIO_ID", "unknown")
        self.idle_timeout = int(os.getenv("IDLE_TIMEOUT_SECONDS", "900"))
        self.max_empty_polls = int(os.getenv("MAX_EMPTY_POLLS", "3"))

        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

        self._validate_and_load_config()

        self.redis = redis.Redis(
            host=self.redis_host,
            port=self.redis_port,
            password=self.redis_auth,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        self.r2 = R2Uploader(
            self.r2_endpoint,
            self.r2_access_key,
            self.r2_secret_key,
            self.r2_bucket,
            self.r2_public_url,
            verify_ssl=False,
        )
        self.heartbeat_key = f"worker:heartbeat:{self.worker_id}"

        _print(f"⚙️ [{self.worker_id}] Initializing VoxCPM2 compute backend...")
        self.engine = self._init_engine()

        self._execute_smoke_test()

    def _validate_and_load_config(self) -> None:
        self.redis_host = os.getenv("REDIS_HOST")
        self.redis_port = int(os.getenv("REDIS_PORT", "6379"))
        self.redis_auth = os.getenv("REDIS_AUTH")
        self.r2_endpoint = os.getenv("R2_ENDPOINT")
        self.r2_access_key = os.getenv("R2_ACCESS_KEY_ID")
        self.r2_secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
        self.r2_bucket = os.getenv("R2_BUCKET")
        self.r2_public_url = os.getenv("R2_PUBLIC_URL")

        required = {
            "REDIS_HOST": self.redis_host,
            "REDIS_AUTH": self.redis_auth,
            "R2_ENDPOINT": self.r2_endpoint,
            "R2_ACCESS_KEY_ID": self.r2_access_key,
            "R2_SECRET_ACCESS_KEY": self.r2_secret_key,
            "R2_BUCKET": self.r2_bucket,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Fatal initialization error. Missing env vars: {missing}")

    def _handle_shutdown(self, signum: int, frame: Any) -> None:
        _print(f"\n⚠️ [{self.worker_id}] Caught signal ({signum}). Flushing and exiting gracefully...")
        self.running = False

    def _execute_network_call_with_retry(
        self,
        func,
        *args,
        max_retries: int = 3,
        **kwargs,
    ) -> Any:
        delay = 1.0
        for attempt in range(1, max_retries + 1):
            try:
                return func(*args, **kwargs)
            except (redis.RedisError, boto3.exceptions.Boto3Error) as error:
                _print(f"⚠️ [{self.worker_id}] I/O failure attempt {attempt}/{max_retries}: {error}", file=sys.stderr)
                if attempt == max_retries:
                    raise
                time.sleep(delay)
                delay *= 2.0

    def _send_heartbeat(self, status: str, queue_depth: int = 0) -> None:
        payload = {
            "ts": time.time(),
            "status": status,
            "worker_id": self.worker_id,
            "studio_id": self.studio_id,
            "gpu_metrics": self._get_platform_gpu_metrics(),
            "queue_depth": queue_depth,
            "idle_timeout": self.idle_timeout,
        }
        try:
            self.redis.setex(self.heartbeat_key, self.idle_timeout + 60, json.dumps(payload))
        except Exception as e:
            _print(f"❌ [{self.worker_id}] Heartbeat publish dropped: {e}", file=sys.stderr)

    def _process_single_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        task_id = task["id"]
        text = task["text"]
        voice_id = task.get("voice_id", "zh_female_1")
        prosody = task.get("prosody", {})
        reference_audio = task.get("reference_audio")

        _print(f"🚀 [{self.worker_id}] Processing task {task_id} ({len(text)} chars)")
        try:
            audio_bytes = self._synthesize(text, voice_id, prosody, reference_audio)
            object_key = f"tts/{task_id}.wav"
            r2_url = self._execute_network_call_with_retry(self.r2.upload, audio_bytes, object_key)

            return {
                "id": task_id,
                "status": "success",
                "url": r2_url,
                "worker": self.worker_id,
                "studio_id": self.studio_id,
                "duration_ms": len(audio_bytes) * 1000 // 48000,
            }
        except Exception as e:
            _print(f"💥 [{self.worker_id}] Task {task_id} pipeline crash: {e}", file=sys.stderr)
            return {
                "id": task_id,
                "status": "failed",
                "error": str(e),
                "worker": self.worker_id,
                "studio_id": self.studio_id,
            }

    def run(self) -> None:
        _print(f"⚡ [{self.worker_id}] System engine ready. Awaiting inbound task blocks...")
        empty_polls = 0

        while self.running:
            try:
                queue_depth = self.redis.llen("tts:tasks")
            except Exception:
                queue_depth = 0

            self._send_heartbeat("idle" if empty_polls > 0 else "processing", queue_depth)

            try:
                task_data = self.redis.blpop("tts:tasks", timeout=300)
            except Exception as e:
                _print(f"🔌 [{self.worker_id}] Connection severed during blocking poll: {e}", file=sys.stderr)
                time.sleep(5)
                continue

            if task_data:
                empty_polls = 0
                _, payload = task_data
                try:
                    task = json.loads(payload)
                except json.JSONDecodeError:
                    _print(f"🚨 [{self.worker_id}] Discarding corrupted payload.", file=sys.stderr)
                    continue

                self._send_heartbeat("processing", queue_depth)
                result = self._process_single_task(task)

                try:
                    self._execute_network_call_with_retry(self.redis.rpush, "tts:results", json.dumps(result))
                except Exception as e:
                    _print(f"❌ [{self.worker_id}] Result packet lost: {e}", file=sys.stderr)

                if result["status"] == "failed":
                    try:
                        self.redis.rpush("tts:tasks", payload)
                        _print(f"🔄 [{self.worker_id}] Task {task['id']} safely re-queued.")
                    except Exception as e:
                        _print(f"🚨 [{self.worker_id}] Critical failure. Task rollback lost: {e}", file=sys.stderr)
            else:
                if not self.running:
                    break
                empty_polls += 1
                _print(f"💤 [{self.worker_id}] Queue empty ({empty_polls}/{self.max_empty_polls})")

                if empty_polls >= self.max_empty_polls:
                    try:
                        if self.redis.llen("tts:tasks") == 0:
                            _print(
                                f"🛑 [{self.worker_id}] Idle timeout triggered quota preservation. Autonomously terminating engine."
                            )
                            self._send_heartbeat("exiting", 0)
                            break
                    except Exception:
                        pass

        _print(f"🛑 [{self.worker_id}] Process shutdown sequence complete.")

    @abc.abstractmethod
    def _init_engine(self) -> Any:
        pass

    @abc.abstractmethod
    def _execute_smoke_test(self) -> None:
        pass

    @abc.abstractmethod
    def _synthesize(
        self,
        text: str,
        voice_id: str,
        prosody: Dict[str, Any],
        reference_audio: Optional[str],
    ) -> bytes:
        pass

    @abc.abstractmethod
    def _get_platform_gpu_metrics(self) -> Dict[str, int]:
        pass


# ==========================================
# 5. ENGINE CLASSES (Paddle + PyTorch dual backend)
# ==========================================
class T4VoxCPM2Engine:
    """
    PyTorch VoxCPM2 inference engine (fallback on Baidu).
    Downloads model from HF Hub at runtime if not cached locally.
    """

    HF_REPO_ID = os.getenv("VOXCPM2_HF_REPO", "openbmb/VoxCPM2")
    CACHE_DIR = "/tmp/voxcpm2-model"

    def __init__(self, model_path: str = None):
        import torch

        self.model_path = model_path or self.CACHE_DIR
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        _log(f"[PyTorch] Detected GPU: {get_device_name()}")
        self.model = None
        self.tokenizer = None
        self._load_model()

    def _load_model(self) -> None:
        import os

        from huggingface_hub import snapshot_download

        if not os.path.exists(os.path.join(self.CACHE_DIR, "config.json")):
            _log(f"📡 [PyTorch] 模型未找到，正在从 Hugging Face 下载: {self.HF_REPO_ID} -> {self.CACHE_DIR}...")
            snapshot_download(
                repo_id=self.HF_REPO_ID,
                local_dir=self.CACHE_DIR,
                local_dir_use_symlinks=False,
                resume_download=True,
            )
            _log("✅ 模型下载完成！")
        else:
            _log(f"📦 [PyTorch] 使用本地缓存模型: {self.CACHE_DIR}")

        self.model_path = self.CACHE_DIR
        _log(f"Loading VoxCPM2 from {self.model_path} on {self.device}...")

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
        _log(f"Model loaded. GPU memory: {get_gpu_memory_used()} MB / {get_gpu_memory_total()} MB")

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


class PaddleVoxCPM2Engine:
    """
    PaddlePaddle VoxCPM2 inference engine (preferred on Baidu).
    Downloads model from HF Hub at runtime if not cached locally.
    """

    HF_REPO_ID = os.getenv("VOXCPM2_HF_REPO", "openbmb/VoxCPM2")
    CACHE_DIR = "/tmp/voxcpm2-model"

    def __init__(self, model_path: str = None):
        self.model_path = model_path or self.CACHE_DIR
        _log(f"[PaddlePaddle] Detected GPU: {get_device_name()}")
        self.model = None
        self.tokenizer = None
        self._load_model()

    def _load_model(self) -> None:
        import os

        from huggingface_hub import snapshot_download

        if not os.path.exists(os.path.join(self.CACHE_DIR, "config.json")):
            _log(f"📡 [Paddle] 模型未找到，正在从 Hugging Face 下载: {self.HF_REPO_ID} -> {self.CACHE_DIR}...")
            snapshot_download(
                repo_id=self.HF_REPO_ID,
                local_dir=self.CACHE_DIR,
                local_dir_use_symlinks=False,
                resume_download=True,
            )
            _log("✅ 模型下载完成！")
        else:
            _log(f"📦 [Paddle] 使用本地缓存模型: {self.CACHE_DIR}")

        self.model_path = self.CACHE_DIR
        _log(f"Loading VoxCPM2 (Paddle) from {self.model_path}...")

        self.tokenizer = PaddleAutoTokenizer.from_pretrained(self.model_path, trust_remote_code=True)
        self.model = PaddleAutoModelForCausalLM.from_pretrained(
            self.model_path,
            dtype="float16",
            device_map="auto",
            trust_remote_code=True,
        )
        self.model.eval()
        _log(f"Model loaded. GPU memory: {get_gpu_memory_used()} MB / {get_gpu_memory_total()} MB")

    @paddle.no_grad()
    def synthesize(
        self,
        text: str,
        voice_id: str,
        prosody: dict,
        reference_audio: str = None,
    ) -> bytes:
        import io

        import soundfile as sf

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
        from pathlib import Path

        import paddle
        import soundfile as sf

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


# ==========================================
# 6. BAIDU WORKER IMPLEMENTATION
# ==========================================
class BaiduWorker(BaseWorker):
    """Baidu AI Studio worker with dual backend (Paddle preferred, PyTorch fallback)."""

    def __init__(self):
        self.prefer_paddle = os.getenv("PREFER_PADDLE", "true").lower() == "true"
        self.backend = None
        super().__init__(platform_prefix="baidu")

    def _init_engine(self):
        # Engine downloads from HF Hub automatically
        if self.prefer_paddle and PADDLE_AVAILABLE:
            try:
                engine = PaddleVoxCPM2Engine()
                self.backend = "paddle"
                _log("Using PaddlePaddle backend (preferred on Baidu)")
                return engine
            except Exception as e:
                _log(f"PaddlePaddle backend failed: {e}")
                _log("Falling back to PyTorch...")

        if TORCH_AVAILABLE:
            try:
                engine = T4VoxCPM2Engine()
                self.backend = "torch"
                _log("Using PyTorch backend (fallback)")
                return engine
            except Exception as e:
                _log(f"PyTorch backend failed: {e}")
                raise

        raise RuntimeError("No inference backend available (need PaddlePaddle or PyTorch)")

    def _execute_smoke_test(self) -> None:
        _print(f"🧪 [{self.worker_id}] Running smoke test ({self.backend})...")
        test_audio = self.engine.synthesize("测试语音合成。", "zh_female_1", {})
        _print(f"✅ Smoke test passed: {len(test_audio)} bytes generated")

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
            "gpu_mem_used_mb": get_gpu_memory_used(),
            "gpu_mem_total_mb": get_gpu_memory_total(),
            "device_name": get_device_name(),
            "backend": self.backend,
        }


def main():
    if not is_gpu_available():
        _print("ERROR: GPU not available. This worker requires V100 GPU on Baidu AI Studio.", file=sys.stderr)
        sys.exit(1)

    worker = BaiduWorker()
    worker.run()


if __name__ == "__main__":
    main()
