"""Remote VoxCPM2 Port Implementation.

Real implementation of RemoteTTSPort that communicates with the remote
VoxCPM2 TTS service via HTTP (Cloudflare Tunnel → Kaggle GPU).

This implementation:
- Uses httpx.AsyncClient with connection pooling (Keep-Alive)
- Implements exponential backoff retry with tenacity
- Integrates with the existing CircuitBreaker for failure isolation
- Maps remote service responses to the RemoteTTSPort contract
- Respects configurable timeouts from environment variables
- Raises specific port exceptions for proper error handling
- Reuses circuit breaker and retry logic from RemoteVoxCPM2Client
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

import httpx
from tenacity import after_log, before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..llm.circuit_breaker import CircuitBreaker
from .port import RemoteTTSPort, TTSStatus, TTSTaskPayload, TTSTaskResult, TTSTaskStatus

logger = logging.getLogger(__name__)


# =============================================================================
# Port Exceptions
# =============================================================================


class PortError(Exception):
    """Base exception for RemoteTTSPort errors."""

    pass


class PortTimeoutError(PortError):
    """Raised when a request times out."""

    pass


class PortConnectionError(PortError):
    """Raised when connection to remote service fails."""

    pass


class PortRemoteError(PortError):
    """Raised when remote service returns an error response."""

    def __init__(self, message: str, status_code: int | None = None, response_body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class PortCircuitOpenError(PortError):
    """Raised when circuit breaker is open."""

    pass


# =============================================================================
# Configuration
# =============================================================================


@dataclass(frozen=True)
class RemoteVoxCPM2PortConfig:
    """Configuration for RemoteVoxCPM2Port.

    All values can be overridden via environment variables:
    - VOXCPM2_ENDPOINT: Remote service endpoint (required for production)
    - VOXCPM2_TIMEOUT_SEC: Total request timeout in seconds (default: 60)
    - VOXCPM2_MAX_RETRIES: Max retry attempts (default: 3)
    - VOXCPM2_CONNECTION_POOL_SIZE: HTTP connection pool size (default: 10)
    - VOXCPM2_CONNECT_TIMEOUT: Connection timeout in seconds (default: 5.0)
    - VOXCPM2_READ_TIMEOUT: Read timeout in seconds (default: 120.0)
    - VOXCPM2_WRITE_TIMEOUT: Write timeout in seconds (default: 30.0)
    - VOXCPM2_POOL_TIMEOUT: Pool timeout in seconds (default: 10.0)
    - VOXCPM2_CB_THRESHOLD: Circuit breaker failure threshold (default: 3)
    - VOXCPM2_CB_TIMEOUT: Circuit breaker recovery timeout in seconds (default: 120.0)
    - VOXCPM2_RETRY_MIN_WAIT: Min exponential backoff wait in seconds (default: 2.0)
    - VOXCPM2_RETRY_MAX_WAIT: Max exponential backoff wait in seconds (default: 30.0)
    - AUDIO_OUTPUT_DIR: Output directory for downloaded audio (default: ./output/remote_tts)
    """

    # Endpoint configuration (REQUIRED for production)
    endpoint: str = os.getenv("VOXCPM2_ENDPOINT", "https://voxcpm2.guwj609.ccwu.cc")

    # Timeout configuration (seconds)
    timeout_sec: float = float(os.getenv("VOXCPM2_TIMEOUT_SEC", "60"))
    connect_timeout: float = float(os.getenv("VOXCPM2_CONNECT_TIMEOUT", "5.0"))
    read_timeout: float = float(os.getenv("VOXCPM2_READ_TIMEOUT", "120.0"))
    write_timeout: float = float(os.getenv("VOXCPM2_WRITE_TIMEOUT", "30.0"))
    pool_timeout: float = float(os.getenv("VOXCPM2_POOL_TIMEOUT", "10.0"))

    # Retry configuration
    max_retries: int = int(os.getenv("VOXCPM2_MAX_RETRIES", "3"))
    retry_min_wait: float = float(os.getenv("VOXCPM2_RETRY_MIN_WAIT", "2.0"))
    retry_max_wait: float = float(os.getenv("VOXCPM2_RETRY_MAX_WAIT", "30.0"))

    # Connection pool configuration
    connection_pool_size: int = int(os.getenv("VOXCPM2_CONNECTION_POOL_SIZE", "10"))
    max_keepalive_connections: int = int(os.getenv("VOXCPM2_MAX_KEEPALIVE", "5"))

    # Circuit breaker configuration
    cb_threshold: int = int(os.getenv("VOXCPM2_CB_THRESHOLD", "3"))
    cb_timeout: float = float(os.getenv("VOXCPM2_CB_TIMEOUT", "120.0"))

    # Output directory for downloaded audio files
    output_dir: Path = Path(os.getenv("AUDIO_OUTPUT_DIR", "./output/remote_tts"))

    # API paths (relative to endpoint base)
    synthesize_path: str = "/synthesize"
    status_path: str = "/status"
    result_path: str = "/result"
    cancel_path: str = "/cancel"
    health_path: str = "/health"

    def __post_init__(self):
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Normalize endpoint (remove trailing slash)
        endpoint = self.endpoint.rstrip("/")
        object.__setattr__(self, "endpoint", endpoint)

        # Build full URLs
        base = endpoint + "/"
        object.__setattr__(self, "synthesize_url", urljoin(base, self.synthesize_path.lstrip("/")))
        object.__setattr__(self, "status_url", urljoin(base, self.status_path.lstrip("/")))
        object.__setattr__(self, "result_url", urljoin(base, self.result_path.lstrip("/")))
        object.__setattr__(self, "cancel_url", urljoin(base, self.cancel_path.lstrip("/")))
        object.__setattr__(self, "health_url", urljoin(base, self.health_path.lstrip("/")))


# =============================================================================
# Response Models (Remote Service Contract)
# =============================================================================


@dataclass(frozen=True)
class SubmitResponse:
    """Response from POST /synthesize."""

    task_id: str
    status: str  # "PENDING" | "RUNNING" | "DONE" | "FAILED"
    message: str | None = None


@dataclass(frozen=True)
class StatusResponse:
    """Response from GET /status/{task_id}."""

    task_id: str
    status: str  # "PENDING" | "RUNNING" | "DONE" | "FAILED"
    progress: float | None = None  # 0.0-1.0
    error_message: str | None = None
    dnsmos_score: float | None = None


@dataclass(frozen=True)
class ResultResponse:
    """Response from GET /result/{task_id}."""

    task_id: str
    status: str  # "DONE" | "FAILED"
    audio_url: str | None = None  # Presigned URL or R2 object key
    audio_path: str | None = None  # Local path if already downloaded
    duration_ms: int | None = None
    error_message: str | None = None
    dnsmos_score: float | None = None
    asr_wer: float | None = None
    speaker_similarity: float | None = None
    started_at: str | None = None
    completed_at: str | None = None


@dataclass(frozen=True)
class CancelResponse:
    """Response from POST /cancel/{task_id}."""

    task_id: str
    cancelled: bool
    message: str | None = None


@dataclass(frozen=True)
class HealthResponse:
    """Response from GET /health."""

    healthy: bool
    latency_ms: float | None = None
    pending_count: int = 0
    running_count: int = 0
    version: str | None = None


# =============================================================================
# Remote VoxCPM2 Port Implementation
# =============================================================================


class RemoteVoxCPM2Port(RemoteTTSPort):
    """Real implementation of RemoteTTSPort for remote VoxCPM2 TTS service.

    Communicates with remote VoxCPM2 service via HTTP over Cloudflare Tunnel.
    Implements the RemoteTTSPort contract with proper error handling,
    retry logic, circuit breaker integration, and connection pooling.

    Usage:
        config = RemoteVoxCPM2PortConfig(
            endpoint="https://voxcpm2.guwj609.ccwu.cc",
            timeout_sec=60.0,
            max_retries=3,
            connection_pool_size=10,
        )
        port = RemoteVoxCPM2Port(config)
        await port.submit("task-123", payload)
        status = await port.get_status("task-123")
        result = await port.get_result("task-123")
        await port.close()
    """

    def __init__(self, config: RemoteVoxCPM2PortConfig | None = None):
        """Initialize the remote VoxCPM2 port.

        Args:
            config: Configuration object. If None, uses environment variables.
        """
        self._config = config or RemoteVoxCPM2PortConfig()
        self._client: httpx.AsyncClient | None = None
        self._circuit_breaker = CircuitBreaker(
            provider_name="voxcpm2_remote",
            failure_threshold=self._config.cb_threshold,
            recovery_timeout_s=self._config.cb_timeout,
            half_open_max_calls=1,
        )
        self._closed = False
        self._lock = asyncio.Lock()

        logger.info(
            f"Initialized RemoteVoxCPM2Port: endpoint={self._config.endpoint}, "
            f"timeout={self._config.timeout_sec}s, pool_size={self._config.connection_pool_size}, "
            f"max_retries={self._config.max_retries}"
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client with connection pooling."""
        async with self._lock:
            if self._client is None or self._client.is_closed:
                timeout = httpx.Timeout(
                    connect=self._config.connect_timeout,
                    read=self._config.read_timeout,
                    write=self._config.write_timeout,
                    pool=self._config.pool_timeout,
                )
                limits = httpx.Limits(
                    max_connections=self._config.connection_pool_size,
                    max_keepalive_connections=self._config.max_keepalive_connections,
                )
                self._client = httpx.AsyncClient(
                    timeout=timeout,
                    limits=limits,
                    follow_redirects=True,
                )
                logger.debug(
                    f"Created HTTP client: pool_size={self._config.connection_pool_size}, "
                    f"keepalive={self._config.max_keepalive_connections}, "
                    f"timeouts=connect={self._config.connect_timeout}, "
                    f"read={self._config.read_timeout}, write={self._config.write_timeout}"
                )
            return self._client

    def _check_circuit_breaker(self) -> None:
        """Check circuit breaker state, raise if open."""
        if not self._circuit_breaker.can_proceed():
            status = self._circuit_breaker.get_status()
            raise PortCircuitOpenError(
                f"Circuit breaker OPEN for voxcpm2_remote "
                f"(failures: {status['failure_count']}/{self._config.cb_threshold}, "
                f"recovery in {status['seconds_since_last_failure']:.0f}s)"
            )

    def _record_success(self) -> None:
        """Record successful call for circuit breaker."""
        self._circuit_breaker.record_success()

    def _record_failure(self) -> None:
        """Record failed call for circuit breaker."""
        self._circuit_breaker.record_failure()

    def _map_remote_status(self, remote_status: str) -> TTSStatus:
        """Map remote service status to TTSStatus enum."""
        status_map = {
            "PENDING": TTSStatus.PENDING,
            "RUNNING": TTSStatus.RUNNING,
            "DONE": TTSStatus.DONE,
            "COMPLETED": TTSStatus.DONE,
            "SUCCESS": TTSStatus.DONE,
            "FAILED": TTSStatus.FAILED,
            "ERROR": TTSStatus.FAILED,
        }
        return status_map.get(remote_status.upper(), TTSStatus.PENDING)

    async def _download_audio(self, audio_url: str, task_id: str) -> Path:
        """Download audio file from remote URL to local storage.

        Args:
            audio_url: URL to download audio from (presigned URL or R2 object key)
            task_id: Task ID for filename

        Returns:
            Local file path of downloaded audio
        """
        client = await self._get_client()
        local_path = self._config.output_dir / f"{task_id}.wav"

        # Download with streaming to handle large files
        async with client.stream("GET", audio_url, timeout=self._config.read_timeout) as response:
            response.raise_for_status()
            with open(local_path, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    f.write(chunk)

        # Verify file exists and has content
        if not local_path.exists() or local_path.stat().st_size == 0:
            raise PortRemoteError(f"Downloaded audio file is empty: {local_path}", response_body=f"URL: {audio_url}")

        logger.debug(f"Downloaded audio for task {task_id}: {local_path} ({local_path.stat().st_size} bytes)")
        return local_path

    @retry(
        retry=retry_if_exception_type(
            (
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.NetworkError,
                PortTimeoutError,
                PortConnectionError,
            )
        ),
        wait=wait_exponential(multiplier=1, min=2.0, max=30.0),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        after=after_log(logger, logging.INFO),
        reraise=True,
    )
    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Make HTTP request with retry logic and circuit breaker.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL to request
            **kwargs: Additional arguments passed to client.request()

        Returns:
            HTTP response

        Raises:
            PortTimeoutError: On timeout
            PortConnectionError: On connection error
            PortRemoteError: On HTTP error response
            PortCircuitOpenError: If circuit breaker is open
        """
        self._check_circuit_breaker()

        client = await self._get_client()
        start_time = time.time()

        try:
            response = await client.request(method, url, **kwargs)
            elapsed_ms = (time.time() - start_time) * 1000

            if response.is_success:
                self._record_success()
                logger.debug(f"{method} {url} -> {response.status_code} ({elapsed_ms:.0f}ms)")
                return response

            # Handle HTTP errors
            self._record_failure()
            error_body = ""
            try:
                error_body = response.text
            except Exception:
                pass

            logger.warning(f"{method} {url} -> {response.status_code} ({elapsed_ms:.0f}ms): {error_body[:200]}")

            if response.status_code == 404:
                raise PortRemoteError(f"Resource not found: {url}", status_code=404, response_body=error_body)
            elif response.status_code >= 500:
                raise PortRemoteError(
                    f"Remote service error: {response.status_code}",
                    status_code=response.status_code,
                    response_body=error_body,
                )
            else:
                raise PortRemoteError(
                    f"Request failed: {response.status_code}",
                    status_code=response.status_code,
                    response_body=error_body,
                )

        except httpx.TimeoutException as e:
            self._record_failure()
            elapsed_ms = (time.time() - start_time) * 1000
            logger.warning(f"{method} {url} timeout after {elapsed_ms:.0f}ms: {e}")
            raise PortTimeoutError(f"Request timeout: {e}") from e

        except httpx.ConnectError as e:
            self._record_failure()
            logger.warning(f"{method} {url} connection error: {e}")
            raise PortConnectionError(f"Connection failed: {e}") from e

        except httpx.NetworkError as e:
            self._record_failure()
            logger.warning(f"{method} {url} network error: {e}")
            raise PortConnectionError(f"Network error: {e}") from e

        except PortRemoteError:
            # Already recorded failure, re-raise
            raise

        except Exception as e:
            self._record_failure()
            logger.error(f"{method} {url} unexpected error: {e}", exc_info=True)
            raise PortRemoteError(f"Unexpected error: {e}") from e

    # =========================================================================
    # RemoteTTSPort Contract Implementation
    # =========================================================================

    async def submit(self, task_id: str, payload: TTSTaskPayload) -> bool:
        """Submit a TTS synthesis task to the remote service.

        Args:
            task_id: Unique task identifier (caller-generated UUID recommended).
            payload: Complete synthesis specification.

        Returns:
            True if task was accepted for scheduling.
            False if task_id already exists (idempotent rejection).

        Raises:
            ValueError: If payload validation fails.
            PortTimeoutError: If request times out.
            PortConnectionError: If connection fails.
            PortRemoteError: If remote service returns error.
            PortCircuitOpenError: If circuit breaker is open.
        """
        if not task_id or not task_id.strip():
            raise ValueError("task_id must be non-empty")

        if not payload.text or not payload.text.strip():
            raise ValueError("text must be non-empty")

        # Validate voice anchor
        voice_anchor = payload.voice_anchor
        if not voice_anchor or not voice_anchor.voice_id:
            raise ValueError("voice_anchor.voice_id must be non-empty")

        # Build request payload for remote service
        request_data = {
            "task_id": task_id,
            "text": payload.text,
            "voice_id": voice_anchor.voice_id,
            "speaker_name": voice_anchor.speaker_name,
            "language": voice_anchor.language,
            "reference_audio_path": voice_anchor.reference_audio_path,
        }

        # Add prosody if provided
        if payload.prosody:
            request_data["prosody"] = {
                "rate": payload.prosody.rate,
                "pitch": payload.prosody.pitch,
                "volume": payload.prosody.volume,
                "emotion": payload.prosody.emotion,
            }

        # Add metadata if provided
        if payload.metadata:
            request_data["metadata"] = payload.metadata

        logger.info(f"Submitting TTS task {task_id} to remote VoxCPM2 (voice={voice_anchor.voice_id})")

        try:
            response = await self._request_with_retry(
                "POST",
                self._config.synthesize_url,
                json=request_data,
            )

            submit_response = SubmitResponse(**response.json())

            if submit_response.status.upper() in ("DONE", "COMPLETED", "SUCCESS", "FAILED", "ERROR"):
                # Task completed synchronously (unlikely but handle it)
                logger.info(f"Task {task_id} completed synchronously: {submit_response.status}")

            logger.info(f"Task {task_id} submitted successfully: {submit_response.status}")
            return True

        except PortRemoteError as e:
            if e.status_code == 409:  # Conflict - task already exists
                logger.warning(f"Task {task_id} already exists (idempotent rejection)")
                return False
            raise

    async def get_status(self, task_id: str) -> TTSTaskStatus:
        """Poll for task status from remote service.

        Non-blocking status check. Returns immediately with current state.

        Args:
            task_id: Task identifier returned from submit().

        Returns:
            TTSTaskStatus with current state. If task_id unknown,
            returns status=PENDING with error_message set.
        """
        try:
            response = await self._request_with_retry(
                "GET",
                f"{self._config.status_url}/{task_id}",
            )

            status_response = StatusResponse(**response.json())

            return TTSTaskStatus(
                task_id=status_response.task_id,
                status=self._map_remote_status(status_response.status),
                progress=status_response.progress,
                error_message=status_response.error_message,
                dnsmos_score=status_response.dnsmos_score,
            )

        except PortRemoteError as e:
            if e.status_code == 404:
                return TTSTaskStatus(
                    task_id=task_id,
                    status=TTSStatus.PENDING,
                    error_message=f"Task {task_id} not found",
                )
            raise

    async def get_result(self, task_id: str) -> TTSTaskResult:
        """Retrieve full task result from remote service.

        Only valid when status is DONE or FAILED.

        Args:
            task_id: Task identifier.

        Returns:
            TTSTaskResult with audio_path and metadata.

        Raises:
            KeyError: If task_id not found or status not in {DONE, FAILED}.
            PortTimeoutError: If request times out.
            PortConnectionError: If connection fails.
            PortRemoteError: If remote service returns error.
        """
        response = await self._request_with_retry(
            "GET",
            f"{self._config.result_url}/{task_id}",
        )

        result_response = ResultResponse(**response.json())

        if result_response.status.upper() not in ("DONE", "COMPLETED", "SUCCESS", "FAILED", "ERROR"):
            raise KeyError(f"Task {task_id} not yet terminal (status: {result_response.status})")

        # Download audio file if available
        audio_path = None
        if result_response.audio_url and result_response.status.upper() in ("DONE", "COMPLETED", "SUCCESS"):
            try:
                downloaded_path = await self._download_audio(result_response.audio_url, task_id)
                audio_path = str(downloaded_path)
            except Exception as e:
                logger.warning(f"Failed to download audio for task {task_id}: {e}")
                # Don't fail the result, just log the warning
                audio_path = None

        return TTSTaskResult(
            task_id=result_response.task_id,
            status=self._map_remote_status(result_response.status),
            audio_path=audio_path,
            duration_ms=result_response.duration_ms,
            error_message=result_response.error_message,
            dnsmos_score=result_response.dnsmos_score,
            asr_wer=result_response.asr_wer,
            speaker_similarity=result_response.speaker_similarity,
            started_at=result_response.started_at,
            completed_at=result_response.completed_at,
        )

    async def cancel(self, task_id: str) -> bool:
        """Request cancellation of a pending/running task.

        Best-effort; success depends on scheduling layer implementation.

        Args:
            task_id: Task identifier.

        Returns:
            True if cancellation was requested (may still complete).
            False if task not found or already terminal.
        """
        try:
            response = await self._request_with_retry(
                "POST",
                f"{self._config.cancel_url}/{task_id}",
            )

            cancel_response = CancelResponse(**response.json())
            return cancel_response.cancelled

        except PortRemoteError as e:
            if e.status_code == 404:
                return False
            raise

    async def health_check(self) -> dict[str, Any]:
        """Check remote service health.

        Returns:
            Dict with keys: 'healthy' (bool), 'latency_ms' (float),
            'pending_count' (int), 'running_count' (int).
        """
        start_time = time.time()

        try:
            response = await self._request_with_retry(
                "GET",
                self._config.health_url,
            )

            latency_ms = (time.time() - start_time) * 1000
            health_response = HealthResponse(**response.json())

            return {
                "healthy": health_response.healthy,
                "latency_ms": latency_ms,
                "pending_count": health_response.pending_count,
                "running_count": health_response.running_count,
                "version": health_response.version,
            }

        except PortRemoteError:
            # Service might be unhealthy
            latency_ms = (time.time() - start_time) * 1000
            return {
                "healthy": False,
                "latency_ms": latency_ms,
                "pending_count": 0,
                "running_count": 0,
                "error": "health_check_failed",
            }
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.warning(f"Health check failed: {e}")
            return {
                "healthy": False,
                "latency_ms": latency_ms,
                "pending_count": 0,
                "running_count": 0,
                "error": str(e),
            }

    async def close(self) -> None:
        """Release resources (connections, pools, etc.)."""
        async with self._lock:
            if self._client is not None and not self._client.is_closed:
                await self._client.aclose()
                self._client = None
                logger.debug("Closed HTTP client connection pool")
            self._closed = True

    # =========================================================================
    # Convenience Properties
    # =========================================================================

    @property
    def config(self) -> RemoteVoxCPM2PortConfig:
        """Get the port configuration."""
        return self._config

    @property
    def circuit_breaker_status(self) -> dict[str, Any]:
        """Get current circuit breaker status."""
        return self._circuit_breaker.get_status()

    @property
    def is_closed(self) -> bool:
        """Check if port is closed."""
        return self._closed


# =============================================================================
# Factory Function
# =============================================================================


def create_remote_voxcpm2_port(config: RemoteVoxCPM2PortConfig | None = None) -> RemoteVoxCPM2Port:
    """Create a RemoteVoxCPM2Port instance.

    Args:
        config: Optional configuration. If None, uses environment variables.

    Returns:
        Configured RemoteVoxCPM2Port instance.
    """
    return RemoteVoxCPM2Port(config)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Exceptions
    "PortError",
    "PortTimeoutError",
    "PortConnectionError",
    "PortRemoteError",
    "PortCircuitOpenError",
    # Configuration
    "RemoteVoxCPM2PortConfig",
    # Port Implementation
    "RemoteVoxCPM2Port",
    "create_remote_voxcpm2_port",
    # Response Models (for testing/inspection)
    "SubmitResponse",
    "StatusResponse",
    "ResultResponse",
    "CancelResponse",
    "HealthResponse",
]
