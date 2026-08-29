"""本地声音克隆模块 - TTS 声音克隆引擎.
实现基于 kokoro-onnx 的本地声音克隆，支持 15s 样本门控 SNR≥20dB。
"""

# Defer annotation evaluation: VoiceCloner (line 146) annotates its __init__ with
# Optional[VoiceCloningEngine], which is defined further down (line 257). Under
# Python <=3.13 annotations are evaluated eagerly at class-definition time, so
# this forward reference raised NameError on 3.11 (e.g. the python:3.11-slim
# Docker image) while Python 3.14's PEP 649 deferred evaluation masked it locally.
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from .kokoro_backend import KokoroBackend
    from .remote_voxcpm2_port import RemoteVoxCPM2Port

import numpy as np

from .port import TTSProsody, TTSStatus, TTSTaskPayload, TTSVoiceAnchor

logger = logging.getLogger(__name__)

# Model availability tracking
_KOKORO_MODEL_AVAILABLE = False
_KOKORO_MODEL_PATH: Optional[Path] = None


def check_kokoro_model_availability(model_path: str = "./models/kokoro-onnx") -> bool:
    """Check if Kokoro-ONNX model files are available."""
    global _KOKORO_MODEL_AVAILABLE, _KOKORO_MODEL_PATH
    path = Path(model_path)
    onnx_file = path / "kokoro-v1.0.onnx"
    voices_file = path / "voices-v1.0.bin"

    # Also check alternative naming
    alt_onnx = path / "model.onnx"
    alt_voices = path / "voices.bin"

    if onnx_file.exists() and voices_file.exists():
        _KOKORO_MODEL_AVAILABLE = True
        _KOKORO_MODEL_PATH = path
        logger.info(f"✅ Kokoro-ONNX models found at {path}")
        return True
    elif alt_onnx.exists() and alt_voices.exists():
        _KOKORO_MODEL_AVAILABLE = True
        _KOKORO_MODEL_PATH = path
        logger.info(f"✅ Kokoro-ONNX models found at {path} (alt names)")
        return True
    else:
        _KOKORO_MODEL_AVAILABLE = False
        _KOKORO_MODEL_PATH = None
        logger.warning(
            f"⚠️ Kokoro-ONNX models NOT found at {path}. "
            f"Expected: kokoro-v1.0.onnx + voices-v1.0.bin "
            f"(or model.onnx + voices.bin). "
            f"Run: python scripts/download_kokoro_model.py"
        )
        return False


def get_kokoro_model_path() -> Optional[Path]:
    """Get the path to Kokoro models if available."""
    return _KOKORO_MODEL_PATH


def is_kokoro_available() -> bool:
    """Check if Kokoro models are loaded and available."""
    return _KOKORO_MODEL_AVAILABLE


# ─────────────────────────────────────────────────────────────────────────────
# P0/A2 honesty: real zero-shot cloning is gated on a GPU clone backend.
# ─────────────────────────────────────────────────────────────────────────────
#
# Under free + no-GPU, true zero-shot cloning is infeasible: Kokoro/Piper discard
# reference_audio, and the GPU neural clone models (F5-TTS / CosyVoice2 / Dia) cannot
# run on CPU at audible speed. This module therefore stores the uploaded sample and
# degrades to *preset* mode until a real clone backend (Track B) registers itself.
# We never claim a usable clone was produced when none was.


# ─────────────────────────────────────────────────────────────────────────────
# P0/A2 honesty: real zero-shot cloning availability is *probed*, not assumed.
# ─────────────────────────────────────────────────────────────────────────────
#
# ``real_clone_available()`` returns True only when a real zero-shot clone backend
# (VoxCPM2 / CosyVoice2) is both configured AND reachable. The same env vars the
# docker-compose.gpu.yml Pro Studio stack sets (``VOXCPM2_ENDPOINT`` /
# ``COSYVOICE_ENDPOINT``) are honored here, so once the self-hosted GPU services
# answer their ``/health`` probe, the API honestly advertises real cloning.
#
# Under free + no-GPU (no endpoint configured) this stays False — we never claim a
# usable clone was produced when no real backend is actually serving requests.
# A cached, TTL-bounded probe avoids hammering the backend on every request.
_CLONE_PROBE_LOCK = threading.Lock()
_CLONE_AVAILABLE_CACHE: Optional[bool] = None
_CLONE_PROBE_TS: float = 0.0
_CLONE_PROBE_TTL_SECONDS = 30.0


def _configured_clone_endpoint() -> Optional[str]:
    """Return a configured real clone backend endpoint, or None.

    Honors ``VOXCPM2_ENDPOINT`` / ``COSYVOICE_ENDPOINT`` (the same env vars the
    Pro Studio docker-compose stack and ``remote_voxcpm2_port.py`` use). An
    explicit opt-out via ``CLONE_BACKEND_DISABLED=true`` short-circuits
    availability (e.g. for hermetic CI or when the operator wants to force preset).
    """
    if os.getenv("CLONE_BACKEND_DISABLED", "").lower() in ("1", "true", "yes"):
        return None
    for env in ("VOXCPM2_ENDPOINT", "COSYVOICE_ENDPOINT"):
        val = (os.getenv(env) or "").strip().rstrip("/")
        if val:
            return val
    return None


def _probe_endpoint_health(url: str, timeout: float = 1.5) -> bool:
    """Return True when ``{url}/health`` responds with HTTP 2xx/3xx.

    A 2xx/3xx means the real clone backend is alive and serving; anything else
    (4xx/5xx/connection error) means it is not, so we must not advertise cloning.
    """
    try:
        import httpx
    except Exception:
        # httpx missing — cannot probe; be honest and report unavailable.
        return False
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(f"{url}/health")
        return 200 <= resp.status_code < 400
    except Exception:
        return False


def probe_clone_availability(force: bool = False) -> bool:
    """Probe configured clone backend(s) and cache the result (TTL-bounded).

    Honest: returns True only when a real zero-shot clone backend endpoint is
    configured AND reachable. Never claims availability under free/no-GPU unless
    a real backend answers its ``/health`` probe.
    """
    global _CLONE_AVAILABLE_CACHE, _CLONE_PROBE_TS
    now = time.monotonic()
    if not force and _CLONE_AVAILABLE_CACHE is not None and (now - _CLONE_PROBE_TS) < _CLONE_PROBE_TTL_SECONDS:
        return _CLONE_AVAILABLE_CACHE
    with _CLONE_PROBE_LOCK:
        now = time.monotonic()
        if not force and _CLONE_AVAILABLE_CACHE is not None and (now - _CLONE_PROBE_TS) < _CLONE_PROBE_TTL_SECONDS:
            return _CLONE_AVAILABLE_CACHE
        endpoint = _configured_clone_endpoint()
        try:
            available = bool(endpoint) and _probe_endpoint_health(endpoint)
        except Exception:  # noqa: BLE001 — a failing probe must never break the caller
            available = False
        _CLONE_AVAILABLE_CACHE = available
        _CLONE_PROBE_TS = now
    return _CLONE_AVAILABLE_CACHE


def refresh_clone_availability() -> bool:
    """Force a fresh probe (e.g. on startup or after backend reconfiguration)."""
    return probe_clone_availability(force=True)


def real_clone_available() -> bool:
    """True only when a real zero-shot clone backend is registered AND reachable.

    Under free + no-GPU this stays ``False`` (no endpoint configured). In Pro
    Studio mode (docker-compose.gpu.yml with the voxcpm2 / cosyvoice profiles)
    the ``VOXCPM2_ENDPOINT`` / ``COSYVOICE_ENDPOINT`` env vars point at a real
    GPU backend whose ``/health`` probe must answer before we advertise real
    cloning. This is the honest Track B integration point: we never claim a
    usable clone was produced when no real backend is actually serving requests.
    """
    return probe_clone_availability()


def clone_mode() -> str:
    """Return the active clone mode: 'clone' (real) or 'preset' (no-GPU fallback)."""
    return "clone" if real_clone_available() else "preset"


def _real_clone_backend() -> Tuple[bool, Optional[str]]:
    """Return (is_real, backend_name) for the configured real clone backend.

    ``is_real`` is True only when ``real_clone_available()`` is True (a real GPU
    VoxCPM2/CosyVoice backend is both configured AND reachable). The backend
    name reflects which endpoint answered its ``/health`` probe. This is the
    honest Track B integration point: we never claim a real clone was produced
    unless a real backend is actually serving requests.
    """
    if not real_clone_available():
        return False, None
    # Prefer the first endpoint that is configured; the probe already verified
    # reachability for whichever ``_configured_clone_endpoint()`` returned.
    if os.getenv("VOXCPM2_ENDPOINT", "").strip():
        return True, "voxcpm2"
    if os.getenv("COSYVOICE_ENDPOINT", "").strip():
        return True, "cosyvoice"
    return True, "voxcpm2"


# ============================================================


def extract_voice_features(audio_path: Path, sample_rate: int = 24000) -> np.ndarray:
    """从音频文件提取 *占位* 声音特征向量（preset placeholder，非真实声纹）.

    ⚠️ 诚实声明：本函数仅基于频谱质心 / 过零率 / RMS 等粗粒度声学统计量构造一个
    256 维向量，**不是** 说话人声纹 / 生物特征 embedding，也**不是** Kokoro 原生的
    voice embedding。真实克隆链路（``real_clone_available()`` 为 True 时）由
    Kokoro-ONNX 自身生成 embedding，不会使用本向量。本向量仅用于模拟/占位模式下让
    调用方拿到一个可复现的 deterministic 特征，便于灰度与回放测试，绝不能用于声纹
    比对或身份认证。

    Args:
        audio_path: 音频文件路径
        sample_rate: 采样率 (kokoro 固定为 24000)

    Returns:
        256 维占位特征向量 (numpy array)，对应 feature_method="spectral_centroid_placeholder"
    """
    try:
        # 延迟导入 soundfile (避免强制依赖)
        import soundfile as sf

        # 加载音频
        audio_data, sr = sf.read(str(audio_path))
        if len(audio_data) == 0:
            # 空音频（或读取失败）直接返回默认特征向量，避免后续 0/0 产生 nan
            return np.ones(256, dtype=np.float32) * 0.5
        if sr != sample_rate:
            # 重采样 (简单线性插值占位)
            ratio = sample_rate / sr
            audio_data = np.interp(
                np.arange(0, len(audio_data) * ratio),
                np.arange(0, len(audio_data)),
                audio_data,
            ).astype(np.float32)

        # 归一化
        if len(audio_data) > 0:
            audio_data = audio_data / np.max(np.abs(audio_data))

        # 提取频谱特征 (简化版 MFCC 替代) —— 占位特征，非真实声纹
        # 实际生产环境建议使用 librosa 提取真正的 MFCC；真实克隆由 Kokoro 自身生成 embedding
        features = []

        # 1. 频谱质心 (Spectral Centroid) —— 占位特征，非真实声纹
        if len(audio_data) > 100:
            # 将音频分成 8 段计算频谱质心
            segment_size = len(audio_data) // 8
            for i in range(8):
                segment = audio_data[i * segment_size : (i + 1) * segment_size]
                if len(segment) > 0:
                    # FFT 频谱质心
                    fft = np.fft.rfft(segment)
                    magnitudes = np.abs(fft)
                    freqs = np.fft.rfftfreq(len(segment), 1 / sample_rate)
                    if np.sum(magnitudes) > 0:
                        centroid = np.sum(magnitudes * freqs) / np.sum(magnitudes)
                        features.append(centroid / sample_rate)  # 归一化

        # 2. 零跨零率 (Zero Crossing Rate)
        zcr = np.sum(np.abs(np.diff(np.sign(audio_data))) > 0) / len(audio_data)
        features.extend([zcr] * 8)

        # 3. 根均方值 (RMS Energy)
        rms = np.sqrt(np.mean(audio_data**2))
        features.extend([rms] * 8)

        # 4. 填充到 256 维 (Kokoro embedding 维度)
        while len(features) < 256:
            features.append(0.5)
        features = features[:256]

        # 再次归一化
        features = np.array(features, dtype=np.float32)
        features = (features - features.min()) / (features.max() - features.min() + 1e-8)

        return features

    except Exception as e:
        logger.error(f"提取声音特征失败: {e}")
        # 返回默认特征向量
        return np.ones(256, dtype=np.float32) * 0.5


class VoiceCloner:
    """声音克隆器 - 封装 Kokoro-ONNX 语音合成的克隆能力."""

    def __init__(self, engine: Optional[VoiceCloningEngine] = None):
        self.engine = engine or VoiceCloningEngine()

    def clone_voice(self, sample_path: Path, speaker_id: str) -> Tuple[bool, str, Optional[str]]:
        """从 15s 样本创建克隆声音.

        Args:
            sample_path: 15s 音频样本路径
            speaker_id: 角色/说话人 ID

        Returns:
            (是否成功, 消息, 克隆声音 ID)
        """
        if not sample_path.exists():
            return False, f"样本文件不存在: {sample_path}", None

        try:
            # 延迟导入 soundfile (避免强制依赖)
            import soundfile as sf

            # 加载音频获取时长
            audio_data, sr = sf.read(str(sample_path))
            duration = len(audio_data) / sr

            # 估算 SNR
            snr_db = VoiceCloningEngine()._estimate_snr(audio_data, sr)

            # 创建 VoiceSample
            sample = VoiceSample(
                id=f"clone_{speaker_id}",
                file_path=sample_path,
                duration=duration,
                sample_rate=sr,
                snr_db=snr_db,
                text_content="[克隆语音]",
                language="zh-CN",
                speaker_id=speaker_id,
            )

            # 添加样本 (会自动创建/更新声音指纹)
            success, message = self.engine.add_voice_sample(sample)
            if success:
                return True, message, speaker_id
            return False, message, None

        except Exception as e:
            return False, f"克隆失败: {str(e)}", None

    def get_cloned_voices(self) -> List[Dict]:
        """获取所有可用的克隆声音列表."""
        return [
            {
                "speaker_id": sp_id,
                **self.engine.get_voice_info(sp_id),
            }
            for sp_id in self.engine.voice_prints.keys()
        ]


class AudioQuality(Enum):
    """音频质量等级"""

    EXCELLENT = "excellent"  # SNR ≥ 25dB
    GOOD = "good"  # SNR 20-24dB
    FAIR = "fair"  # SNR 15-19dB
    POOR = "poor"  # SNR < 15dB


@dataclass
class VoiceSample:
    """声音样本"""

    id: str
    file_path: Path
    duration: float  # 秒
    sample_rate: int  # Hz
    snr_db: float  # 信噪比
    text_content: str  # 对应的文本内容
    language: str
    speaker_id: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    # P2.11 合规: 克隆样本授权存证 (attestation)。红线#1: 授权时间戳 + 授权条款
    # 版本随样本持久化, 供后续审计回溯; 缺失=None 表示旧样本 (历史数据, 非假声明)
    attestation_at: Optional[str] = None
    consent_version: Optional[str] = None


@dataclass
class VoicePrint:
    """声音指纹（声纹）占位对象 —— *不是* 真实生物特征声纹.

    ⚠️ 诚实声明：本结构用于记录模拟/占位模式下的克隆结果。其中的 ``embedding``
    来自 ``extract_voice_features`` 的谱质心占位特征，``voice_hash`` 来自
    ``_calculate_audio_hash`` 的粗粒度统计哈希，二者均**不可**作为说话人身份或
    声纹比对的依据。``feature_method`` 显式标注所用方法；仅当其为占位方法时本对象
    才是占位结果，真实克隆模式下应由 Kokoro-ONNX 提供真正的 embedding。
    """

    speaker_id: str
    voice_hash: str
    embedding: List[float]  # 占位声音特征向量（非真实声纹）
    quality: AudioQuality
    sample_count: int
    avg_snr: float
    created_at: str
    updated_at: str
    feature_method: str = "spectral_centroid_placeholder"  # 诚实标注：占位特征方法
    # Track B / Pro Studio：真实克隆锚点（仅当 feature_method="real_remote_clone" 时有效）。
    # ``is_real_clone=True`` 表示该声音已注册为由真实 GPU 克隆后端合成，
    # ``reference_audio_path`` 为 15s 样本路径（合成时转发给后端），
    # ``clone_backend`` 记录实际后端名 (voxcpm2 / cosyvoice)。
    # 注意：真实声纹 embedding 由后端持有，本结构仅存锚点，绝不伪称本地持有声纹。
    is_real_clone: bool = False
    reference_audio_path: Optional[str] = None
    clone_backend: Optional[str] = None


@dataclass
class CloningConfig:
    """声音克隆配置"""

    min_sample_duration: float = 15.0  # 最小样本时长 (秒)
    min_snr_db: float = 20.0  # 最小信噪比 (dB)
    similarity_threshold: float = 0.85  # 声音相似度阈值
    model_path: str = "./models/kokoro-onnx"
    output_dir: str = "./voices/cloned"


class VoiceCloningEngine:
    """本地声音克隆引擎"""

    def __init__(self, config: CloningConfig = None):
        self.config = config or CloningConfig()
        self.voice_prints: Dict[str, VoicePrint] = {}
        self.voice_samples: Dict[str, List[VoiceSample]] = {}  # speaker_id -> samples
        self._model_ready = False

        # 确保目录存在
        Path(self.config.output_dir).mkdir(parents=True, exist_ok=True)
        Path(self.config.model_path).mkdir(parents=True, exist_ok=True)

        # Check model availability
        self._model_ready = check_kokoro_model_availability(self.config.model_path)

        # 加载已有的声音指纹
        self._load_voice_prints()

        if self._model_ready:
            logger.info("🔊 声音克隆引擎初始化完成 (模型就绪)")
        else:
            logger.info("🔊 声音克隆引擎初始化完成 (模拟模式 - 模型文件缺失)")

    def _load_voice_prints(self):
        """从磁盘加载已保存的声音指纹"""
        prints_file = Path("./voices/voice_prints.json")
        if prints_file.exists():
            try:
                with open(prints_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for sp_id, print_data in data.items():
                        # Convert quality string back to enum
                        if "quality" in print_data and isinstance(print_data["quality"], str):
                            print_data["quality"] = AudioQuality(print_data["quality"].lower())
                        self.voice_prints[sp_id] = VoicePrint(**print_data)
                logger.info(f"📂 加载了 {len(self.voice_prints)} 个已有声音指纹")
            except Exception as e:
                logger.error(f"⚠️ 加载声音指纹失败: {e}")

    def _save_voice_prints(self):
        """保存声音指纹到磁盘"""
        prints_file = Path("./voices/voice_prints.json")
        prints_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = {}
            for sp_id, print_obj in self.voice_prints.items():
                data[sp_id] = {
                    "speaker_id": print_obj.speaker_id,
                    "voice_hash": print_obj.voice_hash,
                    "embedding": print_obj.embedding,
                    "quality": print_obj.quality.value,
                    "sample_count": print_obj.sample_count,
                    "avg_snr": print_obj.avg_snr,
                    "created_at": print_obj.created_at,
                    "updated_at": print_obj.updated_at,
                    "feature_method": print_obj.feature_method,
                    "is_real_clone": print_obj.is_real_clone,
                    "reference_audio_path": print_obj.reference_audio_path,
                    "clone_backend": print_obj.clone_backend,
                }
            with open(prints_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info("💾 声音指纹已保存到磁盘")
        except Exception as e:
            logger.error(f"⚠️ 保存声音指纹失败: {e}")

    def _calculate_audio_hash(self, audio_data: np.ndarray, sample_rate: int) -> str:
        """计算音频数据的 *占位* 哈希值（preset placeholder，非声纹）.

        ⚠️ 诚实声明：仅用均值/标准差/分位数等统计特征做确定性哈希，用于模拟模式下
        区分不同样本，不构成生物特征声纹。
        """
        # 简化实现：使用音频数据的统计特征
        features = [
            np.mean(audio_data),
            np.std(audio_data),
            np.percentile(audio_data, 25),
            np.percentile(audio_data, 50),
            np.percentile(audio_data, 75),
            np.max(audio_data),
            np.min(audio_data),
            len(audio_data) / sample_rate,  # 时长
        ]
        feature_str = ",".join([f"{f:.6f}" for f in features])
        return hashlib.sha256(feature_str.encode()).hexdigest()

    def _estimate_snr(self, audio_data: np.ndarray, sample_rate: int) -> float:
        """估算信噪比 (SNR)"""
        # 简化的SNR估算
        if len(audio_data) == 0:
            return 0.0

        # 估算噪声 floor（使用前100个样本或后100个样本， whichever is quieter）
        noise_floor = min(
            np.std(audio_data[: min(100, len(audio_data))]),
            np.std(audio_data[max(0, len(audio_data) - 100) :]),
        )

        # 估算信号功率
        signal_power = np.std(audio_data)

        if noise_floor > 0:
            snr = 20 * np.log10(signal_power / noise_floor)
            return max(0.0, snr)  # 防止负值
        else:
            return 50.0  # 非常高的SNR（几乎没有噪声）

    def _is_sample_valid(self, sample: VoiceSample) -> Tuple[bool, str]:
        """检查声音样本是否符合克隆要求"""
        if sample.duration < self.config.min_sample_duration:
            return (
                False,
                f"样本时长不足: {sample.duration:.1f}s < {self.config.min_sample_duration}s",
            )

        if sample.snr_db < self.config.min_snr_db:
            return (
                False,
                f"信噪比不足: {sample.snr_db:.1f}dB < {self.config.min_snr_db}dB",
            )

        return True, "样本有效"

    def add_voice_sample(self, sample: VoiceSample) -> Tuple[bool, str]:
        """
        添加声音样本并尝试创建/更新声音指纹

        Returns:
            (是否成功, 消息)
        """
        # 验证样本
        is_valid, message = self._is_sample_valid(sample)
        if not is_valid:
            logger.warning(f"❌ 声音样本验证失败: {message}")
            return False, message

        # 初始化说话人的样本列表
        if sample.speaker_id not in self.voice_samples:
            self.voice_samples[sample.speaker_id] = []

        # 添加样本
        self.voice_samples[sample.speaker_id].append(sample)

        # 尝试创建或更新声音指纹
        return self._update_voice_print(sample.speaker_id)

    def _update_voice_print(self, speaker_id: str) -> Tuple[bool, str]:
        """
        基于说话人的所有样本创建或更新声音指纹

        Returns:
            (是否成功, 消息)
        """
        samples = self.voice_samples.get(speaker_id, [])
        if not samples:
            return False, f"说话人 {speaker_id} 没有有效样本"

        # 过滤出有效样本
        valid_samples = []
        for sample in samples:
            is_valid, _ = self._is_sample_valid(sample)
            if is_valid:
                valid_samples.append(sample)

        if len(valid_samples) == 0:
            return False, f"说话人 {speaker_id} 没有符合要求的有效样本"

        # 计算平均特征
        try:
            avg_snr = sum(s.snr_db for s in valid_samples) / len(valid_samples)

            # 生成声音哈希（基于所有样本的组合特征）
            sample_info = ""
            for sample in sorted(valid_samples, key=lambda s: s.file_path.name):
                sample_info += f"{sample.file_path.name}:{sample.duration:.2f}:{sample.snr_db:.1f}|"

            voice_hash = hashlib.sha256(sample_info.encode()).hexdigest()

            # ── Track B / Pro Studio：真实克隆模式 ───────────────────────────
            # 当真实 GPU 克隆后端可达时，说话人声纹 embedding 由后端持有，
            # 本模块只保存 15s 样本锚点 (reference_audio_path) 并标记该声音为
            # 真实克隆；绝不伪称本地持有可用声纹。占位特征向量留空。
            is_real, clone_backend = _real_clone_backend()
            if is_real and valid_samples and valid_samples[0].file_path.exists():
                embedding: List[float] = []
                reference_audio_path = str(valid_samples[0].file_path)
                feature_method = "real_remote_clone"
                logger.info(
                    f"🎙️ 注册真实克隆声音锚点: {speaker_id} (backend={clone_backend}, " f"ref={reference_audio_path})"
                )
            else:
                # 模拟/占位模式：生成基于统计的 256 维占位特征向量（非声纹）
                is_real = False
                clone_backend = None
                reference_audio_path = None
                feature_method = "spectral_centroid_placeholder"
                if self._model_ready and valid_samples and valid_samples[0].file_path.exists():
                    # 使用真实的声音特征提取 (256 维占位特征)
                    embedding = extract_voice_features(
                        valid_samples[0].file_path, valid_samples[0].sample_rate
                    ).tolist()
                else:
                    # 模拟模式：生成基于统计的特征向量
                    embedding = [
                        avg_snr / 50.0,  # 归一化SNR
                        np.mean([s.duration for s in valid_samples]) / 30.0,  # 归一化时长
                        len(valid_samples) / 10.0,  # 样本数量归一化
                        hash(sample.speaker_id) % 1000 / 1000.0,  # 基于ID的随机特征
                    ]
                    # 填充到 256 维
                    while len(embedding) < 256:
                        embedding.append(0.5)
                    embedding = embedding[:256]

            # 检查是否已存在声音指纹
            if speaker_id in self.voice_prints:
                # 更新现有指纹
                existing = self.voice_prints[speaker_id]
                # 如果哈希变化显著，则更新
                if existing.voice_hash != voice_hash:
                    self.voice_prints[speaker_id] = VoicePrint(
                        speaker_id=speaker_id,
                        voice_hash=voice_hash,
                        embedding=embedding,
                        quality=self._assess_quality(avg_snr),
                        sample_count=len(valid_samples),
                        avg_snr=avg_snr,
                        feature_method=feature_method,
                        is_real_clone=is_real,
                        reference_audio_path=reference_audio_path,
                        clone_backend=clone_backend,
                        created_at=existing.created_at,
                        updated_at=datetime.now().isoformat(),
                    )
                    message = f"更新声音指纹: {speaker_id} (样本: {len(valid_samples)}, SNR: {avg_snr:.1f}dB)"
                    logger.info(f"🔄 {message}")
                else:
                    message = f"声音指纹无变化: {speaker_id}"
                    logger.debug(f"🔄 {message}")
            else:
                # 创建新指纹
                self.voice_prints[speaker_id] = VoicePrint(
                    speaker_id=speaker_id,
                    voice_hash=voice_hash,
                    embedding=embedding,
                    quality=self._assess_quality(avg_snr),
                    sample_count=len(valid_samples),
                    avg_snr=avg_snr,
                    feature_method=feature_method,
                    is_real_clone=is_real,
                    reference_audio_path=reference_audio_path,
                    clone_backend=clone_backend,
                    created_at=datetime.now().isoformat(),
                    updated_at=datetime.now().isoformat(),
                )
                message = f"创建新声音指纹: {speaker_id} (样本: {len(valid_samples)}, SNR: {avg_snr:.1f}dB)"
                logger.info(f"🆕 {message}")

            # 保存到磁盘
            self._save_voice_prints()
            return True, message

        except Exception as e:
            error_msg = f"处理声音样本时出错: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg

    def _assess_quality(self, snr_db: float) -> AudioQuality:
        """根据SNR评估音频质量"""
        if snr_db >= 25.0:
            return AudioQuality.EXCELLENT
        elif snr_db >= 20.0:
            return AudioQuality.GOOD
        elif snr_db >= 15.0:
            return AudioQuality.FAIR
        else:
            return AudioQuality.POOR

    def synthesize_speech(
        self,
        text: str,
        speaker_id: str,
        language: str = "zh-CN",
        emotion: str = "neutral",
    ) -> Tuple[bool, str, Optional[Path]]:
        """
        使用克隆的声音合成语音

        Returns:
            (是否成功, 消息, 输出音频文件路径)
        """
        if speaker_id not in self.voice_prints:
            error_msg = f"找不到说话人 {speaker_id} 的声音指纹"
            logger.error(f"❌ {error_msg}")
            return False, error_msg, None

        voice_print = self.voice_prints[speaker_id]

        # 检查声音质量是否足够
        if voice_print.quality == AudioQuality.POOR:
            error_msg = f"说话人 {speaker_id} 的声音质量太差 (SNR: {voice_print.avg_snr:.1f}dB)"
            logger.error(f"❌ {error_msg}")
            return False, error_msg, None

        # ── Track B / Pro Studio：真实克隆合成链路 ──────────────────────────
        # 当该声音已注册为 *真实* 克隆 (存有 15s 样本锚点且后端可达) 时，实际合成
        # 委托给真实 GPU 克隆后端，而非 Kokoro 占位路径。我们**绝不**在此静默降级
        # 到预设路径——若后端此时不可用，则诚实报错，而非伪造一个克隆音频。
        if voice_print.is_real_clone and voice_print.reference_audio_path:
            if not real_clone_available():
                error_msg = (
                    "真实克隆后端当前不可用 (VOXCPM2_ENDPOINT/COSYVOICE_ENDPOINT 未配置或 "
                    "/health 未响应)，无法为真实克隆声音合成。"
                )
                logger.error(f"❌ {error_msg}")
                raise RuntimeError(error_msg)
            logger.info(
                "🎙️ 路由到真实克隆后端合成: speaker=%s backend=%s",
                speaker_id,
                voice_print.clone_backend,
            )
            output_dir = Path(self.config.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            text_hash = hashlib.sha256(text.encode(), usedforsecurity=False).hexdigest()[:8]
            output_file = output_dir / f"{speaker_id}_{language}_{emotion}_{text_hash}.wav"
            try:
                audio_path = synthesize_real_clone(
                    text=text,
                    reference_audio_path=voice_print.reference_audio_path,
                    language=language,
                    emotion=emotion,
                    output_path=output_file,
                )
            except Exception as e:
                error_msg = f"真实克隆合成失败: {str(e)}"
                logger.error(f"❌ {error_msg}")
                raise RuntimeError(error_msg) from e
            success_msg = f"真实克隆语音合成成功: {Path(audio_path).name}"
            logger.info(f"✅ {success_msg}")
            return True, success_msg, Path(audio_path)

        # 模型未就绪时抛出明确异常
        if not self._model_ready:
            raise RuntimeError(
                "Kokoro-ONNX 模型不可用: models/kokoro-onnx 目录缺失. "
                "请先运行: python scripts/download_kokoro_model.py"
            )

        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 生成输出文件名
        text_hash = hashlib.sha256(text.encode(), usedforsecurity=False).hexdigest()[:8]
        output_file = output_dir / f"{speaker_id}_{language}_{emotion}_{text_hash}.wav"

        # 实际 TTS 调用 - 使用 Kokoro-ONNX
        try:
            # 导入 KokoroBackend
            import asyncio

            from .kokoro_backend import KokoroBackend, create_kokoro_backend

            # 创建 Kokoro backend 实例
            kokoro = KokoroBackend(
                model_path=self.config.model_path,
                sample_rate=24000,
            )

            # 获取或创建克隆声音 ID
            # voice_print.embedding 是 256 维特征向量
            embedding = np.array(voice_print.embedding, dtype=np.float32)

            # 将 embedding 保存为临时 .npy 文件供 Kokoro 使用
            # KokoroBackend 支持 reference_audio 参数
            ref_audio_path = self.voice_samples.get(speaker_id, [])
            if ref_audio_path and ref_audio_path[0].file_path.exists():
                reference_audio = str(ref_audio_path[0].file_path)
            else:
                reference_audio = None

            # 确定 voice_id (使用克隆声音或匹配近似声音)
            # 映射 embedding 到最近的预定义 voice
            voice_id = self._select_closest_voice(voice_print, language)

            # KokoroBackend.synthesize 需要同步/异步 context
            # 使用 asyncio 运行异步 initialize
            asyncio.run(
                self._do_synthesize(
                    kokoro,
                    text,
                    voice_id,
                    output_file,
                    embedding,
                    reference_audio,
                    emotion,
                )
            )

            success_msg = f"语音合成成功: {output_file.name}"
            logger.info(f"✅ {success_msg}")
            return True, success_msg, output_file

        except Exception as e:
            error_msg = f"语音合成失败: {str(e)}"
            logger.error(f"❌ {error_msg}")
            raise RuntimeError(error_msg) from e

    async def _do_synthesize(
        self,
        kokoro: "KokoroBackend",
        text: str,
        voice_id: str,
        output_path: Path,
        embedding: Optional[np.ndarray] = None,
        reference_audio: Optional[str] = None,
        emotion: str = "neutral",
    ):
        """实际执行 Kokoro 语音合成 (异步)."""
        await kokoro.initialize()

        # 准备 prosody 参数 (emotion mapping)
        emotion_map = {
            "neutral": 1.0,
            "happy": 1.1,
            "sad": 0.9,
            "angry": 1.2,
            "surprised": 1.15,
        }
        prosody = {"rate": emotion_map.get(emotion, 1.0)}

        # 如果有 reference_audio，提取实时 embedding (优先于存储的 embedding)
        if reference_audio and Path(reference_audio).exists():
            try:
                live_embedding = extract_voice_features(Path(reference_audio), 24000)
                embedding = live_embedding
            except Exception as e:
                logger.warning(f"无法提取实时语音特征: {e}, 使用存储的 embedding")

        # 执行合成 - 传递 embedding 用于声音克隆
        result = await kokoro.synthesize(
            text=text,
            voice_id=voice_id,
            output_path=output_path,
            prosody=prosody,
            reference_audio=reference_audio,
            embedding=embedding,
        )

        await kokoro.cleanup()
        return result

    def _select_closest_voice(self, voice_print: VoicePrint, language: str) -> str:
        """根据 embedding 选择最接近的预定义声音.

        Kokoro-onnx 使用固定的声音 ID，克隆 embedding 通过 reference_audio 参数传入.
        这里我们选择与目标语言匹配的默认声音.
        """
        # 中文语言映射到中文默认声音
        if language and language.startswith("zh"):
            return "zf_xiaoxiao"  # 中文女声默认
        return "af"  # 英文默认声音

    def get_voice_info(self, speaker_id: str) -> Optional[Dict]:
        """获取说话人的声音信息"""
        if speaker_id not in self.voice_prints:
            return None

        vp = self.voice_prints[speaker_id]
        return {
            "speaker_id": vp.speaker_id,
            "voice_hash": vp.voice_hash[:16] + "...",  # 只显示前16位
            "quality": vp.quality.value,
            "sample_count": vp.sample_count,
            "avg_snr_db": round(vp.avg_snr, 1),
            "created_at": vp.created_at,
            "updated_at": vp.updated_at,
            "is_available_for_cloning": vp.quality in [AudioQuality.EXCELLENT, AudioQuality.GOOD, AudioQuality.FAIR],
            "is_real_clone": vp.is_real_clone,
            "clone_backend": vp.clone_backend,
            "clone_mode": "clone" if vp.is_real_clone else "preset",
        }


# 为了向后兼容，保留原来的类名作为别名
VoiceCloningManager = VoiceCloningEngine


# ─────────────────────────────────────────────────────────────────────────────
# Track B / Pro Studio：真实零样本克隆执行
# ─────────────────────────────────────────────────────────────────────────────
#
# 当 ``real_clone_available()`` 为 True 时，上述克隆路径通过真实 GPU 克隆后端
# (VoxCPM2 / CosyVoice，由 docker-compose.gpu.yml 的 Pro Studio 栈自托管) 实际合成，
# 而非 Kokoro 占位路径。``synthesize_real_clone`` 通过 ``RemoteVoxCPM2Port`` 提交任务、
# 轮询状态、下载音频。后端地址沿用 ``VOXCPM2_ENDPOINT`` / ``COSYVOICE_ENDPOINT``。
#
# 诚实性：仅在 DONE 时返回音频路径；FAILED / 超时则抛出异常，调用方不会静默降级为
# 伪造的预设克隆。


async def _run_remote_clone(
    port: "RemoteVoxCPM2Port",
    *,
    text: str,
    reference_audio_path: str,
    language: str,
    emotion: str,
    task_timeout_s: float = 180.0,
    poll_interval_s: float = 1.0,
    owns_port: bool = False,
) -> Optional[str]:
    """提交一次真实克隆合成任务到远程端口并下载结果音频路径.

    Args:
        port: 已实例化的 ``RemoteVoxCPM2Port``（测试可注入 mock）。
        reference_audio_path: 15s 样本路径，转发给后端作为声纹锚点。
        task_timeout_s: 任务轮询总超时（秒）。
        poll_interval_s: 状态轮询间隔（秒）。
        owns_port: 为 True 时本协程负责关闭端口连接池。

    Returns:
        本地音频文件路径字符串；任务失败/超时则返回 None（由调用方转为异常）。

    Raises:
        RuntimeError: 后端任务显式 FAILED 或整体超时。
    """
    task_id = f"clone-{uuid.uuid4().hex[:16]}"
    payload = TTSTaskPayload(
        text=text,
        voice_anchor=TTSVoiceAnchor(
            voice_id="clone",
            language=language,
            reference_audio_path=reference_audio_path,
        ),
        prosody=TTSProsody(emotion=emotion),
    )
    try:
        await port.submit(task_id, payload)
        deadline = time.monotonic() + task_timeout_s
        while time.monotonic() < deadline:
            status = await port.get_status(task_id)
            if status.status == TTSStatus.DONE:
                result = await port.get_result(task_id)
                return result.audio_path
            if status.status == TTSStatus.FAILED:
                raise RuntimeError(f"真实克隆后端任务失败: {status.error_message or 'unknown'}")
            await asyncio.sleep(poll_interval_s)
        raise RuntimeError("真实克隆后端超时未返回结果 (timeout)")
    finally:
        if owns_port:
            try:
                await port.close()
            except Exception:  # noqa: BLE001 — best-effort close
                pass


def synthesize_real_clone(
    text: str,
    reference_audio_path: str,
    language: str = "zh-CN",
    emotion: str = "neutral",
    output_path: Optional[Path] = None,
    *,
    port: Optional["RemoteVoxCPM2Port"] = None,
    task_timeout_s: float = 180.0,
) -> Path:
    """同步封装：通过已配置的真实克隆后端合成零样本克隆音频.

    沿用 ``VOXCPM2_ENDPOINT`` / ``COSYVOICE_ENDPOINT`` 环境变量；若未显式传入
    ``port`` 则自动创建 ``RemoteVoxCPM2Port``。返回本地 ``.wav`` 路径。

    诚实性：后端未返回音频或任务失败时**抛异常**，绝不降级为预设克隆。
    """
    output_path = output_path or (Path("./output/clone_real") / f"clone_{int(time.time())}.wav")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    created_port = port is None
    if port is None:
        from .remote_voxcpm2_port import create_remote_voxcpm2_port

        port = create_remote_voxcpm2_port()

    audio_path = asyncio.run(
        _run_remote_clone(
            port,
            text=text,
            reference_audio_path=reference_audio_path,
            language=language,
            emotion=emotion,
            task_timeout_s=task_timeout_s,
            owns_port=created_port,
        )
    )

    if not audio_path:
        raise RuntimeError("真实克隆后端未返回音频 (honest failure)")

    src = Path(audio_path)
    if src.resolve() != output_path.resolve():
        shutil.copyfile(src, output_path)
    elif not src.exists():
        raise RuntimeError(f"真实克隆后端返回的路径不存在: {audio_path}")
    return output_path


def main():
    """主函数 - 演示本地声音克隆系统"""
    logger.info("=== Audiobook Studio 本地声音克隆演示 ===\n")

    # 创建配置
    config = CloningConfig(min_sample_duration=15.0, min_snr_db=20.0, similarity_threshold=0.85)

    # 创建管理器
    cloning_manager = VoiceCloningEngine(config)

    logger.info("🔊 模拟添加声音样本...\n")

    # 模拟添加一些声音样本
    import random
    from datetime import datetime, timedelta

    # 为说话人 "阿云" 添加样本
    speaker_id = "阿云"
    base_time = datetime.now() - timedelta(days=2)

    logger.info(f"📝 为说话人 '{speaker_id}' 添加声音样本...")

    for i in range(3):
        # 模拟样本文件
        sample_path = Path(f"./samples/{speaker_id}_sample_{i+1}.wav")

        # 模拟样本属性
        duration = 15.0 + random.uniform(-2.0, 5.0)  # 13-20秒
        snr_db = 22.0 + random.uniform(-3.0, 8.0)  # 19-30dB
        sample_rate = 24000  # kokoro 常用采样率

        sample = VoiceSample(
            id=f"{speaker_id}_sample_{i+1}",
            file_path=sample_path,
            duration=duration,
            sample_rate=sample_rate,
            snr_db=snr_db,
            text_content=f"这是说话人 {speaker_id} 的第 {i+1} 段录音文本，用于声音克隆训练。",
            language="zh-CN",
            speaker_id=speaker_id,
            timestamp=(base_time + timedelta(hours=i * 4)).isoformat(),
        )

        success, message = cloning_manager.add_voice_sample(sample)
        logger.info(f"   样本 {i+1}: {'✅ 成功' if success else '❌ 失败'} - {message}")

        if success:
            # 显示当前声音信息
            info = cloning_manager.get_voice_info(speaker_id)
            if info:
                logger.info(f"      声音指纹: {info['voice_hash']}")
                logger.info(f"      质量等级: {info['quality']}")
                logger.info(f"      平均SNR: {info['avg_snr_db']} dB")
                logger.info(f"      样本数量: {info['sample_count']}")

    logger.info("\n" + "=" * 60)

    # 尝试为另一个说话人添加不足够的样本
    logger.info("\n📝 为说话人 '测试者' 添加不合格的样本...")
    bad_sample = VoiceSample(
        id="bad_sample_001",
        file_path=Path("./samples/bad_sample.wav"),
        duration=5.0,  # 太短：5秒 < 15秒
        sample_rate=24000,
        snr_db=25.0,  # SNR好但时长不足
        text_content="这个样本太短了",
        language="zh-CN",
        speaker_id="测试者",
        timestamp=datetime.now().isoformat(),
    )

    success, message = cloning_manager.add_voice_sample(bad_sample)
    logger.info(f"   添加结果: {'✅ 成功' if success else '❌ 失败'} - {message}")

    logger.info("\n" + "=" * 60)

    # 演示语音合成
    logger.info("\n🎤 演示语音合成功能...")
    test_text = "欢迎使用音频书制作工作室，现在开始克隆声音合成演示。"

    success, message, audio_file = cloning_manager.synthesize_speech(
        text=test_text, speaker_id=speaker_id, language="zh-CN", emotion="happy"
    )

    if success:
        logger.info(f"   ✅ {message}")
        if audio_file:
            logger.info(f"   📁 输出文件: {audio_file}")
    else:
        logger.error(f"   ❌ {message}")

    logger.info("\n" + "=" * 60)
    logger.info("🎙️ 当前所有声音指纹:")
    for sp_id, info in [
        (sp_id, cloning_manager.get_voice_info(sp_id)) for sp_id in cloning_manager.voice_prints.keys()
    ]:
        if info:
            logger.info(f"   👤 {sp_id}:")
            logger.info(f"      质量: {info['quality']} (SNR: {info['avg_snr_db']} dB)")
            logger.info(f"      样本: {info['sample_count']} 段")
            logger.info(f"      可用于克隆: {'✅ 是' if info['is_available_for_cloning'] else '❌ 否'}")

    logger.info("\n" + "=" * 60)
    logger.info("🎉 本地声音克隆演示完成")
    logger.info("=" * 60)


def clone_voice(sample_path: Path, speaker_id: str) -> Tuple[bool, str, Optional[str]]:
    """Convenience function to clone a voice from a sample."""
    cloner = VoiceCloner()
    return cloner.clone_voice(sample_path, speaker_id)


def load_voice_print(speaker_id: str) -> Optional[Dict]:
    """Load voice print info for a speaker."""
    cloner = VoiceCloner()
    return cloner.engine.get_voice_info(speaker_id)


if __name__ == "__main__":
    main()
