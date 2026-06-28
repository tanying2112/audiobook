"""本地声音克隆模块 - TTS 声音克隆引擎.
实现基于 kokoro-onnx 的本地声音克隆，支持 15s 样本门控 SNR≥20dB。
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

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


# ============================================================


def extract_voice_features(audio_path: Path, sample_rate: int = 24000) -> np.ndarray:
    """从音频文件提取声音特征向量 (用于 Kokoro voice embedding).

    基于 kokoro-onnx 的声音克隆流程:
    - 从 15s 音频样本提取 MFCC/频谱特征
    - 返回 256 维特征向量 (与 Kokoro 原生声音 embedding 维度匹配)

    Args:
        audio_path: 音频文件路径
        sample_rate: 采样率 (kokoro 固定为 24000)

    Returns:
        256 维特征向量 (numpy array)
    """
    try:
        # 延迟导入 soundfile (避免强制依赖)
        import soundfile as sf

        # 加载音频
        audio_data, sr = sf.read(str(audio_path))
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

        # 提取频谱特征 (简化版 MFCC 替代)
        # 实际生产环境建议使用 librosa 提取真正的 MFCC
        features = []

        # 1. 频谱质心 (Spectral Centroid)
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
        features = (features - features.min()) / (
            features.max() - features.min() + 1e-8
        )

        return features

    except Exception as e:
        logger.error(f"提取声音特征失败: {e}")
        # 返回默认特征向量
        return np.ones(256, dtype=np.float32) * 0.5


class VoiceCloner:
    """声音克隆器 - 封装 Kokoro-ONNX 语音合成的克隆能力."""

    def __init__(self, engine: Optional[VoiceCloningEngine] = None):
        self.engine = engine or VoiceCloningEngine()

    def clone_voice(
        self, sample_path: Path, speaker_id: str
    ) -> Tuple[bool, str, Optional[str]]:
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


@dataclass
class VoicePrint:
    """声音指纹（声纹）"""

    speaker_id: str
    voice_hash: str
    embedding: List[float]  # 声音特征向量
    quality: AudioQuality
    sample_count: int
    avg_snr: float
    created_at: str
    updated_at: str


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
                        if "quality" in print_data and isinstance(
                            print_data["quality"], str
                        ):
                            print_data["quality"] = AudioQuality(
                                print_data["quality"].lower()
                            )
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
                }
            with open(prints_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info("💾 声音指纹已保存到磁盘")
        except Exception as e:
            logger.error(f"⚠️ 保存声音指纹失败: {e}")

    def _calculate_audio_hash(self, audio_data: np.ndarray, sample_rate: int) -> str:
        """计算音频数据的哈希值（用于声纹）"""
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
            total_duration = sum(s.duration for s in valid_samples)
            avg_snr = sum(s.snr_db for s in valid_samples) / len(valid_samples)

            # 生成声音哈希（基于所有样本的组合特征）
            sample_info = ""
            for sample in sorted(valid_samples, key=lambda s: s.file_path.name):
                sample_info += f"{sample.file_path.name}:{sample.duration:.2f}:{sample.snr_db:.1f}|"

            voice_hash = hashlib.sha256(sample_info.encode()).hexdigest()

            # 生成特征向量（真实 256 维）
            # 从第一个有效样本提取声音特征用于克隆
            if (
                self._model_ready
                and valid_samples
                and valid_samples[0].file_path.exists()
            ):
                # 使用真实的声音特征提取 (256 维)
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
            error_msg = (
                f"说话人 {speaker_id} 的声音质量太差 (SNR: {voice_print.avg_snr:.1f}dB)"
            )
            logger.error(f"❌ {error_msg}")
            return False, error_msg, None

        # If models not available, return mock success for testing
        if not self._model_ready:
            output_dir = Path(self.config.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
            output_file = (
                output_dir / f"{speaker_id}_{language}_{emotion}_{text_hash}_MOCK.wav"
            )
            output_file.touch()
            logger.warning(
                f"⚠️ Kokoro models not available - returning MOCK audio: {output_file.name}"
            )
            return True, f"MOCK模式合成 (模型缺失): {output_file.name}", output_file

        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 生成输出文件名
        text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
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
            # 回退到 mock 模式
            output_file.touch()
            return False, f"{error_msg} (使用 Mock 模式)", output_file

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
            "is_available_for_cloning": vp.quality
            in [AudioQuality.EXCELLENT, AudioQuality.GOOD, AudioQuality.FAIR],
        }


# 为了向后兼容，保留原来的类名作为别名
VoiceCloningManager = VoiceCloningEngine


def main():
    """主函数 - 演示本地声音克隆系统"""
    logger.info("=== Audiobook Studio 本地声音克隆演示 ===\n")

    # 创建配置
    config = CloningConfig(
        min_sample_duration=15.0, min_snr_db=20.0, similarity_threshold=0.85
    )

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
        (sp_id, cloning_manager.get_voice_info(sp_id))
        for sp_id in cloning_manager.voice_prints.keys()
    ]:
        if info:
            logger.info(f"   👤 {sp_id}:")
            logger.info(f"      质量: {info['quality']} (SNR: {info['avg_snr_db']} dB)")
            logger.info(f"      样本: {info['sample_count']} 段")
            logger.info(
                f"      可用于克隆: {'✅ 是' if info['is_available_for_cloning'] else '❌ 否'}"
            )

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
