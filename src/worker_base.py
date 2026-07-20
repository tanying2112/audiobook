"""
Base Worker for Multi-Cloud VoxCPM2 TTS.

Abstract base class implementing the shared distributed lifecycle:
- Redis queue consumption with exponential backoff retry
- Cloudflare R2 upload with retry semantics
- Graceful SIGTERM/SIGINT shutdown handling
- 15-min idle auto-exit for quota preservation
- Heartbeat telemetry with TTL
- At-least-once delivery via re-queue on failure

Platform-specific workers (Kaggle, Lightning, Baidu, Modal) inherit and implement:
- _init_engine(): Model loading for their framework (PyTorch/Paddle)
- _synthesize(): Inference call returning raw WAV bytes
- _execute_smoke_test(): Quick validation at startup
- _get_platform_gpu_metrics(): Hardware telemetry
"""

import abc
import json
import os
import signal
import sys
import time
import uuid
from typing import Any, Dict, Optional

try:
    import boto3
    import redis
except ImportError:
    # 这一步是为了防止本地开发环境缺失依赖导致无法运行 modal 指令
    # 我们将其设为 None，只要你在本地不主动调用这些库的功能，它就不会报错
    boto3 = None
    redis = None
    print("⚠️  检测到本地环境缺少 boto3/redis，这不影响 Modal 云端部署。")


class R2Uploader:
    """Upload audio bytes directly to Cloudflare R2 (S3-compatible)."""

    def __init__(
        self,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        public_url_base: Optional[str] = None,
        verify_ssl: bool = False,
    ):
        self.bucket = bucket
        self.public_url_base = public_url_base or f"https://{bucket}.r2.cloudflarestorage.com"

        # boto3's verify parameter accepts: True/False (bool) or path to CA bundle (str)
        # It does NOT accept an SSLContext object. For custom R2 domains with SSL issues,
        # we simply disable verification by passing False.
        verify = verify_ssl

        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
            verify=verify,
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

    Subclasses must implement the four abstract methods for their
    specific compute framework (PyTorch, PaddlePaddle, etc.).
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

        # Graceful shutdown signal handlers
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
            socket_timeout=600,  # 10 min > 5 min blpop
            socket_connect_timeout=10,
            ssl=True,
        )
        self.r2 = R2Uploader(
            self.r2_endpoint,
            self.r2_access_key,
            self.r2_secret_key,
            self.r2_bucket,
            self.r2_public_url,
            verify_ssl=False,  # Disable SSL verification for R2 custom domains
        )
        self.heartbeat_key = f"worker:heartbeat:{self.worker_id}"

        # Initialize inference engine (platform-specific)
        print(f"⚙️ [{self.worker_id}] Initializing VoxCPM2 compute backend...")
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

        required = {
            "REDIS_HOST": self.redis_host,
            "REDIS_AUTH": self.redis_auth,
            "R2_ENDPOINT": self.r2_endpoint,
            "R2_ACCESS_KEY_ID": self.r2_access_key,
            "R2_SECRET_ACCESS_KEY": self.r2_secret_key,
            "R2_BUCKET": self.r2_bucket,
            "VOXCPM2_MODEL_PATH": self.model_path,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Fatal initialization error. Missing env vars: {missing}")

    def _handle_shutdown(self, signum: int, frame: Any) -> None:
        """Catch OS termination request, finish current task, then exit cleanly."""
        print(
            f"\n⚠️ [{self.worker_id}] Caught termination signal ({signum}). Flushing current transaction and exiting gracefully..."
        )
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
                print(
                    f"⚠️ [{self.worker_id}] Dynamic I/O failure on attempt {attempt}/{max_retries}: {error}",
                    file=sys.stderr,
                )
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
            print(f"❌ [{self.worker_id}] Heartbeat publish dropped: {e}", file=sys.stderr)

    def _process_single_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Orchestrate the internal serialization pipeline for one synthesis target."""
        task_id = task["id"]
        text = task["text"]
        voice_id = task.get("voice_id", "zh_female_1")
        prosody = task.get("prosody", {})
        reference_audio = task.get("reference_audio")

        print(f"🚀 [{self.worker_id}] Processing task {task_id} ({len(text)} chars)")
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
            print(f"💥 [{self.worker_id}] Task {task_id} suffered pipeline hardware crash: {e}", file=sys.stderr)
            return {
                "id": task_id,
                "status": "failed",
                "error": str(e),
                "worker": self.worker_id,
                "studio_id": self.studio_id,
            }

    def run(self) -> None:
        """Main consumer loop implementing free-tier survival rules."""
        print(f"⚡ [{self.worker_id}] System engine ready. Awaiting inbound task blocks...")
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
                print(f"🔌 [{self.worker_id}] Connection severed during blocking poll: {e}", file=sys.stderr)
                time.sleep(5)
                continue

            if task_data:
                empty_polls = 0
                _, payload = task_data
                try:
                    task = json.loads(payload)
                except json.JSONDecodeError:
                    print(f"🚨 [{self.worker_id}] Discarding corrupted payload.", file=sys.stderr)
                    continue

                self._send_heartbeat("processing", queue_depth)
                result = self._process_single_task(task)

                # Push result back
                try:
                    self._execute_network_call_with_retry(self.redis.rpush, "tts:results", json.dumps(result))
                except Exception as e:
                    print(f"❌ [{self.worker_id}] Result packet lost: {e}", file=sys.stderr)

                # At-least-once: safe rollback on failure
                if result["status"] == "failed":
                    try:
                        self.redis.rpush("tts:tasks", payload)
                        print(f"🔄 [{self.worker_id}] Task {task['id']} safely re-queued.")
                    except Exception as e:
                        print(f"🚨 [{self.worker_id}] Critical failure. Task rollback lost: {e}", file=sys.stderr)
            else:
                if not self.running:
                    break
                empty_polls += 1
                print(f"💤 [{self.worker_id}] Queue empty ({empty_polls}/{self.max_empty_polls})")

                if empty_polls >= self.max_empty_polls:
                    try:
                        if self.redis.llen("tts:tasks") == 0:
                            print(
                                f"🛑 [{self.worker_id}] Idle timeout triggered quota preservation. Autonomously terminating engine."
                            )
                            self._send_heartbeat("exiting", 0)
                            break
                    except Exception:
                        pass

        print(f"🛑 [{self.worker_id}] Process shutdown sequence complete.")

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
        """Must map local model tensor generation to contiguous native audio byte streams."""
        pass

    @abc.abstractmethod
    def _get_platform_gpu_metrics(self) -> Dict[str, int]:
        """Must expose localized hardware telemetry fields to tracing bus."""
        pass
