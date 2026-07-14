"""Remote VoxCPM2 TTS Client.

HTTP client for remote VoxCPM2 TTS service with retry logic, circuit breaker,
and structured logging. Designed for cloud/hybrid hardware profiles.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from ..llm.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


# Default remote VoxCPM2 endpoint
DEFAULT_VOXCPM2_ENDPOINT = "https://voxcpm2.guwj609.ccwu.cc/generate"


@dataclass
class RemoteVoxCPM2Config:
    """Configuration for Remote VoxCPM2 client."""

    endpoint: str = DEFAULT_VOXCPM2_ENDPOINT
    connect_timeout: float = 5.0
    read_timeout: float = 120.0
    write_timeout: float = 30.0
    pool_timeout: float = 10.0
    max_retries: int = 3
    retry_min_wait: float = 2.0
    retry_max_wait: float = 30.0
    circuit_breaker_threshold: int = 3
    circuit_breaker_timeout: float = 120.0

    @classmethod
    def from_env(cls) -> "RemoteVoxCPM2Config":
        """Create config from environment variables."""
        return cls(
            endpoint=os.getenv("VOICEPM2_REMOTE_ENDPOINT", DEFAULT_VOXCPM2_ENDPOINT),
            connect_timeout=float(os.getenv("VOICEPM2_CONNECT_TIMEOUT", "5.0")),
            read_timeout=float(os.getenv("VOICEPM2_READ_TIMEOUT", "120.0")),
            write_timeout=float(os.getenv("VOICEPM2_WRITE_TIMEOUT", "30.0")),
            pool_timeout=float(os.getenv("VOICEPM2_POOL_TIMEOUT", "10.0")),
            max_retries=int(os.getenv("VOICEPM2_MAX_RETRIES", "3")),
            retry_min_wait=float(os.getenv("VOICEPM2_RETRY_MIN_WAIT", "2.0")),
            retry_max_wait=float(os.getenv("VOICEPM2_RETRY_MAX_WAIT", "30.0")),
            circuit_breaker_threshold=int(os.getenv("VOICEPM2_CB_THRESHOLD", "3")),
            circuit_breaker_timeout=float(os.getenv("VOICEPM2_CB_TIMEOUT", "120.0")),
        )


class RemoteVoxCPM2Client:
    """Async HTTP client for remote VoxCPM2 TTS service.

    Features:
    - Configurable timeouts (connect, read, write, pool)
    - Exponential backoff retry with tenacity
    - Circuit breaker for failure isolation
    - Structured logging with standard logging module
    - Proper resource cleanup via close()
    """

    def __init__(
        self,
        config: Optional[RemoteVoxCPM2Config] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        """Initialize remote VoxCPM2 client.

        Args:
            config: Client configuration. If None, uses from_env().
            circuit_breaker: Optional external circuit breaker. If None, creates internal one.
        """
        self.config = config or RemoteVoxCPM2Config.from_env()
        self._circuit_breaker = circuit_breaker or CircuitBreaker(
            provider_name="voxcpm2_remote",
            failure_threshold=self.config.circuit_breaker_threshold,
            recovery_timeout_s=self.config.circuit_breaker_timeout,
        )
        self._client: Optional[httpx.AsyncClient] = None
        self._closed = False

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client with configured timeouts."""
        if self._closed:
            raise RuntimeError("Client is closed, cannot create new connection")
        if self._client is None or self._client.is_closed:
            timeout = httpx.Timeout(
                connect=self.config.connect_timeout,
                read=self.config.read_timeout,
                write=self.config.write_timeout,
                pool=self.config.pool_timeout,
            )
            self._client = httpx.AsyncClient(timeout=timeout)
        return self._client

    def _check_circuit_breaker(self) -> bool:
        """Check if circuit breaker allows the request."""
        if not self._circuit_breaker.can_proceed():
            logger.warning(
                "Circuit breaker OPEN for voxcpm2_remote, rejecting request",
                extra={"circuit_state": self._circuit_breaker.state},
            )
            return False
        return True

    def _is_retryable_error(exc: BaseException) -> bool:
        """Check if an exception should trigger a retry.

        Retries on: timeout, connection error, 5xx server errors
        Fails fast on: 4xx client errors
        """
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return 500 <= exc.response.status_code < 600
        return False

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception(_is_retryable_error),
        reraise=True,
    )
    async def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> httpx.Response:
        """Execute HTTP request with retry logic.

        Retries on: timeout, connection error, 5xx server errors
        Fails fast on: 4xx client errors
        """
        client = self._get_client()
        response = await client.request(method, url, json=json, headers=headers)
        # Raise for 5xx errors to trigger retry, 4xx fails fast
        if 500 <= response.status_code < 600:
            response.raise_for_status()
        # For 4xx, raise without retry (handled by tenacity's retry_if_exception_type)
        elif 400 <= response.status_code < 500:
            response.raise_for_status()
        return response

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        prosody: Optional[dict] = None,
        reference_audio: Optional[str] = None,
    ) -> bytes:
        """Synthesize speech using remote VoxCPM2 service.

        Args:
            text: Text to synthesize.
            voice_id: Voice identifier (e.g., "zh_female_1", "en_male_1").
            prosody: Optional prosody controls (rate, pitch, volume).
            reference_audio: Optional path to reference audio for voice cloning.

        Returns:
            Audio data as bytes (WAV format).

        Raises:
            httpx.TimeoutException: Request timeout.
            httpx.ConnectError: Connection error.
            httpx.HTTPStatusError: Non-2xx response (after retries for 5xx).
            RuntimeError: Circuit breaker open or client closed.
        """
        if self._closed:
            raise RuntimeError("Client is closed, cannot synthesize")

        if not self._check_circuit_breaker():
            raise RuntimeError("Circuit breaker open for voxcpm2_remote")

        # Prepare request payload
        payload = {
            "text": text,
            "voice_id": voice_id,
        }
        if prosody:
            payload["prosody"] = prosody
        if reference_audio:
            payload["reference_audio"] = reference_audio

        headers = {"Content-Type": "application/json", "Accept": "audio/wav"}

        try:
            logger.info(
                "Synthesizing via remote VoxCPM2",
                extra={
                    "voice_id": voice_id,
                    "text_length": len(text),
                    "has_prosody": prosody is not None,
                    "has_reference_audio": reference_audio is not None,
                },
            )

            response = await self._request_with_retry(
                "POST",
                self.config.endpoint,
                json=payload,
                headers=headers,
            )

            # Success - record in circuit breaker
            self._circuit_breaker.record_success()

            audio_data = response.content
            logger.info(
                "Remote VoxCPM2 synthesis completed",
                extra={
                    "voice_id": voice_id,
                    "audio_bytes": len(audio_data),
                    "status_code": response.status_code,
                },
            )
            return audio_data

        except httpx.HTTPStatusError as e:
            # Record failure for 4xx (client errors) and 5xx (server errors after retries)
            self._circuit_breaker.record_failure()
            logger.error(
                "Remote VoxCPM2 synthesis failed with HTTP error",
                extra={
                    "voice_id": voice_id,
                    "status_code": e.response.status_code,
                    "error": str(e),
                },
            )
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            # Record failure for timeout/connection errors
            self._circuit_breaker.record_failure()
            logger.error(
                "Remote VoxCPM2 synthesis failed with network error",
                extra={"voice_id": voice_id, "error_type": type(e).__name__, "error": str(e)},
            )
            raise
        except Exception as e:
            # Record failure for unexpected errors
            self._circuit_breaker.record_failure()
            logger.exception(
                "Remote VoxCPM2 synthesis failed with unexpected error",
                extra={"voice_id": voice_id, "error_type": type(e).__name__},
            )
            raise

    async def synthesize_to_file(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        prosody: Optional[dict] = None,
        reference_audio: Optional[str] = None,
    ) -> Path:
        """Synthesize speech and save to file.

        Args:
            text: Text to synthesize.
            voice_id: Voice identifier.
            output_path: Output file path.
            prosody: Optional prosody controls.
            reference_audio: Optional reference audio path.

        Returns:
            Path to the saved audio file.
        """
        audio_data = await self.synthesize(text, voice_id, prosody, reference_audio)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_data)

        logger.info(
            "Saved remote VoxCPM2 audio to file",
            extra={"output_path": str(output_path), "size_bytes": len(audio_data)},
        )
        return output_path

    def get_circuit_breaker_status(self) -> dict:
        """Get current circuit breaker status."""
        return self._circuit_breaker.get_status()

    def reset_circuit_breaker(self) -> None:
        """Manually reset circuit breaker to closed state."""
        self._circuit_breaker.reset()
        logger.info("Circuit breaker manually reset for voxcpm2_remote")

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._closed = True
        logger.info("Remote VoxCPM2 client closed")

    async def __aenter__(self) -> "RemoteVoxCPM2Client":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()


async def create_remote_voxcpm2_client(
    config: Optional[RemoteVoxCPM2Config] = None,
) -> RemoteVoxCPM2Client:
    """Factory function to create and initialize remote VoxCPM2 client.

    Args:
        config: Optional client configuration.

    Returns:
        Initialized RemoteVoxCPM2Client instance.
    """
    client = RemoteVoxCPM2Client(config=config)
    logger.info(
        "Created remote VoxCPM2 client",
        extra={"endpoint": client.config.endpoint},
    )
    return client
