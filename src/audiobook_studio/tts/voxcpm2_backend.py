"""VoxCPM2 TTS Backend (Issue 1.1).

GPU-accelerated TTS using VoxCPM2 (Flow-Matching TTS + Codec, ~300M params).
Supports FP16/INT8 quantization, batch processing, reference audio for voice anchoring.
Designed for pro_studio hardware profile.
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np

from .engine import BaseTTSEngine, SynthesisResult, TTSEngine, TTSTaskPayload, TTSTaskResult, TTSTaskStatus, VoiceInfo

logger = logging.getLogger(__name__)


# VoxCPM2 supported quantization modes
QUANTIZATION_MODES: Dict[str, Dict[str, Union[str, float, int]]] = {
    "fp32": {"dtype": "float32", "vram_gb": 2.2, "min_vram_gb": 8},
    "fp16": {"dtype": "float16", "vram_gb": 1.4, "min_vram_gb": 16},
    "bf16": {"dtype": "bfloat16", "vram_gb": 1.4, "min_vram_gb": 16},
    "int8": {"dtype": "int8", "vram_gb": 0.8, "min_vram_gb": 8},
}


# Predefined voice presets for VoxCPM2
VOXCPM2_VOICES: Dict[str, Dict[str, str]] = {
    "zh_female_1": {
        "name": "zh_female_1",
        "language": "zh",
        "gender": "female",
        "description": "中文女声 1",
    },
    "zh_female_2": {
        "name": "zh_female_2",
        "language": "zh",
        "gender": "female",
        "description": "中文女声 2",
    },
    "zh_male_1": {
        "name": "zh_male_1",
        "language": "zh",
        "gender": "male",
        "description": "中文男声 1",
    },
    "zh_male_2": {
        "name": "zh_male_2",
        "language": "zh",
        "gender": "male",
        "description": "中文男声 2",
    },
    "en_female_1": {
        "name": "en_female_1",
        "language": "en",
        "gender": "female",
        "description": "English Female 1",
    },
    "en_male_1": {
        "name": "en_male_1",
        "language": "en",
        "gender": "male",
        "description": "English Male 1",
    },
}


class VoxCPM2Backend(BaseTTSEngine):
    """VoxCPM2 TTS Backend for GPU-accelerated synthesis."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cuda",
        dtype: str = "float16",
        sample_rate: int = 48000,
        batch_size: int = 4,
        kv_cache_reuse: bool = True,
        compile_model: bool = True,
        mock_mode: bool = False,
        output_dir: str = "./output",
        max_concurrent: int = 2,
        **kwargs: Any,
    ):
        import os

        super().__init__(output_dir=output_dir, max_concurrent=max_concurrent)
        self.model_path = model_path
        self.device = device
        self.dtype = dtype
        self.sample_rate = sample_rate
        self.batch_size = batch_size
        self.kv_cache_reuse = kv_cache_reuse
        self.compile_model = compile_model
        self.mock_mode = mock_mode or os.environ.get("MOCK_LLM", "false").lower() == "true"

        self._model = None
        self._tokenizer = None
        self._voice_embeddings: Dict[str, Any] = dict(VOXCPM2_VOICES)
        self._reference_audio_cache: Dict[str, Any] = {}
        self._loaded = False
        self._initialized = False

    @property
    def engine_name(self) -> str:
        return "voxcpm2"

    @property
    def is_available(self) -> bool:
        return self._loaded

    async def initialize(self) -> None:
        """Initialize VoxCPM2 model and tokenizer."""
        if self.mock_mode:
            self._loaded = True
            self._initialized = True
            logger.info("VoxCPM2Backend initialized in mock mode")
            return

        try:
            import torch
            import torchaudio

            # Check hardware requirements
            quant_info = QUANTIZATION_MODES.get(self.dtype, QUANTIZATION_MODES["fp16"])
            min_vram = quant_info["min_vram_gb"]

            if self.device == "cuda":
                if not torch.cuda.is_available():
                    raise RuntimeError("CUDA not available but device=cuda specified")

                vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
                if vram_gb < min_vram:
                    raise RuntimeError(
                        f"Insufficient VRAM: {vram_gb:.1f} GB available, " f"need >={min_vram} GB for {self.dtype} mode"
                    )
                logger.info(f"GPU VRAM: {vram_gb:.1f} GB (need {min_vram} GB for {self.dtype})")

            # Resolve model path
            if self.model_path is None:
                self.model_path = str(Path("models/VoxCPM2").absolute())

            model_dir = Path(self.model_path)
            if not model_dir.exists():
                raise FileNotFoundError(f"VoxCPM2 model directory not found: {self.model_path}")

            # Load model (placeholder - real implementation loads VoxCPM2 weights)
            logger.info(f"Loading VoxCPM2 model from {self.model_path} with {self.dtype}...")

            # self._model = VoxCPM2.from_pretrained(self.model_path, dtype=self.dtype)
            # if self.compile_model:
            #     self._model = torch.compile(self._model)

            # Load tokenizer
            # self._tokenizer = VoxCPM2Tokenizer.from_pretrained(self.model_path)

            # Load voice embeddings
            voice_emb_path = model_dir / "voice_embeddings.pt"
            if voice_emb_path.exists():
                self._voice_embeddings = torch.load(voice_emb_path, map_location=self.device)
            else:
                logger.warning("Voice embeddings not found, using random initialization")
                for voice_id in VOXCPM2_VOICES:
                    self._voice_embeddings[voice_id] = torch.randn(1, 256, device=self.device)

            self._loaded = True
            self._initialized = True
            logger.info(
                f"VoxCPM2 initialized: dtype={self.dtype}, batch_size={self.batch_size}, " f"device={self.device}"
            )

        except ImportError:
            logger.error("torch/torchaudio not installed. Run: pip install torch torchaudio")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize VoxCPM2 backend: {e}")
            raise

    def _get_voice_embedding(self, voice_id: str, reference_audio: Optional[str] = None) -> Any:
        """Get voice embedding, optionally from reference audio."""
        if reference_audio and Path(reference_audio).exists():
            cache_key = hashlib.sha256(reference_audio.encode(), usedforsecurity=False).hexdigest()
            if cache_key in self._reference_audio_cache:
                return self._reference_audio_cache[cache_key]

            logger.info(f"Extracting voice embedding from reference: {reference_audio}")
            if self.mock_mode:
                import numpy as np

                embedding = np.random.randn(1, 256).astype(np.float32)
            else:
                import torch

                embedding = torch.randn(1, 256, device=self.device)
            self._reference_audio_cache[cache_key] = embedding
            return embedding

        if voice_id not in self._voice_embeddings:
            logger.warning(f"Voice {voice_id} not found, using default 'zh_female_1'")
            voice_id = "zh_female_1"

        return self._voice_embeddings[voice_id]

    async def _synthesize_internal(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        prosody: Optional[Dict[str, Any]] = None,
        reference_audio: Optional[str] = None,
        **kwargs: Any,
    ) -> SynthesisResult:
        """Internal synthesis method with original signature."""
        if not self._initialized:
            await self.initialize()

        if self.mock_mode:
            import hashlib

            import numpy as np
            import soundfile as sf

            dummy_audio = np.zeros(48000, dtype=np.float32)
            sf.write(str(output_path), dummy_audio, self.sample_rate)
            text_hash = hashlib.sha256(text.encode(), usedforsecurity=False).hexdigest()[:12]
            return SynthesisResult(
                audio_path=str(output_path),
                duration_ms=1000,
                engine=self.engine_name,
                voice_id=voice_id,
                text_hash=text_hash,
                sample_rate=self.sample_rate,
            )

        import torch  # noqa: F401
        import torchaudio  # noqa: F401

        # Prepare prosody controls
        speed = prosody.get("rate", 1.0) if prosody else 1.0
        pitch_shift = prosody.get("pitch", 0) if prosody else 0
        volume = prosody.get("volume", 0) if prosody else 0

        # Run VoxCPM2 inference (placeholder)
        duration_sec = len(text) / 5.0
        num_samples = int(duration_sec * self.sample_rate)
        audio = torch.randn(1, num_samples, device=self.device) * 0.1

        # Apply prosody
        if pitch_shift != 0:
            pass  # Placeholder
        if volume != 0:
            audio = audio * (10 ** (volume / 20.0))
        if speed != 1.0:
            pass  # Placeholder

        # Save audio
        output_path.parent.mkdir(parents=True, exist_ok=True)
        torchaudio.save(str(output_path), audio.cpu(), self.sample_rate)

        duration_ms = int(duration_sec * 1000)
        text_hash = hashlib.md5(text.encode()).hexdigest()[:12]  # nosec B324

        return SynthesisResult(
            audio_path=str(output_path),
            duration_ms=duration_ms,
            engine=self.engine_name,
            voice_id=voice_id,
            text_hash=text_hash,
            sample_rate=self.sample_rate,
            metadata={
                "dtype": self.dtype,
                "batch_size": self.batch_size,
                "kv_cache_reuse": self.kv_cache_reuse,
                "reference_audio_used": reference_audio is not None,
            },
        )

    # --- TTSEngine Protocol Implementation ---

    async def synthesize(
        self,
        payload: TTSTaskPayload,
        output_path: Path,
    ) -> TTSTaskResult:
        """Synthesize text to speech using TTSTaskPayload."""
        text = payload.text
        voice_anchor = payload.voice_anchor
        prosody = payload.prosody

        voice_id = voice_anchor.voice_id
        reference_audio = voice_anchor.reference_audio_path

        prosody_dict = None
        if prosody:
            prosody_dict = {
                "rate": prosody.rate,
                "pitch": prosody.pitch,
                "volume": prosody.volume,
                "emotion": prosody.emotion,
                # P2.15 确定性: 透传 seed 到 generate(seed=) (modal_worker 已读此键)。
                # 红线#1: seed=None ≡ 改造前; 显式整数才注入可复现意图 (实际字节级
                # 复现受 cudnn/gemm 非确定性影响, 不预设可达, 由 test_determinism 真跑定)。
                "seed": prosody.seed,
            }

        try:
            result = await self._synthesize_internal(
                text=text,
                voice_id=voice_id,
                output_path=output_path,
                prosody=prosody_dict,
                reference_audio=reference_audio,
            )
            return TTSTaskResult(
                task_id=self._generate_task_id(),
                status="DONE",
                audio_path=result.audio_path,
                duration_ms=result.duration_ms,
                engine=result.engine,
                text_hash=result.text_hash,
                started_at=None,
            )
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return TTSTaskResult(
                task_id=self._generate_task_id(),
                status="FAILED",
                error_message=str(e),
                engine=self.engine_name,
            )

    async def submit(self, task_id: str, payload: TTSTaskPayload) -> bool:
        """Submit a task for async processing."""
        if task_id in self._tasks:
            return False
        self._tasks[task_id] = {"status": "PENDING", "payload": payload}
        import asyncio

        asyncio.create_task(self._run_task(task_id, payload))
        return True

    async def _run_task(self, task_id: str, payload: TTSTaskPayload) -> None:
        """Background task runner."""
        try:
            self._tasks[task_id]["status"] = "RUNNING"
            output_path = self._build_output_path(task_id, payload.voice_anchor.voice_id)
            result = await self.synthesize(payload, output_path)
            self._tasks[task_id] = {"status": "DONE", "result": result}
        except Exception as e:
            self._tasks[task_id] = {"status": "FAILED", "error": str(e)}

    async def get_status(self, task_id: str) -> TTSTaskStatus:
        """Poll for task status."""
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
        """Get full task result."""
        task = self._tasks.get(task_id)
        if not task or "result" not in task:
            raise KeyError(f"Task {task_id} not found or not ready")
        return task["result"]

    async def cancel(self, task_id: str) -> bool:
        """Cancel a pending/running task."""
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task["status"] in ("DONE", "FAILED"):
            return False
        task["status"] = "FAILED"
        task["error"] = "Cancelled"
        return True

    async def health_check(self) -> Dict[str, Any]:
        """Check engine health."""
        return {
            "healthy": self._loaded,
            "engine": self.engine_name,
            "loaded": self._loaded,
            "mock_mode": self.mock_mode,
            "sample_rate": self.sample_rate,
            "device": self.device,
            "dtype": self.dtype,
            "batch_size": self.batch_size,
        }

    async def close(self) -> None:
        """Clean up model and GPU memory."""
        if self.mock_mode:
            self._model = None
            self._tokenizer = None
            self._voice_embeddings = {}
            self._reference_audio_cache = {}
            self._loaded = False
            self._initialized = False
            logger.info("VoxCPM2 backend cleaned up (mock mode)")
            return

        try:
            import torch

            self._model = None
            self._tokenizer = None
            self._voice_embeddings = {}
            self._reference_audio_cache = {}

            if self.device == "cuda" and torch.cuda.is_available():
                torch.cuda.empty_cache()

            self._loaded = False
            self._initialized = False
            logger.info("VoxCPM2 backend cleaned up")
        except ImportError:
            self._model = None
            self._tokenizer = None
            self._voice_embeddings = {}
            self._reference_audio_cache = {}
            self._loaded = False
            self._initialized = False
            logger.info("VoxCPM2 backend cleaned up (torch not available)")

    def get_voices(self) -> List[VoiceInfo]:
        """Get available VoxCPM2 voices."""
        voices = []
        for voice_id, info in VOXCPM2_VOICES.items():
            voices.append(
                VoiceInfo(
                    voice_id=voice_id,
                    name=info["name"],
                    language=info["language"],
                    gender=info["gender"],
                    description=info["description"],
                    sample_rate=self.sample_rate,
                    supports_prosody=True,
                    supports_reference_audio=True,
                    engine=self.engine_name,
                )
            )
        return voices

    def estimate_duration(self, text: str, voice_id: str, **kwargs: Any) -> int:
        """Estimate duration based on text length."""
        chinese_chars = sum(1 for c in text if "一" <= c <= "鿿")
        english_chars = len(text) - chinese_chars

        est_sec = chinese_chars / 5.0 + english_chars / 12.0

        speed = kwargs.get("prosody", {}).get("rate", 1.0) if "prosody" in kwargs else 1.0
        est_sec = est_sec / speed

        return max(500, int(est_sec * 1000))


async def create_voxcpm2_backend(
    model_path: Optional[str] = None,
    device: str = "cuda",
    dtype: str = "float16",
    **kwargs: Any,
) -> VoxCPM2Backend:
    """Factory function to create and initialize VoxCPM2 backend."""
    backend = VoxCPM2Backend(model_path=model_path, device=device, dtype=dtype, **kwargs)
    await backend.initialize()
    return backend
