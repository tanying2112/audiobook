#!/usr/bin/env python3
"""
v6 程序化音乐床收编冒烟测试.

验证:
1. 生成 30s、3 段情绪 (tense/neutral/triumphant) 床
   - 文件存在、时长 30±0.5s
   - 非静音 (RMS > -50dBFS)
   - ebur128 integrated 在 -30..-22 之间
2. 和弦映射函数单测: tense→小调系、happy→大调系
3. batch_exporter import 检查 + auto 分支函数级冒烟
   (mock paragraphs 列表，不真跑导出)
"""

import sys
import subprocess
from pathlib import Path

# 确保 src 在 path 中
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from audiobook_studio.export.music_bed_generator import (
    generate_music_bed,
    EmotionSegment,
    emotion_to_progression,
    build_timeline_from_paragraphs,
)
from audiobook_studio.export.batch_exporter import _resolve_bgm_path, ExportJob


def test_chord_mapping():
    """测试情绪->和弦映射."""
    print("=== Test 1: chord mapping ===")
    # 小调系
    for emo in ("tense", "anxious", "fearful", "sad", "gloomy"):
        chords, db = emotion_to_progression(emo)
        assert "Am" in chords or "F" in chords or "E" in chords, f"{emo}: expected minor chords, got {chords}"
        print(f"  {emo}: {chords} @ {db}dB ✓")

    # 大调系
    for emo in ("happy", "excited", "hopeful", "triumphant"):
        chords, db = emotion_to_progression(emo)
        assert "C" in chords or "G" in chords or "F" in chords, f"{emo}: expected major chords, got {chords}"
        print(f"  {emo}: {chords} @ {db}dB ✓")

    # 中性
    chords, db = emotion_to_progression("neutral")
    assert "Am" in chords and "F" in chords and "C" in chords and "G" in chords
    print(f"  neutral: {chords} @ {db}dB ✓")

    # 愤怒
    chords, db = emotion_to_progression("angry")
    assert "Am" in chords and "E" in chords
    print(f"  angry: {chords} @ {db}dB ✓")

    print("chord mapping: ALL PASS\n")


def test_generate_music_bed():
    """测试完整音乐床生成."""
    print("=== Test 2: generate_music_bed (30s, 3 segments) ===")
    out_path = Path("/tmp/smoke_music_bed.wav")
    if out_path.exists():
        out_path.unlink()

    timeline = [
        EmotionSegment(0.0, 10.0, "tense", 0.8),
        EmotionSegment(10.0, 20.0, "neutral", 0.5),
        EmotionSegment(20.0, 30.0, "triumphant", 1.0),
    ]

    result_path = generate_music_bed(
        timeline=timeline,
        total_duration_s=30.0,
        out_path=out_path,
        sr=44100,
        seed=42,
    )

    assert result_path.exists(), "output file not created"
    print(f"  file exists: {result_path} ✓")

    # 检查时长
    import soundfile as sf
    data, sr = sf.read(str(result_path))
    dur = len(data) / sr
    assert abs(dur - 30.0) < 0.5, f"duration {dur}s not in 30±0.5s"
    print(f"  duration: {dur:.2f}s (expected 30±0.5s) ✓")

    # 检查非静音 (RMS > -50dBFS)
    rms = float(np.sqrt(np.mean(data ** 2)))
    rms_db = 20 * np.log10(rms + 1e-12)
    assert rms_db > -50, f"RMS {rms_db:.1f}dBFS too low (silence)"
    print(f"  RMS: {rms_db:.1f}dBFS (> -50dBFS) ✓")

    # 检查 LUFS
    import subprocess
    import re
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(result_path), "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True
    )
    err = r.stderr[r.stderr.find("Summary:"):]
    match = re.search(r"I:\s*(-?\d+\.?\d*)\s*LUFS", err)
    assert match, f"ebur128 parse failed: {err[-200:]}"
    lufs = float(match.group(1))
    assert -30 <= lufs <= -22, f"LUFS {lufs} not in [-30, -22]"
    print(f"  LUFS: {lufs:.1f} (in [-30, -22]) ✓")

    result_path.unlink(missing_ok=True)
    print("generate_music_bed: ALL PASS\n")


def test_batch_exporter_import():
    """测试 batch_exporter 导入 + auto 分支函数级冒烟."""
    print("=== Test 3: batch_exporter import & auto branch ===")

    # 导入检查
    from audiobook_studio.export import batch_exporter
    print("  import batch_exporter: OK ✓")

    # 模拟 job.bgm_path == "auto" 的 _resolve_bgm_path 调用
    mock_job = type("MockJob", (), {"bgm_path": "auto"})()
    mock_paragraphs = [
        {"duration_ms": 10000, "emotion": "tense", "emotion_intensity": 0.7},
        {"duration_ms": 10000, "emotion": "neutral", "emotion_intensity": 0.4},
        {"duration_ms": 10000, "emotion": "triumphant", "emotion_intensity": 1.0},
    ]
    mock_output_dir = Path("/tmp/smoke_export_test")
    mock_output_dir.mkdir(exist_ok=True)

    # 这是函数级冒烟：不真跑导出，只验证 _resolve_bgm_path 能被调用且返回路径
    # 注意: 这里会实际生成床文件，验证完整流程
    bgm_path = _resolve_bgm_path(mock_job, mock_paragraphs, mock_output_dir)
    assert bgm_path is not None, "_resolve_bgm_path returned None for 'auto'"
    assert Path(bgm_path).exists(), f"generated bed file not found: {bgm_path}"
    print(f"  _resolve_bgm_path('auto') -> {bgm_path} ✓")

    # 清理
    Path(bgm_path).unlink(missing_ok=True)
    mock_output_dir.rmdir()

    # 测试非 auto 情况
    mock_job2 = type("MockJob", (), {"bgm_path": "/some/path/bgm.wav"})()
    result = _resolve_bgm_path(mock_job2, mock_paragraphs, mock_output_dir)
    assert result == "/some/path/bgm.wav", "non-auto path should pass through"
    print(f"  _resolve_bgm_path(path) passthrough: OK ✓")

    # 测试 None 情况
    mock_job3 = type("MockJob", (), {"bgm_path": None})()
    result = _resolve_bgm_path(mock_job3, mock_paragraphs, mock_output_dir)
    assert result is None, "None path should return None"
    print(f"  _resolve_bgm_path(None) -> None: OK ✓")

    print("batch_exporter auto branch: ALL PASS\n")


if __name__ == "__main__":
    import numpy as np
    test_chord_mapping()
    test_generate_music_bed()
    test_batch_exporter_import()
    print("=== ALL SMOKE TESTS PASSED ===")