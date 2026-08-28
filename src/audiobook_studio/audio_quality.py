"""Audio Quality Check Module for Automated Quality Gate.

Provides automated audio quality checks for synthesized segments:
1. Silence Detection - RMS-based silence region detection
2. Corruption Detection - Decode failure validation via ffprobe
3. Clipping Detection - Peak level analysis for digital clipping

Integrates with SynthesizePipeline for auto-retry on failure (max 2 retries).
Produces quality_report.json for dashboard consumption.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .utils.ffmpeg_probe import detect_silence, get_audio_info, get_duration, get_rms_peak, read_pcm_samples

logger = logging.getLogger(__name__)


# ── Thresholds (configurable via env vars) ────────────────────────────────────

# Silence detection: segments with >30% silence ratio flagged
SILENCE_THRESHOLD_DB = float(__import__("os").getenv("AUDIO_SILENCE_THRESHOLD_DB", "-40.0"))
SILENCE_MIN_DURATION_MS = int(__import__("os").getenv("AUDIO_SILENCE_MIN_DURATION_MS", "500"))
MAX_SILENCE_RATIO = float(__import__("os").getenv("AUDIO_MAX_SILENCE_RATIO", "0.30"))

# Clipping detection: peak level > -0.5 dB indicates potential clipping
CLIPPING_THRESHOLD_DB = float(__import__("os").getenv("AUDIO_CLIPPING_THRESHOLD_DB", "-0.5"))

# Corruption: ffprobe decode failure
MIN_VALID_DURATION_MS = int(__import__("os").getenv("AUDIO_MIN_VALID_DURATION_MS", "100"))
MAX_VALID_DURATION_MS = int(__import__("os").getenv("AUDIO_MAX_VALID_DURATION_MS", "300000"))  # 5 min

# UTMOS quality threshold (1-5)
UTMOS_THRESHOLD = float(__import__("os").getenv("AUDIO_UTMOS_THRESHOLD", "3.5"))


@dataclass
class SegmentQualityResult:
    """Quality check result for a single audio segment."""

    segment_id: str
    file_path: str
    duration_ms: int

    # Silence check
    silence_detected: bool = False
    silence_ratio: float = 0.0
    silence_regions: List[Dict[str, float]] = None

    # Corruption check
    corruption_detected: bool = False
    corruption_error: Optional[str] = None
    decode_valid: bool = True

    # Clipping check
    clipping_detected: bool = False
    peak_db: float = -60.0
    rms_db: float = -60.0

    # ── 硬质检四件套 (P0.2 + UTMOS) — 真实音频指标，来自 quality/metrics.py ──────────────
    # None = 该指标未计算（依赖缺失或缺少参考输入），区别于"计算并通过"。
    # 越界（指标已计算且低于阈值）会把 issues / passed 翻转，overall_passed 随之 False。
    mos: Optional[float] = None  # DNSMOS 综合 MOS (1-5)，免费 CPU 门槛
    utmos: Optional[float] = None  # UTMOS 语音质量评分 (1-5)，真实听感评分
    wer: Optional[float] = None  # ASR 字错误率 0-1（需 reference_text）
    voice_cosine: Optional[float] = None  # 声纹余弦相似度 0-1（需参考音频）
    metrics_status: Optional[str] = None  # 硬指标运行说明：None=全跑、含"skipped"提示降级原因
    needs_manual_review: bool = False  # 重合成耗尽 max_retries 仍不过 → 人工复核标记（P0.2 DoD #5）

    # Overall
    passed: bool = True
    issues: List[str] = None

    def __post_init__(self):
        if self.silence_regions is None:
            self.silence_regions = []
        if self.issues is None:
            self.issues = []

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QualityReport:
    """Aggregated quality report for a synthesis batch."""

    project_id: str
    chapter_index: int
    total_segments: int
    passed_segments: int
    failed_segments: int
    segment_results: List[SegmentQualityResult]
    overall_passed: bool
    generated_at: str

    # ── P2.13 长文一致性聚合字段 — 全章视角的声纹漂移观测 ───────────────────
    # voice_cosine_mean: 本章所有已计算声纹余弦的均值 (None=全段无参考未算, 诚实降级)
    # chapter_voice_cosine_means: {speaker_canonical_name: mean_cosine} 每角色均值, 空 dict=无
    # drift_alerts: 本章 VoiceAnchor 记录的漂移告警列表 (over-threshold 角色段).
    # breach_reason: 若 overall_passed=False 时简述首条越界原因 (供 UI 高亮), None=通过.
    voice_cosine_mean: Optional[float] = None
    chapter_voice_cosine_means: Dict[str, float] = None
    drift_alerts: List[Dict[str, Any]] = None
    breach_reason: Optional[str] = None

    def __post_init__(self):
        if self.chapter_voice_cosine_means is None:
            self.chapter_voice_cosine_means = {}
        if self.drift_alerts is None:
            self.drift_alerts = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "chapter_index": self.chapter_index,
            "total_segments": self.total_segments,
            "passed_segments": self.passed_segments,
            "failed_segments": self.failed_segments,
            "segment_results": [r.to_dict() for r in self.segment_results],
            "overall_passed": self.overall_passed,
            "generated_at": self.generated_at,
            "voice_cosine_mean": self.voice_cosine_mean,
            "chapter_voice_cosine_means": self.chapter_voice_cosine_means,
            "drift_alerts": self.drift_alerts,
            "breach_reason": self.breach_reason,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


# ── Async check functions ────────────────────────────────────────────────────


async def _check_silence_async(file_path: Path) -> Dict[str, Any]:
    """Check for excessive silence in audio segment (async version)."""
    result = {
        "silence_detected": False,
        "silence_ratio": 0.0,
        "silence_regions": [],
    }

    try:
        duration_ms = await get_duration(file_path)
        if duration_ms <= 0:
            result["silence_detected"] = True
            result["silence_ratio"] = 1.0
            result["silence_regions"] = [{"start_ms": 0, "end_ms": 0, "duration_ms": 0}]
            return result

        silence_regions = await detect_silence(
            file_path,
            threshold_db=SILENCE_THRESHOLD_DB,
            min_duration_ms=SILENCE_MIN_DURATION_MS,
        )

        total_silence_ms = sum(end - start for start, end in silence_regions)
        silence_ratio = total_silence_ms / duration_ms

        result["silence_regions"] = [
            {"start_ms": start, "end_ms": end, "duration_ms": end - start} for start, end in silence_regions
        ]
        result["silence_ratio"] = silence_ratio
        result["silence_detected"] = silence_ratio > MAX_SILENCE_RATIO

        logger.debug(
            f"Silence check {file_path.name}: ratio={silence_ratio:.2%}, " f"detected={result['silence_detected']}"
        )

    except Exception as e:
        logger.warning(f"Silence check failed for {file_path}: {e}")
        result["silence_detected"] = True
        result["silence_ratio"] = 1.0
        result["silence_regions"] = [{"start_ms": 0, "end_ms": 0, "duration_ms": 0}]

    return result


async def _check_corruption_async(file_path: Path) -> Dict[str, Any]:
    """Check for audio corruption via ffprobe decode validation (async version)."""
    result = {
        "corruption_detected": False,
        "decode_valid": True,
        "corruption_error": None,
    }

    try:
        # Quick ffprobe validation - if this fails, file is corrupted/unreadable
        info = await get_audio_info(file_path)

        # Check format info exists
        if not info.get("format"):
            result["corruption_detected"] = True
            result["decode_valid"] = False
            result["corruption_error"] = "No format info from ffprobe"
            return result

        # Check duration is valid
        duration_str = info["format"].get("duration")
        if duration_str is None:
            result["corruption_detected"] = True
            result["decode_valid"] = False
            result["corruption_error"] = "No duration in format info"
            return result

        duration_ms = float(duration_str) * 1000
        if duration_ms < MIN_VALID_DURATION_MS or duration_ms > MAX_VALID_DURATION_MS:
            result["corruption_detected"] = True
            result["decode_valid"] = False
            result["corruption_error"] = f"Invalid duration: {duration_ms}ms"
            return result

        # Check for audio stream
        audio_streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
        if not audio_streams:
            result["corruption_detected"] = True
            result["decode_valid"] = False
            result["corruption_error"] = "No audio stream found"
            return result

        # Try to decode a small sample to verify data integrity
        try:
            await read_pcm_samples(file_path, sample_rate=16000, channels=1)
        except Exception as e:
            result["corruption_detected"] = True
            result["decode_valid"] = False
            result["corruption_error"] = f"PCM decode failed: {e}"
            return result

        logger.debug(f"Corruption check {file_path.name}: valid")

    except subprocess.CalledProcessError as e:
        result["corruption_detected"] = True
        result["decode_valid"] = False
        result["corruption_error"] = f"ffprobe failed: {e.stderr if hasattr(e, 'stderr') else str(e)}"
    except Exception as e:
        result["corruption_detected"] = True
        result["decode_valid"] = False
        result["corruption_error"] = f"Validation error: {e}"

    return result


async def _check_clipping_async(file_path: Path) -> Dict[str, Any]:
    """Check for digital clipping via peak level analysis (async version)."""
    result = {
        "clipping_detected": False,
        "peak_db": -60.0,
        "rms_db": -60.0,
    }

    try:
        rms_db, peak_db = await get_rms_peak(file_path)
        result["rms_db"] = rms_db
        result["peak_db"] = peak_db
        result["clipping_detected"] = peak_db > CLIPPING_THRESHOLD_DB

        logger.debug(
            f"Clipping check {file_path.name}: peak={peak_db:.2f}dB, "
            f"rms={rms_db:.2f}dB, clipping={result['clipping_detected']}"
        )

    except Exception as e:
        logger.warning(f"Clipping check failed for {file_path}: {e}")
        result["clipping_detected"] = True
        result["peak_db"] = 0.0
        result["rms_db"] = -60.0

    return result


async def _run_hard_metrics_async(
    file_path: Path,
    reference_text: str = "",
    reference_speaker_audio: Optional[Path] = None,
    reference_speaker_id: Optional[str] = None,
    suite: Any = None,
) -> Dict[str, Any]:
    """Run DNSMOS/ASR-WER/Speaker-Sim hard metrics on a segment (P0.2).

    复用 quality/metrics.py 的 QualityCheckSuite —— 不重复造指标。每个指标各自
    依赖门控（onnxruntime / faster-whisper / funasr / speechbrain），缺失依赖只跳过
    该指标：返回 None 并在 status 里诚实记录"skipped"，绝不用跳过充当"通过"（红线 #1）。
    仅当指标 success=True 才填入数值并可计入越界 issues。

    P2.13: reference_speaker_audio / reference_speaker_id 由真主路径 (synthesize.run
    via check_all_segments) 透传而来 —— VoiceAnchor 唯一参考音频源。此前 check_all 仅
    收 audio_path+reference_text，speaker_sim 恒无参考 → voice_cosine 恒 None → 漂移门死。
    reference_speaker_id 命中 SpeakerSimilarityMetric._reference_embeddings 缓存 (P2.13 §36)
    后免去每段重 HF-extract。

    suite: 复用的 QualityCheckSuite 实例 (P2.13 §36 缓存跨段保留)。None (默认) 时惰性
    新建 —— 但新建实例的 _reference_embeddings 为空，缓存不跨段命中，仅向后兼容单段调用。

    runs QualityCheckSuite.check_all in a worker thread (it loads ONNX/torch
    models synchronously) so this stays non-blocking under the async loop.
    """
    # delayed import: allows systems without onnxruntime to import audio_quality
    # without paying for the quality package import chain at module load.
    try:
        from .quality import QualityCheckResult, QualityCheckSuite
    except ModuleNotFoundError:
        logger.debug("quality package unavailable — hard metrics skipped")
        return {
            "mos": None,
            "wer": None,
            "voice_cosine": None,
            "issues": [],
            "status": "skipped:quality-package-unavailable",
        }

    # 复用传入 suite (跨段缓存生效); 否则惰性新建 (向后兼容, 缓存仅本段)。
    if suite is None:
        suite = QualityCheckSuite()
    try:
        qc_result: QualityCheckResult = await asyncio.to_thread(
            suite.check_all,
            audio_path=Path(file_path),
            reference_text=reference_text,
            reference_speaker_id=reference_speaker_id,
            reference_speaker_audio=reference_speaker_audio,
        )
    except Exception as e:  # 指标层任何异常都不应击穿启发式主流程
        logger.warning(f"Hard metrics suite raised for {file_path}: {e}")
        return {
            "mos": None,
            "utmos": None,
            "wer": None,
            "voice_cosine": None,
            "issues": [f"硬指标计算失败: {e}"],
            "status": f"skipped:suite-error:{type(e).__name__}",
        }

    out: Dict[str, Any] = {"mos": None, "utmos": None, "wer": None, "voice_cosine": None, "issues": []}
    skipped: List[str] = []

    if qc_result.dnsmos is not None:
        d = qc_result.dnsmos
        out["mos"] = d.mos_ovr if d.success else None
        if not d.success:
            skipped.append(f"dnsmos({d.error or 'failed'})")
    else:
        skipped.append("dnsmos(dep-missing)")

    if qc_result.utmos is not None:
        u = qc_result.utmos
        out["utmos"] = u.mos if u.success else None
        if not u.success:
            skipped.append(f"utmos({u.error or 'failed'})")
    else:
        skipped.append("utmos(dep-missing)")

    if qc_result.wer is not None:
        w = qc_result.wer
        out["wer"] = w.wer if w.success else None
        if not w.success:
            skipped.append(f"wer({w.error or 'failed'})")
    else:
        skipped.append("wer(dep-missing)" if reference_text else "wer(no-reference)")

    if qc_result.speaker_sim is not None:
        s = qc_result.speaker_sim
        out["voice_cosine"] = s.similarity if s.success else None
        if not s.success:
            skipped.append(f"speaker_sim({s.error or 'failed'})")
    else:
        skipped.append("speaker_sim(dep-missing)")

    # 把硬指标层判定的越界 issue 透传（QualityCheckSuite 已按阈值比较，并设置 passed/overall_message）
    if not qc_result.passed and qc_result.overall_message:
        out["issues"].append(f"硬质检门禁: {qc_result.overall_message}")

    out["status"] = ("skipped:" + ",".join(skipped)) if skipped else "all-ran"
    out["speaker_sim_result"] = qc_result.speaker_sim  # 原始 SpeakerSimilarityResult (P2.13 漂移门用)
    return out


async def _check_segment_async(
    file_path: Path,
    segment_id: str,
    reference_text: str = "",
    speaker: Optional[str] = None,
    chapter_index: int = 0,
    book_id: str = "",
    suite: Any = None,
    registered_speakers: Optional[set] = None,
) -> SegmentQualityResult:
    """Run all quality checks on a single audio segment (async version).

    Args:
        file_path: Audio file path.
        segment_id: Segment identifier.
        reference_text: Optional reference transcript — enables ASR WER (免费 CPU
            backends faster-whisper/funasr 不可用时该指标诚实跳过，略过不充当通过）。
        speaker: P2.13 该段说话人规范名 (由 synthesize 透传)。VoiceAnchor 据此取参考音频。
        chapter_index: P2.13 章节顺序号 (synthesize 的 inp.chapter_index, 非 DB chapter_id)。
            VoiceAnchor per-chapter 锚 / 漂移告警按此键。
        book_id: P2.13 用于 §36 缓存键 f"{book_id}/ch{chapter}/{speaker}" 区分跨书同角色。
        suite: 复用的 QualityCheckSuite (跨段 §36 缓存生效)。None (默认) 时 _run_hard_metrics_async 惰性新建。
        registered_speakers: 调用方持有的已注册 §36 缓存键集合 (跨段共享)。首次命中角色时
            register_speaker 写入缓存 + 加入本集合, 后续段命中即跳过注册 (避免重复 extract)。
    """
    result = SegmentQualityResult(
        segment_id=segment_id,
        file_path=str(file_path),
        duration_ms=0,
    )

    try:
        # Get duration first
        result.duration_ms = await get_duration(file_path)
    except Exception as e:
        logger.warning(f"Could not get duration for {file_path}: {e}")
        result.duration_ms = 0

    # Run all checks
    silence_result = await _check_silence_async(file_path)
    result.silence_detected = silence_result["silence_detected"]
    result.silence_ratio = silence_result["silence_ratio"]
    result.silence_regions = silence_result["silence_regions"]

    corruption_result = await _check_corruption_async(file_path)
    result.corruption_detected = corruption_result["corruption_detected"]
    result.corruption_error = corruption_result["corruption_error"]
    result.decode_valid = corruption_result["decode_valid"]

    clipping_result = await _check_clipping_async(file_path)
    result.clipping_detected = clipping_result["clipping_detected"]
    result.peak_db = clipping_result["peak_db"]
    result.rms_db = clipping_result["rms_db"]

    # Aggregate heuristic issues
    if result.silence_detected:
        result.issues.append(f"Excessive silence: {result.silence_ratio:.1%} > {MAX_SILENCE_RATIO:.0%}")
    if result.corruption_detected:
        result.issues.append(f"Corruption detected: {result.corruption_error}")
    if result.clipping_detected:
        result.issues.append(f"Clipping detected: peak {result.peak_db:.1f}dB > {CLIPPING_THRESHOLD_DB}dB")

    # ── P2.13: VoiceAnchor 唯一参考音频源 → §36 缓存注册/命中 → speaker_sim ──
    # 此前 _run_hard_metrics_async 只传 audio_path+reference_text, speaker_sim 恒无参考 →
    # voice_cosine 恒 None → 漂移门死。现在从 VA 取参考音频, 首次命中角色注册 §36 缓存,
    # 后续段复用嵌入 (reference_speaker_id 命中), 免每段重 HF-extract ECAPA (贵)。
    # compute 同时收 reference_audio + reference_id 时 reference_audio 优先 (每段重 extract),
    # 故已注册后只传 reference_speaker_id 命中缓存。
    ref_speaker_audio: Optional[Path] = None
    ref_speaker_id: Optional[str] = None
    if speaker:
        try:
            from .pipeline.voice_anchor import get_voice_anchor_manager

            va = get_voice_anchor_manager()
            if va.config.enabled:
                ref_path_str = va.get_reference_audio(speaker, chapter_index=chapter_index)
                if ref_path_str and Path(ref_path_str).exists():
                    ref_id = f"{book_id}/ch{chapter_index}/{speaker}" if book_id else f"ch{chapter_index}/{speaker}"
                    # §36: 首次命中角色注册缓存; registered_speakers 跨段共享避免重复 extract。
                    if registered_speakers is None:
                        registered_speakers = set()
                    if ref_id not in registered_speakers and suite is not None:
                        # register 需复用同一 suite, 否则缓存随新建实例丢失。
                        if suite.register_speaker(ref_id, Path(ref_path_str)):
                            registered_speakers.add(ref_id)
                            ref_speaker_id = ref_id
                        else:
                            # 注册失败 (依赖缺/extract 异常) -> fallback 每段传 audio (诚实降级, 仍可算 sim)
                            ref_speaker_audio = Path(ref_path_str)
                    else:
                        ref_speaker_id = ref_id  # 命中已注册缓存
        except Exception as e:
            logger.debug(f"P2.13 VoiceAnchor reference resolve failed for {segment_id}: {e}")
            ref_speaker_audio = None
            ref_speaker_id = None

    # ── 硬质检三件套 (P0.2) — 复用 quality/metrics.py 的 QualityCheckSuite ──────
    # 不重复造指标；每个指标各自依赖门控，缺失依赖只跳过该指标，略过不充当通过（红线 #1）。
    # metrics_status 诚实记录降级，只把"已计算且越界"的指标计入 issues / passed 翻转。
    metrics_run = await _run_hard_metrics_async(
        file_path,
        reference_text,
        reference_speaker_audio=ref_speaker_audio,
        reference_speaker_id=ref_speaker_id,
        suite=suite,
    )
    result.mos = metrics_run.get("mos")
    result.utmos = metrics_run.get("utmos")
    result.wer = metrics_run.get("wer")
    result.voice_cosine = metrics_run.get("voice_cosine")
    result.metrics_status = metrics_run.get("status")
    result.issues.extend(metrics_run.get("issues", []))

    # ── P2.13: 漂移门 — speaker_sim 计算成功且非同一说话人 → 录漂移告警 ──────────
    sim_result = metrics_run.get("speaker_sim_result")
    if (
        sim_result is not None
        and getattr(sim_result, "success", False)
        and speaker
        and not getattr(sim_result, "is_same_speaker", True)
    ):
        try:
            from .pipeline.voice_anchor import get_voice_anchor_manager

            va = get_voice_anchor_manager()
            if va.config.enabled:
                va._record_drift_alert(
                    character_name=speaker,
                    chapter_index=chapter_index,
                    similarity=sim_result.similarity,
                    threshold=sim_result.threshold,
                    generated_audio=str(file_path),
                )
        except Exception as e:
            logger.debug(f"P2.13 drift alert record failed for {segment_id}: {e}")

    result.passed = len(result.issues) == 0

    return result


# ── Sync wrappers for backward compatibility ────────────────────────────────


def check_silence(file_path: Path) -> Dict[str, Any]:
    """Sync wrapper for silence check."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're in an async context - can't use asyncio.run()
        # Run in executor to avoid nested event loop
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, _check_silence_async(file_path))
            return future.result()
    else:
        return asyncio.run(_check_silence_async(file_path))


def check_corruption(file_path: Path) -> Dict[str, Any]:
    """Sync wrapper for corruption check."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, _check_corruption_async(file_path))
            return future.result()
    else:
        return asyncio.run(_check_corruption_async(file_path))


def check_clipping(file_path: Path) -> Dict[str, Any]:
    """Sync wrapper for clipping check."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, _check_clipping_async(file_path))
            return future.result()
    else:
        return asyncio.run(_check_clipping_async(file_path))


def check_segment(file_path: Path, segment_id: str) -> SegmentQualityResult:
    """Sync wrapper for segment check."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, _check_segment_async(file_path, segment_id))
            return future.result()
    else:
        return asyncio.run(_check_segment_async(file_path, segment_id))


async def check_all_segments(
    segment_files: List[Path],
    segment_ids: List[str],
    project_id: str,
    chapter_index: int,
    max_retries: int = 2,
    retry_callback=None,
    reference_texts: Optional[List[str]] = None,
    speaker_map: Optional[Dict[str, str]] = None,
) -> QualityReport:
    """Check quality of all segments with auto-retry on failure (async version).

    Args:
        segment_files: List of audio file paths
        segment_ids: List of corresponding segment IDs
        project_id: Project identifier
        chapter_index: Chapter index
        max_retries: Maximum retry attempts per segment (default 2)
        retry_callback: Optional async callback(segment_id, attempt) -> new_file_path for re-synthesis
        reference_texts: Optional per-segment reference transcripts enabling ASR WER.
            Same length/order as segment_files. Omissions → WER honestly skipped.
        speaker_map: P2.13 segment_id -> speaker_canonical_name (由 synthesize.run 透传).
            驱动 VoiceAnchor 参考音频注入 + §36 嵌入缓存 + 漂移门。None (默认, 向后兼容)
            时 speaker_sim 恒无参考 (与改造前等价, 诚实 skip)。

    Returns:
        QualityReport with results for all segments. Segments still failing after
        max_retries are marked needs_manual_review (P0.2 DoD #5) rather than silently passed.
    """
    from datetime import datetime, timezone

    # P2.13 §36: suite 跨段复用, _reference_embeddings 缓存不随新建实例丢失。
    # 复用前需 quality 包可 import; 不可用时 speaker_sim 路径降级 (suite=None, 仍跑规则+dnsmos/wer)。
    shared_suite: Any = None
    if speaker_map:
        try:
            from .quality import QualityCheckSuite

            shared_suite = QualityCheckSuite()
        except ModuleNotFoundError:
            logger.debug("quality package unavailable — P2.13 speaker_sim/drift path degraded")
            shared_suite = None
    registered_speakers: set = set()

    segment_results = []
    passed = 0
    failed = 0

    for idx, (file_path, segment_id) in enumerate(zip(segment_files, segment_ids)):
        ref_text = reference_texts[idx] if reference_texts and idx < len(reference_texts) else ""
        speaker = speaker_map.get(segment_id) if speaker_map else None

        if not file_path.exists():
            logger.warning(f"Segment file not found: {file_path}")
            result = SegmentQualityResult(
                segment_id=segment_id,
                file_path=str(file_path),
                duration_ms=0,
                corruption_detected=True,
                corruption_error="File not found",
                decode_valid=False,
                passed=False,
                issues=["File not found"],
                needs_manual_review=True,
            )
            segment_results.append(result)
            failed += 1
            continue

        # Initial check
        result = await _check_segment_async(
            file_path,
            segment_id,
            reference_text=ref_text,
            speaker=speaker,
            chapter_index=chapter_index,
            book_id=project_id,
            suite=shared_suite,
            registered_speakers=registered_speakers,
        )

        # Retry on failure (P0.2 DoD #5: capped, then manual review — never infinite)
        attempt = 0
        current_path = file_path
        while not result.passed and attempt < max_retries and retry_callback:
            attempt += 1
            logger.info(f"Quality check failed for {segment_id}, retry {attempt}/{max_retries}")

            try:
                # Call retry callback to re-synthesize (supports both sync and async)
                retry_result = retry_callback(segment_id, attempt)
                if asyncio.iscoroutine(retry_result):
                    new_path = await retry_result
                else:
                    new_path = retry_result
                if new_path and Path(new_path).exists():
                    current_path = Path(new_path)
                    result = await _check_segment_async(
                        current_path,
                        segment_id,
                        reference_text=ref_text,
                        speaker=speaker,
                        chapter_index=chapter_index,
                        book_id=project_id,
                        suite=shared_suite,
                        registered_speakers=registered_speakers,
                    )
                    logger.info(f"Retry {attempt} for {segment_id}: {'passed' if result.passed else 'failed'}")
                else:
                    logger.warning(f"Retry {attempt} for {segment_id} returned no valid file")
                    break
            except Exception as e:
                logger.error(f"Retry {attempt} for {segment_id} failed: {e}")
                break

        # 三振出局 → 标记人工复核，而非让其静默通过或无限重试（P0.2 DoD #5）
        if not result.passed:
            result.needs_manual_review = True
            if f"已重合成 {attempt} 次仍不过，标记人工复核" not in result.issues:
                result.issues.append(f"已重合成 {attempt} 次仍不过，标记人工复核")

        segment_results.append(result)
        if result.passed:
            passed += 1
        else:
            failed += 1

    report = QualityReport(
        project_id=project_id,
        chapter_index=chapter_index,
        total_segments=len(segment_files),
        passed_segments=passed,
        failed_segments=failed,
        segment_results=segment_results,
        overall_passed=(failed == 0),
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )

    # ── P2.13: 聚合声纹漂移观测到 QualityReport (全章视角) ─────────────────────
    # voice_cosine_mean / chapter_voice_cosine_means: 从 segment_results 按 speaker
    # 聚合 (speaker 来自 speaker_map 反查)。仅计入非 None 的 voice_cosine (已计算者)，
    # None (无参考未算) 不污染均值 — 这是诚实降级, 非"跳过当通过" (红线 #1)。
    # drift_alerts: 从 VoiceAnchor 取本章漂移告警 (over-threshold 角色段)。
    # breach_reason: overall_passed=False 时首条越界原因 (drift_alerts 优先, 次段 issues)。
    per_speaker_cosines: Dict[str, List[float]] = {}
    all_cosines: List[float] = []
    for seg in segment_results:
        if seg.voice_cosine is None:
            continue
        all_cosines.append(seg.voice_cosine)
        speaker = speaker_map.get(seg.segment_id) if speaker_map else None
        if speaker:
            per_speaker_cosines.setdefault(speaker, []).append(seg.voice_cosine)
    report.voice_cosine_mean = round(sum(all_cosines) / len(all_cosines), 4) if all_cosines else None
    report.chapter_voice_cosine_means = {sp: round(sum(cs) / len(cs), 4) for sp, cs in per_speaker_cosines.items()}

    try:
        from .pipeline.voice_anchor import get_voice_anchor_manager

        va = get_voice_anchor_manager()
        if va.config.enabled:
            report.drift_alerts = list(va.get_drift_alerts(chapter_index))
    except Exception as e:
        logger.debug(f"P2.13 drift alerts aggregation failed for chapter {chapter_index}: {e}")

    if not report.overall_passed:
        if report.drift_alerts:
            first = report.drift_alerts[0]
            report.breach_reason = (
                f"声纹漂移: {first.get('character_name')} ch{first.get('chapter_index')} "
                f"cosine={first.get('similarity')} < 阈值{first.get('threshold')}"
            )
        else:
            # 取首条段越界 issue (非人工复核占位)
            for seg in segment_results:
                real_issues = [i for i in seg.issues if i and "人工复核" not in i]
                if real_issues:
                    report.breach_reason = real_issues[0]
                    break

    return report


def sync_check_all_segments(
    segment_files: List[Path],
    segment_ids: List[str],
    project_id: str,
    chapter_index: int,
    max_retries: int = 2,
    retry_callback=None,
    reference_texts: Optional[List[str]] = None,
    speaker_map: Optional[Dict[str, str]] = None,
) -> QualityReport:
    """Sync wrapper for check_all_segments."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                asyncio.run,
                check_all_segments(
                    segment_files,
                    segment_ids,
                    project_id,
                    chapter_index,
                    max_retries,
                    retry_callback,
                    reference_texts,
                    speaker_map,
                ),
            )
            return future.result()
    else:
        return asyncio.run(
            check_all_segments(
                segment_files,
                segment_ids,
                project_id,
                chapter_index,
                max_retries,
                retry_callback,
                reference_texts,
                speaker_map,
            )
        )


def save_quality_report(report: QualityReport, output_path: Path) -> Path:
    """Save quality report to JSON file.

    Args:
        report: QualityReport to save
        output_path: Output file path

    Returns:
        Path to saved file
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.to_json(), encoding="utf-8")
    logger.info(f"Quality report saved to {output_path}")
    return output_path


def load_quality_report(report_path: Path) -> Optional[QualityReport]:
    """Load quality report from JSON file.

    Args:
        report_path: Path to quality report JSON

    Returns:
        QualityReport or None if not found/invalid
    """
    if not report_path.exists():
        return None

    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))

        segment_results = [SegmentQualityResult(**sr) for sr in data.get("segment_results", [])]

        return QualityReport(
            project_id=data["project_id"],
            chapter_index=data["chapter_index"],
            total_segments=data["total_segments"],
            passed_segments=data["passed_segments"],
            failed_segments=data["failed_segments"],
            segment_results=segment_results,
            overall_passed=data["overall_passed"],
            generated_at=data["generated_at"],
        )
    except Exception as e:
        logger.error(f"Failed to load quality report {report_path}: {e}")
        return None


if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1:
        test_path = Path(sys.argv[1])
        if test_path.exists():
            print(f"Testing: {test_path}")
            print(f"Duration: {get_duration_sync(test_path)}ms")
            print(f"Silence: {check_silence(test_path)}")
            print(f"Corruption: {check_corruption(test_path)}")
            print(f"Clipping: {check_clipping(test_path)}")
            print(f"Full check: {check_segment(test_path, 'test_segment')}")
        else:
            print(f"File not found: {test_path}")
    else:
        print("Usage: python -m audiobook_studio.audio_quality <audio_file>")


def get_duration_sync(path: Path) -> int:
    """Sync wrapper for get_duration."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, get_duration(path))
            return future.result()
    else:
        return asyncio.run(get_duration(path))
