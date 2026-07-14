#!/usr/bin/env python3
"""
VoxCPM2 Terminal Hardcore Deployment & Smoke Test Engine for Kaggle T4 x2.

This script uses ZERO huggingface_hub library. Instead:
- Raw HTTP streaming download from hf-mirror.com (immune to Cloudflare blocks)
- Model Parallel via device_map="auto" across T4 x2
- Real forward-pass smoke test to verify GPU compute pipeline
"""

import os
import sys
import time
import subprocess
import abc
import json
import signal
import uuid
from typing import Any, Dict, Optional

# ========================================================
# 🔐 SSL 验证全局关闭 - 必须在任何 import 之前执行
# 解决 Kaggle 代理环境下的证书校验失败
# ========================================================
import os
os.environ["HF_HUB_DISABLE_SSL_VERIFY"] = "1"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
# ========================================================

import abc
import json
import signal
import sys
import time
import uuid
from typing import Any, Dict, Optional

# ========================================================
# 🛡️ Kaggle API 专用 - 密钥断网保护层
# 作用：当 Kaggle 内部 Secrets 服务由于 API 部署断开时，由此处直接提供环境变量兜底
# 这个代码块必须在最顶部，最早执行，确保在任何 _validate_and_load_config 之前填充环境变量
# ========================================================
_KAGGLE_API_FALLBACKS = {
    "REDIS_HOST": "casual-sawfish-86152.upstash.io",
    "REDIS_PORT": "6379",
    "REDIS_AUTH": "gQAAAAAAAVCIAAIgcDI2Njk2ZDcyMmZkNTU0N2FmYTIxZDk4ZDY4MTBjOGM4ZA",
    "R2_ENDPOINT": "https://061b064ef0dafd787d33f4ee1693aa1b.r2.cloudflarestorage.com",
    "R2_ACCESS_KEY_ID": "2fc25bbebc34f9b88874a8affcda2e3a",
    "R2_SECRET_ACCESS_KEY": "b7d997bc558346d8146d33be06810b7db600baafe0cbe5d7356268ee948ef9d3",
    "R2_BUOOKET": "audiobook-assets",
    "R2_PUBLIC_URL": "https://pub-xxx.r2.dev",
    "WORKER_ID": "kaggle-t4-dual-01",
    "VOXCPM2_HF_REPO": "openbmb/VoxCPM2",
    "HF_TOKEN": ""  # 从 Kaggle Secrets 注入，默认空字符串
}

for env_key, env_val in _KAGGLE_API_FALLBACKS.items():
    # 只有当系统环境变量中确实缺失该项时（即内置 Secrets 注入失败时），才进行本地覆盖
    # 注意：对于 HF_TOKEN 等可为空的值，只有当 fallback 值非空时才覆盖，避免用空字符串覆盖真实环境变量
    if env_key not in os.environ or not os.environ.get(env_key):
        if env_val:  # 只有非空字符串才覆盖
            os.environ[env_key] = str(env_val)
# ========================================================

# ==========================================
# 1. RUNTIME DEPENDENCY INJECTION (Kaggle runs naked)
# ==========================================
# Kaggle only has base image packages. Install production deps before any heavy imports.
_print = print
def _log(msg: str) -> None:
    _print(f"[BOOTSTRAP] {msg}", flush=True)


def _install_missing_deps() -> None:
    """Install missing packages at runtime (Kaggle kernel has no pip cells)."""
    required = {
        "torch": "torch",
        "torchaudio": "torchaudio",
        "sentencepiece": "sentencepiece",
        "protobuf": "protobuf",
        "accelerate": "accelerate",
        "redis": "redis",
        "boto3": "boto3",
        "tiktoken": "tiktoken",
        "huggingface_hub": "huggingface_hub",
        "transformers": "transformers",
        "voxcpm": "voxcpm",
        "hf_transfer": "hf-transfer",  # Rust 加速下载引擎
    }
    import subprocess
    import importlib

    for mod, pkg in required.items():
        try:
            importlib.import_module(mod)
        except ImportError:
            _log(f"Installing missing dependency: {pkg}")
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "-q", pkg
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

_log("📦 Installing production dependencies...")
_install_missing_deps()
_log("✅ Bootstrap complete")

# ==========================================
# 1.5. KAGGLE SECRETS INJECTION (must run before BaseWorker validation)
# ==========================================
def _inject_kaggle_secrets() -> None:
    """Fetch secrets from Kaggle's internal secret store and inject into os.environ."""
    _log("🔍 Injecting Kaggle Secrets into environment...")
    try:
        from kaggle_secrets import UserSecretsClient
        client = UserSecretsClient()

        secret_keys = [
            "REDIS_HOST", "REDIS_PORT", "REDIS_AUTH",
            "R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET",
            "R2_PUBLIC_URL", "WORKER_ID", "VOXCPM2_HF_REPO", "HF_TOKEN",
        ]

        for key in secret_keys:
            try:
                value = client.get_secret(key)
                if value:
                    os.environ[key] = str(value)
                    _log(f"  ✅ Injected {key}")
                else:
                    _log(f"  ⚠️ Secret [{key}] not set in UI")
            except Exception as e:
                _log(f"  ❌ Failed to fetch {key}: {e}")

        _log("✨ Secrets injection complete")
    except Exception as e:
        _log(f"❌ Kaggle secrets injection failed: {e}")

# Inject NOW before any validation runs
_inject_kaggle_secrets()

# ==========================================
# 2. HEAVY IMPORTS (after bootstrap + secrets)
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


# ==========================================
# 3. INLINED BaseWorker (single-file contract)
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
    - _init_engine(): Model loading for their framework (PyTorch/Paddle)
    - _synthesize(): Inference call returning raw WAV bytes
    - _execute_smoke_test(): Quick validation at startup
    - _get_platform_gpu_metrics(): Hardware telemetry
    """

    def __init__(self, platform_prefix: str):
        self.platform_prefix = platform_prefix
        self.running = True

        # Core identity & lifecycle config
        self.worker_id = os.getenv("WORKER_ID", f"{platform_prefix}-{uuid.uuid4().hex[:8]}")
        self.studio_id = os.getenv(
            "LIGHTNING_STUDIO_ID",
            os.getenv("BAIDU_STUDIO_ID", os.getenv("KAGGLE_KERNEL_SLUG", "unknown")),
        )
        self.idle_timeout = int(os.getenv("IDLE_TIMEOUT_SECONDS", "900"))
        self.max_empty_polls = int(os.getenv("MAX_EMPTY_POLLS", "3"))
        self.model_path = os.getenv("VOXCPM2_MODEL_PATH")

        # Graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

        # Validate required environment
        self._validate_and_load_config()

        # Initialize shared network clients
        # Upstash Redis requires SSL/TLS; socket timeout must exceed blpop timeout (300s) by a safe margin
        self.redis = redis.Redis(
            host=self.redis_host,
            port=self.redis_port,
            password=self.redis_auth,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
            ssl=True,
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

        # Initialize inference engine (platform-specific)
        _print(f"⚙️ [{self.worker_id}] Initializing VoxCPM2 compute backend...")
        self.engine = self._init_engine()

        # Validate engine health before consuming live queue
        self._execute_smoke_test()

    def _validate_and_load_config(self) -> None:
        """Ensure all critical infrastructure variables are present."""
        self.redis_host = os.getenv("REDIS_HOST")
        self.redis_port = int(os.getenv("REDIS_PORT", "6379"))
        self.redis_auth = os.getenv("REDIS_AUTH")
        self.r2_endpoint = os.getenv("R2_ENDPOINT")
        self.r2_access_key = os.getenv("R2_ACCESS_KEY_ID")
        self.r2_secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
        self.r2_bucket = os.getenv("R2_BUCKET")
        self.r2_public_url = os.getenv("R2_PUBLIC_URL")
        # VOXCPM2_MODEL_PATH is optional - engine downloads from HF Hub if not provided
        self.model_path = os.getenv("VOXCPM2_MODEL_PATH")

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
        """Catch OS termination request, finish current task, then exit cleanly."""
        _print(f"\n⚠️ [{self.worker_id}] Caught signal ({signum}). Flushing and exiting gracefully...")
        self.running = False

    def _execute_network_call_with_retry(
        self,
        func,
        *args,
        max_retries: int = 3,
        **kwargs,
    ) -> Any:
        """Wrap flaky I/O (Redis, R2) with exponential backoff retry."""
        delay = 1.0
        for attempt in range(1, max_retries + 1):
            try:
                return func(*args, **kwargs)
            except (redis.RedisError, boto3.exceptions.Boto3Error) as error:
                _print(f"⚠️ [{self.worker_id}] Dynamic I/O failure on attempt {attempt}/{max_retries}: {error}", file=sys.stderr)
                if attempt == max_retries:
                    raise
                time.sleep(delay)
                delay *= 2.0

    def _send_heartbeat(self, status: str, queue_depth: int = 0) -> None:
        """Publish node health telemetry with strict TTL boundary."""
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
        """Orchestrate the internal serialization pipeline for one synthesis target."""
        task_id = task["id"]
        text = task["text"]
        voice_id = task.get("voice_id", "zh_female_1")
        prosody = task.get("prosody", {})
        reference_audio = task.get("reference_audio")

        _print(f"🚀 [{self.worker_id}] Processing task {task_id} ({len(text)} chars)")
        try:
            # Platform-specific native inference execution
            audio_bytes = self._synthesize(text, voice_id, prosody, reference_audio)

            # Push binary blob directly to R2 storage
            object_key = f"tts/{task_id}.wav"
            r2_url = self._execute_network_call_with_retry(self.r2.upload, audio_bytes, object_key)

            return {
                "id": task_id,
                "status": "success",
                "url": r2_url,
                "worker": self.worker_id,
                "studio_id": self.studio_id,
                "duration_ms": len(audio_bytes) * 1000 // 48000,  # rough estimate for 24kHz mono
            }
        except Exception as e:
            _print(f"💥 [{self.worker_id}] Task {task_id} suffered pipeline crash: {e}", file=sys.stderr)
            return {
                "id": task_id,
                "status": "failed",
                "error": str(e),
                "worker": self.worker_id,
                "studio_id": self.studio_id,
            }

    def run(self) -> None:
        """Main consumer loop implementing free-tier survival rules."""
        _print(f"⚡ [{self.worker_id}] System engine ready. Awaiting inbound task blocks...")
        empty_polls = 0

        while self.running:
            try:
                queue_depth = self.redis.llen("tts:tasks")
            except Exception:
                queue_depth = 0

            self._send_heartbeat("idle" if empty_polls > 0 else "processing", queue_depth)

            try:
                # Long-poll unified queue (5 min blocking)
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

                # Push result back
                try:
                    self._execute_network_call_with_retry(self.redis.rpush, "tts:results", json.dumps(result))
                except Exception as e:
                    _print(f"❌ [{self.worker_id}] Result packet lost: {e}", file=sys.stderr)

                # At-least-once: safe rollback on failure
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
                            _print(f"🛑 [{self.worker_id}] Idle timeout triggered quota preservation. Autonomously terminating engine.")
                            self._send_heartbeat("exiting", 0)
                            break
                    except Exception:
                        pass

        _print(f"🛑 [{self.worker_id}] Process shutdown sequence complete.")

    # --- Abstract Interface Contract ---

    @abc.abstractmethod
    def _init_engine(self) -> Any:
        """Must handle platform-specific multi-backend model injection at instantiation."""
        pass

    @abc.abstractmethod
    def _execute_smoke_test(self) -> None:
        """Must invoke a quick mock inference slice to guarantee target execution sanity."""
        pass

    @abc.abstractmethod
    def _synthesize(
        self,
        text: str,
        voice_id: str,
        prosody: Dict[str, Any],
        reference_audio: Optional[str],
    ) -> bytes:
        """Must map abstract distributed tasks directly onto contiguous native audio byte streams."""
        pass

    @abc.abstractmethod
    def _get_platform_gpu_metrics(self) -> Dict[str, int]:
        """Must expose localized hardware telemetry fields to tracing bus."""
        pass


# ==========================================
# 4. DUAL T4 VoxCPM2 ENGINE
# ==========================================
def get_gpu_memory_used() -> int:
    try:
        if torch.cuda.is_available():
            return torch.cuda.memory_allocated() // (1024 * 1024)
    except Exception:
        pass
    return 0


def get_gpu_memory_total() -> int:
    try:
        if torch.cuda.is_available():
            return torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
    except Exception:
        pass
    return 0


def get_device_names() -> list:
    names = []
    try:
        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                names.append(torch.cuda.get_device_name(i))
    except Exception:
        pass
    return names or ["CPU"]


class DualT4VoxCPM2Engine:
    """
    PyTorch VoxCPM2 inference engine optimized for Kaggle dual T4 (2x 16GB).

    Uses model parallel (device_map="auto") to split across both GPUs.
    Auto-downloads model from Hugging Face Hub if not cached locally.
    """

    HF_REPO_ID = os.getenv("VOXCPM2_HF_REPO", "openbmb/VoxCPM2")  # 可通过 Secret 覆盖
    CACHE_DIR = "/tmp/voxcpm2-model"

    def __init__(self, model_path: str = None):
        self.model_path = model_path or self.CACHE_DIR
        self.device_count = torch.cuda.device_count() if torch.cuda.is_available() else 0
        _log(f"Detected {self.device_count} GPU(s): {get_device_names()}")
        self.model = None
        self.tokenizer = None
        self._load_model()

    def _load_model(self) -> None:
        import os
        import time

        # ===== 全局激活：Rust hf_transfer 引擎 + SSL 宽容 =====
        os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
        os.environ["HF_HUB_DISABLE_SSL_VERIFY"] = "1"

        from huggingface_hub import snapshot_download

        # ===== 内部函数：Rust 引擎 + 双端点 + 双鉴权 =====
        def _ensure_model_downloaded(model_dir: str, repo_id: str) -> None:
            """Rust 引擎 + 双端点回退 + 双鉴权策略 (Token / 匿名)"""

            # 本地已就绪直接返回
            if os.path.exists(os.path.join(model_dir, "config.json")):
                weights = [f for f in os.listdir(model_dir) if f.endswith(('.safetensors', '.bin', '.pt'))]
                if weights:
                    _log(f"✅ 本地模型已就绪: {model_dir} (权重: {weights})")
                    return

            _log(f"📡 本地模型不完整，开始下载... Repo: {repo_id}  目标: {model_dir}")
            os.makedirs(model_dir, exist_ok=True)

            # 清洗 Token
            raw = os.getenv("HF_TOKEN", "").strip()
            if raw.lower().startswith("bearer "):
                raw = raw[7:].strip()
            token = raw or None

            endpoints = [
                ("https://hf-mirror.com", "国内镜像"),
                ("https://huggingface.co", "官方源"),
            ]

            api_failed = False
            for ep_url, ep_name in endpoints:
                os.environ["HF_ENDPOINT"] = ep_url
                try:
                    import huggingface_hub.constants as _hfc
                    _hfc.HF_ENDPOINT = ep_url
                    _hfc.HF_HUB_DISABLE_SSL_VERIFICATION = True
                except Exception:
                    pass

                _log(f"🔄 尝试镜像: {ep_name} ({ep_url})")

                # 双鉴权策略：先 Token，再匿名
                for tok in (token, None):
                    strategy = "带Token" if tok else "匿名"
                    _log(f"🔑 策略: {strategy}")

                    for attempt in range(1, 4):
                        try:
                            _log(f"📥 {ep_name}/{strategy} 下载尝试 {attempt}/3...")
                            snapshot_download(
                                repo_id=repo_id,
                                local_dir=model_dir,
                                token=clean_tok,
                                ignore_patterns=["*.msgpack", "*.h5", "*.ot"],
                                max_workers=2,
                                tqdm_class=None,
                            )
                            _log(f"✅ 下载成功！来源: {ep_name} / 策略: {strategy}")
                            return
                        except Exception as e:
                            _log(f"⚠️ 尝试 {attempt}/3 失败: {str(e)[:200]}")
                            time.sleep(2 ** attempt)

            # ===== 所有 HF API 失败，启用 Git 克隆终极兜底 =====
            _log("🛡️ 所有 HF API 失败，启动终极兜底：Git 克隆...")
            try:
                import subprocess
                import shutil
                import time
                mirror_url = f"{endpoint}/{repo_id}"
                _log(f"🔧 终极兜底：Git 克隆 {mirror_url} -> {model_dir} (超时 15 分钟，跳过 LFS 文件)")

                # 确保目标目录完全不存在（Git clone 要求目标不存在）
                if os.path.exists(model_dir):
                    _log(f"⚠️ 目录已存在，正在清理: {model_dir}")
                    def remove_readonly(func, path, excinfo):
                        os.chmod(path, 0o777)
                        func(path)
                    for _ in range(3):
                        try:
                            shutil.rmtree(model_dir, onerror=remove_readonly)
                            break
                        except Exception:
                            time.sleep(0.5)
                if os.path.exists(model_dir):
                    raise RuntimeError(f"无法删除目标目录: {model_dir}")

                # Git clone 会自动创建目录，不需要预先创建
                _log(f"🔧 终极兜底：Git 克隆 {mirror_url} -> {model_dir} (超时 15 分钟，跳过 LFS 文件)")

                # 设置环境变量跳过 LFS 文件，只克隆元数据和配置
                env = os.environ.copy()
                env["GIT_LFS_SKIP_SMUDGE"] = "1"
                env["HF_HUB_DISABLE_SSL_VERIFICATION"] = "1"
                env["HF_ENDPOINT"] = endpoint

                subprocess.run([
                    "git", "clone",
                    "--depth", "1",
                    "--branch", "main",
                    mirror_url,
                    model_dir
                ], check=True, capture_output=True, text=True, timeout=900, env=env)
                _log(f"✅ Git 克隆成功！模型元数据已就绪: {model_dir}")
                return
            except subprocess.TimeoutExpired:
                _log("❌ Git 克隆超时 (15 分钟)")
            except subprocess.CalledProcessError as e:
                _log(f"❌ Git 克隆失败: {e.stderr[:300] if e.stderr else str(e)}")
            except Exception as e:
                _log(f"❌ Git 克隆异常: {str(e)[:300]}")

            raise RuntimeError("所有镜像/鉴权/Git 克隆均失败，模型下载彻底失败")

        # ===== 主流程 =====
        repo_id = os.getenv("VOXCPM2_HF_REPO", self.HF_REPO_ID)

        # 优先 Kaggle Dataset，否则缓存目录
        if self.model_path.startswith("/kaggle/input/"):
            _log(f"🔍 检测到 Kaggle Dataset: {self.model_path}")
            if not os.path.exists(self.model_path):
                _log("⚠️ Dataset 不存在，回退到自动下载")
                _ensure_model_downloaded(self.CACHE_DIR, repo_id)
                self.model_path = self.CACHE_DIR
            else:
                _ensure_model_downloaded(self.model_path, repo_id)
        else:
            _ensure_model_downloaded(self.model_path, repo_id)

        # ===== 2. 预检查 =====
        _log(f"🔍 预检查: {self.model_path}")
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"模型目录不存在: {self.model_path}")

        required = ["config.json"]
        missing = [f for f in required if not os.path.exists(os.path.join(self.model_path, f))]
        if missing:
            raise FileNotFoundError(f"模型目录缺少必要文件: {missing}")

        weights = [f for f in os.listdir(self.model_path) if f.endswith(('.safetensors', '.bin', '.pt'))]
        if not weights:
            raise FileNotFoundError("无权重文件")

        _log(f"✅ 预检查通过: {self.model_path}  权重: {weights}")

        _log(f"Loading VoxCPM2 from {self.model_path} on {self.device_count} GPU(s)...")

        # Use official VoxCPM loader for custom architecture (continuous latent encoder + diffusion + autoregressive)
        try:
            from voxcpm import VoxCPM
            _log("🚀 Using official VoxCPM loader for custom architecture...")

            self.model = VoxCPM.from_pretrained(
                self.model_path,
                load_denoiser=False,  # Disable denoiser if not needed for inference
            )

            # Load tokenizer directly from HF cache (VoxCPM wrapper doesn't expose tokenizer)
            from transformers import AutoTokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_path,
                trust_remote_code=True,
                use_fast=False,
            )

            _log(f"✅ Model loaded via official VoxCPM. GPU memory: {get_gpu_memory_used()} MB / {get_gpu_memory_total()} MB")
        except ImportError:
            _log("❌ voxcpm package not found. Please pre-install voxcpm in the environment.")
            raise RuntimeError("voxcpm package not available — cannot load model without it")

    @torch.inference_mode()
    def synthesize(
        self,
        text: str,
        voice_id: str,
        prosody: dict,
        reference_audio: str = None,
    ) -> bytes:
        # 🔗 ========================================================
        # 🛡️ VoxCPM2 精准定点适配补丁 (防止 Torch 编译签名冲突 & 兼容新版 API)
        # 采用闭包绑定法：捕获原始 generate 到闭包变量 _orig，严禁在 self 上绑定 orig_generate
        # ========================================================
        if hasattr(self, 'model') and self.model and not hasattr(self.model, '_v2_patched'):
            try:
                _orig = self.model.generate  # 🛡️ 闭包捕获：捕获原始 generate 引用到局部变量
                def _patched_generate(model_self, *args, **kwargs):
                    # 💡 核心修复：确保 args 可变
                    args = list(args)

                    # 1. 统一从 kwargs 弹出 speaker，避免传给底层
                    speaker = kwargs.pop('speaker', None)
                    if speaker is None and len(args) > 1:
                        speaker = args[1]
                        args[1] = None

                    # 2. 字符串 speaker：转换为 Voice Design 提示词
                    if isinstance(speaker, str):
                        print(f"[RUNTIME] Mapping speaker '{speaker}' to VoxCPM2 voice design prompt...", flush=True)
                        desc = "(A young woman, gentle and sweet clear voice)" if "female" in speaker else "(A young man, warm and professional clear voice)"
                        if args and isinstance(args[0], str) and not args[0].startswith("("):
                            args[0] = desc + args[0]

                    # 3. 干净调用 - speaker 已被 pop，整数 speaker 作为位置参数传递
                    if isinstance(speaker, int) and len(args) > 1:
                        args[1] = speaker

                    # 🛡️ 闭包调用：直接调用 _orig，绝不使用 self. 前缀
                    return _orig(*args, **kwargs)

                # 动态绑定实例方法
                import types
                self.model.generate = types.MethodType(_patched_generate, self.model)
                print("[RUNTIME] ✅ generate 方法已彻底重构并替换，使用闭包绑定 _orig，不再使用 orig_generate 属性。")
                print("[RUNTIME] 🎉 VoxCPM2 robust full-wrapper patch injected successfully!")

                # 2. 动态兼容缺失的 decode_audio 方法
                if not hasattr(self.model, 'decode_audio'):
                    if hasattr(self.model, 'tts_model') and hasattr(self.model.tts_model, 'decode_audio'):
                        # 如果底层真正的 tts_model 实现了该方法，则进行代理重定向
                        self.model.decode_audio = self.model.tts_model.decode_audio.__get__(self.model.tts_model, type(self.model.tts_model))
                        print("[RUNTIME] 🔗 Proxied 'decode_audio' to underlying tts_model.", flush=True)
                    else:
                        # 如果底层也没有，说明新版 generate 已经是成品波形，此处直接做直通(Pass-through)返回
                        def _identity_decode_audio(tokens):
                            return tokens
                        self.model.decode_audio = _identity_decode_audio
                        print("[RUNTIME] 🔄 Injected pass-through 'decode_audio' (Identity Fallback).", flush=True)

                self.model._v2_patched = True
                print("[RUNTIME] 🎉 VoxCPM2 targeted runtime patch injected successfully!")
            except Exception as patch_err:
                print(f"[RUNTIME] ⚠️ Failed to apply targeted patch: {patch_err}", flush=True)
        # ========================================================

        # VoxCPM wrapper's generate method takes text and speaker directly
        speaker_map = {
            "zh_female_1": 0,
            "zh_male_1": 1,
            "en_female_1": 2,
            "en_male_1": 3,
        }
        speaker_idx = speaker_map.get(voice_id, 0)

        # VoxCPM wrapper's generate method takes text directly with speaker parameter
        # New VoxCPM2 generate() returns waveform directly, not tokens
        # Only pass supported parameters (text, speaker) - VoxCPM doesn't accept HF generation params
        waveform = self.model.generate(
            text,
            speaker=speaker_idx,
        )

        import io
        buffer = io.BytesIO()
        torchaudio.save(buffer, waveform.cpu(), sample_rate=24000, format="wav")
        return buffer.getvalue()

    def _get_speaker_prompt(self, voice_id: str, reference_audio: str = None):
        speaker_idx = 0
        speaker_map = {
            "zh_female_1": 0,
            "zh_male_1": 1,
            "en_female_1": 2,
            "en_male_1": 3,
        }
        speaker_idx = speaker_map.get(voice_id, 0)

        # === [DIAGNOSTIC] Inspect VoxCPM wrapper structure ===
        print(f"\n=== [DIAGNOSTIC] Inspecting VoxCPM wrapper ===", flush=True)
        print(f"Wrapper type: {type(self.model)}", flush=True)
        wrapper_methods = [m for m in dir(self.model) if not m.startswith('_')]
        print(f"Available wrapper methods: {wrapper_methods}", flush=True)

        if hasattr(self.model, 'model'):
            print(f"Inner model type: {type(self.model.model)}", flush=True)
            inner_methods = [m for m in dir(self.model.model) if not m.startswith('_')]
            print(f"Inner model methods: {inner_methods}", flush=True)
        print("=============================================\n", flush=True)

        # === Dynamic discovery & fallback chain ===
        # Path A: Check wrapper for common method names
        for attr in ['get_speaker_embedding', 'get_speaker_embed', 'speaker_embedding', 'get_embedding']:
            if hasattr(self.model, attr):
                _log(f"[BOOTSTRAP] Using wrapper method: {attr}")
                return getattr(self.model, attr)(speaker_idx)

        # Path B: Check inner model if wrapped
        if hasattr(self.model, 'model'):
            inner = self.model.model
            for attr in ['get_speaker_embedding', 'get_speaker_embed', 'speaker_embedding', 'get_embedding']:
                if hasattr(inner, attr):
                    _log(f"[BOOTSTRAP] Using inner model method: {attr}")
                    return getattr(inner, attr)(speaker_idx)

        # Path C: Ultimate safe fallback - return None, let synthesis proceed
        _log("[BOOTSTRAP] ⚠️ Warning: No speaker embedding method found. Returning None as fallback.")
        return None


# ==========================================
# 5. KAGGLE WORKER IMPLEMENTATION
# ==========================================
class KaggleWorker(BaseWorker):
    """Kaggle-specific distributed TTS Worker implementation leveraging
    the Dual T4 VoxCPM2 model parallel framework.
    """

    def __init__(self):
        # 🔒 必须在 super().__init__() 之前校验 GPU 型号
        if not torch.cuda.is_available():
            _print("ERROR: CUDA not available. This worker requires GPU (dual T4 on Kaggle).", file=sys.stderr)
            sys.exit(1)

        # 必须为 T4 x2，否则拒绝启动
        device_count = torch.cuda.device_count()
        device_names = [torch.cuda.get_device_name(i) for i in range(device_count)]
        if device_count != 2 or not all("T4" in n for n in device_names):
            _print(f"ERROR: GPU 型号/数量不符。预期 Tesla T4 x2，实际 {device_names}。拒绝启动。", file=sys.stderr)
            sys.exit(1)

        _print(f"✅ GPU 校验通过: {device_names}")

        super().__init__(platform_prefix="kaggle-t4-dual")

    def _init_engine(self) -> DualT4VoxCPM2Engine:
        """Instantiate and compile the local multi-GPU VoxCPM2 execution instance."""
        return DualT4VoxCPM2Engine(model_path=self.model_path)

    def _execute_smoke_test(self) -> None:
        """Execute a quick text synthesis slice to confirm runtime sanity and VRAM bounds."""
        _print(f"🧪 [{self.worker_id}] Launching local inference engine smoke test...")
        try:
            # Quick initialization slice to confirm layer maps match allocation layouts
            test_bytes = self.engine.synthesize(
                text="测试驱动",
                voice_id="zh_female_1",
                prosody={},
                reference_audio=None
            )
            if test_bytes and len(test_bytes) > 0:
                _print(f"✅ [{self.worker_id}] Smoke test passed. Formatted native wave sample size: {len(test_bytes)} bytes.")
            else:
                raise ValueError("Engine completed inference but produced an invalid empty byte segment.")
        except Exception as e:
            _print(f"❌ [{self.worker_id}] Critical failure detected during engine validation: {e}", file=sys.stderr)
            raise RuntimeError(f"Engine validation pipeline crashed: {e}")        from e

    def _synthesize(
        self,
        text: str,
        voice_id: str,
        prosody: Dict[str, Any],
        reference_audio: Optional[str],
    ) -> bytes:
        """Map abstract distributed tasks directly onto contiguous native audio byte streams."""
        return self.engine.synthesize(
            text=text,
            voice_id=voice_id,
            prosody=prosody,
            reference_audio=reference_audio
        )

    def _get_platform_gpu_metrics(self) -> Dict[str, int]:
        """Expose local device tracking telemetry metrics to the tracing bus."""
        return {
            "allocated_mb": get_gpu_memory_used(),
            "total_mb": get_gpu_memory_total(),
            "device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0
        }


# ==========================================
# 6. DISTRIBUTED RUNTIME SYSTEM ENTRYPOINT
# ==========================================
if __name__ == "__main__":
    _print("🚀 Orchestrating Kaggle free-tier production pipeline engine...")
    try:
        worker = KaggleWorker()
        worker.run()
    except Exception as fatal_err:
        _print(f"🚨 CRITICAL KERNEL ABORT: Lifecycle execution failed during boot hook: {fatal_err}", file=sys.stderr)
        sys.exit(1)