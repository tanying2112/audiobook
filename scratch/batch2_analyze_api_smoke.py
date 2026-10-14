#!/usr/bin/env python3
"""Batch 2.4 冒烟: /api/tts/voices/analyze-reference 端点.

不拉起整个 app (避免重型导入), 直接:
  A. 路由注册验证 (router.routes 含路径)
  B. 真实英文语音 (football 8s 片段) → male 判定 + am_* blend 建议
  C. zh 校准音 (golden 280Hz 正弦) → female 判定 + zf_* blend 建议
  D. gender_hint 覆盖 (golden zh_male 181Hz 落 165-200 重叠区, hint=male 纠正)
  E. 诚实降级: 静音样本 → f0 None + warnings, 不虚构数值
  F. 坏 content_type / 坏 gender_hint → DomainError 422 语义
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
PASS, FAIL = [], []


def check(name, fn):
    try:
        detail = fn()
        PASS.append(name)
        print(f"[PASS] {name}" + (f" — {detail}" if detail else ""), flush=True)
    except Exception as e:
        FAIL.append(name)
        print(f"[FAIL] {name} — {e}", flush=True)


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _upload(path, content_type="audio/wav"):
    from starlette.datastructures import UploadFile
    f = open(path, "rb")
    return UploadFile(filename=Path(path).name, file=f, headers={"content-type": content_type})


def t_route_registered():
    from audiobook_studio.api.tts_voices import router
    paths = {getattr(r, "path", "") for r in router.routes}
    expect("/tts/voices/analyze-reference" in paths, f"路由未注册: {sorted(paths)[:8]}...")
    return "路由已注册"


def t_real_en_voice():
    from audiobook_studio.api.tts_voices import analyze_reference_voice
    res = asyncio.run(analyze_reference_voice(
        _upload("/tmp/ref_clip_en_8s.wav"), language="en", gender_hint=""))
    expect(res.success, f"success=False: {res.warnings}")
    expect(res.gender_guess == "male", f"英文男声判定错: {res.gender_guess}")
    expect(res.suggested_blend.startswith("am_"), f"en 池应选 am_*: {res.suggested_blend}")
    expect(-6.0 <= res.suggested_pitch_st <= 6.0, "pitch_st 越界")
    expect(0.7 <= res.suggested_speed <= 1.3, "speed 越界")
    expect(res.profile.f0_median_hz and 80 < res.profile.f0_median_hz < 200,
            f"F0 异常: {res.profile.f0_median_hz}")
    return f"f0={res.profile.f0_median_hz:.0f}Hz blend={res.suggested_blend} pitch={res.suggested_pitch_st:+.2f}st speed={res.suggested_speed}"


def t_zh_sine_ref():
    from audiobook_studio.api.tts_voices import analyze_reference_voice
    res = asyncio.run(analyze_reference_voice(
        _upload("tests/golden/v04_multilingual/ref_zh_female_001.wav"), language="zh", gender_hint=""))
    expect(res.success, f"success=False: {res.warnings}")
    expect(res.gender_guess == "female", f"280Hz 校准音应判 female: {res.gender_guess}")
    expect(res.suggested_blend.startswith("zf_"), f"zh 池应选 zf_*: {res.suggested_blend}")
    expect(res.profile.f0_median_hz and 250 < res.profile.f0_median_hz < 320,
            f"校准音 F0 应 ~280Hz: {res.profile.f0_median_hz}")
    return f"f0={res.profile.f0_median_hz:.0f}Hz blend={res.suggested_blend}"


def t_gender_hint_override():
    from audiobook_studio.api.tts_voices import analyze_reference_voice
    # zh_male 校准音 ~181Hz 落 165-200 重叠区, F0 推断不可靠 → hint 纠正
    res = asyncio.run(analyze_reference_voice(
        _upload("tests/golden/v04_multilingual/ref_zh_male_001.wav"),
        language="zh", gender_hint="male"))
    expect(res.gender_guess == "male", f"hint=male 未生效: {res.gender_guess}")
    expect(res.suggested_blend.startswith("zm_"), f"男声 zh 池应选 zm_*: {res.suggested_blend}")
    expect(any("gender_hint" in w for w in res.warnings), f"覆盖行为应记入 warnings: {res.warnings}")
    return f"hint 生效 → {res.suggested_blend}"


def t_silent_degrades_honestly():
    import tempfile
    import numpy as np
    import soundfile as sf
    from audiobook_studio.api.tts_voices import analyze_reference_voice
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, np.zeros(24000 * 2, dtype=np.float32), 24000)  # 2s 纯静音
        silent = tmp.name
    try:
        res = asyncio.run(analyze_reference_voice(_upload(silent), language="zh", gender_hint=""))
        expect(res.success, "静音可解码, success 应为 True")
        expect(res.profile.f0_median_hz is None, f"静音不应虚构 F0: {res.profile.f0_median_hz}")
        expect(len(res.warnings) > 0, "静音应有 warnings")
        expect(res.suggestion_confidence <= 0.01, f"静音置信度应≈0: {res.suggestion_confidence}")
        return "静音诚实降级: f0=None + warnings"
    finally:
        Path(silent).unlink(missing_ok=True)


def t_bad_inputs():
    from audiobook_studio.api.tts_voices import analyze_reference_voice
    from audiobook_studio.exceptions import DomainError
    try:
        asyncio.run(analyze_reference_voice(_upload(
            "/tmp/ref_clip_en_8s.wav", content_type="video/mp4")))
        raise AssertionError("坏 content_type 未拒绝")
    except DomainError as e:
        expect("Unsupported audio format" in str(e), f"错误语义异常: {e}")
    try:
        asyncio.run(analyze_reference_voice(_upload(
            "/tmp/ref_clip_en_8s.wav"), gender_hint="robot"))
        raise AssertionError("坏 gender_hint 未拒绝")
    except DomainError as e:
        expect("gender_hint" in str(e), f"错误语义异常: {e}")
    return "非法输入 → DomainError (422 语义)"


for name, fn in [
    ("A 路由注册", t_route_registered),
    ("B 真实英文语音", t_real_en_voice),
    ("C zh 校准音参考", t_zh_sine_ref),
    ("D gender_hint 覆盖", t_gender_hint_override),
    ("E 静音诚实降级", t_silent_degrades_honestly),
    ("F 非法输入拒绝", t_bad_inputs),
]:
    check(name, fn)

print("=" * 60)
print(f"汇总: {len(PASS)} passed, {len(FAIL)} failed")
sys.exit(0 if not FAIL else 1)
