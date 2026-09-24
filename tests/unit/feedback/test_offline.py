"""M5 — 离线兜底：offline 硬件档 + 离线确定性评判器。"""

from __future__ import annotations

import pytest

from audiobook_studio.config.hardware_profile import HardwareProfile, get_hardware_profile, reset_hardware_profile
from audiobook_studio.feedback.offline_judge import OfflineJudge, OfflineVerdict, build_judge


@pytest.fixture
def offline_profile():
    reset_hardware_profile()
    prof = HardwareProfile(config_path="config/hardware_profile.yaml")
    prof.set_active_profile("offline")
    yield prof
    reset_hardware_profile()


def test_offline_profile_selectable_and_parses(offline_profile: HardwareProfile):
    assert offline_profile.active_profile == "offline"
    assert offline_profile.is_offline is True
    # 离线档质量检查应为规则优先（无云端硬指标）
    assert offline_profile.quality_check.rules_enabled is True
    assert offline_profile.quality_check.dnsmos_enabled is False
    assert offline_profile.quality_check.asr_enabled is False


def test_offline_env_triggers_recommendation(monkeypatch):
    monkeypatch.setenv("AUDIOBOOK_OFFLINE", "1")
    monkeypatch.delenv("HARDWARE_PROFILE", raising=False)
    reset_hardware_profile()
    prof = get_hardware_profile(config_path="config/hardware_profile.yaml")
    assert prof.active_profile == "offline"
    reset_hardware_profile()


def test_set_unknown_profile_raises():
    prof = HardwareProfile(config_path="config/hardware_profile.yaml")
    with pytest.raises(ValueError):
        prof.set_active_profile("does_not_exist")


def test_offline_judge_quality_clean_passes():
    j = OfflineJudge()
    v = j.judge_quality(duration_ms=3000, rms_db=-20.0, peak_db=-6.0, has_clipping=False, silence_regions=[])
    assert isinstance(v, OfflineVerdict)
    assert v.passed is True
    assert v.needs_regeneration is False
    assert v.overall_score == 1.0


def test_offline_judge_quality_clipping_and_silence_fail():
    j = OfflineJudge()
    v = j.judge_quality(
        duration_ms=3000,
        rms_db=-20.0,
        peak_db=-6.0,
        has_clipping=True,
        silence_regions=[(0.0, 800.0)],  # 800ms 静音 > 阈值
    )
    assert v.passed is False
    assert "clipping" in v.issues
    assert "silent_segment" in v.issues
    assert v.needs_regeneration is True
    assert v.overall_score < 1.0


def test_offline_judge_score_reuses_deterministic_compare():
    j = OfflineJudge()
    expected = {"needs_regeneration": False, "overall_score": 0.9}
    assert j.score({}, {"needs_regeneration": False, "overall_score": 0.9}, expected, "judge") == 1.0
    low = j.score({}, {"needs_regeneration": True, "overall_score": 0.1}, expected, "judge")
    assert 0.0 <= low < 1.0


def test_build_judge_falls_back_to_offline():
    # 不提供在线 judge → 离线兜底
    assert isinstance(build_judge(None), OfflineJudge)
    # 提供在线 judge → 原样返回
    online = object()
    assert build_judge(online) is online
