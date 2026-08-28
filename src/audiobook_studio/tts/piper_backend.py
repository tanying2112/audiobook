"""Piper TTS Backend (S2-4).

Local CPU TTS via the `piper` inference binary
(https://github.com/rhasspy/piper) — the preferred local engine (priority 0 in
``config/tts_providers.yaml``), with Kokoro as fallback.

Piper runs as a CLI: it reads text from stdin and writes a 16/22.05/24 kHz mono
WAV. This backend wraps that subprocess, downloads the required ``.onnx`` voice
model on demand (reusing the P0-2 downloader), and converts to MP3 when the
requested output format requires it.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .engine import BaseTTSEngine, SynthesisResult, TTSEngine, TTSTaskPayload, TTSTaskResult, TTSTaskStatus, VoiceInfo
from .piper_models import (
    DEFAULT_PIPER_VOICE,
    PIPER_DEFAULT_MODEL_DIR,
    detect_piper_availability,
    ensure_piper_models,
    get_piper_model_path,
    list_piper_voices,
)

logger = logging.getLogger(__name__)


def _write_silence_wav(path: Path, sample_rate: int, seconds: float = 1.0) -> None:
    """Write a deterministic silent WAV (offline / mock mode).

    Prefers ``soundfile`` (already a project dependency via Kokoro); falls back to
    the stdlib ``wave`` module so the backend also works in minimal environments.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import numpy as np
        import soundfile as sf

        sf.write(str(path), np.zeros(int(sample_rate * seconds), dtype=np.float32), sample_rate)
    except Exception:  # pragma: no cover - fallback path
        import math
        import struct
        import wave

        n = int(sample_rate * seconds)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            frame = struct.pack("<h", 0)
            w.writeframes(frame * n)


class PiperBackend(BaseTTSEngine):
    """Local TTS backend wrapping the Piper CLI.

    Honors ``mock_mode=True`` (offline silent-WAV generation, no binary/model
    required) for tests and CI. In real mode it locates the ``piper`` binary and
    the requested ``.onnx`` voice model, downloading the latter on demand unless
    ``auto_download=False``.
    """

    def __init__(
        self,
        model_dir: Optional[str] = None,
        voice: Optional[str] = None,
        piper_bin: Optional[str] = None,
        auto_download: bool = False,
        mock_mode: bool = False,
        output_dir: str = "./output",
        max_concurrent: int = 2,
        sample_rate: int = 22050,
        **kwargs: Any,
    ):
        super().__init__(output_dir=output_dir, max_concurrent=max_concurrent)
        self.model_dir = Path(model_dir) if model_dir else PIPER_DEFAULT_MODEL_DIR
        self.voice = voice or os.environ.get("PIPER_VOICE", DEFAULT_PIPER_VOICE)
        self.piper_bin = piper_bin
        self.auto_download = auto_download
        self.mock_mode = mock_mode
        self.sample_rate = sample_rate
        self._loaded = False
        self._model_path: Optional[Path] = None
        self._json_path: Optional[Path] = None

    @property
    def engine_name(self) -> str:
        return "piper"

    @property
    def is_available(self) -> bool:
        return self._loaded

    @staticmethod
    def detect() -> tuple[bool, Dict[str, Any]]:
        """Convenience wrapper around :func:`piper_models.detect_piper_availability`."""
        return detect_piper_availability()

    async def initialize(self) -> None:
        """Locate the Piper binary and voice model (downloading the model if allowed)."""
        if self.mock_mode:
            self._loaded = True
            logger.info("PiperBackend initialized in mock mode")
            return

        # 1) Binary
        bin_path = self.piper_bin or os.environ.get("PIPER_BIN") or shutil.which("piper") or shutil.which("piper-tts")
        if not bin_path or not (Path(bin_path).exists() or shutil.which(bin_path)):
            raise RuntimeError(
                "Piper binary not found. Install piper-tts (`pip install piper-tts`) "
                "or set PIPER_BIN to the executable path."
            )
        self.piper_bin = bin_path

        # 2) Model
        model_path, json_path = get_piper_model_path(self.voice, self.model_dir)
        if not model_path.exists():
            if self.auto_download:
                logger.info(f"Piper model {model_path.name} missing; downloading into {self.model_dir}")
                ok = ensure_piper_models(self.model_dir, voices=[self.voice])
                if not ok:
                    raise RuntimeError(f"Failed to download Piper model: {model_path.name}")
            else:
                raise FileNotFoundError(
                    f"Piper model not found: {model_path}. "
                    "Set auto_download=True or run `python -m scripts.download_piper_models`."
                )

        if not json_path.exists():
            logger.warning(f"Piper model config missing (optional): {json_path}")

        self._model_path = model_path
        self._json_path = json_path
        self._loaded = True
        logger.info(f"PiperBackend initialized: binary={bin_path}, model={model_path}")

    async def _synthesize_internal(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        prosody: Optional[Dict[str, Any]] = None,
        reference_audio: Optional[str] = None,
        embedding: Optional[Any] = None,
        **kwargs: Any,
    ) -> SynthesisResult:
        if not self._loaded:
            await self.initialize()

        if self.mock_mode:
            _write_silence_wav(output_path, self.sample_rate, seconds=1.0)
            text_hash = hashlib.sha256(text.encode(), usedforsecurity=False).hexdigest()[:12]
            return SynthesisResult(
                audio_path=str(output_path),
                duration_ms=int(self.sample_rate),  # 1s of silence
                engine=self.engine_name,
                voice_id=voice_id,
                text_hash=text_hash,
                sample_rate=self.sample_rate,
            )

        # Resolve model for the requested voice (fall back to the configured voice).
        if voice_id and voice_id != self.voice:
            model_path, _ = get_piper_model_path(voice_id, self.model_dir)
            if not model_path.exists():
                logger.warning(f"Requested Piper voice {voice_id} not found; using {self.voice}")
                model_path = self._model_path
        else:
            model_path = self._model_path

        # Piper reads text from stdin and writes a WAV.
        wav_path = output_path.with_suffix(".wav")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        txt_path = output_path.with_suffix(".txt")
        txt_path.write_text(text, encoding="utf-8")

        cmd = [
            self.piper_bin,
            "--model",
            str(model_path),
            "--output_file",
            str(wav_path),
            "--sentence-silence",
            "0.2",
        ]
        # Map prosody -> Piper CLI knobs (length_scale is inverse of speed).
        if prosody:
            rate = float(prosody.get("rate", 1.0))
            if rate and rate != 1.0:
                cmd += ["--length-scale", f"{1.0 / rate:.3f}"]
            noise = prosody.get("noise_scale")
            if noise is not None:
                cmd += ["--noise-scale", f"{float(noise):.3f}"]

        try:
            proc = subprocess.run(
                cmd,
                stdin=open(txt_path, "r", encoding="utf-8"),
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            txt_path.unlink(missing_ok=True)

        if proc.returncode != 0:
            raise RuntimeError(f"Piper synthesis failed (exit {proc.returncode}): {proc.stderr.strip()}")

        # Convert to MP3 if requested.
        if output_path.suffix == ".mp3":
            ffmpeg = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(wav_path),
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    "128k",
                    str(output_path),
                ],
                capture_output=True,
            )
            if ffmpeg.returncode != 0:
                logger.warning("ffmpeg MP3 conversion failed; keeping WAV")
                output_path = wav_path
            else:
                wav_path.unlink(missing_ok=True)
        else:
            output_path = wav_path

        # Probe resulting audio for true duration/sample rate.
        duration_ms, sample_rate = self._probe_audio(output_path)
        text_hash = hashlib.sha256(text.encode(), usedforsecurity=False).hexdigest()[:12]
        return SynthesisResult(
            audio_path=str(output_path),
            duration_ms=duration_ms,
            engine=self.engine_name,
            voice_id=voice_id,
            text_hash=text_hash,
            sample_rate=sample_rate,
            metadata={"model": str(model_path.name)},
        )

    @staticmethod
    def _probe_audio(path: Path) -> tuple[int, int]:
        """Return (duration_ms, sample_rate) for a WAV/MP3 file."""
        try:
            import soundfile as sf

            info = sf.info(str(path))
            return int(info.frames / info.samplerate * 1000), int(info.samplerate)
        except Exception:
            return 1000, 22050

    # --- TTSEngine Protocol Implementation (mirrors KokoroBackend) ---

    async def synthesize(
        self,
        payload: TTSTaskPayload,
        output_path: Path,
    ) -> TTSTaskResult:
        text = payload.text
        voice_anchor = payload.voice_anchor
        prosody = payload.prosody
        metadata = payload.metadata

        voice_id = voice_anchor.voice_id
        reference_audio = voice_anchor.reference_audio_path
        embedding = metadata.get("embedding") if metadata else None

        prosody_dict = None
        if prosody:
            prosody_dict = {
                "rate": prosody.rate,
                "pitch": prosody.pitch,
                "volume": prosody.volume,
                "emotion": prosody.emotion,
            }

        try:
            result = await self._synthesize_internal(
                text=text,
                voice_id=voice_id,
                output_path=output_path,
                prosody=prosody_dict,
                reference_audio=reference_audio,
                embedding=embedding,
            )
            return TTSTaskResult(
                task_id=self._generate_task_id(),
                status="DONE",
                audio_path=result.audio_path,
                duration_ms=result.duration_ms,
                engine=result.engine,
                text_hash=result.text_hash,
                voice_id=result.voice_id,
                started_at=None,
            )
        except Exception as e:
            logger.error(f"Piper synthesis failed: {e}")
            return TTSTaskResult(
                task_id=self._generate_task_id(),
                status="FAILED",
                error_message=str(e),
                engine=self.engine_name,
            )

    async def submit(self, task_id: str, payload: TTSTaskPayload) -> bool:
        if task_id in self._tasks:
            return False
        self._tasks[task_id] = {"status": "PENDING", "payload": payload}
        asyncio.create_task(self._run_task(task_id, payload))
        return True

    async def _run_task(self, task_id: str, payload: TTSTaskPayload) -> None:
        try:
            self._tasks[task_id]["status"] = "RUNNING"
            output_path = self._build_output_path(task_id, payload.voice_anchor.voice_id)
            result = await self.synthesize(payload, output_path)
            self._tasks[task_id] = {"status": "DONE", "result": result}
        except Exception as e:  # noqa: BLE001
            self._tasks[task_id] = {"status": "FAILED", "error": str(e)}

    async def get_status(self, task_id: str) -> TTSTaskStatus:
        task = self._tasks.get(task_id)
        if not task:
            return TTSTaskStatus(
                task_id=task_id,
                status="PENDING",
                error_message=f"Task {task_id} not found",
            )
        return TTSTaskStatus(
            task_id=task_id,
            status=task["status"],
            error_message=task.get("error"),
        )

    async def get_result(self, task_id: str) -> TTSTaskResult:
        task = self._tasks.get(task_id)
        if not task or "result" not in task:
            raise KeyError(f"Task {task_id} not found or not ready")
        return task["result"]

    async def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task["status"] in ("DONE", "FAILED"):
            return False
        task["status"] = "FAILED"
        task["error"] = "Cancelled"
        return True

    async def health_check(self) -> Dict[str, Any]:
        available, detail = detect_piper_availability(self.piper_bin, self.model_dir)
        # In mock mode there is no real binary/model, but the engine is usable.
        healthy = self._loaded and (self.mock_mode or available)
        return {
            "healthy": healthy,
            "engine": self.engine_name,
            "loaded": self._loaded,
            "mock_mode": self.mock_mode,
            "sample_rate": self.sample_rate,
            "model": str(self._model_path) if self._model_path else None,
            "detection": detail,
        }

    async def warmup(self) -> bool:
        """Lightweight readiness check: binary + model present (no full load)."""
        if self.mock_mode:
            self._loaded = True
            return True
        try:
            available, _ = detect_piper_availability(self.piper_bin, self.model_dir)
            if available:
                self._loaded = True
            return available
        except Exception as e:  # noqa: BLE001
            logger.error(f"PiperBackend warmup failed: {e}")
            return False

    async def close(self) -> None:
        self._model_path = None
        self._json_path = None
        self._loaded = False
        logger.info("Piper backend cleaned up")

    def get_voices(self) -> List[VoiceInfo]:
        return list_piper_voices(self.model_dir)

    def estimate_duration(self, text: str, voice_id: str, **kwargs: Any) -> int:
        """Estimate duration: ~5 Chinese chars/sec or ~12.5 english chars/sec."""
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        english_chars = len(text) - chinese_chars
        est_sec = chinese_chars / 5.0 + english_chars / 12.5
        speed = kwargs.get("prosody", {}).get("rate", 1.0) if "prosody" in kwargs else 1.0
        est_sec = est_sec / speed if speed else est_sec
        return max(500, int(est_sec * 1000))

    async def stream(self, payload: TTSTaskPayload):
        """Pseudo-streaming: synthesize fully, then yield in ~100ms chunks.

        Piper generates a complete WAV; we stream it in chunks for progressive
        playback (not true incremental generation).
        """
        if not self._loaded:
            await self.initialize()

        if self.mock_mode:
            import numpy as np

            yield np.zeros(2205, dtype=np.int16).tobytes()  # ~100ms silence @ 22.05kHz
            return

        import tempfile

        import soundfile as sf

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            result = await self._synthesize_internal(
                text=payload.text,
                voice_id=payload.voice_anchor.voice_id,
                output_path=tmp_path,
            )
            audio_data, sr = sf.read(result.audio_path)
            if audio_data.ndim > 1:
                audio_data = audio_data.mean(axis=1)
            audio_int16 = (audio_data * 32767).astype("int16")
            chunk_size = int(sr * 0.1)
            for i in range(0, len(audio_int16), chunk_size):
                yield audio_int16[i : i + chunk_size].tobytes()
        finally:
            tmp_path.unlink(missing_ok=True)


async def create_piper_backend(
    model_dir: Optional[str] = None,
    voice: Optional[str] = None,
    piper_bin: Optional[str] = None,
    auto_download: bool = False,
    mock_mode: bool = False,
    **kwargs: Any,
) -> PiperBackend:
    """Factory: create and initialize a :class:`PiperBackend`."""
    backend = PiperBackend(
        model_dir=model_dir,
        voice=voice,
        piper_bin=piper_bin,
        auto_download=auto_download,
        mock_mode=mock_mode,
        **kwargs,
    )
    await backend.initialize()
    return backend


# Alias for engine.py registry compatibility.
create_piper_engine = create_piper_backend
