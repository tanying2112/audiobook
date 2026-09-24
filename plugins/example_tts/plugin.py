"""Example third-party TTS engine plugin.

This plugin registers an OpenAI-compatible HTTP TTS engine.
It demonstrates how a third-party can add TTS engines without modifying core code.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from audiobook_studio.plugins import PluginContext
from audiobook_studio.tts.engine import (
    TTSEngine,
    TTSTaskPayload,
    TTSTaskResult,
    TTSTaskStatus,
    TTSVoiceAnchor,
    TTSProsody,
)

logger = logging.getLogger(__name__)


@dataclass
class ExampleTTSConfig:
    """Configuration for Example TTS engine."""
    base_url: str
    api_key_env: str = "EXAMPLE_TTS_API_KEY"
    default_voice: str = "example-tts-voice-1"
    timeout: int = 30


class ExampleTTSEngine:
    """Example TTS engine using OpenAI-compatible HTTP API."""

    def __init__(
        self,
        base_url: str,
        api_key_env: str = "EXAMPLE_TTS_API_KEY",
        default_voice: str = "example-tts-voice-1",
        timeout: int = 30,
        output_dir: str = "./output",
        max_concurrent: int = 2,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = os.getenv(api_key_env, "")
        self.default_voice = default_voice
        self.timeout = timeout
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._loaded = False

    @property
    def engine_name(self) -> str:
        return "example_tts"

    @property
    def is_available(self) -> bool:
        return bool(self.api_key) and self._loaded

    async def initialize(self) -> None:
        """Initialize the engine (verify API reachability)."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
                resp = await client.get(f"{self.base_url}/models", headers=headers)
                self._loaded = resp.status_code < 500
        except Exception as e:
            logger.warning("Example TTS engine health check failed: %s", e)
            self._loaded = False

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def synthesize(
        self,
        payload: TTSTaskPayload,
        output_path: Path,
    ) -> TTSTaskResult:
        """Synthesize text to speech via HTTP API."""
        task_id = f"tts_{hashlib.md5(str(payload.text).encode()).hexdigest()[:8]}"
        started_at = ""

        async with self._semaphore:
            voice_id = payload.voice_anchor.voice_id or self.default_voice
            text = payload.text

            # Map prosody to API parameters
            prosody = payload.prosody
            body = {
                "model": "example-tts",
                "input": text,
                "voice": voice_id,
                "response_format": "mp3",
            }
            if prosody:
                if prosody.rate != 1.0:
                    body["speed"] = prosody.rate

            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/audio/speech",
                        json=body,
                        headers=self._headers(),
                    )
                    resp.raise_for_status()
                    audio_bytes = resp.content

                # Write to output file
                output_path.write_bytes(audio_bytes)

                # Estimate duration (rough: 150 chars/sec)
                duration_ms = int(len(text) / 150 * 1000)

                return TTSTaskResult(
                    task_id=task_id,
                    status="DONE",
                    audio_path=str(output_path),
                    duration_ms=duration_ms,
                    engine=self.engine_name,
                    voice_id=voice_id,
                    text_hash=hashlib.md5(text.encode()).hexdigest(),
                    started_at=started_at,
                )
            except Exception as e:
                logger.error("Example TTS synthesis failed: %s", e)
                return TTSTaskResult(
                    task_id=task_id,
                    status="FAILED",
                    error_message=str(e),
                    engine=self.engine_name,
                    voice_id=voice_id,
                    text_hash=hashlib.md5(text.encode()).hexdigest(),
                    started_at=started_at,
                )

    async def submit(self, task_id: str, payload: TTSTaskPayload) -> bool:
        """Submit async task - not supported in this example."""
        raise NotImplementedError("Example TTS engine does not support async submit")

    async def get_status(self, task_id: str) -> TTSTaskStatus:
        raise NotImplementedError("Example TTS engine does not support async status")

    async def get_result(self, task_id: str) -> TTSTaskResult:
        raise NotImplementedError("Example TTS engine does not support async result")

    async def cancel(self, task_id: str) -> bool:
        raise NotImplementedError("Example TTS engine does not support async cancel")

    async def stream(
        self,
        payload: TTSTaskPayload,
    ) -> AsyncIterator[bytes]:
        """Stream audio chunks - not supported in this example."""
        raise NotImplementedError("Example TTS engine does not support streaming")

    async def health_check(self) -> Dict[str, Any]:
        """Check engine health."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self.base_url}/models",
                    headers=self._headers(),
                )
                return {
                    "healthy": resp.status_code < 500,
                    "status_code": resp.status_code,
                    "engine": self.engine_name,
                }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
                "engine": self.engine_name,
            }

    async def close(self) -> None:
        """Release resources."""
        self._loaded = False


async def create_example_tts_engine(
    base_url: str,
    api_key_env: str = "EXAMPLE_TTS_API_KEY",
    default_voice: str = "example-tts-voice-1",
    timeout: int = 30,
    output_dir: str = "./output",
    max_concurrent: int = 2,
) -> ExampleTTSEngine:
    """Factory function for creating the example TTS engine."""
    engine = ExampleTTSEngine(
        base_url=base_url,
        api_key_env=api_key_env,
        default_voice=default_voice,
        timeout=timeout,
        output_dir=output_dir,
        max_concurrent=max_concurrent,
    )
    await engine.initialize()
    return engine


def register(ctx: PluginContext) -> None:
    """Plugin entrypoint - called by PluginManager."""
    ctx.register_tts_engine(
        engine_name="example_tts",
        factory=create_example_tts_engine,
        config_schema=ExampleTTSConfig,
        default_config={
            "base_url": "https://api.example.com/v1",
            "api_key_env": "EXAMPLE_TTS_API_KEY",
            "default_voice": "example-tts-voice-1",
            "timeout": 30,
        },
    )