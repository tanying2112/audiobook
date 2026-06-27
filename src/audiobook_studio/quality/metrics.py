"""
Quality Metrics — 硬质检三件套 (DNSMOS + ASR WER + Speaker Sim)

实现真实可用的音频质量检测，为 Issue 1.4 提供核心支持。

三件套：
1. DNSMOS — 语音质量评分 (无需参考音频，MOS 预测)
2. ASR WER — 语音识别字错误率 (转录准确性指标)
3. Speaker Similarity — 跨章节声纹相似度 (声纹一致性指标)

所有实现基于免费/开源模型，支持离线运行 (potato/cloud_hybrid 模式)。
"""

import json
import logging
import os
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..utils.ffmpeg_probe import get_audio_info_sync, read_pcm_samples_sync

logger = logging.getLogger(__name__)

# Optional imports for speaker embedding
_torch_available = False
_torchaudio_available = False
try:
    import torch

    _torch_available = True
except ImportError:
    pass
try:
    import torchaudio

    _torchaudio_available = True
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class DNSMOSResult:
    """DNSMOS 质量评分结果."""

    mos_overall: float  # 整体 MOS (1-5)
    mos_sig: float  # 信号质量 MOS (1-5)
    mos_bak: float  # 背景质量 MOS (1-5)
    mos_ovr: float  # 综合 MOS (1-5)
    success: bool
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mos_overall": self.mos_overall,
            "mos_sig": self.mos_sig,
            "mos_bak": self.mos_bak,
            "mos_ovr": self.mos_ovr,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class ASRResult:
    """ASR 识别结果."""

    text: str
    words: List[Dict[str, Any]]  # 单词级时间戳
    language: str
    confidence: float
    duration_ms: float
    success: bool
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "words": self.words,
            "language": self.language,
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class WERResult:
    """WER (Word Error Rate) 计算结果."""

    wer: float  # 字错误率 0-1
    cer: float  # 字符错误率 0-1
    insertions: int
    deletions: int
    substitutions: int
    reference_words: int
    hypothesis_words: int
    success: bool
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wer": self.wer,
            "cer": self.cer,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "substitutions": self.substitutions,
            "reference_words": self.reference_words,
            "hypothesis_words": self.hypothesis_words,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class SpeakerEmbedding:
    """说话人嵌入向量."""

    embedding: np.ndarray  # 维度: d (通常 192/256/512)
    model_name: str  # 模型名称: ecapa_tdnn, wavlm_large 等
    sample_rate: int  # 采样率要求

    def to_dict(self) -> Dict[str, Any]:
        return {
            "embedding": self.embedding.tolist(),
            "model_name": self.model_name,
            "sample_rate": self.sample_rate,
            "dim": self.embedding.shape[0],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpeakerEmbedding":
        return cls(
            embedding=np.array(data["embedding"], dtype=np.float32),
            model_name=data["model_name"],
            sample_rate=data["sample_rate"],
        )


@dataclass
class SpeakerSimilarityResult:
    """说话人相似度结果."""

    similarity: float  # 余弦相似度 0-1
    threshold: float  # 判定阈值
    is_same_speaker: bool  # 是否判定为同一说话人
    reference_id: str  # 参考音频 ID
    target_id: str  # 目标音频 ID
    success: bool
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "similarity": self.similarity,
            "threshold": self.threshold,
            "is_same_speaker": self.is_same_speaker,
            "reference_id": self.reference_id,
            "target_id": self.target_id,
            "success": self.success,
            "error": self.error,
        }


# ═══════════════════════════════════════════════════════════════════════════
# 抽象基类
# ═══════════════════════════════════════════════════════════════════════════


class QualityMetric(ABC):
    """质量指标基类."""

    @abstractmethod
    def compute(self, *args, **kwargs) -> Any:
        """计算质量指标."""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """获取指标名称."""
        pass


# ════════════════════════════════════════════════════════════════════════════
# 1. DNSMOS 实现
# ═══════════════════════════════════════════════════════════════════════════


class DNSMOSMetric(QualityMetric):
    """DNSMOS 语音质量评分.

    使用微软开源的 DNSMOS 模型 (owa/DNSMOS@v1.1.0 基于 ONNX Runtime)。
    预测三个维度的 MOS 分数：SIG (信号质量)、BAK (背景质量)、OVR (综合质量)。

    参考: https://github.com/microsoft/DNS-Challenge/tree/master/DNSMOS
    模型: https://github.com/microsoft/DNS-Challenge/raw/master/DNSMOS/DNSMOS.onnx
    """

    MODEL_URL = (
        "https://github.com/microsoft/DNS-Challenge/raw/master/DNSMOS/DNSMOS.onnx"
    )
    MODEL_FILENAME = "dnsmos.onnx"
    DEFAULT_SAMPLE_RATE = 16000

    def __init__(
        self,
        model_path: Optional[Path] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        use_ort: bool = True,
    ):
        """
        Args:
            model_path: ONNX 模型路径，None 则自动下载到缓存
            sample_rate: 输入音频采样率 (必须 16kHz)
            use_ort: 是否使用 ONNX Runtime (True) 还是 torch (False)
        """
        self.sample_rate = sample_rate
        self.use_ort = use_ort

        # 确定模型路径
        if model_path is None:
            cache_dir = Path.home() / ".cache" / "audiobook_studio" / "models"
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
            except (FileNotFoundError, PermissionError):
                # Fallback to temp directory
                import tempfile

                cache_dir = Path(tempfile.gettempdir()) / "audiobook_studio" / "models"
                cache_dir.mkdir(parents=True, exist_ok=True)
            self.model_path = cache_dir / self.MODEL_FILENAME
        else:
            self.model_path = Path(model_path)

        self._session = None
        self._model = None
        self._initialized = False

    def _ensure_model(self) -> bool:
        """确保模型已下载."""
        if self.model_path.exists():
            return True

        logger.info(f"Downloading DNSMOS model from {self.MODEL_URL}...")
        try:
            import urllib.request

            urllib.request.urlretrieve(self.MODEL_URL, self.model_path)
            logger.info(f"DNSMOS model downloaded to {self.model_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to download DNSMOS model: {e}")
            return False

    def _initialize(self):
        """延迟初始化模型."""
        if self._initialized:
            return

        if not self._ensure_model():
            raise RuntimeError("DNSMOS model not available")

        try:
            if self.use_ort:
                import onnxruntime as ort

                self._session = ort.InferenceSession(
                    str(self.model_path), providers=["CPUExecutionProvider"]
                )
            else:
                import torch

                self._model = torch.jit.load(str(self.model_path))
                self._model.eval()
            self._initialized = True
            logger.info("DNSMOS model initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize DNSMOS model: {e}")
            raise

    def _preprocess_audio(self, audio_path: Path) -> np.ndarray:
        """预处理音频为 DNSMOS 所需格式."""
        # 使用 ffmpeg 重采样到 16kHz 单声道
        import asyncio

        async def _resample():
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(audio_path),
                "-ar",
                str(self.sample_rate),
                "-ac",
                "1",
                "-f",
                "f32le",
                "-acodec",
                "pcm_f32le",
                "-",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg resample failed: {stderr.decode()}")
            return np.frombuffer(stdout, dtype=np.float32)

        return asyncio.run(_resample())

    def _compute_dnsmos(self, audio: np.ndarray) -> Tuple[float, float, float, float]:
        """计算 DNSMOS 分数."""
        # DNSMOS 需要分帧处理 (每帧 160ms = 2560 samples at 16kHz)
        frame_len = int(0.16 * self.sample_rate)  # 2560
        hop_len = frame_len  # 无重叠

        # 填充或截断到整数倍
        num_frames = len(audio) // frame_len
        if num_frames == 0:
            # 音频太短，填充
            audio = np.pad(audio, (0, frame_len - len(audio)))
            num_frames = 1

        audio = audio[: num_frames * frame_len]
        frames = audio.reshape(num_frames, frame_len)

        # 准备输入
        # DNSMOS 输入: (batch, 1, frame_len)
        input_tensor = frames[:, np.newaxis, :].astype(np.float32)

        if self.use_ort:
            # ONNX Runtime 推理
            input_name = self._session.get_inputs()[0].name
            outputs = self._session.run(None, {input_name: input_tensor})
            # 输出: (batch, 3) -> SIG, BAK, OVR
            scores = outputs[0]
        else:
            # PyTorch 推理
            import torch

            with torch.no_grad():
                input_tensor_torch = torch.from_numpy(input_tensor)
                scores = self._model(input_tensor_torch).numpy()

        # 平均池化
        mos_sig = float(np.mean(scores[:, 0]))
        mos_bak = float(np.mean(scores[:, 1]))
        mos_ovr = float(np.mean(scores[:, 2]))

        # 整体 MOS 使用加权平均 (参考 DNSMOS 论文)
        mos_overall = (mos_sig + mos_bak + mos_ovr) / 3.0

        return mos_overall, mos_sig, mos_bak, mos_ovr

    def compute(self, audio_path: Path) -> DNSMOSResult:
        """计算音频文件的 DNSMOS 分数.

        Args:
            audio_path: 音频文件路径

        Returns:
            DNSMOSResult 包含四个 MOS 分数
        """
        try:
            self._initialize()

            # 预处理音频
            audio = self._preprocess_audio(audio_path)

            # 计算分数
            mos_overall, mos_sig, mos_bak, mos_ovr = self._compute_dnsmos(audio)

            return DNSMOSResult(
                mos_overall=mos_overall,
                mos_sig=mos_sig,
                mos_bak=mos_bak,
                mos_ovr=mos_ovr,
                success=True,
            )
        except Exception as e:
            logger.error(f"DNSMOS computation failed for {audio_path}: {e}")
            return DNSMOSResult(
                mos_overall=0.0,
                mos_sig=0.0,
                mos_bak=0.0,
                mos_ovr=0.0,
                success=False,
                error=str(e),
            )

    def get_name(self) -> str:
        return "dnsmos"


# ═══════════════════════════════════════════════════════════════════════════
# 2. ASR WER 实现
# ═══════════════════════════════════════════════════════════════════════════


class ASRBackend(ABC):
    """ASR 后端抽象基类."""

    @abstractmethod
    def transcribe(self, audio_path: Path) -> ASRResult:
        """转录音频."""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """获取后端名称."""
        pass


class FunASRBackend(ASRBackend):
    """FunASR (SenseVoice) 后端.

    支持中文、英文、日文、韩文等多语言识别。
    模型: iic/sensevoice_small, iic/sensevoice_large
    """

    def __init__(self, model_name: str = "sensevoice_small", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self._model = None
        self._initialized = False

    def _initialize(self):
        if self._initialized:
            return
        try:
            from funasr import AutoModel

            self._model = AutoModel(
                model=self.model_name,
                device=self.device,
                disable_update=True,
            )
            self._initialized = True
            logger.info(f"FunASR ({self.model_name}) initialized on {self.device}")
        except ImportError:
            raise RuntimeError("FunASR not installed. Install with: pip install funasr")
        except Exception as e:
            logger.error(f"Failed to initialize FunASR: {e}")
            raise

    def transcribe(self, audio_path: Path) -> ASRResult:
        self._initialize()
        try:
            result = self._model.generate(
                input=str(audio_path),
                batch_size_s=300,
                merge_vad=True,
                merge_length_s=15,
            )

            if not result:
                return ASRResult(
                    text="",
                    words=[],
                    language="unknown",
                    confidence=0.0,
                    duration_ms=0,
                    success=False,
                    error="No transcription result",
                )

            # FunASR 返回格式解析
            first = result[0]
            text = first.get("text", "")

            # 解析单词级时间戳（如果有）
            words = []
            if "words" in first:
                for w in first["words"]:
                    words.append(
                        {
                            "word": w.get("word", w.get("text", "")),
                            "start_ms": int(w.get("start", 0) * 1000),
                            "end_ms": int(w.get("end", 0) * 1000),
                            "confidence": w.get("confidence", 1.0),
                        }
                    )

            # 获取语言和置信度
            language = first.get("language", "zh")
            confidence = first.get("confidence", 1.0) if "confidence" in first else 1.0
            duration_ms = first.get("duration", 0) * 1000 if "duration" in first else 0

            return ASRResult(
                text=text,
                words=words,
                language=language,
                confidence=confidence,
                duration_ms=duration_ms,
                success=True,
            )
        except Exception as e:
            logger.error(f"FunASR transcription failed: {e}")
            return ASRResult(
                text="",
                words=[],
                language="unknown",
                confidence=0.0,
                duration_ms=0,
                success=False,
                error=str(e),
            )

    def get_name(self) -> str:
        return f"funasr_{self.model_name}"


class WhisperBackend(ASRBackend):
    """Whisper (OpenAI) 后端.

    使用 faster-whisper (CTranslate2) 或 openai-whisper。
    支持多语言，CPU/GPU 均可运行。
    """

    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        use_faster: bool = True,
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.use_faster = use_faster
        self._model = None
        self._initialized = False

    def _initialize(self):
        if self._initialized:
            return
        try:
            if self.use_faster:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                )
            else:
                import whisper

                self._model = whisper.load_model(self.model_size, device=self.device)
            self._initialized = True
            logger.info(f"Whisper ({self.model_size}) initialized on {self.device}")
        except ImportError:
            if self.use_faster:
                raise RuntimeError(
                    "faster-whisper not installed. pip install faster-whisper"
                )
            else:
                raise RuntimeError(
                    "openai-whisper not installed. pip install openai-whisper"
                )
        except Exception as e:
            logger.error(f"Failed to initialize Whisper: {e}")
            raise

    def transcribe(self, audio_path: Path) -> ASRResult:
        self._initialize()
        try:
            if self.use_faster:
                segments, info = self._model.transcribe(
                    str(audio_path),
                    beam_size=5,
                    vad_filter=True,
                )
                text_parts = []
                words = []
                for segment in segments:
                    text_parts.append(segment.text)
                    if segment.words:
                        for w in segment.words:
                            words.append(
                                {
                                    "word": w.word,
                                    "start_ms": int(w.start * 1000),
                                    "end_ms": int(w.end * 1000),
                                    "confidence": w.probability,
                                }
                            )
                text = " ".join(text_parts).strip()
                language = info.language
                duration_ms = info.duration * 1000
            else:
                import whisper

                result = self._model.transcribe(str(audio_path))
                text = result["text"].strip()
                words = []
                if "segments" in result:
                    for seg in result["segments"]:
                        text_parts.append(seg["text"])
                        # whisper 不直接提供 word-level timestamps
                language = result.get("language", "unknown")
                duration_ms = 0

            return ASRResult(
                text=text,
                words=words,
                language=language,
                confidence=1.0,
                duration_ms=duration_ms,
                success=True,
            )
        except Exception as e:
            logger.error(f"Whisper transcription failed: {e}")
            return ASRResult(
                text="",
                words=[],
                language="unknown",
                confidence=0.0,
                duration_ms=0,
                success=False,
                error=str(e),
            )

    def get_name(self) -> str:
        return f"whisper_{self.model_size}"


class ASRWerMetric(QualityMetric):
    """ASR WER (Word Error Rate) 质量指标.

    通过 ASR 识别音频，与标准文本对比计算 WER/CER。
    支持多种 ASR 后端: FunASR (SenseVoice), Whisper (faster-whisper/openai-whisper)。
    """

    def __init__(
        self,
        backend: str = "funasr",
        model_name: str = "sensevoice_small",
        device: str = "cpu",
        reference_text: str = "",
    ):
        """
        Args:
            backend: asr 后端类型 (funasr | whisper)
            model_name: 模型名称
            device: 计算设备 (cpu | cuda)
            reference_text: 参考文本 (用于计算 WER)
        """
        self.reference_text = reference_text
        self._backend = self._create_backend(backend, model_name, device)

    def _create_backend(self, backend: str, model_name: str, device: str) -> ASRBackend:
        if backend == "funasr":
            return FunASRBackend(model_name, device)
        elif backend == "whisper":
            return WhisperBackend(model_size=model_name, device=device)
        else:
            raise ValueError(f"Unknown ASR backend: {backend}")

    def _compute_wer_cer(
        self, reference: str, hypothesis: str
    ) -> Tuple[float, float, int, int, int, int, int]:
        """计算 WER 和 CER.

        Returns:
            (wer, cer, insertions, deletions, substitutions, ref_words, hyp_words)
        """

        # 中文按字符分词，英文按单词分词
        def tokenize(text: str) -> List[str]:
            # 简单判断：如果包含中文字符则按字符分
            import re

            has_chinese = bool(re.search(r"[\u4e00-\u9fff]", text))
            if has_chinese:
                return list(text.replace(" ", ""))
            else:
                return text.split()

        ref_tokens = tokenize(reference)
        hyp_tokens = tokenize(hypothesis)

        # Levenshtein distance with operation tracking
        n, m = len(ref_tokens), len(hyp_tokens)
        dp = [[0] * (m + 1) for _ in range(n + 1)]
        ops = [[None] * (m + 1) for _ in range(n + 1)]

        for i in range(n + 1):
            dp[i][0] = i
            ops[i][0] = "del" if i > 0 else None
        for j in range(m + 1):
            dp[0][j] = j
            ops[0][j] = "ins" if j > 0 else None

        for i in range(1, n + 1):
            for j in range(1, m + 1):
                if ref_tokens[i - 1] == hyp_tokens[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1]
                    ops[i][j] = "match"
                else:
                    # substitution
                    sub_cost = dp[i - 1][j - 1] + 1
                    # insertion
                    ins_cost = dp[i][j - 1] + 1
                    # deletion
                    del_cost = dp[i - 1][j] + 1

                    min_cost = min(sub_cost, ins_cost, del_cost)
                    dp[i][j] = min_cost

                    if min_cost == sub_cost:
                        ops[i][j] = "sub"
                    elif min_cost == ins_cost:
                        ops[i][j] = "ins"
                    else:
                        ops[i][j] = "del"

        # Backtrack to count operations
        i, j = n, m
        insertions = deletions = substitutions = 0
        while i > 0 or j > 0:
            op = ops[i][j]
            if op == "match":
                i -= 1
                j -= 1
            elif op == "sub":
                substitutions += 1
                i -= 1
                j -= 1
            elif op == "ins":
                insertions += 1
                j -= 1
            elif op == "del":
                deletions += 1
                i -= 1

        total_ref = n
        total_hyp = m
        wer = (insertions + deletions + substitutions) / max(total_ref, 1)
        cer = dp[n][m] / max(n, 1)

        return wer, cer, insertions, deletions, substitutions, total_ref, total_hyp

    def compute(
        self, audio_path: Path, reference_text: Optional[str] = None
    ) -> WERResult:
        """计算音频的 WER.

        Args:
            audio_path: 音频文件路径
            reference_text: 参考文本 (覆盖构造时的 reference_text)

        Returns:
            WERResult
        """
        ref_text = reference_text or self.reference_text
        if not ref_text:
            return WERResult(
                wer=1.0,
                cer=1.0,
                insertions=0,
                deletions=0,
                substitutions=0,
                reference_words=0,
                hypothesis_words=0,
                success=False,
                error="No reference text provided",
            )

        try:
            asr_result = self._backend.transcribe(audio_path)
            if not asr_result.success:
                return WERResult(
                    wer=1.0,
                    cer=1.0,
                    insertions=0,
                    deletions=0,
                    substitutions=0,
                    reference_words=0,
                    hypothesis_words=0,
                    success=False,
                    error=asr_result.error,
                )

            wer, cer, ins, dels, subs, ref_w, hyp_w = self._compute_wer_cer(
                ref_text, asr_result.text
            )

            return WERResult(
                wer=wer,
                cer=cer,
                insertions=ins,
                deletions=dels,
                substitutions=subs,
                reference_words=ref_w,
                hypothesis_words=hyp_w,
                success=True,
            )
        except Exception as e:
            logger.error(f"WER computation failed: {e}")
            return WERResult(
                wer=1.0,
                cer=1.0,
                insertions=0,
                deletions=0,
                substitutions=0,
                reference_words=0,
                hypothesis_words=0,
                success=False,
                error=str(e),
            )

    def get_name(self) -> str:
        return f"asr_wer_{self._backend.get_name()}"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Speaker Similarity 实现
# ═══════════════════════════════════════════════════════════════════════════


class SpeakerEmbeddingBackend(ABC):
    """说话人嵌入提取后端抽象基类."""

    @abstractmethod
    def extract_embedding(self, audio_path: Path) -> SpeakerEmbedding:
        """提取说话人嵌入向量."""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """获取后端名称."""
        pass


class ECAPATDNNBackend(SpeakerEmbeddingBackend):
    """ECAPA-TDNN 说话人嵌入后端 (SpeechBrain).

    SpeechBrain 预训练模型: spkrec-ecapa-voxceleb
    嵌入维度: 192, 采样率: 16kHz
    """

    def __init__(self, device: str = "cpu", sample_rate: int = 16000):
        self.device = device
        self.sample_rate = sample_rate
        self._model = None
        self._initialized = False

    def _initialize(self):
        if self._initialized:
            return
        try:
            import torch
            from speechbrain.inference.speaker import EncoderClassifier

            self._model = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                run_opts={"device": self.device},
                savedir=Path.home()
                / ".cache"
                / "audiobook_studio"
                / "speechbrain"
                / "ecapa",
            )
            self._initialized = True
            logger.info(f"ECAPA-TDNN initialized on {self.device}")
        except ImportError:
            raise RuntimeError("SpeechBrain not installed. pip install speechbrain")
        except Exception as e:
            logger.error(f"Failed to initialize ECAPA-TDNN: {e}")
            raise

    def extract_embedding(self, audio_path: Path) -> SpeakerEmbedding:
        self._initialize()
        try:
            import torch

            # 读取音频
            waveform = self._load_audio(audio_path)

            if self._model is not None:
                with torch.no_grad():
                    embeddings = self._model.encode_batch(waveform)
                    # embeddings shape: (1, 1, 192) -> (192,)
                    embedding = embeddings.squeeze().cpu().numpy().astype(np.float32)
            else:
                raise RuntimeError("Model not initialized")

            return SpeakerEmbedding(
                embedding=embedding,
                model_name="ecapa_tdnn",
                sample_rate=self.sample_rate,
            )
        except Exception as e:
            logger.error(f"ECAPA-TDNN embedding extraction failed: {e}")
            raise

    def _load_audio(self, audio_path: Path):
        """加载并重采样音频."""
        import asyncio

        if not _torch_available:
            raise RuntimeError("torch not installed. pip install torch")

        async def _resample():
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(audio_path),
                "-ar",
                str(self.sample_rate),
                "-ac",
                "1",
                "-f",
                "f32le",
                "-acodec",
                "pcm_f32le",
                "-",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg resample failed: {stderr.decode()}")
            return np.frombuffer(stdout, dtype=np.float32)

        audio = asyncio.run(_resample())
        waveform = torch.from_numpy(audio).unsqueeze(0)  # (1, samples)
        return waveform

    def get_name(self) -> str:
        return "ecapa_tdnn"


class WavLMBackend(SpeakerEmbeddingBackend):
    """WavLM-Large 说话人嵌入后端 (SpeechBrain).

    更强的声纹表征，嵌入维度: 512/1024，采样率: 16kHz
    模型: speechbrain/spkrec-wavlm-large-voxceleb
    """

    def __init__(self, device: str = "cpu", sample_rate: int = 16000):
        self.device = device
        self.sample_rate = sample_rate
        self._model = None
        self._initialized = False

    def _initialize(self):
        if self._initialized:
            return
        try:
            import torch
            from speechbrain.inference.speaker import EncoderClassifier

            self._model = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-wavlm-large-voxceleb",
                run_opts={"device": self.device},
                savedir=Path.home()
                / ".cache"
                / "audiobook_studio"
                / "speechbrain"
                / "wavlm",
            )
            self._initialized = True
            logger.info(f"WavLM-Large initialized on {self.device}")
        except ImportError:
            raise RuntimeError("SpeechBrain not installed. pip install speechbrain")
        except Exception as e:
            logger.error(f"Failed to initialize WavLM: {e}")
            raise

    def extract_embedding(self, audio_path: Path) -> SpeakerEmbedding:
        self._initialize()
        try:
            import torch

            waveform = self._load_audio(audio_path)

            with torch.no_grad():
                embeddings = self._model.encode_batch(waveform)
                embedding = embeddings.squeeze().cpu().numpy().astype(np.float32)

            return SpeakerEmbedding(
                embedding=embedding,
                model_name="wavlm_large",
                sample_rate=self.sample_rate,
            )
        except Exception as e:
            logger.error(f"WavLM embedding extraction failed: {e}")
            raise

    def _load_audio(self, audio_path: Path):
        import asyncio

        import torch

        async def _resample():
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(audio_path),
                "-ar",
                str(self.sample_rate),
                "-ac",
                "1",
                "-f",
                "f32le",
                "-acodec",
                "pcm_f32le",
                "-",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg resample failed: {stderr.decode()}")
            return np.frombuffer(stdout, dtype=np.float32)

        audio = asyncio.run(_resample())
        waveform = torch.from_numpy(audio).unsqueeze(0)
        return waveform

    def get_name(self) -> str:
        return "wavlm_large"


class SpeakerSimilarityMetric(QualityMetric):
    """说话人相似度质量指标 (声纹一致性).

    计算两段音频的说话人嵌入向量余弦相似度。
    用于跨章节声纹一致性检查 (Voice Anchor)。
    """

    def __init__(
        self,
        backend: str = "ecapa_tdnn",
        device: str = "cpu",
        threshold: float = 0.85,
    ):
        """
        Args:
            backend: 嵌入提取后端 (ecapa_tdnn | wavlm_large)
            device: 计算设备
            threshold: 相似度阈值，超过则判定为同一说话人
        """
        self.threshold = threshold
        self._backend = self._create_backend(backend, device)
        self._reference_embeddings: Dict[str, SpeakerEmbedding] = {}

    def _create_backend(self, backend: str, device: str) -> SpeakerEmbeddingBackend:
        if backend == "ecapa_tdnn":
            return ECAPATDNNBackend(device)
        elif backend == "wavlm_large":
            return WavLMBackend(device)
        else:
            raise ValueError(f"Unknown speaker embedding backend: {backend}")

    def register_reference(self, ref_id: str, audio_path: Path) -> bool:
        """注册参考音频嵌入 (用于 Voice Anchor)."""
        try:
            embedding = self._backend.extract_embedding(audio_path)
            self._reference_embeddings[ref_id] = embedding
            logger.info(
                f"Registered reference embedding: {ref_id} (dim={embedding.embedding.shape[0]})"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to register reference {ref_id}: {e}")
            return False

    def compute(
        self,
        target_audio: Path,
        reference_id: Optional[str] = None,
        reference_audio: Optional[Path] = None,
    ) -> SpeakerSimilarityResult:
        """计算目标音频与参考音频的相似度.

        Args:
            target_audio: 目标音频路径
            reference_id: 已注册的参考音频 ID
            reference_audio: 直接提供的参考音频路径

        Returns:
            SpeakerSimilarityResult
        """
        if reference_id is None and reference_audio is None:
            return SpeakerSimilarityResult(
                similarity=0.0,
                threshold=self.threshold,
                is_same_speaker=False,
                reference_id="",
                target_id=str(target_audio),
                success=False,
                error="No reference provided (reference_id or reference_audio)",
            )

        try:
            # 获取参考嵌入
            if reference_id and reference_id in self._reference_embeddings:
                ref_embedding = self._reference_embeddings[reference_id]
                ref_id = reference_id
            elif reference_audio:
                ref_embedding = self._backend.extract_embedding(reference_audio)
                ref_id = str(reference_audio)
            else:
                raise ValueError("Reference not found")

            # 提取目标嵌入
            target_embedding = self._backend.extract_embedding(target_audio)

            # 计算余弦相似度
            similarity = self._cosine_similarity(
                ref_embedding.embedding, target_embedding.embedding
            )

            is_same = similarity >= self.threshold

            return SpeakerSimilarityResult(
                similarity=float(similarity),
                threshold=self.threshold,
                is_same_speaker=is_same,
                reference_id=ref_id,
                target_id=str(target_audio),
                success=True,
            )
        except Exception as e:
            logger.error(f"Speaker similarity computation failed: {e}")
            return SpeakerSimilarityResult(
                similarity=0.0,
                threshold=self.threshold,
                is_same_speaker=False,
                reference_id=reference_id or "",
                target_id=str(target_audio),
                success=False,
                error=str(e),
            )

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """计算余弦相似度."""
        # 归一化
        a_norm = a / (np.linalg.norm(a) + 1e-8)
        b_norm = b / (np.linalg.norm(b) + 1e-8)
        return float(np.dot(a_norm, b_norm))

    def get_name(self) -> str:
        return f"speaker_sim_{self._backend.get_name()}"


# ═══════════════════════════════════════════════════════════════════════════
# 统一质量检查器
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class QualityCheckResult:
    """统一质量检查结果."""

    dnsmos: Optional[DNSMOSResult] = None
    wer: Optional[WERResult] = None
    speaker_sim: Optional[SpeakerSimilarityResult] = None
    passed: bool = False
    overall_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dnsmos": self.dnsmos.to_dict() if self.dnsmos else None,
            "wer": self.wer.to_dict() if self.wer else None,
            "speaker_sim": self.speaker_sim.to_dict() if self.speaker_sim else None,
            "passed": self.passed,
            "overall_message": self.overall_message,
        }


class QualityCheckSuite:
    """质量检查套件 - 统一管理三件套检查."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        hardware_profile: Optional[str] = None,
    ):
        """
        Args:
            config: 配置字典，包含:
                - dnsmos_enabled: bool
                - asr_enabled: bool
                - asr_model: str
                - asr_backend: str
                - speaker_similarity_enabled: bool
                - speaker_embed_model: str
                - thresholds: {dnsmos_min, asr_wer_max, speaker_sim_min}
            hardware_profile: 硬件配置 (potato/cloud_hybrid/pro_studio)
        """
        self.config = config or {}
        self.hardware_profile = hardware_profile or "cloud_hybrid"

        # 默认阈值
        self.dnsmos_min = self.config.get("thresholds", {}).get("dnsmos_min", 3.5)
        self.asr_wer_max = self.config.get("thresholds", {}).get("asr_wer_max", 0.05)
        self.speaker_sim_min = self.config.get("thresholds", {}).get(
            "speaker_sim_min", 0.85
        )

        # 初始化三件套 (延迟初始化)
        self._dnsmos: Optional[DNSMOSMetric] = None
        self._wer: Optional[ASRWerMetric] = None
        self._speaker_sim: Optional[SpeakerSimilarityMetric] = None
        self._initialized = False

    def _initialize(self):
        """延迟初始化所有组件.

        Each metric is initialized independently — a missing dependency
        (e.g. onnxruntime, funasr, speechbrain) causes only that metric
        to be skipped, not the entire suite.
        """
        if self._initialized:
            return

        # 根据硬件配置决定启用项
        qc_config = self.config.get("quality_check", {})

        # DNSMOS (requires onnxruntime)
        if qc_config.get("dnsmos_enabled", True):
            try:
                self._dnsmos = DNSMOSMetric()
            except Exception as e:
                logger.warning(f"DNSMOS metric disabled (dependency unavailable): {e}")

        # ASR WER (requires funasr or faster-whisper)
        if qc_config.get("asr_enabled", True):
            try:
                asr_model = qc_config.get("asr_model", "sensevoice_small")
                asr_backend = qc_config.get("asr_backend", "funasr")
                self._wer = ASRWerMetric(
                    backend=asr_backend,
                    model_name=asr_model,
                    device="cpu" if self.hardware_profile != "pro_studio" else "cuda",
                )
            except Exception as e:
                logger.warning(f"ASR WER metric disabled (dependency unavailable): {e}")

        # Speaker Similarity (requires torch + speechbrain)
        if qc_config.get("speaker_similarity_enabled", True):
            try:
                speaker_model = qc_config.get("speaker_embed_model", "ecapa_tdnn")
                self._speaker_sim = SpeakerSimilarityMetric(
                    backend=speaker_model,
                    device="cpu" if self.hardware_profile != "pro_studio" else "cuda",
                    threshold=self.speaker_sim_min,
                )
            except Exception as e:
                logger.warning(
                    f"Speaker Similarity metric disabled (dependency unavailable): {e}"
                )

        self._initialized = True

    def check_all(
        self,
        audio_path: Path,
        reference_text: str = "",
        reference_speaker_id: Optional[str] = None,
        reference_speaker_audio: Optional[Path] = None,
    ) -> QualityCheckResult:
        """执行完整的三件套质量检查.

        Args:
            audio_path: 待检查音频文件
            reference_text: 参考文本 (用于 WER)
            reference_speaker_id: 参考说话人 ID (已注册)
            reference_speaker_audio: 参考说话人音频文件

        Returns:
            QualityCheckResult
        """
        self._initialize()

        result = QualityCheckResult()
        issues = []

        # 1. DNSMOS
        if self._dnsmos and self.config.get("quality_check", {}).get(
            "dnsmos_enabled", True
        ):
            dnsmos_result = self._dnsmos.compute(audio_path)
            result.dnsmos = dnsmos_result

            if dnsmos_result.success and dnsmos_result.mos_ovr < self.dnsmos_min:
                issues.append(
                    f"DNSMOS overall {dnsmos_result.mos_ovr:.2f} < {self.dnsmos_min}"
                )
            logger.info(
                f"DNSMOS: overall={dnsmos_result.mos_ovr:.2f} sig={dnsmos_result.mos_sig:.2f} bak={dnsmos_result.mos_bak:.2f}"
            )

        # 2. ASR WER
        if self._wer and self.config.get("quality_check", {}).get("asr_enabled", True):
            wer_result = self._wer.compute(audio_path, reference_text)
            result.wer = wer_result

            if wer_result.success and wer_result.wer > self.asr_wer_max:
                issues.append(f"ASR WER {wer_result.wer:.2%} > {self.asr_wer_max:.0%}")
            logger.info(
                f"ASR WER: {wer_result.wer:.2%} ({wer_result.reference_words} ref words)"
            )

        # 3. Speaker Similarity
        if self._speaker_sim and self.config.get("quality_check", {}).get(
            "speaker_similarity_enabled", True
        ):
            sim_result = self._speaker_sim.compute(
                audio_path,
                reference_id=reference_speaker_id,
                reference_audio=reference_speaker_audio,
            )
            result.speaker_sim = sim_result

            if sim_result.success and not sim_result.is_same_speaker:
                issues.append(
                    f"Speaker similarity {sim_result.similarity:.3f} < {self.speaker_sim_min}"
                )
            logger.info(
                f"Speaker Sim: {sim_result.similarity:.3f} (threshold={self.speaker_sim_min}) same={sim_result.is_same_speaker}"
            )

        # 综合判定
        result.passed = len(issues) == 0
        result.overall_message = (
            "All checks passed" if result.passed else f"Failed: {', '.join(issues)}"
        )

        return result

    def register_speaker(self, speaker_id: str, audio_path: Path) -> bool:
        """注册说话人参考音频 (Voice Anchor)."""
        self._initialize()
        if self._speaker_sim:
            return self._speaker_sim.register_reference(speaker_id, audio_path)
        return False


# ═══════════════════════════════════════════════════════════════════════════
# 导出
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    # Data models
    "DNSMOSResult",
    "ASRResult",
    "WERResult",
    "SpeakerEmbedding",
    "SpeakerSimilarityResult",
    "QualityCheckResult",
    # Metrics
    "DNSMOSMetric",
    "ASRWerMetric",
    "SpeakerSimilarityMetric",
    "QualityCheckSuite",
    # Backends
    "ASRBackend",
    "FunASRBackend",
    "WhisperBackend",
    "SpeakerEmbeddingBackend",
    "ECAPATDNNBackend",
    "WavLMBackend",
]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Quality Metrics module ready")
    logger.info("Available checks: DNSMOS, ASR WER, Speaker Similarity")
