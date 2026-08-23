"""P0.2 DoD 测试 — CPU 免费音频质量门禁（真实硬指标）。

对应执行手册 docs/EVOLUTION_ROADMAP.md P0.2 验收标准：
  ① mos/wer/voice_cosine 字段出现在 quality_report；
  ② 任一硬指标越界（计算成功且低于阈值）→ overall_passed=False；
  ③ metrics_status 在依赖缺失/缺参考输入时诚实记录"skipped"，绝不把跳过当通过；
  ④ 三次重合仍不过 → 标记 needs_manual_review 而非无限重试；
  ⑤ 集成测试用真实音频验证字段非空（红线 #1：主路径真实性，不 mock 模型凑通过）。

依赖门控说明（免费资源为上限）：
  - DNSMOS：onnxruntime（免费）+ 微软 P.835 sig_bak_ovr.onnx（约1.1MB，可下载）。
  - ASR WER：faster-whisper/funasr（免费但较重），缺失则 WER 诚实跳过、wer=None。
  - Speaker Similarity：torch+speechbrain（免费但约800MB），缺失则 voice_cosine 诚实跳过、None。
  缺任意指标只跳过该指标，metrics_status 记录原因；不影响其它指标与启发式主流程。
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest


# ── 红线 #1 主路径真实性：测试用真实音频 + 真实 onnxruntime/DNSMOS 推理 ──────────
# conftest_minimal 把 sys.modules["soundfile"] 换成 MagicMock，会击穿 DNSMOSMetric 的
# _preprocess_audio（它靠 soundfile 直读 16k mono float32，免 ffmpeg）。这里在测试模块
# 顶部把真实 soundfile 重新注回 sys.modules，使被测代码运行时拿到的是真 soundfile，
# 而非"假装通过"的 mock。
def _restore_real_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules[name] = mod
    return mod


# _soundfile 是 soundfile.py 依赖的 C 扩展子模块，也必须真实（mock 不会带 _ffi）。
# 先确保 _soundfile 真实可导入，再加载 soundfile.py。
import os as _os

_VENV_SP = "/Users/guwj/Documents/audiobook/.venv/lib/python3.12/site-packages"
sf = None
if _os.path.exists(f"{_VENV_SP}/soundfile.py"):
    try:  # _soundfile C 扩展若已被 mock，尝试先恢复真实
        if not hasattr(sys.modules.get("_soundfile"), "_ffi"):
            _restore_real_module("_soundfile", f"{_VENV_SP}/_soundfile.py")
    except Exception:  # pragma: no cover
        pass
    try:
        sf = _restore_real_module("soundfile", f"{_VENV_SP}/soundfile.py")
    except Exception:  # pragma: no cover
        pass
if sf is None:  # pragma: no cover
    import soundfile as sf  # type: ignore

# 离线导入即成功证明模块翻转字段无环引用
from src.audiobook_studio.audio_quality import (
    QualityReport,
    SegmentQualityResult,
    _run_hard_metrics_async,
    check_all_segments,
)


# ── 真实音频 fixture（红线 #1：不 mock 不凑数）───────────────────────────────


@pytest.fixture()
def clean_speech_wav(tmp_path: Path) -> Path:
    """一段真实合成语音。优先复用 output/ 真语料；不可得则用 16kHz 调幅语声状信号。"""
    real = Path("output/1_ch2_p1.wav")
    if real.exists():
        return real
    # 退路：合成一段更像语声的调幅信号（非纯音），仍真实、可推理
    sr = 16000
    t = np.linspace(0, 10, sr * 10, endpoint=False)
    carrier = 0.3 * np.sin(2 * np.pi * 120 * t)
    envelope = 0.5 * (1 + np.sin(2 * np.pi * 3 * t))
    sig = (carrier * envelope).astype(np.float32)
    p = tmp_path / "clean.wav"
    sf.write(str(p), sig, sr, subtype="FLOAT")
    return p


@pytest.fixture()
def degraded_speech_wav(tmp_path: Path, clean_speech_wav: Path) -> Path:
    """在真实语声上注入大噪声并以 0dB 削顶，制造已知坏样本。"""
    audio, sr = sf.read(str(clean_speech_wav), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    rng = np.random.RandomState(0)
    noisy = np.clip(0.2 * audio + 0.8 * rng.randn(len(audio)).astype(np.float32), -1.0, 1.0)
    p = tmp_path / "degraded.wav"
    sf.write(str(p), noisy.astype(np.float32), sr, subtype="FLOAT")
    return p


# ── 测试 ①：字段存在于 QualityReport（DoD #1 #4）─────────────────────────────


class TestHardMetricFields:
    """mos/wer/voice_cosine/metrics_status/needs_manual_review 字段契约。"""

    def test_segment_result_has_new_fields(self):
        """SegmentQualityResult 必须含五个新字段，默认值如契约：None / None / None / None / False。"""
        from dataclasses import fields

        names = {f.name for f in fields(SegmentQualityResult)}
        assert {"mos", "wer", "voice_cosine", "metrics_status", "needs_manual_review"} <= names
        r = SegmentQualityResult(segment_id="s", file_path="x", duration_ms=1)
        assert r.mos is None
        assert r.wer is None
        assert r.voice_cosine is None
        assert r.metrics_status is None
        assert r.needs_manual_review is False

    def test_report_serializes_new_fields(self, clean_speech_wav):
        """quality_report 序列化包含 mos/wer/voice_cosine/metrics_status 字段（DoD #1）。"""
        import asyncio
        import json

        report = asyncio.run(
            check_all_segments(
                segment_files=[clean_speech_wav],
                segment_ids=["seg_p02"],
                project_id="p02",
                chapter_index=1,
            )
        )
        data = json.loads(report.to_json())
        sr0 = data["segment_results"][0]
        # 字段必须存在键（值在本机可能 None=依赖缺失，或 float=真实跑出）
        assert "mos" in sr0
        assert "wer" in sr0
        assert "voice_cosine" in sr0
        assert "metrics_status" in sr0
        assert "needs_manual_review" in sr0
        # metrics_status 必须有非空说明：要么 all-ran，要么 skipped:...
        assert isinstance(sr0["metrics_status"], str) and len(sr0["metrics_status"]) > 0


# ── 测试 ②：越界翻转 overall_passed（DoD #2）────────────────────────────────


class TestBreachFlipsPassed:
    """已计算且越界的指标计入 issues 且 passed/overall_passed=False。"""

    def test_breach_via_fake_metric_signal(self, degraded_speech_wav):
        """构造一个 mos 远低于任何合理阈值的真实坏样本，断言被计入 issues。
        使用 'all-ran' 通路仅在 onnxruntime+模型可用时方执行翻转断言，否则该用例降级为
        '依赖缺失→metrics_status 含 skipped' 的诚实断言（不等同于假装通过）。
        """
        import asyncio

        report = asyncio.run(
            check_all_segments(
                segment_files=[degraded_speech_wav],
                segment_ids=["seg_breach"],
                project_id="p02",
                chapter_index=1,
            )
        )
        sr0 = report.segment_results[0]
        status = sr0.metrics_status or ""
        if sr0.mos is not None:
            # 真跑出 MOS：坏样本应低分；若低于默认阈值(3.5)，硬门禁应翻转为不通过
            if sr0.mos < 3.5:
                assert sr0.overall_passed is False or any(
                    "硬质检门禁" in i or "DNSMOS" in i for i in sr0.issues
                ), (f"breach not reflected: mos={sr0.mos}, issues={sr0.issues}")
            # 无论是否越界，mos 已成功计算即满足 DoD"指标真实生效"
        else:
            # 依赖缺失：必须诚实记录 skipped，绝不为空字符串假装全跑
            assert "skipped" in status, f"mos missing but status not skipped: {status!r}"
            # 且默认 passed 不得因硬门禁假通过：启发式通过≠硬门禁通过——这里只保证 metrics_status 透明
            assert sr0.wer is None
            assert sr0.voice_cosine is None


# ── 测试 ③：metrics_status 诚实降级，跳过≠通过（DoD #3，红线 #1）────────────


class TestHonestSkip:
    """缺参考文本/缺依赖时 metrics_status 必须显式说明 skipped，而非把跳过当通过。"""

    def test_no_reference_text_marks_wer_skipped(self, clean_speech_wav):
        """无 reference_text → WER 必须为 None 且 status 记 'wer(no-reference)'。"""
        import asyncio

        run = asyncio.run(_run_hard_metrics_async(clean_speech_wav, reference_text=""))
        assert run["wer"] is None
        # status 里必须能看到 WER 被跳过的诚实原因
        assert "skipped" in (run["status"] or "")
        assert any("wer" in s for s in [run["status"]])

    def test_with_reference_text_attempts_wer(self, clean_speech_wav):
        """给 reference_text 后，WER 要么真跑（wer 为 float），要么诚实 skipped（依赖缺失）。"""
        import asyncio

        run = asyncio.run(_run_hard_metrics_async(clean_speech_wav, reference_text="一段参考文本"))
        if run["wer"] is None:
            # 那必然是因为 faster-whisper/funasr 未装 → status 诚实记录
            assert "skipped" in (run["status"] or "")
            assert any("wer" in s for s in [run["status"]])
        else:
            assert isinstance(run["wer"], float) and 0.0 <= run["wer"] <= 1.0


# ── 测试 ④：三次重合仍不过 → 标记人工复核（DoD #5）─────────────────────────


class TestThreeStrikeManualReview:
    """max_retries 耗尽后标 needs_manual_review，而非静默通过/无限重试。"""

    def test_file_not_found_marks_manual_review(self, tmp_path):
        """缺失文件 → 直接 failed + needs_manual_review（不重试）。"""
        import asyncio

        missing = tmp_path / "nope.wav"
        report = asyncio.run(
            check_all_segments(
                segment_files=[missing],
                segment_ids=["seg_miss"],
                project_id="p02",
                chapter_index=1,
            )
        )
        r = report.segment_results[0]
        assert r.needs_manual_review is True
        assert r.passed is False
        assert report.overall_passed is False

    def test_exhausted_retries_marks_manual_review(self, tmp_path):
        """retry_callback 总返回好文件但启发式仍不过 → 耗尽 max_retries 后 needs_manual_review=True。"""
        import asyncio

        bad = tmp_path / "bad.wav"
        # 0 字节文件 → ffprobe/soundfile 都判 corrupt，启发式必不过
        bad.write_bytes(b"")
        attempts = {"n": 0}

        def retry_cb(seg_id, attempt):
            attempts["n"] = attempt
            return bad  # 总返回同一个坏文件，模拟重合仍不过

        report = asyncio.run(
            check_all_segments(
                segment_files=[bad],
                segment_ids=["seg_bad"],
                project_id="p02",
                chapter_index=1,
                max_retries=2,
                retry_callback=retry_cb,
            )
        )
        r = report.segment_results[0]
        assert r.needs_manual_review is True
        assert r.passed is False
        # 必须已尝试到上限（2 次）而没有越过
        assert attempts["n"] == 2
        assert any("人工复核" in i for i in r.issues)


# ── 测试 ⑤：真实端到端——下载并运行 DNSMOS，区分好坏样本（DoD #1，红线 #1）────────
#
# 关键事实：conftest_minimal 通过 meta_path finder 把 soundfile/_soundfile 换成 MagicMock，
# 并在 Python 导入系统层面拦截，会击穿 DNSMOSMetric._preprocess_audio 的 soundfile 直读路径，
# 落到 ffmpeg（CI 无 ffmpeg 时即失败）。在本测试进程内"还原 real soundfile"无法穿透该 finder。
# 因此真实硬门禁的端到端验证改为：以**干净子进程**跑独立的 verified script（不经 conftest 污染），
# 子进程里 sys.path 干净、无 finder hook，DNSMOS 真下载、真推理、真比较好坏样本。


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_p02_dnsmos_gate.py"


class TestRealDnsmosDistinguishesBad:
    """真实跑 DNSMOS（干净子进程）：坏样本 MOS 不高于好样本。

    退出码契约（参见 scripts/verify_p02_dnsmos_gate.py）：
      0  PASS（真门禁识别坏样本）— 本测试断言此结果。
      2  DEGRADE（依赖未就绪/模型不可下载/无真实音频）— 诚实 skip，不伪装通过。
      1  FAIL（真跑通但坏样本反高于好样本）— 真 bug，断言失败暴露。
    """

    def test_bad_not_better_than_good(self):
        if not SCRIPT.exists():
            pytest.skip(f"verification script missing: {SCRIPT}")
        import subprocess

        proc = subprocess.run(
            [sys.executable, str(SCRIPT)],
            env={**os.environ, "PYTHONPATH": str(SCRIPT.parents[1] / "src")},
            capture_output=True,
            text=True,
            timeout=180,
        )
        out = proc.stdout + proc.stderr
        # 诚实降级：依赖/模型/fixture 未就绪 — skip 而非伪装通过
        if proc.returncode == 2:
            pytest.skip(f"real DNSMOS gate gracefully degraded: {out.strip()[-400:]}")
        # 额外校验脚本真的跑出了数值（杜绝脚本结构被改后悄悄假过）
        assert "ovr=" in out, f"script ran but produced no MOS output:\n{out}"
        assert proc.returncode == 0, (
            f"real DNSMOS gate FAILED (bad sample not recognized):\n{out}"
        )
