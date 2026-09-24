"""Sprint 1 S1-4 coverage: feedback control-plane logic with external LLM mocked.

The feedback area mixes pure decision logic (kill switch, promotion gate) with
LLM-driven critics. These tests cover the pure logic paths; LLM-dependent
critics are excluded (they are external adapters omitted from coverage).
"""

from __future__ import annotations

from src.audiobook_studio.feedback.kill_switch import DegradationLevel, KillSwitch, KillSwitchConfig
from src.audiobook_studio.feedback.promotion_gate import PromotionGate


def test_kill_switch_starts_normal() -> None:
    """A fresh kill switch reports NORMAL degradation."""
    ks = KillSwitch()
    assert ks.level == DegradationLevel.NORMAL
    report = ks.get_status_report()
    assert report["level"] == "normal"


def test_kill_switch_records_calls_and_stays_healthy() -> None:
    """A handful of successful calls keeps the switch healthy."""
    ks = KillSwitch(KillSwitchConfig(max_consecutive_failures=2))
    for _ in range(3):
        ks.record_call("openai", success=True)
    assert ks.should_fallback("openai") is False
    assert ks.level == DegradationLevel.NORMAL


def test_kill_switch_triggers_fallback_after_failures() -> None:
    """Consecutive failures trip the kill switch into fallback mode."""
    ks = KillSwitch(KillSwitchConfig(max_consecutive_failures=2))
    ks.record_call("openai", success=False)
    ks.record_call("openai", success=False)
    assert ks.should_fallback("openai") is True
    assert ks.level != DegradationLevel.NORMAL


def test_promotion_gate_default_thresholds() -> None:
    """PromotionGate exposes the documented default thresholds."""
    gate = PromotionGate()
    status = gate.get_status()
    assert status["thresholds"]["格式合规率"] == 0.95
    assert status["thresholds"]["黄金数据集通过率"] == 0.90


def test_promotion_gate_custom_thresholds() -> None:
    """Custom thresholds override defaults without touching external services."""
    gate = PromotionGate(thresholds={"格式合规率": 0.80})
    assert gate.get_status()["thresholds"]["格式合规率"] == 0.80
