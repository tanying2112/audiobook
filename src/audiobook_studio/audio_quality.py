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

from .utils.ffmpeg_probe import (
    detect_silence,
    get_audio_info,
    get_duration,
    get_rms_peak,
    read_pcm_samples,
)

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

    # ── 硬质检三件套 (P0.2) — 真实音频指标，来自 quality/metrics.py ──────────────
    # None = 该指标未计算（依赖缺失或缺少参考输入），区别于"计算并通过"。
    # 越界（指标已计算且低于阈值）会把 issues / passed 翻转，overall_passed 随之 False。
    mos: Optional[float] = None  # DNSMOS 综合 MOS (1-5)，免费 CPU 门槛
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
            f"Silence check {file_path.name}: ratio={silence_ratio:.2%}, "
            f"detected={result['silence_detected']}"
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
    file_path: Path, reference_text: str = ""
) -> Dict[str, Any]:
    """Run DNSMOS/ASR-WER/Speaker-Sim hard metrics on a segment (P0.2).

    复用 quality/metrics.py 的 QualityCheckSuite —— 不重复造指标。每个指标各自
    依赖门控（onnxruntime / faster-whisper / funasr / speechbrain），缺失依赖只跳过
    该指标：返回 None 并在 status 里诚实记录"skipped"，绝不用跳过充当"通过"（红线 #1）。
    仅当指标 success=True 才填入数值并可计入越界 issues。

    runs QualityCheckSuite.check_all in a worker thread (it loads ONNX/torch
    models synchronously) so this stays non-blocking under the async loop.
    """
    # delayed import: allows systems without onnxruntime to import audio_quality
    # without paying for the quality package import chain at module load.
    try:
        from .quality import QualityCheckSuite, QualityCheckResult
    except ModuleNotFoundError:
        logger.debug("quality package unavailable — hard metrics skipped")
        return {"mos": None, "wer": None, "voice_cosine": None, "issues": [], "status": "skipped:quality-package-unavailable"}

    suite = QualityCheckSuite()
    try:
        qc_result: QualityCheckResult = await asyncio.to_thread(
            suite.check_all,
            audio_path=Path(file_path),
            reference_text=reference_text,
        )
    except Exception as e:  # 指标层任何异常都不应击穿启发式主流程
        logger.warning(f"Hard metrics suite raised for {file_path}: {e}")
        return {"mos": None, "wer": None, "voice_cosine": None, "issues": [f"硬指标计算失败: {e}"], "status": f"skipped:suite-error:{type(e).__name__}"}

    out: Dict[str, Any] = {"mos": None, "wer": None, "voice_cosine": None, "issues": []}
    skipped: List[str] = []

    if qc_result.dnsmos is not None:
        d = qc_result.dnsmos
        out["mos"] = d.mos_ovr if d.success else None
        if not d.success:
            skipped.append(f"dnsmos({d.error or 'failed'})")
    else:
        skipped.append("dnsmos(dep-missing)")

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
    return out


async def _check_segment_async(
    file_path: Path, segment_id: str, reference_text: str = ""
) -> SegmentQualityResult:
    """Run all quality checks on a single audio segment (async version).

    Args:
        file_path: Audio file path.
        segment_id: Segment identifier.
        reference_text: Optional reference transcript — enables ASR WER (免费 CPU
            backends faster-whisper/funasr 不可用时该指标诚实跳过，略过不充当通过）。
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

    # ── 硬质检三件套 (P0.2) — 复用 quality/metrics.py 的 QualityCheckSuite ──────
    # 不重复造指标；每个指标各自依赖门控，缺失依赖只跳过该指标，略过不充当通过（红线 #1）。
    # metrics_status 诚实记录降级，只把"已计算且越界"的指标计入 issues / passed 翻转。
    metrics_run = await _run_hard_metrics_async(file_path, reference_text)
    result.mos = metrics_run.get("mos")
    result.wer = metrics_run.get("wer")
    result.voice_cosine = metrics_run.get("voice_cosine")
    result.metrics_status = metrics_run.get("status")
    result.issues.extend(metrics_run.get("issues", []))

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

    Returns:
        QualityReport with results for all segments. Segments still failing after
        max_retries are marked needs_manual_review (P0.2 DoD #5) rather than silently passed.
    """
    from datetime import datetime, timezone

    segment_results = []
    passed = 0
    failed = 0

    for idx, (file_path, segment_id) in enumerate(zip(segment_files, segment_ids)):
        ref_text = reference_texts[idx] if reference_texts and idx < len(reference_texts) else ""

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
        result = await _check_segment_async(file_path, segment_id, reference_text=ref_text)

        # Retry on failure (P0.2 DoD #5: capped, then manual review — never infinite)
        attempt = 0
        current_path = file_path
        while not result.passed and attempt < max_retries and retry_callback:
            attempt += 1
            logger.info(f"Quality check failed for {segment_id}, retry {attempt}/{max_retries}")

            try:
                # Call retry callback to re-synthesize
                new_path = retry_callback(segment_id, attempt)
                if new_path and Path(new_path).exists():
                    current_path = Path(new_path)
                    result = await _check_segment_async(current_path, segment_id, reference_text=ref_text)
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

    return report


def sync_check_all_segments(
    segment_files: List[Path],
    segment_ids: List[str],
    project_id: str,
    chapter_index: int,
    max_retries: int = 2,
    retry_callback=None,
    reference_texts: Optional[List[str]] = None,
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
                    segment_files, segment_ids, project_id, chapter_index, max_retries, retry_callback, reference_texts
                ),
            )
            return future.result()
    else:
        return asyncio.run(
            check_all_segments(
                segment_files, segment_ids, project_id, chapter_index, max_retries, retry_callback, reference_texts
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